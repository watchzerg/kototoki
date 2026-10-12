import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import judge as J, stats, synth
from experiments.translation_v3.common import REPO
from experiments.translation_v3.test_support import judgement_for, reference_windows, write_fake_run

MAJOR = [{"category": "mistranslation", "severity": "major", "evidence_zh": "错"}]
CRITICAL = [{"category": "negation-number-condition", "severity": "critical", "evidence_zh": "反"}]
MINOR_FLUENCY = [{"category": "unnatural", "severity": "minor", "evidence_zh": "生硬"}]
POLICY = {"mde": 0.3, "noninferiority_margin": 0.2, "risk_major_margin": 0.5}


def judge_all(run_dir: Path, reference, errors_for=lambda cue_id: [], replicate: int = 0, split="screening"):
    ctx = J.prepare_run(run_dir, reference, split, replicate)
    for packet in ctx.packets:
        payload = ctx.payloads[packet["packet_id"]]
        errors = {c["id"]: errors_for(c["id"]) for w in payload["windows"] for c in w["scored_cues"] if errors_for(c["id"])}
        J.write_result(ctx, packet, payload, J.validate_response(judgement_for(payload, errors), payload), "cli", {})
    return ctx


class SynthTest(unittest.TestCase):
    def test_perturbations(self):
        self.assertEqual(synth.negation_flip("我不去"), "我去")
        self.assertEqual(synth.negation_flip("这是猫"), "这不是猫")
        self.assertIsNone(synth.negation_flip("好"))
        self.assertEqual(synth.number_change("有3个"), "有4个")
        self.assertEqual(synth.number_change("三个人"), "五个人")
        self.assertIsNone(synth.number_change("一起走吧"))
        self.assertEqual(synth.key_info_deletion("我们走吧，去那个很远的城市"), "我们走吧")
        self.assertIsNone(synth.key_info_deletion("好"))

    def test_make_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, scenes = reference_windows()
            base = write_fake_run(root, "c0__s20261008__screening", scenes, translate=lambda k: f"这是第3个，{k}我们不去那里")
            run_dir, manifest = synth.make_synthetic(root, base, reference, split="screen-a", target=6)
            self.assertEqual(manifest["count"], 6)
            self.assertFalse(any(p.name.endswith("manifest.json") for p in run_dir.rglob("*")))
            perturbed = {k for p in manifest["perturbations"] for k in p["cue_ids"]}
            first = manifest["perturbations"][0]
            judge_all(run_dir, reference, lambda k: MAJOR if k in perturbed and k != first["cue_ids"][0] else [], split="screen-a")
            report = synth.detection_report(manifest, J.load_judgements(run_dir)[0])
            self.assertEqual(report["judged"], 6)
            self.assertGreaterEqual(report["detection_rate"], 5 / 6)
            self.assertEqual(report["accuracy_errors_on_untouched"], 0)
            with self.assertRaises(FileExistsError):
                synth.make_synthetic(root, base, reference, split="screen-a", target=6)


BOOTSTRAP_SCRIPT = r"""
import json
from experiments.translation_v3 import stats
from experiments.translation_v3.test_support import reference_windows
reference, _ = reference_windows()
keys = set(reference)  # set iteration order depends on PYTHONHASHSEED
deltas = {k: (len(k) % 7) / 3 - 1 for k in keys}
print(json.dumps(stats.cluster_bootstrap(deltas, reference, reps=300, clusters={"W01": "S", "W02": "S"}), sort_keys=True))
"""


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.reference, self.scenes = reference_windows()

    def tearDown(self):
        self.tmp.cleanup()

    def policy(self, **extra):
        (self.root / stats.POLICY_FILE).write_text(json.dumps(POLICY | extra), encoding="utf-8")

    def runs(self, name, errors_for, *, seeds=(1, 2, 3), failed=None, split="screening"):
        for seed in seeds:
            run = write_fake_run(self.root, f"{name}__s{seed}__screening", self.scenes, seed=seed,
                                 failed=failed if seed == seeds[-1] else None)
            judge_all(run, self.reference, errors_for, split=split)

    def test_penalties_and_work_equal_aggregate(self):
        cue = {"errors": MAJOR + MINOR_FLUENCY + CRITICAL}
        self.assertEqual(stats.cue_scores(cue), {"accuracy": 15, "fluency": 1, "major_plus": 1.0, "critical": 1.0})
        keys = sorted(self.reference)
        values = {k: (1.0 if self.reference[k].meta.work_id == "W01" else 0.0) for k in keys}
        values.pop(next(k for k in keys if self.reference[k].meta.work_id == "W01"))
        result = stats.aggregate(values, self.reference)
        self.assertAlmostEqual(result["anime_series"], 0.5)
        self.assertAlmostEqual(result["animation_movie"], 0.0)
        self.assertAlmostEqual(result["overall"], 0.25)
        self.assertAlmostEqual(result["pooled"], 0.25)

    def test_bootstrap_deterministic_across_hash_seeds_and_series(self):
        outputs = set()
        for hash_seed in ("1", "2", "3"):
            env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(REPO))
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", BOOTSTRAP_SCRIPT], capture_output=True,
                                    cwd=REPO, env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            outputs.add(result.stdout)
        self.assertEqual(len(outputs), 1)
        deltas = {k: (-1.0 if i % 3 else 0.5) for i, k in enumerate(sorted(self.reference))}
        plain = stats.cluster_bootstrap(deltas, self.reference, reps=300)
        series = stats.cluster_bootstrap(deltas, self.reference, reps=300, clusters={"W01": "S", "W02": "S"})
        self.assertEqual(plain, stats.cluster_bootstrap(deltas, self.reference, reps=300))
        self.assertNotEqual(plain["anime_series"], series["anime_series"])
        self.assertEqual(series["clusters"], "series-map")
        h = stats.holm({"x": 0.01, "y": 0.04, "z": 0.03})
        self.assertTrue(h["x"]["reject"])
        self.assertAlmostEqual(h["z"]["p_holm"], 0.06)
        self.assertFalse(h["y"]["reject"])

    def test_policy_required_and_promising(self):
        self.runs("c0", lambda k: MAJOR if k.endswith(("2", "4")) else [])
        self.runs("tok400", lambda k: MAJOR if k.endswith("2") else [])
        with self.assertRaises(PermissionError):
            stats.compare(self.root, self.reference, ["tok400"], "c0", "screen-a", reps=200)
        self.assertEqual(stats.compare(self.root, self.reference, ["c0"], "c0", "screen-a", reps=200)
                         ["candidates"]["c0"]["decision"], "no_policy")
        self.policy(series_clusters={"W01": "S", "W02": "S"})
        row = stats.compare(self.root, self.reference, ["tok400"], "c0", "screen-a", reps=200)["candidates"]["tok400"]
        self.assertEqual(row["decision"], "promising", row.get("reason"))
        self.assertLess(row["primary"]["delta"]["overall"], -0.3)
        self.assertEqual(set(row["per_work_delta"]), {"W01", "W02", "M01", "M02"})
        self.assertTrue(all(v["passes"] for v in row["leave_one_work_out"].values()))
        self.assertEqual(row["primary"]["bootstrap"]["clusters"], "series-map")
        self.assertEqual(row["delivery_failure_rate"], {"candidate": 0.0, "control": 0.0})
        screening = stats.compare(self.root, self.reference, ["tok400"], "c0", "screening", reps=200)["candidates"]["tok400"]
        self.assertEqual(screening["decision"], "promising", screening.get("reason"))

    def test_failed_windows_count_as_critical_and_gate_delivery(self):
        self.policy()
        self.runs("c0", lambda k: MAJOR if k.endswith(("2", "4")) else [])
        self.runs("tok400", lambda k: MAJOR if k.endswith("2") else [], failed={self.scenes[0].scene_id})
        result = stats.run_window_metrics(self.root / "runs/tok400__s3__screening", stats.split_meta(self.reference, "screen-a"))
        self.assertEqual(len(result["undelivered"]), 2)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["metrics"][result["undelivered"][0]],
                         {"accuracy": 10.0, "fluency": 0.0, "major_plus_rate": 1.0, "critical": 5.0})
        row = stats.compare(self.root, self.reference, ["tok400"], "c0", "screen-a", reps=200)["candidates"]["tok400"]
        self.assertGreater(row["delivery_failure_rate"]["candidate"], 0)
        self.assertFalse(row["gates"]["delivery_noninferior"])
        self.assertNotEqual(row["decision"], "promising")

    def test_split_coverage_and_seed_mismatch_are_insufficient(self):
        self.policy()
        self.runs("c0", lambda k: [])
        self.runs("tok400", lambda k: [], split="screen-a")
        row = stats.compare(self.root, self.reference, ["tok400"], "c0", "screening", reps=200)["candidates"]["tok400"]
        self.assertEqual(row["decision"], "insufficient")
        self.assertEqual(len(row["missing_windows"]["tok400__s1__screening"]), 8)
        self.runs("b10", lambda k: [], seeds=(1, 2))
        row = stats.compare(self.root, self.reference, ["b10"], "c0", "screen-a", reps=200)["candidates"]["b10"]
        self.assertEqual(row["decision"], "insufficient")
        self.assertIn("seeds", row["reason"])

    def test_risk_gate_and_leave_one_work_out(self):
        self.policy()
        risk = {u["id"] for w in self.reference.values() if w.meta.selection_type == "risk" for u in w.units}
        w01 = {u["id"] for w in self.reference.values() if w.meta.work_id == "W01" for u in w.units}
        self.runs("c0", lambda k: MAJOR if k.endswith(("2", "4")) and k not in risk else [])
        self.runs("riskbad", lambda k: MAJOR if k in risk else [])
        row = stats.compare(self.root, self.reference, ["riskbad"], "c0", "screening", reps=200)["candidates"]["riskbad"]
        self.assertFalse(row["gates"]["risk_major_upper_within_margin"])
        self.assertTrue(row["gates"]["overall_at_most_minus_mde"])
        self.assertEqual(row["decision"], "insufficient")
        self.runs("c0w", lambda k: MAJOR if k in w01 else [])
        self.runs("onework", lambda k: [])
        row = stats.compare(self.root, self.reference, ["onework"], "c0w", "screen-a", reps=200)["candidates"]["onework"]
        self.assertTrue(row["gates"]["overall_at_most_minus_mde"])
        self.assertFalse(row["leave_one_work_out"]["W01"]["passes"])
        self.assertFalse(row["gates"]["leave_one_work_out"])
        self.assertEqual(row["decision"], "insufficient")
        self.runs("crit", lambda k: CRITICAL if k in risk else [])
        row = stats.compare(self.root, self.reference, ["crit"], "c0", "screening", reps=200)["candidates"]["crit"]
        self.assertFalse(row["gates"]["critical_risk"])

    def test_repeat_noise_on_decision_scale(self):
        for seed in (1, 2):
            run = write_fake_run(self.root, f"c0__s{seed}__screening", self.scenes, seed=seed)
            judge_all(run, self.reference, lambda k: MAJOR if k.endswith("3") else [])
            judge_all(run, self.reference, lambda k: MAJOR if k.endswith(("3", "5" if seed == 1 else "7")) else [], replicate=1)
        report = stats.repeat_noise(stats.find_runs(self.root, "c0", "screening"), stats.split_meta(self.reference, "screening"),
                                    reps=300)
        self.assertEqual(report["runs"], ["c0__s1__screening", "c0__s2__screening"])
        self.assertEqual(report["paired_windows"], 16)
        self.assertGreater(report["major_flip_rate"], 0)
        self.assertIsNotNone(report["aggregate_diff"]["overall"])
        self.assertAlmostEqual(report["suggested_mde"], 2 * report["se"])


if __name__ == "__main__":
    unittest.main()
