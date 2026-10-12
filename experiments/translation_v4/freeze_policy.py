"""Write decision-policy-v4.json from calibration/*.json (run once, before any candidate compare).

Usage: python -m experiments.translation_v4.freeze_policy <v4 root>. Refuses to overwrite a frozen policy.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
out = root / "decision-policy-v4.json"
if out.exists():
    sys.exit("already frozen")
power = json.loads((root / "calibration" / "power.json").read_text(encoding="utf-8"))
cal = {k: json.loads((root / "calibration" / f"{k}.json").read_text(encoding="utf-8"))
       for k in ("pair-aa", "pair-bridge", "repeat-noise", "synthetic-detection", "reference-self-check")}
policy = {
    "schema": "hy30-flow-v4-decision-policy-v1",
    "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    "frozen_before_candidate_scores": True,
    "control": "b10-joint",
    "judge_profile": "claude-opus-5-5-mqm-v1",
    "primary_endpoint": "per-cue accuracy penalty (minor 1 / major 5 / critical 10), work-equal, series/movie 50:50",
    "bootstrap": {"unit": "tiled 5-cue window within work (works fixed)", "reps": 10000,
                  "seed": "v4-bootstrap-20261011", "scene_unit_reported": True},
    "alpha": 0.10,
    "alpha_confirm": 0.05,
    "noninferiority_margin": 0.05,
    "critical_margin": 0.002,
    "risk_major_margin": 0.03,
    "stage_A": "continue to half B iff the half-A accuracy delta < 0 (point estimate)",
    "dev_full": ("promising iff one-sided bootstrap p(delta>=0) < alpha (0.10) on dev A+B, every category "
                 "delta <= noninferiority_margin, critical delta <= critical_margin and its CI90 lower bound <= 0, "
                 "risk-set major+ CI90 upper <= risk_major_margin, delivery failures not above control, "
                 "every leave-one-work-out delta < 0"),
    "replication_on_dev": "a promising candidate is re-generated with the dev replicate seeds and must keep delta < 0",
    "confirm": ("at most 3 locked recipes; confirm generated with 3 seeds per scene for each locked recipe and "
                "the control; one-sided p < alpha_confirm with Holm across locked recipes plus the same safety "
                "gates; confirmed recipes are reported, never auto-adopted"),
    "calibration_summary": {"power": power, "aa_delta": cal["pair-aa"]["delta"], "aa_se": cal["pair-aa"]["se"],
                            "bridge_delta": cal["pair-bridge"]["delta"], "bridge_se": cal["pair-bridge"]["se"],
                            "repeat_se": cal["repeat-noise"]["se"],
                            "synthetic_detection_rate": cal["synthetic-detection"]["detection_rate"],
                            "reference_self_accuracy": cal["reference-self-check"]["accuracy"]},
}
text = json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True)
out.write_text(text + "\n", encoding="utf-8")
print(hashlib.sha256((text + "\n").encode()).hexdigest())
