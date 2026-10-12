"""Offline provenance, scope, interrupted delivery and atomic export checks."""

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import srt
from .cli import APEX_SHA256, digest, export, load_prepared, main, parser, prepare, write_json
from .worker import CANDIDATE


def source_text(count=7):
    return "\n\n".join(
        f"{10 + i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n明日は行きません。{i}"
        for i in range(count)) + "\n"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "ja.srt"
        self.source.write_bytes(source_text().replace("\n", "\r\n").encode("utf-8"))
        self.original = self.source.read_bytes()
        self.prepared = self.root / "prepared"

    def tearDown(self):
        self.temp.cleanup()

    def prepare_args(self, *extra):
        return parser().parse_args([
            "prepare", "--source", str(self.source), "--output", str(self.prepared),
            "--stage", "P0", "--target-size", "3", "--max-translation-calls", "10",
            "--max-judge-calls", "0", "--max-estimated-tokens", "20000",
            "--max-wall-seconds", "60", *extra])

    def make_run(self):
        manifest, document, windows, item = load_prepared(self.prepared)
        run_dir = self.root / "run"
        run_dir.mkdir()
        write_json(run_dir / "run.json", {
            "lane": "P-flow", "candidate": CANDIDATE,
            "input_sha256": manifest["artifacts"]["model-input.jsonl"],
            "session_plan_sha256": manifest["artifacts"]["session-plan.json"],
            "expected_window_ids": [w["id"] for w in windows], "settings": item,
            "asset": {"id": CANDIDATE, "sha256": APEX_SHA256},
            "engine": {"model_sha256": APEX_SHA256},
        })
        (run_dir / "inputs.jsonl").write_bytes((self.prepared / "model-input.jsonl").read_bytes())
        results, ledger = [], []
        for n, window in enumerate(windows):
            translations = {key: f"译文{n}。" for key in window["translate_ids"]}
            raw_dir = run_dir / "transport" / str(n)
            raw_dir.mkdir(parents=True)
            write_json(raw_dir / "response.raw", {"content": translations})
            results.append({"id": window["id"], "translations": translations, "elapsed_seconds": 1.0})
            ledger.append({"window_id": window["id"], "translations": translations,
                           "status": "delivered", "attempts": [{"original_response": str(raw_dir)}]})
        self.write_rows(run_dir / "results.jsonl", results)
        self.write_rows(run_dir / "ledger.jsonl", ledger)
        args = argparse.Namespace(prepared=self.prepared, translation_run=run_dir,
                                  output=self.root / "export")
        return args, document, results, ledger

    def write_rows(self, path, rows):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def test_prepare_preserves_source_identity_tail_batch_and_reference_firewall(self):
        manifest = prepare(self.prepare_args())
        _, doc, windows, _ = load_prepared(self.prepared)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(manifest["source_sha256"], digest(self.source))
        self.assertEqual([len(w["translate_ids"]) for w in windows], [3, 3, 1])
        self.assertEqual(sum(len(w["translate_ids"]) for w in windows), len(doc.cues))
        self.assertTrue(all(set(w) == {"id", "source_language", "target_language", "context", "translate_ids"} for w in windows))
        plan = json.loads((self.prepared / "session-plan.json").read_text())
        self.assertEqual(plan["lane"], "P-flow")
        with self.assertRaises(FileExistsError):
            prepare(self.prepare_args())

    def test_current_defaults_publish_official_cached_output_budget_and_keep_legacy_explicit(self):
        from .recipes import completion_request
        prepare(self.prepare_args())
        _, _, windows, item = load_prepared(self.prepared)
        request = completion_request(item["recipe"], item["sampling"], windows[0], [1],
                                     item["n_predict"], item["seed"])
        self.assertEqual(request["temperature"], .7)
        self.assertEqual(request["top_p"], 1.0)
        self.assertEqual(request["top_k"], 0)
        self.assertEqual(request["repeat_penalty"], 1.0)
        self.assertTrue(request["cache_prompt"])
        self.assertEqual(request["n_predict"], 4096)
        legacy = self.prepare_args("--recipe", "b0", "--sampling", "b0", "--n-predict", "1024")
        self.assertEqual((legacy.recipe, legacy.sampling, legacy.n_predict), ("b0", "b0", 1024))

    def test_excerpt_uses_original_indices_times_and_full_source_sha(self):
        prepare(self.prepare_args("--start-cue", "12", "--end-cue", "15"))
        manifest, document, windows, _ = load_prepared(self.prepared)
        self.assertEqual([c.index for c in document.cues], [12, 13, 14, 15])
        self.assertEqual(document.cues[0].ordinal, 3)
        self.assertEqual(document.source_sha256, digest(self.source))
        self.assertEqual(manifest["scope"]["kind"], "continuous_excerpt")
        self.assertEqual(len({item["id"] for w in windows for item in w["context"]}), 4)
        args, _, _, _ = self.make_run()
        export(args)
        output = srt.read_srt(args.output / "chn.srt")
        self.assertEqual([c.index for c in output.cues], [12, 13, 14, 15])
        self.assertEqual(output.cues[0].start_ms, 2000)

    def test_complete_export_has_original_timing_mapping_and_raw_hashes(self):
        prepare(self.prepare_args())
        args, document, _, _ = self.make_run()
        report = export(args)
        self.assertEqual(report["status"], "complete")
        delivered = srt.read_srt(args.output / "chn.srt")
        self.assertEqual([(c.index_text, c.time_line) for c in delivered.cues],
                         [(c.index_text, c.time_line) for c in document.cues])
        sidecar = json.loads((args.output / "export-sidecar.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["exported_srt_sha256"], digest(args.output / "chn.srt"))
        self.assertEqual(len(sidecar["raw_response_sha256"]), 3)
        self.assertFalse(sidecar["semantic_quality_checked"])
        with self.assertRaises(FileExistsError):
            export(args)

    def test_missing_tail_and_failed_batch_produce_sidecars_without_source_fallback(self):
        prepare(self.prepare_args())
        args, _, results, ledger = self.make_run()
        results = results[:-1]
        results[0]["translations"] = {}
        ledger[0].update(status="translation_failed", translations={})
        self.write_rows(args.translation_run / "results.jsonl", results)
        self.write_rows(args.translation_run / "ledger.jsonl", ledger)
        report = export(args)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(len(report["missing_ids"]), 4)
        self.assertEqual(len(report["missing_batch_ids"]), 1)
        self.assertFalse((args.output / "chn.srt").exists())
        self.assertTrue((args.output / "export-sidecar.json").is_file())

    def test_duplicate_batch_and_result_ledger_conflicts_fail_delivery(self):
        for mode in ("duplicate", "conflict", "reference"):
            with self.subTest(mode=mode):
                if not self.prepared.exists():
                    prepare(self.prepare_args())
                args, _, results, _ = self.make_run()
                if mode == "duplicate":
                    results.append(results[0])
                elif mode == "conflict":
                    results[0]["translations"] = {key: "不同译文" for key in results[0]["translations"]}
                else:
                    results[0]["reference"] = "参考内容不可作为输出"
                self.write_rows(args.translation_run / "results.jsonl", results)
                self.assertEqual(export(args)["status"], "partial")
                self.assertFalse((args.output / "chn.srt").exists())
                # Each subsequent case has independent immutable artifact ownership.
                self.root = self.root / mode
                self.root.mkdir()

    def test_duplicate_json_key_and_absent_artifact_preserve_failure_diagnostics(self):
        prepare(self.prepare_args())
        args, _, _, _ = self.make_run()
        (args.translation_run / "results.jsonl").write_text('{"id":"a","id":"b","translations":{}}\n', encoding="utf-8")
        (args.translation_run / "ledger.jsonl").unlink()
        report = export(args)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(sum(p["reason"] == "unreadable_output_artifact" for p in report["problems"]), 2)
        self.assertFalse((args.output / "chn.srt").exists())

    def test_changed_source_or_inputs_and_wrong_run_identity_are_rejected(self):
        prepare(self.prepare_args())
        args, _, _, _ = self.make_run()
        self.source.write_bytes(self.original + b"\n")
        with self.assertRaisesRegex(ValueError, "source SRT hash"):
            export(args)
        self.source.write_bytes(self.original)
        run = json.loads((args.translation_run / "run.json").read_text())
        run["lane"] = "V2-native-adapted"
        (args.translation_run / "run.json").write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "run identity"):
            export(args)
        (self.prepared / "model-input.jsonl").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            load_prepared(self.prepared)

    def test_interrupted_atomic_publication_leaves_no_final_or_temp_srt(self):
        prepare(self.prepare_args())
        args, _, _, _ = self.make_run()
        with patch("experiments.translation_flow.cli.os.link", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                export(args)
        self.assertFalse((args.output / "chn.srt").exists())
        self.assertEqual(list(args.output.glob(".chn-*.tmp")), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_invalid_bounds_and_missing_explicit_budget_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, "Cue bounds"):
            prepare(self.prepare_args("--start-cue", "99"))
        self.assertFalse(self.prepared.exists())
        with self.assertRaises(SystemExit):
            parser().parse_args(["prepare", "--source", str(self.source), "--output", str(self.prepared)])
        code = main(["prepare", "--source", str(self.source), "--output", str(self.prepared),
                     "--stage", "P0", "--max-translation-calls", "0", "--max-judge-calls", "0",
                     "--max-estimated-tokens", "100", "--max-wall-seconds", "60"])
        self.assertEqual(code, 2)
        self.assertFalse((self.prepared / "prepared.json").exists())


if __name__ == "__main__":
    unittest.main()
