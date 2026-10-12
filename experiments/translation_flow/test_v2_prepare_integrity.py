"""Offline published-source integrity and complete-command failure evidence."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from .cli import digest
from .v2_prepare import identity, prepare, verified_counts
from .v2_execute import execute


APEX_SHA256 = "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PreparationIntegrityTests(unittest.TestCase):
    def source_fixture(self, root):
        source = root / "合成 源文"
        source.mkdir()
        scene = {"id": "scene-a", "scene_id": "scene-a", "source_language": "ja", "target_language": "zh-Hans",
                 "context": [{"id": "s1", "text": "もし雨なら", "start": 1, "end": 2},
                             {"id": "s2", "text": "出かけません。", "start": 2, "end": 3}],
                 "translate_ids": ["s1", "s2"]}
        manifest = source / "source-manifest.json"
        write_json(manifest, {"windows": [{"id": "score-a", "window_id": "score-a", "scene_id": "scene-a",
                                          "split": "screen-a", "scored_ids": ["s1", "s2"]}]})
        scenes = source / "scenes.jsonl"
        scenes.write_text(json.dumps(scene, ensure_ascii=False) + "\n", encoding="utf-8")
        write_json(source / "freeze-manifest.json", {"version": "hy30-flow-v2-source-v1",
                   "state": "source_frozen_reference_unreviewed", "role": "screening",
                   "artifacts": [{"path": path.name, "sha256": digest(path)} for path in (manifest, scenes)]})
        return manifest, scenes, scene

    def prepare_fixture(self, root, **options):
        manifest, scenes, scene = self.source_fixture(root)
        output = root / "prepared"
        defaults = {"manifest": manifest, "scenes": scenes, "output": output, "split": "screen-a",
                    "recipe_id": "C0-test", "target_size": 1, "stage": "qualification"}
        return defaults, scene

    def token_fixture(self, root, scene):
        sources = {cue["id"]: cue["text"] for cue in scene["context"]}
        measured = {"schema": "hy30-source-token-counts-v2", "complete": True,
                    "asset": {"id": "hy-mt2-30b-a3b-apex-i-compact", "sha256": APEX_SHA256},
                    "template_sha256": "a" * 64, "engine_manifest_sha256": "b" * 64,
                    "source_text_sha256": identity(sources),
                    "tokenize_parameters": {"add_special": False, "parse_special": True},
                    "cue_token_counts": {cue_id: 3 for cue_id in sources},
                    "attempts": [{"cue_id": cue_id, "source_text_sha256": identity(text), "status": "accepted",
                                  "tokens": 3, "elapsed_seconds": .01, "exchange": "synthetic-tokenize"}
                                 for cue_id, text in sources.items()]}
        path = root / "counts.json"
        write_json(path, measured)
        return path, measured

    def test_source_or_manifest_drift_rejected_before_publication(self):
        for target in ("manifest", "scenes"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                args, _ = self.prepare_fixture(Path(temp))
                path = args[target]
                # Even a byte change with identical logical JSON loses freeze identity.
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "published freeze"):
                    prepare(**args)
                self.assertFalse(args["output"].exists())

    def test_unpublished_source_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args, _ = self.prepare_fixture(root)
            substitute = args["scenes"].with_name("unpublished-scenes.jsonl")
            substitute.write_bytes(args["scenes"].read_bytes())
            args["scenes"] = substitute
            with self.assertRaisesRegex(ValueError, "published freeze"):
                prepare(**args)

    def test_options_cannot_overwrite_any_frozen_identity(self):
        forbidden = {"inputs": "other.jsonl", "input_sha256": "f" * 64, "recipe": "semantic",
                     "label": "other", "seed": 7, "packed_mapping_sha256": "f" * 64,
                     "source_manifest_sha256": "f" * 64, "cache_prompt": False}
        for key, value in forbidden.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                args, _ = self.prepare_fixture(Path(temp))
                with self.assertRaisesRegex(ValueError, "overwrite frozen workload identities"):
                    prepare(**args, options={key: value})
                self.assertFalse(args["output"].exists())

    def test_supported_style_option_does_not_change_identity_or_publish_invalid_c0(self):
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.prepare_fixture(Path(temp))
            args["recipe"] = "base-json"
            prepare(**args, options={"style": "natural-dialogue"})
            plan = json.loads((args["output"] / "session-plan.json").read_text(encoding="utf-8"))
            item = plan["workloads"][0]
            self.assertEqual(item["label"], "C0-test")
            self.assertEqual(item["recipe"], "base-json")
            self.assertEqual(item["seed"], 20261008)
            self.assertEqual(item["style"], "natural-dialogue")
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.prepare_fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, "C0"):
                prepare(**args, options={"style": "natural-dialogue"})
            self.assertFalse((args["output"] / "preparation.json").exists())

    def test_worker_token_artifact_packs_and_freezes_correct_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args, scene = self.prepare_fixture(root)
            path, _ = self.token_fixture(root, scene)
            with patch("experiments.translation_flow.v2_prepare.time.perf_counter", side_effect=[10, 10.25]):
                summary = prepare(**args, token_target=4, token_counts_path=path)
            self.assertEqual(summary["batches"], 2)
            mapping = json.loads((args["output"] / "packed-mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(mapping["token_counts"]["sha256"], digest(path))
            self.assertEqual([batch["source_token_count"] for batch in mapping["batches"]], [3, 3])
            record = json.loads((args["output"] / "preparation.json").read_text(encoding="utf-8"))
            self.assertEqual(record["preparation_seconds"], .25)
            self.assertFalse(record["quality_evidence"])

    def test_token_count_incompatible_or_incomplete_provenance_rejected(self):
        mutations = (lambda obj: obj.update(schema="other-schema"),
                     lambda obj: obj.update(complete=False),
                     lambda obj: obj["asset"].update(sha256="f" * 64),
                     lambda obj: obj.pop("template_sha256"),
                     lambda obj: obj.pop("engine_manifest_sha256"),
                     lambda obj: obj["tokenize_parameters"].update(add_special=True),
                     lambda obj: obj["tokenize_parameters"].update(parse_special=False))
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                args, scene = self.prepare_fixture(root)
                path, measured = self.token_fixture(root, scene)
                mutate(measured)
                write_json(path, measured)
                with self.assertRaisesRegex(ValueError, "tokenizer provenance"):
                    prepare(**args, token_target=4, token_counts_path=path)
                self.assertFalse(args["output"].exists())

    def test_token_text_accepted_result_count_or_coverage_mismatch_rejected(self):
        mutations = (lambda obj: obj["attempts"][0].update(source_text_sha256=identity("別の台詞")),
                     lambda obj: obj["attempts"][0].update(status="failed"),
                     lambda obj: obj["attempts"][0].update(tokens=4),
                     lambda obj: obj["cue_token_counts"].update(s1=4),
                     lambda obj: obj["attempts"].pop(0))
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                args, scene = self.prepare_fixture(root)
                path, measured = self.token_fixture(root, scene)
                mutate(measured)
                write_json(path, measured)
                with self.assertRaisesRegex(ValueError, "source text or accepted result changed|coverage differ"):
                    prepare(**args, token_target=4, token_counts_path=path)

    def test_token_counts_require_positive_integer_for_packing(self):
        for value in (0, -1, True, 2.5):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                args, scene = self.prepare_fixture(root)
                path, measured = self.token_fixture(root, scene)
                measured["cue_token_counts"]["s1"] = value
                measured["attempts"][0]["tokens"] = value
                write_json(path, measured)
                with self.assertRaisesRegex(ValueError, "positive counts"):
                    prepare(**args, token_target=4, token_counts_path=path)

    def test_source_freeze_state_version_and_split_role_are_required(self):
        mutations = (lambda obj: obj.update(state="draft"),
                     lambda obj: obj.update(state="frozen_double_fresh_reference_review"),
                     lambda obj: obj.update(version="other-version"),
                     lambda obj: obj.update(role="confirmation"))
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp:
                args, _ = self.prepare_fixture(Path(temp))
                path = args["manifest"].parent / "freeze-manifest.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                mutate(value)
                write_json(path, value)
                with self.assertRaisesRegex(ValueError, "version/state/role"):
                    prepare(**args)
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.prepare_fixture(Path(temp))
            args["split"] = "confirmation"
            with self.assertRaisesRegex(ValueError, "selected split"):
                prepare(**args)

    def test_source_freeze_hash_syntax_and_duplicate_artifacts_rejected(self):
        for value in ("truthy", "A" * 64, "a" * 63):
            with self.subTest(hash=value), tempfile.TemporaryDirectory() as temp:
                args, _ = self.prepare_fixture(Path(temp))
                path = args["manifest"].parent / "freeze-manifest.json"
                obj = json.loads(path.read_text(encoding="utf-8"))
                obj["artifacts"][0]["sha256"] = value
                write_json(path, obj)
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    prepare(**args)
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.prepare_fixture(Path(temp))
            path = args["manifest"].parent / "freeze-manifest.json"
            obj = json.loads(path.read_text(encoding="utf-8"))
            obj["artifacts"].append(deepcopy(obj["artifacts"][0]))
            write_json(path, obj)
            with self.assertRaisesRegex(ValueError, "unique"):
                prepare(**args)

    def qualify_source_fixture(self, root, args):
        path = args["manifest"].parent / "freeze-manifest.json"
        original = root / "original-source-freeze.json"
        original.write_bytes(path.read_bytes())
        accepted = root / "reference-qualification-metadata.json"
        write_json(accepted, {"synthetic_metadata_only": True})
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(state="source_frozen_reference_qualified",
                     original_source_freeze={"path": str(original.resolve()), "sha256": digest(original)},
                     reference_qualification={"path": str(accepted.resolve()), "sha256": digest(accepted),
                                              "version": "hy30-flow-v2-reference-v1",
                                              "state": "frozen_double_fresh_reference_review", "inference_allowed": True})
        write_json(path, value)
        return path, accepted

    def test_unreviewed_source_rejected_for_semantic_evidence_stages(self):
        for stage in ("screening", "confirmation", "full-flow"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                args, _ = self.prepare_fixture(Path(temp))
                args["stage"] = stage
                with self.assertRaisesRegex(ValueError, "engineering qualification only"):
                    prepare(**args)

    def test_qualified_source_accepts_only_bound_approval_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args, _ = self.prepare_fixture(root)
            self.qualify_source_fixture(root, args)
            args["stage"] = "screening"
            prepare(**args)
            self.assertTrue((args["output"] / "preparation.json").exists())
        mutations = (lambda obj: obj["reference_qualification"].update(inference_allowed=False),
                     lambda obj: obj["reference_qualification"].update(state="draft"),
                     lambda obj: obj["reference_qualification"].update(sha256="truthy"),
                     lambda obj: obj.pop("original_source_freeze"))
        for number, mutate in enumerate(mutations):
            with self.subTest(mutation=number), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                args, _ = self.prepare_fixture(root)
                path, _ = self.qualify_source_fixture(root, args)
                obj = json.loads(path.read_text(encoding="utf-8"))
                mutate(obj)
                write_json(path, obj)
                args["stage"] = "screening"
                with self.assertRaisesRegex(ValueError, "qualified source"):
                    prepare(**args)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args, _ = self.prepare_fixture(root)
            _, metadata = self.qualify_source_fixture(root, args)
            metadata.write_bytes(metadata.read_bytes() + b"\n")
            args["stage"] = "screening"
            with self.assertRaisesRegex(ValueError, "approval metadata hash changed"):
                prepare(**args)

    def test_token_provenance_hashes_require_exact_lowercase_sha256(self):
        for field in ("template_sha256", "engine_manifest_sha256", "source_text_sha256"):
            for value in ("truthy", "A" * 64, "a" * 63):
                with self.subTest(field=field, hash=value), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    args, scene = self.prepare_fixture(root)
                    path, measured = self.token_fixture(root, scene)
                    measured[field] = value
                    write_json(path, measured)
                    with self.assertRaisesRegex(ValueError, "tokenizer provenance"):
                        prepare(**args, token_target=4, token_counts_path=path)

    def test_duplicate_token_attempts_and_entire_header_drift_rejected(self):
        for mutation in ("duplicate", "header"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                args, scene = self.prepare_fixture(root)
                path, measured = self.token_fixture(root, scene)
                if mutation == "duplicate":
                    measured["attempts"].append(deepcopy(measured["attempts"][0]))
                else:
                    measured["source_text_sha256"] = "f" * 64
                write_json(path, measured)
                with self.assertRaisesRegex(ValueError, "duplicate|header hash"):
                    prepare(**args, token_target=4, token_counts_path=path)

    def test_larger_token_map_binds_subset_by_per_cue_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, scene = self.prepare_fixture(root)
            path, measured = self.token_fixture(root, scene)
            subset = deepcopy(scene)
            subset["context"] = subset["context"][:1]
            subset["translate_ids"] = ["s1"]
            # Whole-map hash describes both source cues, so cannot equal subset hash.
            self.assertEqual(verified_counts(path, [subset]), {"s1": 3, "s2": 3})
            measured["attempts"][0]["source_text_sha256"] = identity("改変された台詞")
            write_json(path, measured)
            with self.assertRaisesRegex(ValueError, "source text"):
                verified_counts(path, [subset])


class CompleteCommandEvidenceTests(unittest.TestCase):
    def prepared_fixture(self, root):
        prepared = root / "prepared"
        prepared.mkdir()
        write_json(prepared / "session-plan.json", {"schema": "synthetic-plan"})
        write_json(prepared / "packed-mapping.json", {"schema": "synthetic-mapping"})
        write_json(prepared / "preparation.json", {
            "session_plan_sha256": digest(prepared / "session-plan.json"),
            "mapping_sha256": digest(prepared / "packed-mapping.json")})
        return prepared

    def test_complete_command_wall_and_nonzero_exit_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = self.prepared_fixture(root)
            output = root / "run"
            with patch("experiments.translation_flow.v2_execute.subprocess.run",
                       return_value=subprocess.CompletedProcess(args=["synthetic"], returncode=4)) as fake, \
                 patch("experiments.translation_flow.v2_execute.time.perf_counter", side_effect=[100, 125]):
                code = execute(prepared, output, port=8099)
            self.assertEqual(code, 4)
            final = json.loads((output / "command-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(final["returncode"], 4)
            self.assertEqual(final["command_seconds"], 25)
            self.assertIn("pre-load model SHA256", final["measurement_scope"])
            self.assertIn("finished_at_utc", final)
            command = fake.call_args.args[0]
            self.assertEqual(command[command.index("--port") + 1], "8099")
            self.assertEqual(command[command.index("--session-worker") + 1], "experiments.translation_flow.v2_worker")
            self.assertFalse(fake.call_args.kwargs["check"])
            self.assertEqual(final["plan_sha256"], digest(prepared / "session-plan.json"))

    def test_start_failure_and_interruption_preserve_nullable_failure_evidence(self):
        for error in (FileNotFoundError("synthetic launch failure"), KeyboardInterrupt("synthetic interruption")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                prepared = self.prepared_fixture(root)
                output = root / "run"
                with patch("experiments.translation_flow.v2_execute.subprocess.run", side_effect=error) as fake, \
                     patch("experiments.translation_flow.v2_execute.time.perf_counter", side_effect=[100, 102.5]):
                    with self.assertRaises(type(error)):
                        execute(prepared, output)
                final = json.loads((output / "command-completion.json").read_text(encoding="utf-8"))
                self.assertIsNone(final["returncode"])
                self.assertEqual(final["command_seconds"], 2.5)
                self.assertIn(type(error).__name__, final["error"])
                self.assertTrue((output / "command.json").exists())
                self.assertEqual(fake.call_count, 1)

    def test_modified_prepared_plan_or_mapping_never_dispatches(self):
        for name in ("session-plan.json", "packed-mapping.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                prepared = self.prepared_fixture(root)
                path = prepared / name
                path.write_bytes(path.read_bytes() + b"\n")
                with patch("experiments.translation_flow.v2_execute.subprocess.run") as fake:
                    with self.assertRaisesRegex(ValueError, "prepared identities changed"):
                        execute(prepared, root / "run")
                fake.assert_not_called()
                self.assertFalse((root / "run").exists())


if __name__ == "__main__":
    unittest.main()
