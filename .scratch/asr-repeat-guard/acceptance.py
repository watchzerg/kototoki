"""票据 04 的 GPU 验收驱动（计划 §5 第 1、2 项）：产品 asr＋align worker 在 HF II、HF III 上重算，官方 CER 用 v14 的口径。

用法（仓库根目录）：`uv run --locked --offline python -X utf8 .scratch/asr-repeat-guard/acceptance.py`
输入复用对照工作目录的 `audio-16k.wav`（硬链接）与 `vad.json`（原字节复制）；输出在 `.local/asr-repeat-guard/04/`。
报告 `report.json` 只含计数与 CER，不含转写文字。不改任何对照目录。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.asr_robustness_v14 import common, decode, workers  # noqa: E402
from kototoki import artifacts, plan, recipes  # noqa: E402

OUT = common.LOCAL / "asr-repeat-guard" / "04"
EXPECTED = {
    "hf-iii": {"guarded": [51], "action": "collapse", "chars_after": 31, "CER": 13.3973, "S": 769, "D": 448, "I": 304},
    "hf-ii": {"guarded": [], "CER": 16.8073, "S": 876, "D": 676, "I": 260},
}
FILMS = ("hf-ii", "hf-iii")


def main() -> int:
    preflight = common.other_gpu_jobs()
    blocking = [p for p in preflight["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    if preflight["gpu_lock"] or blocking:
        raise SystemExit(f"GPU not free (lock {preflight['gpu_lock']}, processes {blocking}); nothing started")
    works = {}
    for film in FILMS:
        control = common.FILMS[film]["work"]
        work = OUT / film / control.name
        decode.link_audio(work, control)
        shutil.copyfile(control / artifacts.VAD, work / artifacts.VAD)
        for stale in (artifacts.ASR, artifacts.ALIGN, artifacts.FAILURE):
            (work / stale).unlink(missing_ok=True)
        works[film] = work
    order = [works[film] for film in FILMS]
    with common.gpu_lock("asr-repeat-guard ticket 04 acceptance (asr + align, HF II / HF III)"):
        asr_run = workers.run_worker("asr", workers.write_jobs("asr", order, OUT / "jobs-asr.json"), OUT / "logs")
        align_run = workers.run_worker("align", workers.write_jobs("align", order, OUT / "jobs-align.json"), OUT / "logs")

    report = {"recipe": recipes.W0["id"], "w0_recipe_hash": plan.recipe_hash("asr", engine="w0"), "preflight": preflight,
              "asr": {k: asr_run[k] for k in ("exit_code", "wall_s", "vram_peak_mib", "events")},
              "align": {k: align_run[k] for k in ("exit_code", "wall_s", "vram_peak_mib", "events")}, "films": {}}
    passed = True
    for film in FILMS:
        control_dir, work = common.FILMS[film]["work"], works[film]
        control, new = common.read_json(control_dir / artifacts.ASR), common.read_json(work / artifacts.ASR)
        reference = common.load_reference_doc(film)
        before = common.cer_summary(common.official_cer(reference, common.read_json(control_dir / artifacts.ALIGN)))
        after = common.cer_summary(common.official_cer(reference, common.read_json(work / artifacts.ALIGN)))
        guarded = [{"window": i, **trace["guard"], "chars_before": len(control["original_segments"][i]["text"]),
                    "chars_after": len(new["original_segments"][i]["text"])}
                   for i, trace in enumerate(new["asr_traces"]) if trace and "guard" in trace]
        guarded_index = {g["window"] for g in guarded}
        same_windows = len(control["original_segments"]) == len(new["original_segments"])
        differing = [i for i, (a, b) in enumerate(zip(control["original_segments"], new["original_segments"]))
                     if a["text"] != b["text"] and i not in guarded_index]
        expect = EXPECTED[film]
        checks = {
            "same_window_count": same_windows,
            "unguarded_windows_identical_to_control": not differing,
            "guarded_windows_as_expected": [g["window"] for g in guarded] == expect["guarded"],
            "cer_as_expected": all(after[k] == expect[k] for k in ("CER", "S", "D", "I")),
            "no_failed_windows_beyond_control": len(new["failed_windows"]) == len(control["failed_windows"]),
        }
        if film == "hf-iii":
            checks["window_51_collapsed_to_31_chars"] = (
                len(guarded) == 1 and guarded[0]["action"] == expect["action"]
                and guarded[0]["chars_after"] == expect["chars_after"])
        else:
            checks["cer_identical_to_control"] = all(after[k] == before[k] for k in ("CER", "S", "D", "I"))
        passed = passed and all(checks.values())
        report["films"][film] = {
            "windows": len(new["original_segments"]), "guarded": guarded, "differing_unguarded_windows": len(differing),
            "failed_windows": len(new["failed_windows"]), "control_failed_windows": len(control["failed_windows"]),
            "control": before, "new": after, "expected": expect, "checks": checks,
            "asr_identity_recipe_hash": new["identity"]["recipe_hash"],
        }
    report["passed"] = passed
    common.write_json(OUT / "report.json", report)
    for film, row in report["films"].items():
        print(film, "guarded", [(g["window"], g["action"], g["chars_before"], g["chars_after"]) for g in row["guarded"]],
              "differing", row["differing_unguarded_windows"], "new", row["new"], "checks", row["checks"])
    print("asr", report["asr"]["wall_s"], "s", report["asr"]["vram_peak_mib"], "MiB; align", report["align"]["wall_s"], "s",
          report["align"]["vram_peak_mib"], "MiB")
    print("PASSED" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
