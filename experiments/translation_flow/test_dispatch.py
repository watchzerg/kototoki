"""Offline shared-server dispatcher identity and sequential failure checks."""

import argparse
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, read_json, sha
from .dispatch import SCHEMA, execute_dispatch, load_dispatch
from .worker import CANDIDATE, SCHEMA as WORKER_SCHEMA, load_plan


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-dispatch-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.calls = []
        self.dispatch = self.root / "dispatch.json"
        entries = []
        for number in range(3):
            directory = self.root / f"prepared-{number}"
            dump_jsonl(directory / "inputs.jsonl", [{"id": f"w{number}", "source_language": "ja",
                       "target_language": "zh-Hans", "context": [{"id": "c1", "text": "日文。"}], "translate_ids": ["c1"]}])
            dump(directory / "session-plan.json", {"schema": WORKER_SCHEMA, "lane": "P-flow", "stage": "P1",
                 "budgets": {"max_translation_calls": 10, "max_judge_calls": 0,
                             "max_estimated_tokens": 20000, "max_wall_seconds": 60},
                 "workloads": [{"label": "b0-prompt", "inputs": "inputs.jsonl", "input_sha256": sha(directory / "inputs.jsonl"),
                                "recipe": "b0-prompt", "sampling": "official-temperature0", "n_predict": 1024}]})
            entries.append({"label": f"excerpt-{number}", "plan": f"prepared-{number}/session-plan.json",
                            "plan_sha256": sha(directory / "session-plan.json")})
        dump(self.dispatch, {"schema": SCHEMA, "entries": entries})
        self.args = argparse.Namespace(candidate=CANDIDATE, session_plan=self.dispatch,
            output_dir=self.root / "output", server_url="http://127.0.0.1:8080",
            engine_manifest=self.root / "managed-engine.json", context_size=4096,
            asset_manifest=[self.root / "assets.json"], stop_on_oom=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fake_execute(self, args: argparse.Namespace) -> int:
        self.calls.append(deepcopy(args))
        _, loaded = load_plan(args.session_plan)
        args.output_dir.mkdir()
        dump(args.output_dir / "b0-prompt/run.json", {"session_plan_sha256": sha(args.session_plan),
                                                     "settings": loaded[0][0]})
        return 0

    def test_sequential_children_share_server_and_preserve_immutable_settings(self) -> None:
        original = deepcopy(vars(self.args))
        self.assertEqual(execute_dispatch(self.args, execute_fn=self.fake_execute), 0)
        self.assertEqual(vars(self.args), original)
        self.assertEqual([args.output_dir.name for args in self.calls], ["excerpt-0", "excerpt-1", "excerpt-2"])
        for number, child in enumerate(self.calls):
            self.assertEqual(child.session_plan, (self.root / f"prepared-{number}/session-plan.json").resolve())
            for field in ("candidate", "server_url", "engine_manifest", "context_size", "asset_manifest", "stop_on_oom"):
                self.assertEqual(getattr(child, field), getattr(self.args, field))
            state = read_json(child.output_dir / "b0-prompt/run.json")
            self.assertEqual(state["session_plan_sha256"], sha(child.session_plan))
            self.assertEqual(state["settings"]["label"], "b0-prompt")
        completion = read_json(self.args.output_dir / "dispatch-completion.json")
        self.assertTrue(completion["complete"])
        self.assertIsNone(completion["cold_load_seconds"])
        self.assertIsNone(completion["resource_peak"])
        self.assertEqual((self.args.output_dir / "dispatch-plan.json").read_bytes(), self.dispatch.read_bytes())
        self.assertEqual(len(list(self.args.output_dir.glob("excerpt-*"))), 3)

    def test_late_plan_hash_mismatch_rejects_all_before_first_child(self) -> None:
        path = self.root / "prepared-2/session-plan.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "plan hash changed"):
            execute_dispatch(self.args, execute_fn=self.fake_execute)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.output_dir.exists())

    def test_late_source_input_mismatch_rejects_all_before_first_child(self) -> None:
        (self.root / "prepared-2/inputs.jsonl").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Source input hash changed"):
            execute_dispatch(self.args, execute_fn=self.fake_execute)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.output_dir.exists())

    def test_failed_child_stops_and_records_unexecuted_tail(self) -> None:
        def execute(args: argparse.Namespace) -> int:
            self.fake_execute(args)
            return 1 if len(self.calls) == 2 else 0
        self.assertEqual(execute_dispatch(self.args, execute_fn=execute), 1)
        completion = read_json(self.args.output_dir / "dispatch-completion.json")
        self.assertEqual([entry["status"] for entry in completion["entries"]], ["succeeded", "failed", "not_run"])
        self.assertFalse((self.args.output_dir / "excerpt-2").exists())
        self.assertEqual(len(self.calls), 2)

    def test_callback_exception_is_preserved_without_running_tail(self) -> None:
        def execute(args: argparse.Namespace) -> int:
            self.calls.append(deepcopy(args))
            raise RuntimeError("synthetic failure")
        self.assertEqual(execute_dispatch(self.args, execute_fn=execute), 1)
        completion = read_json(self.args.output_dir / "dispatch-completion.json")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(completion["entries"][0]["error_kind"], "RuntimeError")
        self.assertEqual(completion["entries"][0]["error_message"], "synthetic failure")
        self.assertEqual([entry["status"] for entry in completion["entries"][1:]], ["not_run", "not_run"])

    def test_duplicate_unsafe_labels_and_arbitrary_commands_are_rejected(self) -> None:
        original = read_json(self.dispatch)
        for variant in ("duplicate", "unsafe", "command"):
            with self.subTest(variant=variant):
                plan = deepcopy(original)
                if variant == "duplicate":
                    plan["entries"][1]["label"] = plan["entries"][0]["label"]
                elif variant == "unsafe":
                    plan["entries"][0]["label"] = "../escape"
                else:
                    plan["entries"][0]["command"] = "arbitrary"
                dump(self.dispatch, plan)
                with self.assertRaises(ValueError):
                    load_dispatch(self.dispatch)

    def test_source_changes_between_children_stop_before_next_execute(self) -> None:
        def execute(args: argparse.Namespace) -> int:
            self.fake_execute(args)
            if len(self.calls) == 1:
                (self.root / "prepared-1/inputs.jsonl").write_text("{}\n", encoding="utf-8")
            return 0
        self.assertEqual(execute_dispatch(self.args, execute_fn=execute), 1)
        self.assertEqual(len(self.calls), 1)
        completion = read_json(self.args.output_dir / "dispatch-completion.json")
        self.assertEqual([entry["status"] for entry in completion["entries"]], ["succeeded", "failed", "not_run"])

    def test_fresh_output_only(self) -> None:
        self.args.output_dir.mkdir()
        with self.assertRaisesRegex(ValueError, "fresh directory"):
            execute_dispatch(self.args, execute_fn=self.fake_execute)


if __name__ == "__main__":
    unittest.main()
