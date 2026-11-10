"""票据 05 C3 翻译影响：日文转写先按专名表统一人名写法，再翻译，中文是否更好。

- **两臂**：`control`＝对照 `ja.srt`（产品 w0 输出）；`candidate`＝票据 04 的纯规则头写法变体 `c3a-entity` 的 `ja.srt`
  （2026-11-10 用户裁定不按有害率条件、直接跑；两部都用 Q3 表：HF II 产品表、HF III 本轮建的表）。
- **翻译**（GPU：一个 Strata session）：产品路径 `kototoki.translate.plan`＋`translate_document`（配方 `q2-degrade-v1`），
  两臂注入同一张表，seed 20261054–56 各翻一次，共 2 臂 × 2 部 × 3 seed＝12 次；已有中文 SRT 的跳过（可续跑）。
  单条仍失败时产品保留日文，计入 `fallback_count`（即交付失败口径）。
- **裁判**（离线，Opus 经 `claude` CLI）：直接复用 `experiments.scene_batching_v6.asr10` 的 `plan`／`judge`／`estimate`
  （裁判 `v5-asr-pairwise-v1`；x＝control、y＝candidate，同 seed，seed 序号在单元上轮转；两侧文字相同的单元不判、按 Δ＝0 计）。
- **不一致率**：`quality_v5.consistency` 整片口径，每臂用自己的 `ja.srt` 配对。

中文与日文文字只写 `.local/asr-robustness-v15/05/`；报告与日志只含计数与指标。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v15 import common

TICKET = "05"
SEEDS = (20261054, 20261055, 20261056)
CONTROL, CANDIDATE = "control", "candidate"
CANDIDATE_ARM_04 = "c3a-entity"
FILM_ID = {"hf-ii": "HF-II", "hf-iii": "HF-III"}  # asr10 的影片键
COMPARISON = f"{CANDIDATE}-vs-{CONTROL}"


def out_dir() -> Path:
    return common.ticket_dir(TICKET)


def judge_root() -> Path:
    """`asr10` 的 root：其下 `zh/<arm>/<FILM>.s<seed>.zh.srt` 与 `judge/<比较名>/`。"""
    return out_dir() / "root"


def ja_path(arm: str, film: str) -> Path:
    if arm == CONTROL:
        return common.FILMS[film]["work"] / "ja.srt"
    return common.ticket_dir("04") / CANDIDATE_ARM_04 / film / "ja.srt"


def runs(films: tuple[str, ...]) -> list[tuple[int, str, str]]:
    return [(seed, film, arm) for seed in SEEDS for film in films for arm in (CONTROL, CANDIDATE)]


def translate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """每臂：次数、回退条数（交付失败口径）、翻译秒数；只含计数。"""
    out: dict[str, Any] = {}
    for arm in (CONTROL, CANDIDATE):
        mine = [r for r in rows if r["arm"] == arm]
        out[arm] = {"runs": len(mine), "fallback_cues": sum(r["fallback_count"] for r in mine),
                    "runs_with_fallback": sum(1 for r in mine if r["fallback_count"]),
                    "seconds": round(sum(r["seconds"] for r in mine), 1),
                    "by_run": {f"{FILM_ID[r['film']]}.s{r['seed']}": r["fallback_count"] for r in mine}}
    return out


def run_translate(films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    """GPU 1 run（一个 Strata session）：12 次产品翻译。"""
    from experiments.asr_robustness_v14 import correct
    from experiments.asr_robustness_v15 import names_replace
    from experiments.scene_batching_v6 import asr10
    from kototoki import config as config_module
    from kototoki import srt, translate
    from kototoki.strata import Session

    root = out_dir() / "strata"
    index = len(list(root.glob("session-*"))) + 1 if root.is_dir() else 1
    session_dir = root / f"session-{index:02d}"
    session_dir.mkdir(parents=True, exist_ok=True)
    for name in ("input", "work"):
        (root / name).mkdir(parents=True, exist_ok=True)
    common.write_text(root / "kototoki.toml", names_replace.CONFIG_TOML)
    config = config_module.load(root / "kototoki.toml")
    tables = {}
    for film in films:
        path, table, fallback = names_replace.table_for(film)
        if fallback:
            raise SystemExit(f"{film}: no Q3 table (ticket 04 names-build must have produced one)")
        tables[film] = (path, table)
    preflight = correct.preflight(session_dir)
    progress = out_dir() / "translate.json"
    rows: list[dict[str, Any]] = common.read_json(progress)["runs"] if progress.is_file() else []
    report: dict[str, Any] = {"recipe": translate.recipes.RECIPE_NAME, "recipe_hash": translate.recipes.RECIPE_HASH,
                              "seeds": list(SEEDS), "films": list(films), "candidate": CANDIDATE_ARM_04,
                              "tables": {f: names_replace.table_summary(*tables[f]) for f in films},
                              "preflight": preflight, "runs": rows}
    started = common.timed()
    with common.gpu_lock("v15-05 C3 translation impact (q2-degrade-v1 on Strata)"):
        session = Session(config)
        try:
            for seed, film, arm in runs(films):
                target = asr10.zh_path(arm, FILM_ID[film], seed, judge_root())
                if target.is_file():
                    continue
                seeded = dataclasses.replace(config, translate=dataclasses.replace(config.translate, seed=seed))
                document = srt.read_srt(ja_path(arm, film))
                plan = translate.plan(out_dir() / "work" / arm / film, document, tables[film][1], seeded)
                began = common.timed()
                result = translate.translate_document(plan, session)
                common.write_text(target, srt.render_srt(document, result.translations))
                rows.append({"arm": arm, "film": film, "seed": seed, "cues": len(document.cues),
                             "fallback_count": result.fallback_count, "seconds": round(common.timed() - began, 1),
                             "names_rows": len(plan.names), "run_dir": plan.relative})
                common.write_json(progress, report)
            report["sessions"] = session.ordinal
        finally:
            session.stop()
    report["wall_s"] = round(common.timed() - started, 1)
    report["vram_used_after_stop_mib"] = common.v14.vram_used_mib()
    report["summary"] = translate_summary(rows)
    common.write_json(progress, report)
    common.write_json(root / f"run-{index:02d}.json", {k: v for k, v in report.items() if k != "runs"})
    return {k: v for k, v in report.items() if k != "runs"}


def judge_plan() -> dict[str, Any]:
    from experiments.scene_batching_v6 import asr10, v11

    path = asr10.plan(CONTROL, CANDIDATE, v11.PRODUCT_QUOTAS, root=judge_root(), seeds=SEEDS, skip_identical=True)
    plan = common.read_json(path)
    return {"plan": str(path), "to_judge": len(plan["items"]), "identical": len(plan["identical"])}


def judge() -> int:
    from experiments.scene_batching_v6 import asr10

    return asr10.judge(COMPARISON, root=judge_root())


def inconsistency() -> dict[str, Any]:
    """每臂的中文与**该臂自己的**日文配对（`asr10.inconsistency` 固定用对照日文，这里不用它）。"""
    from experiments.quality_v5 import asr_source, consistency
    from experiments.scene_batching_v6 import asr10

    out: dict[str, Any] = {}
    for arm in (CONTROL, CANDIDATE):
        rows = {}
        for film, film_id in FILM_ID.items():
            ja = consistency.read_srt_texts(ja_path(arm, film))
            for seed in SEEDS:
                zh = asr10.cue_texts(arm, film_id, seed, judge_root())
                rows[f"{film_id}.s{seed}"] = consistency.work_summary(consistency.analyze_work(list(zip(ja, zh))))
        values = [r["inconsistency"] for r in rows.values() if r["inconsistency"] is not None]
        out[arm] = {"runs": rows, "mean_inconsistency": asr_source.mean(values)}
    common.write_json(out_dir() / "inconsistency.json", out)
    return out


def judge_cost() -> dict[str, Any]:
    packets = sorted((judge_root() / "judge" / COMPARISON / "packets").glob("packet-*.json"))
    metas = [common.read_json(p).get("meta") or {} for p in packets]
    return {"packets": len(packets), "usd": round(sum(m.get("total_cost_usd") or 0 for m in metas), 2),
            "wall_seconds": round(sum(m.get("wall_seconds") or 0 for m in metas), 1)}


def touched() -> dict[str, Any]:
    """事后切分（非预先登记）：按单元是否含被改写的 cue 分两组，各出全体桶的估计。"""
    from experiments.quality_v5 import asr_source
    from experiments.scene_batching_v6 import asr10
    from kototoki import srt

    folder = judge_root() / "judge" / COMPARISON
    rows = asr_source.collect(folder / "plan.json", folder / "packets")
    identical = common.read_json(folder / "plan.json")["identical"]
    units = asr10.load_units()
    changed = {}
    for film in FILM_ID:
        pairs = zip(srt.read_srt(ja_path(CONTROL, film)).cues, srt.read_srt(ja_path(CANDIDATE, film)).cues)
        changed[film] = {i for i, (x, y) in enumerate(pairs) if x.text != y.text}

    def hit(row: dict[str, Any]) -> bool:
        return bool(set(units[row["film"]][row["unit"]]["asr_ids"]) & changed[row["film"]])

    keys = ("n", "n_judged", "n_identical", "delta", "ci90", "pref_control", "pref_candidate", "critical",
            "addition", "name_errors", "name_error_delta_ci90", "by_film_delta")
    out = {}
    for name, want in (("touched", True), ("untouched", False)):
        bucket = asr10.summarize(name, [r for r in rows if hit(r) is want],
                                 [u for u in identical if hit(u) is want])["buckets"]["all"]
        out[name] = {k: bucket[k] for k in keys}
    common.write_json(out_dir() / "touched.json", out)
    return out


def report() -> dict[str, Any]:
    """裁判估计（全体与各桶 Δ、CI90、人名错误、critical／addition）、不一致率、交付失败、成本。"""
    from experiments.scene_batching_v6 import asr10

    translated = common.read_json(out_dir() / "translate.json")
    incons = inconsistency()
    out = {"estimate": asr10.estimate(COMPARISON, root=judge_root()),
           "inconsistency": {arm: {"mean": incons[arm]["mean_inconsistency"],
                                   "by_run": {k: r["inconsistency"] for k, r in incons[arm]["runs"].items()}}
                             for arm in incons},
           "touched": touched(),
           "translate": translate_summary(translated["runs"]), "wall_s": translated.get("wall_s"),
           "judge_cost": judge_cost()}
    common.write_json(out_dir() / "report.json", out)
    return out
