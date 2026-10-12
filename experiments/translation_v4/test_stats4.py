import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import judge as J
from experiments.translation_v3.common import atomic_write_json, sha256_bytes
from experiments.translation_v3.data import ReferenceWindow, WindowMeta
from experiments.translation_v3.test_support import make_scene, write_fake_run

from experiments.translation_v4 import stats4 as S

POLICY = {"noninferiority_margin": 0.05, "critical_margin": 0.002, "risk_major_margin": 0.03, "alpha": 0.05}
WORKS = [("W01", "anime_series"), ("W02", "anime_series"), ("M01", "animation_movie"), ("M02", "animation_movie")]


def layout():
    scenes, windows = [], {}
    for work, category in WORKS:
        for k in range(3):
            scene = make_scene(f"{work}-S{k}", 10, work_id=work, category=category,
                               text="行かない" if k == 0 else None)
            scenes.append(scene)
            for start in (0, 5):
                ids = tuple(scene.ids[start:start + 5])
                meta = WindowMeta(f"{scene.scene_id}-W{start + 1:04d}", scene.scene_id, f"dev-{'A' if k < 2 else 'B'}",
                                  work, work, category, "representative", (), ids)
                units = tuple({"id": i, "ja": c.text, "zh": "参", "confidence": "high", "ambiguity_zh": None}
                              for i, c in zip(scene.ids, scene.cues) if i in ids)
                windows[meta.window_id] = ReferenceWindow(meta, units, tuple({"id": i, "ja": "x", "scored": i in ids}
                                                                            for i in scene.ids))
    return scenes, windows


def write_judgements(run_dir, windows, penalty_of):
    out = run_dir / "judge" / J.PROFILE_ID
    for n, (key, window) in enumerate(sorted(windows.items())):
        cues = {}
        for unit in window.units:
            severity = penalty_of(unit["id"])
            cues[unit["id"]] = {"no_error": severity is None,
                                "errors": [] if severity is None else
                                [{"category": "mistranslation", "severity": severity, "evidence_zh": "x"}]}
        packet = "p" + sha256_bytes(f"{run_dir.name}{key}".encode())[:19]
        atomic_write_json(out / f"{packet}.json", {"packet_id": packet, "profile_hash": J.PROFILE_HASH, "surface": "cli",
                                                   "judgement": {key: cues}})


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scenes, self.windows = layout()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, recipe, penalty_of, seed=1, failed=None):
        run = write_fake_run(self.root, f"{recipe}__s{seed}__dev", self.scenes, seed=seed, scope="dev", failed=failed)
        write_judgements(run, {k: w for k, w in self.windows.items() if w.meta.scene_id not in (failed or set())},
                         penalty_of)
        return run

    def test_better_candidate_and_gates(self):
        self.make("ctrl", lambda c: "major" if c.endswith(("J001", "J004", "J007")) else None)
        self.make("cand", lambda c: "minor" if c.endswith("J001") else None)
        atomic_write_json(self.root / "decision-policy-v4.json", POLICY)
        report = S.compare(self.root, self.windows, "cand", "ctrl", "dev", halves=("A", "B"), reps=500)
        acc = report["accuracy"]
        self.assertAlmostEqual(acc["control"]["overall"], 1.5)
        self.assertAlmostEqual(acc["delta"]["overall"], 0.1 - 1.5)
        self.assertEqual(report["cues"], 120)
        self.assertEqual(report["decision"], "promising")
        self.assertEqual(report["delivery_failed_scenes"]["candidate"], [])
        self.assertGreater(report["risk_major_plus"]["cues"], 0)

    def test_stage_a_and_undelivered(self):
        self.make("ctrl", lambda c: None)
        self.make("cand", lambda c: None, failed={"W01-S0"})
        atomic_write_json(self.root / "decision-policy-v4.json", POLICY)
        report = S.compare(self.root, self.windows, "cand", "ctrl", "dev", halves=("A",), reps=200)
        self.assertEqual(report["cues"], 80)
        # W01: 2 scenes in half A, one undelivered (10 per cue) -> W01 mean 5, series mean 2.5, overall 1.25
        self.assertAlmostEqual(report["accuracy"]["delta"]["overall"], 1.25)
        self.assertEqual(report["decision"], "stop_at_A")
        self.assertFalse(report["gates"]["delivery_not_worse"])

    def test_policy_and_calibration_gates(self):
        self.make("ctrl", lambda c: None)
        self.make("cand", lambda c: None)
        with self.assertRaises(PermissionError):
            S.compare(self.root, self.windows, "cand", "ctrl", "dev", halves=("A",), reps=10)
        with self.assertRaises(PermissionError):
            S.compare(self.root, self.windows, "cand", "ctrl", "dev", halves=("A",), reps=10, calibration=True)

    def test_missing_judgements_insufficient(self):
        self.make("ctrl", lambda c: None)
        run = write_fake_run(self.root, "cand__s1__dev", self.scenes, seed=1, scope="dev")
        atomic_write_json(self.root / "decision-policy-v4.json", POLICY)
        report = S.compare(self.root, self.windows, "cand", "ctrl", "dev", halves=("A",), reps=10)
        self.assertEqual(report["decision"], "insufficient")

    def test_bootstrap_scene_resampling(self):
        cues = {u["id"] for w in self.windows.values() for u in w.units}
        lay = S.Layout(self.windows, cues)
        constant = S.bootstrap({c: 1.0 for c in cues}, lay, reps=50)
        self.assertAlmostEqual(constant["overall"]["se"], 0.0)
        varied = S.bootstrap({c: float(c.startswith("W01-S0")) for c in cues}, lay, reps=300)
        self.assertGreater(varied["overall"]["se"], 0.0)
        self.assertIsNone(varied["animation_movie"]["se"] if varied["animation_movie"]["se"] else None)

    def test_window_bootstrap_with_one_scene_per_work(self):
        first = {s for s in {w.meta.scene_id for w in self.windows.values()} if s.endswith("S0")}
        windows = {k: w for k, w in self.windows.items() if w.meta.scene_id in first}
        cues = {u["id"] for w in windows.values() for u in w.units}
        lay = S.Layout(windows, cues)
        self.assertTrue(all(len(s) == 1 for s in lay.works.values()))
        values = {c: float(int(c[-1]) % 2) for c in cues}
        self.assertEqual(S.bootstrap(values, lay, reps=200, unit="scene")["overall"]["se"], 0.0)
        self.assertGreater(S.bootstrap(values, lay, reps=200)["overall"]["se"], 0.0)


if __name__ == "__main__":
    unittest.main()
