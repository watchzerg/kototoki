"""Synthetic frozen source/event projection checks; no inference or judge calls."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json
from .cli import APEX_SHA256, load_prepared, parser, prepare
from .project_evaluation import project
from .srt import read_srt
from .worker import CANDIDATE


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-projection-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.srt"
        text = "\n\n".join(f"{100 + index}\n00:00:{index:02},000 --> 00:00:{index:02},900\n日文{index}。"
                            for index in range(10)) + "\n"
        self.source.write_text(text, encoding="utf-8")
        cues = read_srt(self.source).cues
        self.ids = [f"original-{index}" for index in range(5)]
        self.request = {"id": "window", "context": [{"id": uid, "text": cue.text}
                         for uid, cue in zip(self.ids, cues[2:7])], "translate_ids": self.ids}
        self.ref = {"id": "window", "work": "合成作品", "category": "movie", "scored_ids": self.ids,
                    "units": [{"id": item["id"], "ja": item["text"], "zh": "REFERENCE PRIVATE", "score": True}
                              for item in self.request["context"]]}
        dump_jsonl(self.root / "inputs.jsonl", [self.request])
        dump_jsonl(self.root / "references.jsonl", [self.ref])
        dump(self.root / "corpus.json", {"version": "synthetic"})
        self.plan = {"inputs": "inputs.jsonl", "references": "references.jsonl", "corpus_manifest": "corpus.json",
                     "append_batch_context": True,
                     "windows": [{"window_id": "window", "source_srt": "source.srt",
                                  "cue_map": {uid: cue.id for uid, cue in zip(self.ids, cues[2:7])}}],
                     "candidates": {"c1": [self.make_run("c1", 3)], "c2": [self.make_run("c2", 2)]}}
        self.plan_path = self.root / "plan.json"
        self.output = self.root / "projected"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_run(self, label: str, target_size: int) -> dict:
        prepared_dir, run_dir = self.root / f"{label}-prepared", self.root / f"{label}-run"
        args = parser().parse_args(["prepare", "--source", str(self.source), "--output", str(prepared_dir),
                                   "--target-size", str(target_size), "--stage", "P1", "--max-translation-calls", "20",
                                   "--max-judge-calls", "0", "--max-estimated-tokens", "50000", "--max-wall-seconds", "60"])
        prepare(args)
        manifest, _, windows, workload = load_prepared(prepared_dir)
        run_dir.mkdir()
        dump(run_dir / "run.json", {"lane": "P-flow", "candidate": CANDIDATE,
             "input_sha256": manifest["artifacts"]["model-input.jsonl"],
             "session_plan_sha256": manifest["artifacts"]["session-plan.json"],
             "expected_window_ids": [window["id"] for window in windows], "settings": workload,
             "asset": {"sha256": APEX_SHA256}, "engine": {"model_sha256": APEX_SHA256}})
        (run_dir / "inputs.jsonl").write_bytes((prepared_dir / "model-input.jsonl").read_bytes())
        results, ledger = [], []
        for window in windows:
            translations = {uid: f"{label}译文{uid}。" for uid in window["translate_ids"]}
            results.append({"id": window["id"], "translations": translations, "elapsed_seconds": 3})
            ledger.append({"window_id": window["id"], "translations": translations,
                           "status": "delivered", "elapsed_seconds": 3, "attempts": []})
        dump_jsonl(run_dir / "results.jsonl", results)
        dump_jsonl(run_dir / "ledger.jsonl", ledger)
        return {"prepared": prepared_dir.name, "translation_run": run_dir.name}

    def run_projection(self, prepare_evaluation: bool = True) -> dict:
        dump(self.plan_path, self.plan)
        return project(self.plan_path, self.output, prepare_evaluation=prepare_evaluation)

    def test_projection_preserves_five_scored_ids_and_union_source_context(self) -> None:
        self.run_projection()
        inputs = load_jsonl(self.output / "inputs.jsonl")[0]
        reference = load_jsonl(self.output / "references.jsonl")[0]
        self.assertEqual(inputs["translate_ids"], self.ids)
        self.assertEqual(reference["scored_ids"], self.ids)
        self.assertEqual(len(inputs["context"]), 10)
        self.assertEqual([unit["text"] for unit in inputs["context"]], [cue.text for cue in read_srt(self.source).cues])
        extra = [unit for unit in reference["units"] if not unit["score"]]
        self.assertTrue(extra)
        self.assertTrue(all("zh" not in unit for unit in extra))
        results = load_jsonl(self.output / "c1/results.jsonl")[0]
        self.assertEqual(set(results["translations"]), set(self.ids))
        first_source_id = self.plan["windows"][0]["cue_map"][self.ids[0]]
        self.assertEqual(results["translations"][self.ids[0]], f"c1译文{first_source_id}。")
        self.assertIsNone(results["elapsed_seconds"])
        expected = load_jsonl(self.output / "evaluation/expected.jsonl")
        self.assertEqual(len(expected), 2)
        self.assertTrue(all(row["lane"] == "P-flow" and row["elapsed_seconds"] is None for row in expected))
        packet = read_json(self.output / "evaluation/packets/c1/window.json")
        self.assertEqual(set(packet["reference"]), set(self.ids))
        self.assertNotIn("REFERENCE PRIVATE", (self.root / "c1-prepared/model-input.jsonl").read_text())

    def test_context_extension_can_be_disabled(self) -> None:
        self.plan["append_batch_context"] = False
        self.run_projection()
        self.assertEqual(load_jsonl(self.output / "inputs.jsonl")[0]["context"], self.request["context"])

    def test_source_identity_text_time_and_prepared_changes_are_setup_errors(self) -> None:
        original_plan = deepcopy(self.plan)
        original_bytes = self.source.read_bytes()
        for variant in ("map", "time", "text", "prepared"):
            with self.subTest(variant=variant):
                self.plan = deepcopy(original_plan)
                if variant == "map":
                    self.plan["windows"][0]["cue_map"][self.ids[0]] = "3"
                elif variant == "time":
                    self.source.write_bytes(original_bytes.replace(b"00:00:02,900", b"00:00:02,800"))
                elif variant == "text":
                    self.source.write_text(original_bytes.decode().replace("日文2。", "変更。"), encoding="utf-8")
                else:
                    path = self.root / "c1-prepared/batch-mapping.json"
                    saved = path.read_bytes()
                    path.write_text("{}", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.run_projection()
                self.assertFalse(self.output.exists())
                self.source.write_bytes(original_bytes)
                if variant == "prepared":
                    path.write_bytes(saved)

    def test_duplicate_excerpt_target_coverage_is_rejected(self) -> None:
        self.plan["candidates"]["c1"].append(deepcopy(self.plan["candidates"]["c1"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate source target coverage"):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_missing_candidate_output_never_fabricates_translation_or_time(self) -> None:
        path = self.root / "c1-run/results.jsonl"
        results = load_jsonl(path)
        dump_jsonl(path, [results[0], *results[2:]])
        self.run_projection()
        projected = load_jsonl(self.output / "c1/results.jsonl")[0]
        self.assertEqual(len(projected["translations"]), 2)
        self.assertTrue(all(text.startswith("c1译文") for text in projected["translations"].values()))
        packet = read_json(self.output / "evaluation/packets/c1/window.json")
        self.assertEqual(len(packet["structural"]["missing_ids"]), 3)
        self.assertEqual(packet["structural"]["status"], "partial_delivery")
        self.assertIsNone(projected["elapsed_seconds"])

    def test_conflicting_result_ledger_or_run_identity_cannot_score(self) -> None:
        path = self.root / "c1-run/ledger.jsonl"
        rows = load_jsonl(path)
        first_key = next(iter(rows[0]["translations"]))
        rows[0]["translations"][first_key] = "不同文本"
        dump_jsonl(path, rows)
        with self.assertRaisesRegex(ValueError, "translations conflict"):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_explicit_unexecuted_batches_are_not_delivery_zero(self) -> None:
        run = self.root / "c1-run"
        original = load_jsonl(run / "ledger.jsonl")
        dump_jsonl(run / "results.jsonl", [])
        dump_jsonl(run / "ledger.jsonl", [])
        dump_jsonl(run / "schedule.jsonl", [{"window_id": row["window_id"], "status": "not_run", "reason": "未启动。"}
                                             for row in original])
        self.run_projection()
        expected = [row for row in load_jsonl(self.output / "evaluation/expected.jsonl") if row["candidate_alias"] == "c1"]
        self.assertEqual(expected[0]["structural_status"], "not_run")
        self.assertEqual(load_jsonl(self.output / "c1/results.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
