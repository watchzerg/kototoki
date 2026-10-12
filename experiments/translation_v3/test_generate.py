import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v3.generate import load_run_translations, run_generation, run_id_for, scene_state
from experiments.translation_v3.procs import LockError
from experiments.translation_v3.test_support import FakeClient, FakeSessions, make_scene


def quiet(_message: str) -> None:
    pass


class GenerationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scenes = [make_scene(f"S{i}", 7) for i in range(3)]

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, recipe, clients, scenes=None, **kwargs):
        run_id = run_id_for(recipe, 7, "screening")
        sessions = FakeSessions(clients)
        run = run_generation(self.root / "runs" / run_id, recipe, 7, scenes or self.scenes, scope="screening",
                             sources={"x": "1"}, session_factory=sessions, log=quiet, **kwargs)
        return self.root / "runs" / run_id, run, sessions

    def test_complete_run(self):
        client = FakeClient()
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [client])
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertFalse(run["resumed"])
        self.assertTrue(run["performance_comparable"])
        scene = read_json(run_dir / "scenes/S0.json")
        self.assertEqual(scene["translations"]["S0-J006"], "译S0-J006")
        self.assertEqual(scene["positions"]["S0-J005"]["position"], "first")
        self.assertEqual(len(scene["requests"]), 2)
        attempt = scene["requests"][0]["attempts"][0]
        self.assertEqual(attempt["cache_reset_check"]["first_cache_n"], 0)
        self.assertIn("timings", attempt)
        self.assertEqual(client.requests[0]["n_predict"], 4096)
        self.assertEqual(run["recipe_hash"], R.BUILTIN["c0"].recipe_hash)
        self.assertIn("package_sha256", run["code"])
        translations, failed = load_run_translations(run_dir)
        self.assertEqual(len(translations), 21)
        # Rerun does not start a server when everything is written.
        _, _, sessions = self.run_with(R.BUILTIN["c0"], [])
        self.assertEqual(sessions.opened, 0)

    def test_infra_failure_is_not_terminal_and_is_retried(self):
        # Scene 0 uses completions 1-2; completion 3 (scene 1) is an OOM.
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient(plan={3: "oom"})])
        self.assertEqual(run["completion"]["state"], "partial")
        self.assertEqual(run["completion"]["missing_scene_ids"], ["S1", "S2"])
        session = run["sessions"][0]
        self.assertEqual((session["stop_reason"], session["infra_failure"]["kind"]), ("oom", "oom"))
        self.assertFalse((run_dir / "scenes/S1.json").exists())
        evidence = read_json(run_dir / "infra-failures/S1--session-01.json")
        self.assertEqual(len(evidence["requests"][0]["attempts"]), 1)
        self.assertFalse((run_dir / "scenes/S2.json").exists())
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient()])
        self.assertTrue(run["resumed"])
        self.assertFalse(run["performance_comparable"])
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertEqual(run["sessions"][1]["pending_at_start"], ["S1", "S2"])
        self.assertEqual(run["sessions"][1]["index"], 2)

    def test_legacy_infra_scene_file_is_retried(self):
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient()])
        legacy = read_json(run_dir / "scenes/S1.json") | {"status": "failed", "translations": {},
                                                          "failure": {"kind": "oom", "fatal": True}}
        atomic_write_json(run_dir / "scenes/S1.json", legacy)
        self.assertEqual(scene_state(run_dir, "S1"), "infra_failed")
        _, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient()])
        self.assertEqual(run["sessions"][-1]["pending_at_start"], ["S1"])
        self.assertEqual(run["completion"]["state"], "complete")

    def test_first_completion_must_have_empty_cache(self):
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient(first_cache_n=17)])
        self.assertFalse((run_dir / "scenes/S0.json").exists())
        self.assertEqual(run["sessions"][0]["infra_failure"]["kind"], "cache")
        self.assertEqual(run["completion"]["missing_scene_ids"], ["S0", "S1", "S2"])

    def test_lock_or_port_failure_before_start_records_no_session(self):
        def refusing(run_dir, index):
            raise LockError("GPU lock held by live pid 1")
        run_id = run_id_for(R.BUILTIN["c0"], 7, "screening")
        with self.assertRaises(LockError):
            run_generation(self.root / "runs" / run_id, R.BUILTIN["c0"], 7, self.scenes, scope="screening",
                           sources={"x": "1"}, session_factory=refusing, log=quiet)
        self.assertFalse((self.root / "runs" / run_id / "run.json").exists())
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient(plan={3: "oom"})])
        with self.assertRaises(LockError):
            run_generation(run_dir, R.BUILTIN["c0"], 7, self.scenes, scope="screening",
                           sources={"x": "1"}, session_factory=refusing, log=quiet)
        self.assertEqual(len(read_json(run_dir / "run.json")["sessions"]), 1)
        _, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient()])
        self.assertEqual([s["index"] for s in run["sessions"]], [1, 2])
    def test_parse_retry_and_failure(self):
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient(plan={1: "bad_json", 4: "limit", 5: "limit"})])
        first = read_json(run_dir / "scenes/S0.json")
        self.assertEqual(first["status"], "complete")
        self.assertEqual([a["status"] for a in first["requests"][0]["attempts"]], ["failed", "accepted"])
        second = read_json(run_dir / "scenes/S1.json")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["failure"]["kind"], "limit")
        attempts = second["requests"][0]["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertTrue(attempts[0]["stopped_limit"])
        self.assertGreater(attempts[0]["whitespace_ratio"], 0.3)
        self.assertEqual(second["totals"]["limit_failures"], 2)
        self.assertEqual(read_json(run_dir / "scenes/S2.json")["status"], "complete")

    def test_context_budget_is_recorded_without_dispatch(self):
        big = make_scene("BIG", 3, text="長" * 1500)
        run_dir, run, _ = self.run_with(R.BUILTIN["c0"], [FakeClient()], scenes=[big])
        scene = read_json(run_dir / "scenes/BIG.json")
        self.assertEqual(scene["failure"]["kind"], "context")
        self.assertFalse(scene["requests"][0]["attempts"][0]["dispatched"])
        self.assertEqual(len(scene["requests"][0]["attempts"]), 1)

    def test_resume_refuses_changed_recipe(self):
        self.run_with(R.BUILTIN["c0"], [FakeClient(plan={3: "oom"})])
        other = R.compose("c0", "c0", context_before=0)
        with self.assertRaises(ValueError):
            self.run_with(other, [FakeClient()])

    def test_token_terms_review_recipes(self):
        client = FakeClient()
        recipe = R.compose("tok-terms-review", "tok300", preanalysis="terms", review="risk-trigger")
        scenes = [make_scene("S0", 9, text="行かないで台詞")]
        run_dir, run, _ = self.run_with(recipe, [client], scenes=scenes)
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertTrue((run_dir / "token-counts.json").is_file())
        scene = read_json(run_dir / "scenes/S0.json")
        self.assertEqual([t["source"] for t in scene["terms"]["terms"]], ["台詞"])
        self.assertTrue(all(b["review_triggered"] for b in scene["batches"]))
        self.assertTrue(all(v.startswith("审") for v in scene["translations"].values()))
        self.assertEqual(scene["requests"][0]["stage"], "terms")
        self.assertGreater(scene["batches"][0]["terms_injected"], 0)


if __name__ == "__main__":
    unittest.main()
