import json
import os
from dataclasses import replace
import subprocess
import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import judge as J
from experiments.translation_v3.procs import process_created
from experiments.translation_v3.test_support import cli_stdout, judgement_for, reference_windows, write_fake_run


class FakeRunner:
    """Stands in for subprocess.run; replies with queued (stdout, returncode) pairs per call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, cmd, *, input, capture_output, cwd, timeout):
        self.calls.append({"cmd": cmd, "input": input.decode("utf-8"), "cwd": cwd})
        reply = self.replies.pop(0)
        if callable(reply):
            stdout, code = reply(input.decode("utf-8"))
        else:
            stdout, code = reply
        return subprocess.CompletedProcess(cmd, code, stdout, b"")


def answer_from_prompt(prompt: str):
    payload = json.loads(prompt[len(J.USER_PREFIX):])
    return cli_stdout(judgement_for(payload)), 0


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.reference, self.scenes = reference_windows()
        self.run_dir = write_fake_run(self.root, "tok400__s20261008__screening", self.scenes)

    def tearDown(self):
        self.tmp.cleanup()

    def test_packets_are_blind_deterministic_and_shared_across_runs(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        other = write_fake_run(self.root, "c0__s20261009__screening", self.scenes, seed=20261009)
        ctx2 = J.prepare_run(other, self.reference, "screen-a")
        self.assertEqual([p["window_ids"] for p in ctx.packets], [p["window_ids"] for p in ctx2.packets])
        self.assertNotEqual(ctx.packets[0]["packet_id"], ctx2.packets[0]["packet_id"])
        self.assertEqual(sum(len(p["window_ids"]) for p in ctx.packets), 8)
        self.assertTrue(all(len(p["window_ids"]) <= 4 for p in ctx.packets))
        text = J.user_prompt(ctx.payloads[ctx.packets[0]["packet_id"]])
        for leak in ("tok400", "20261008", "screening", "__s"):
            self.assertNotIn(leak, text)
        payload = ctx.payloads[ctx.packets[0]["packet_id"]]
        cue = payload["windows"][0]["scored_cues"][0]
        self.assertEqual(set(cue), {"id", "ja", "reference_zh", "reference_confidence", "acceptable_ambiguity_zh", "candidate_zh"})
        replicate = J.prepare_run(self.run_dir, self.reference, "screen-a", replicate=1)
        self.assertEqual(replicate.out_dir.name, J.PROFILE_ID + "@rep1")
        self.assertEqual(J.prepare_run(self.run_dir, self.reference, "screen-a").packets, ctx.packets)

    def test_undeliverable_windows_are_excluded(self):
        run = write_fake_run(self.root, "b10__s1__screening", self.scenes, failed={self.scenes[0].scene_id})
        ctx = J.prepare_run(run, self.reference, "screening")
        self.assertEqual(len(ctx.undeliverable), 4)
        self.assertEqual(sum(len(p["window_ids"]) for p in ctx.packets), 12)

    def test_validation(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        payload = ctx.payloads[ctx.packets[0]["packet_id"]]
        good = judgement_for(payload, {payload["windows"][0]["scored_cues"][0]["id"]:
                                       [{"category": "omission", "severity": "major", "evidence_zh": "漏了"}]})
        self.assertEqual(len(J.validate_response(good, payload)), len(payload["windows"]))
        bad_cases = []
        missing = json.loads(json.dumps(good)); missing["windows"][0]["cues"].pop(); bad_cases.append(missing)
        dup = json.loads(json.dumps(good)); dup["windows"][0]["cues"][1]["id"] = dup["windows"][0]["cues"][0]["id"]; bad_cases.append(dup)
        enum = json.loads(json.dumps(good)); enum["windows"][0]["cues"][0]["errors"][0]["severity"] = "huge"; bad_cases.append(enum)
        incons = json.loads(json.dumps(good)); incons["windows"][0]["cues"][0]["no_error"] = True; bad_cases.append(incons)
        extra = json.loads(json.dumps(good)); extra["windows"].append({"window_id": "X", "cues": []}); bad_cases.append(extra)
        for case in bad_cases:
            with self.assertRaises(J.JudgeInvalid):
                J.validate_response(case, payload)

    def test_cli_success_and_rerun_only_missing(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screening")
        runner = FakeRunner([answer_from_prompt] * len(ctx.packets))
        backend = J.CliBackend("claude.exe", runner=runner)
        summary = J.judge_run(self.root, ctx, backend, parallel=2, sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["remaining"], 0)
        cmd = runner.calls[0]["cmd"]
        for flag in ("-p", "--safe-mode", "--no-session-persistence", "--json-schema", "--system-prompt"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-opus-5-5")
        self.assertFalse(Path(runner.calls[0]["cwd"]).exists())
        result = json.loads((ctx.out_dir / f"{ctx.packets[0]['packet_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(result["surface"], "cli")
        self.assertEqual(result["meta"]["model_identity"], ["claude-opus-5-5"])
        again = J.judge_run(self.root, ctx, J.CliBackend("claude.exe", runner=FakeRunner([])), sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(again["judged_now"], 0)
        windows, surfaces = J.load_judgements(self.run_dir)
        self.assertEqual((len(windows), surfaces), (16, {"cli"}))

    def test_quota_and_login_exit_75_without_failing_packets(self):
        for stdout in (cli_stdout(is_error=True, status=429, result="API Error: 429 rate limit"),
                       cli_stdout(is_error=True, result="Not logged in · Please run /login")):
            ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
            runner = FakeRunner([(stdout, 1)] * 10)
            summary = J.judge_run(self.root, ctx, J.CliBackend("claude.exe", runner=runner), parallel=1,
                                  sleep=lambda s: None, log=lambda m: None)
            self.assertEqual(summary["exit_code"], J.EXIT_BLOCKED)
            self.assertTrue((self.root / "judge-blocked.json").is_file())
            self.assertEqual(list(ctx.out_dir.glob("*.error.json")), [])
            self.assertEqual(len(runner.calls), 1)
        # Recovery clears the blocked marker.
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        J.judge_run(self.root, ctx, J.CliBackend("c", runner=FakeRunner([answer_from_prompt] * 4)), sleep=lambda s: None, log=lambda m: None)
        self.assertFalse((self.root / "judge-blocked.json").exists())

    def test_transient_retry_then_error_record(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        overloaded = (cli_stdout(is_error=True, status=529, result="Overloaded"), 1)
        sleeps = []
        runner = FakeRunner([overloaded, answer_from_prompt] + [(b"garbage", 1)] * 3)
        summary = J.judge_run(self.root, ctx, J.CliBackend("c", runner=runner), parallel=1,
                              sleep=sleeps.append, log=lambda m: None)
        self.assertEqual(summary["judged_now"], 1)
        self.assertEqual(summary["exit_code"], 1)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(sleeps, [10, 10, 20])
        wrong_model = FakeRunner([lambda p: (cli_stdout(judgement_for(json.loads(p[len(J.USER_PREFIX):])), model="claude-haiku-4"), 0)])
        ctx2 = J.prepare_run(write_fake_run(self.root, "b3__s1__screening", self.scenes), self.reference, "screen-a")
        J.judge_run(self.root, ctx2, J.CliBackend("c", runner=wrong_model), max_packets=1, parallel=1,
                    sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(len(wrong_model.calls), 1)

    def test_export_and_ingest(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        exported = J.export_packets(self.root, ctx)
        self.assertEqual(len(exported), len(ctx.packets))
        md = (self.root / "judge-queue" / f"{exported[0]}.md").read_text(encoding="utf-8")
        self.assertIn(J.SYSTEM_PROMPT, md)
        self.assertNotIn("tok400", md)
        inbox = self.root / "judge-inbox"
        inbox.mkdir()
        good = judgement_for(ctx.payloads[exported[0]])
        (inbox / f"{exported[0]}.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        bad = judgement_for(ctx.payloads[exported[1]]) if len(exported) > 1 else {"windows": []}
        bad["windows"] = bad["windows"][:0]
        if len(exported) > 1:
            (inbox / f"{exported[1]}.json").write_text(json.dumps(bad), encoding="utf-8")
        report = J.ingest_packets(self.root, [J.prepare_run(self.run_dir, self.reference, "screen-a")])
        self.assertEqual(report["accepted"], [exported[0]])
        result = json.loads((ctx.out_dir / f"{exported[0]}.json").read_text(encoding="utf-8"))
        self.assertEqual(result["surface"], "export-ingest")
        self.assertFalse((self.root / "judge-queue" / f"{exported[0]}.md").exists())
        if len(exported) > 1:
            self.assertEqual(report["rejected"], [exported[1]])
            self.assertTrue((inbox / f"{exported[1]}.invalid.json").is_file())

    def test_prompt_v2_profile_and_neighbours(self):
        self.assertEqual(J.PROFILE["prompt_version"], "prompt-v2")
        for phrase in ("不得仅凭参考判错", "同一问题只记一次", "不算 cue-attribution", "音译不算错误", "严重度锚点"):
            self.assertIn(phrase, J.SYSTEM_PROMPT)
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        window = ctx.payloads[ctx.packets[0]["packet_id"]]["windows"][0]
        neighbours = window["neighbor_cues_not_scored"]
        self.assertEqual([n["position"] for n in neighbours], ["before", "after"])
        self.assertTrue(all(n["note"] == "不评分" and n["candidate_zh"].startswith("译") for n in neighbours))
        scored = {c["id"] for c in window["scored_cues"]}
        self.assertFalse(scored & {n["id"] for n in neighbours})

    def test_cli_isolation_flags_and_model_usage(self):
        cmd = J.cli_command("claude")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        J.check_model_usage({"claude-opus-5-5": {"outputTokens": 5}, "claude-haiku-4": {"outputTokens": 0}})
        for usage in ({"claude-opus-5-5": {"outputTokens": 5}, "claude-haiku-4": {"outputTokens": 3}}, {},
                      {"claude-sonnet-5": {"outputTokens": 9}}):
            with self.assertRaises(J.JudgeModelMismatch):
                J.check_model_usage(usage)
        mixed = lambda p: (cli_stdout(judgement_for(json.loads(p[len(J.USER_PREFIX):]))).replace(
            b'"modelUsage": {', b'"modelUsage": {"claude-haiku-4": {"outputTokens": 7}, '), 0)
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        runner = FakeRunner([mixed])
        summary = J.judge_run(self.root, ctx, J.CliBackend("c", runner=runner), max_packets=1, parallel=1,
                              sleep=lambda s: None, log=lambda m: None)
        self.assertEqual((summary["judged_now"], len(runner.calls)), (0, 1))
        # Empty --setting-sources rejected by the CLI -> retry with 'project'.
        rejected = (b"error: option '--setting-sources' argument invalid", 1)
        runner = FakeRunner([rejected, answer_from_prompt])
        backend = J.CliBackend("c", runner=runner)
        J.judge_run(self.root, ctx, backend, max_packets=1, parallel=1, sleep=lambda s: None, log=lambda m: None)
        second = runner.calls[1]["cmd"]
        self.assertEqual(second[second.index("--setting-sources") + 1], "project")
        result = json.loads(J.result_path(ctx, ctx.packets[0]["packet_id"]).read_text(encoding="utf-8"))
        self.assertEqual(result["meta"]["setting_sources"], "project")
        self.assertIn("model_usage", result["meta"])

    def test_concurrent_judge_lock(self):
        ctx = J.prepare_run(self.run_dir, self.reference, "screen-a")
        me = os.getpid()
        (ctx.out_dir / ".lock").write_text(json.dumps({"pid": me, "pid_created": process_created(me)}), encoding="utf-8")
        runner = FakeRunner([])
        summary = J.judge_run(self.root, ctx, J.CliBackend("c", runner=runner), sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(summary["exit_code"], J.EXIT_LOCKED)
        self.assertEqual(runner.calls, [])
        # A dead owner's lock is replaced and recorded.
        (ctx.out_dir / ".lock").write_text(json.dumps({"pid": 2 ** 31 - 3, "pid_created": 1}), encoding="utf-8")
        summary = J.judge_run(self.root, ctx, J.CliBackend("c", runner=FakeRunner([answer_from_prompt] * 2)),
                              sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["replaced_stale_lock"]["pid"], 2 ** 31 - 3)
        self.assertFalse((ctx.out_dir / ".lock").exists())

    def test_confirmation_gates(self):
        confirmation_ref = {k: replace(w, meta=replace(w.meta, split="confirmation")) for k, w in self.reference.items()}
        run = write_fake_run(self.root, "tok400__s1__confirmation", self.scenes, scope="confirmation")
        with self.assertRaises(PermissionError):
            J.prepare_run(run, confirmation_ref, "confirmation")
        locked = self.root / "locked-candidates.json"
        locked.write_text(json.dumps({"recipes": [{"name": "tok400", "recipe_hash": "other"}]}), encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "different recipe_hash"):
            J.prepare_run(run, confirmation_ref, "confirmation")
        locked.write_text(json.dumps({"recipes": [{"name": "tok400", "recipe_hash": "x"}]}), encoding="utf-8")
        ctx = J.prepare_run(run, confirmation_ref, "confirmation")
        self.assertTrue(ctx.confirmation)
        J.export_packets(self.root, ctx)
        self.assertEqual(len(list((self.root / "judge-queue-confirmation").glob("*.md"))), len(ctx.packets))
        self.assertFalse((self.root / "judge-queue").exists())
        # A confirmation result dropped in the screening inbox is rejected.
        packet_id = ctx.packets[0]["packet_id"]
        (self.root / "judge-inbox").mkdir()
        (self.root / "judge-inbox" / f"{packet_id}.json").write_text(json.dumps(judgement_for(ctx.payloads[packet_id])), encoding="utf-8")
        report = J.ingest_packets(self.root, [ctx])
        self.assertEqual(report["rejected"], [packet_id])
        (self.root / "judge-inbox-confirmation").mkdir()
        (self.root / "judge-inbox-confirmation" / f"{packet_id}.json").write_text(json.dumps(judgement_for(ctx.payloads[packet_id])), encoding="utf-8")
        self.assertEqual(J.ingest_packets(self.root, [ctx])["accepted"], [packet_id])
        from experiments.translation_v3.cli import scope_scenes
        from experiments.translation_v3.recipes import BUILTIN
        with self.assertRaises(PermissionError):
            scope_scenes(self.root, BUILTIN["tok400"], "confirmation")


if __name__ == "__main__":
    unittest.main()
