"""瓶颈定位（票据 02）：同一翻译配方分别翻译参考日文与产品 ASR 日文，量化 ASR 误差传到中文的比例。

机械层：参考 cue 与产品 cue 按时间重叠连成"单元"（重叠图的连通分量），逐单元算日文 CER 并分桶：
  exact（CER 0）、light（0 < CER ≤ LIGHT_MAX）、heavy（> LIGHT_MAX 且 ASR 有字）、missed（ASR 无字）、
  inserted（参考无字，ASR 多出的语音或幻觉）。
裁判层：profile `v5-asr-pairwise-v1`，输入参考日文与两个盲序中文，输出偏好与各自的错误列表（严重度
minor 1／major 5／critical 10，与 v4 MQM 同权）；参考源中文 vs ASR 源中文。校准：同一候选两份（应平局）、
参考源 seed 对 seed（偏好约 50%）、同一包重判（一致率）。

命令（仓库根目录，python -X utf8 -m experiments.quality_v5.asr_source <子命令>）：
  units     --film F --reference REF.json --asr-ja JA.srt --clean-zh S1 S2 S3 --asr-zh S1 S2 S3 --out U.jsonl
  plan      --units U... --quota exact 60 --quota calib-same 30 ... --out plan.json（只写一次）
  judge     --plan plan.json --units U... --out-dir DIR（消耗配额，退出码 75＝配额耗尽，可续跑）
  estimate  --plan plan.json --units U... --out-dir DIR --out report.json
"""

import argparse
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kototoki_eval.schema import normalize

LIGHT_MAX = 0.25
TIME = r"(\d+):(\d+):(\d+)[,.](\d+)"
BLOCK = re.compile(r"(\d+)\s*\n" + TIME + r"\s*-->\s*" + TIME + r"[^\n]*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def read_srt(path: Path) -> list[dict]:
    """[{index, start, end, text}]；多行以空格相连。"""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for match in BLOCK.finditer(text + "\n\n"):
        g = match.groups()
        to_s = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 10 ** len(ms)  # noqa: E731
        cues.append({"index": int(g[0]), "start": to_s(*g[1:5]), "end": to_s(*g[5:9]),
                     "text": " ".join(line.strip() for line in g[9].strip().split("\n") if line.strip())})
    return cues


def edit_distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def cer(reference: str, hypothesis: str) -> float | None:
    ref, hyp = normalize(reference).text, normalize(hypothesis).text
    if not ref:
        return None
    return edit_distance(ref, hyp) / len(ref)


def overlap_units(reference: list[dict], product: list[dict]) -> list[tuple[list[int], list[int]]]:
    """按时间重叠（交集 > 0）把参考 cue 与产品 cue 连成连通分量，返回 (参考下标, 产品下标) 按时间排序。"""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i in range(len(reference)):
        parent[("r", i)] = ("r", i)
    for j in range(len(product)):
        parent[("p", j)] = ("p", j)
    j0 = 0
    for i, r in enumerate(reference):
        while j0 < len(product) and product[j0]["end"] <= r["start"]:
            j0 += 1
        j = j0
        while j < len(product) and product[j]["start"] < r["end"]:
            if min(r["end"], product[j]["end"]) - max(r["start"], product[j]["start"]) > 0:
                union(("r", i), ("p", j))
            j += 1
    groups: dict = {}
    for node in parent:
        groups.setdefault(find(node), []).append(node)
    units = []
    for nodes in groups.values():
        refs = sorted(i for kind, i in nodes if kind == "r")
        prods = sorted(j for kind, j in nodes if kind == "p")
        units.append((refs, prods))

    def start(unit):
        refs, prods = unit
        return min([reference[i]["start"] for i in refs] + [product[j]["start"] for j in prods])

    return sorted(units, key=start)


@dataclass
class Unit:
    unit_id: str
    film: str
    start: float
    end: float
    ref_ids: list[int]
    asr_ids: list[int]
    ref_ja: str
    asr_ja: str
    cer: float | None
    bucket: str
    clean_zh: list[str] = field(default_factory=list)  # 每个 seed 一份（参考源翻译）
    asr_zh: list[str] = field(default_factory=list)  # 每个 seed 一份（ASR 源翻译）


def bucket_of(ref_ja: str, asr_ja: str, value: float | None) -> str:
    if not normalize(ref_ja).text:
        return "inserted"
    if not normalize(asr_ja).text:
        return "missed"
    if value == 0:
        return "exact"
    return "light" if value <= LIGHT_MAX else "heavy"


def build_units(film: str, reference: list[dict], asr_ja: list[dict], clean_zh: list[list[dict]],
                asr_zh: list[list[dict]]) -> list[Unit]:
    """reference：参考 cue（text 为评分用文本）；clean_zh 与 reference 等长，asr_zh 与 asr_ja 等长（每 seed 一份）。"""
    for doc in clean_zh:
        if len(doc) != len(reference):
            raise ValueError(f"{film}: clean translation has {len(doc)} cues, reference {len(reference)}")
    for doc in asr_zh:
        if len(doc) != len(asr_ja):
            raise ValueError(f"{film}: ASR translation has {len(doc)} cues, ASR source {len(asr_ja)}")
    units = []
    for n, (refs, prods) in enumerate(overlap_units(reference, asr_ja), 1):
        ref_text = "".join(reference[i]["text"] for i in refs)
        asr_text = "".join(asr_ja[j]["text"] for j in prods)
        value = cer(ref_text, asr_text)
        times = [reference[i][k] for i in refs for k in ("start", "end")] + \
                [asr_ja[j][k] for j in prods for k in ("start", "end")]
        units.append(Unit(f"{film}-u{n:04d}", film, min(times), max(times), refs, prods, ref_text, asr_text, value,
                          bucket_of(ref_text, asr_text, value),
                          [" ".join(doc[i]["text"] for i in refs) for doc in clean_zh],
                          [" ".join(doc[j]["text"] for j in prods) for doc in asr_zh]))
    return units


def bucket_table(units: list[Unit]) -> dict:
    table: dict[str, dict] = {}
    for unit in units:
        row = table.setdefault(unit.bucket, {"units": 0, "ref_cues": 0, "ref_chars": 0, "asr_cues": 0})
        row["units"] += 1
        row["ref_cues"] += len(unit.ref_ids)
        row["asr_cues"] += len(unit.asr_ids)
        row["ref_chars"] += len(normalize(unit.ref_ja).text)
    return table


def load_reference(path: Path) -> list[dict]:
    spans = json.loads(path.read_text(encoding="utf-8"))["spans"]
    return [{"index": s["cue_id"], "start": s["start"], "end": s["end"], "text": s["text"]} for s in spans]


# ---------- 裁判层 ----------

PROFILE = "v5-asr-pairwise-v1"
SEVERITY = {"minor": 1, "major": 5, "critical": 10}
PACKET_SIZE = 8
SYSTEM_PROMPT = """你是日译中字幕的翻译质量评审。每个条目给出一段日文字幕原文（这是准确的原文，以它为准），
前后各两条日文作语境（只供理解，不评），以及两个中文候选 A、B。候选可能由不同流程产生，顺序随机，
可能完全相同，也可能为空（空表示观众在这段时间看不到任何中文）。
对每个条目：
1. 分别列出 A、B 相对日文原文的翻译错误（只评原文这一段的内容）：category 取 mistranslation（误译、意思不符，
   包括人名专名译错）、omission（漏译，含整段空白）、addition（增译、原文没有的内容）、terminology（人名专名
   与通行译法不一致）、grammar（语法、不通顺）、other；severity 取 minor（不影响理解）、major（影响理解或明显错误）、
   critical（意思相反或严重误导）。没有错误就给空列表。同一处错误只记一次。
2. 给出 preference：A 更准确、B 更准确，或 tie（同样好或同样差，含两者相同）。
只依据给出的文字判断，不要猜测流程来源。"""
ERROR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["category", "severity", "note"],
                "properties": {"category": {"enum": ["mistranslation", "omission", "addition", "terminology",
                                                     "grammar", "other"]},
                               "severity": {"enum": list(SEVERITY)}, "note": {"type": "string"}}}
RESPONSE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "errors_a", "errors_b", "preference"],
        "properties": {"id": {"type": "string"}, "errors_a": {"type": "array", "items": ERROR_SCHEMA},
                       "errors_b": {"type": "array", "items": ERROR_SCHEMA},
                       "preference": {"enum": ["A", "B", "tie"]}}}}}}
JUDGED_BUCKETS = ("exact", "light", "heavy", "missed")


def read_units(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def context(units: list[dict], index: int) -> tuple[str, str]:
    """前后各两个单元的参考日文（不含被评单元）。"""
    before = [u["ref_ja"] for u in units[max(0, index - 2):index] if u["ref_ja"]]
    after = [u["ref_ja"] for u in units[index + 1:index + 3] if u["ref_ja"]]
    return " ／ ".join(before), " ／ ".join(after)


def plan_items(units_by_film: dict[str, list[dict]], quotas: dict[str, int], seed: int) -> list[dict]:
    """抽样并配对。arm：main（参考源 x vs ASR 源 y，seed 轮换）、calib-same（同一候选两份）、
    calib-seed（参考源 seed k vs k+1）、calib-repeat（main 的一部分原样重判，A／B 顺序不变）。
    每条的 A／B 顺序随机，记录 x 在哪一侧；最后打散到各包。"""
    rng = random.Random(seed)
    pool = [(film, i) for film, units in sorted(units_by_film.items()) for i, _ in enumerate(units)]
    items = []

    def add(arm, film, i, k, x, y, y_label):
        unit = units_by_film[film][i]
        items.append({"arm": arm, "bucket": unit["bucket"], "film": film, "unit": i, "seed_index": k,
                      "x": x, "y": y, "y_label": y_label})

    for bucket in JUDGED_BUCKETS:
        chosen = [x for x in pool if units_by_film[x[0]][x[1]]["bucket"] == bucket]
        rng.shuffle(chosen)
        for n, (film, i) in enumerate(chosen[:quotas.get(bucket, 0)]):
            unit = units_by_film[film][i]
            k = n % len(unit["clean_zh"])
            add("main", film, i, k, unit["clean_zh"][k], unit["asr_zh"][k], "asr")
    text_units = [x for x in pool if units_by_film[x[0]][x[1]]["bucket"] in ("exact", "light", "heavy")]
    for arm in ("calib-same", "calib-seed"):
        rng.shuffle(text_units)
        for n, (film, i) in enumerate(text_units[:quotas.get(arm, 0)]):
            clean = units_by_film[film][i]["clean_zh"]
            k = n % len(clean)
            add(arm, film, i, k, clean[k], clean[k] if arm == "calib-same" else clean[(k + 1) % len(clean)],
                "clean" if arm == "calib-same" else "clean-next")
    for n, item in enumerate(items, 1):
        item["id"] = f"q{n:04d}"
        flip = rng.random() < 0.5
        item["a"], item["b"] = (item["y"], item["x"]) if flip else (item["x"], item["y"])
        item["x_side"] = "B" if flip else "A"
    mains = [item for item in items if item["arm"] == "main"]
    rng.shuffle(mains)
    for n, original in enumerate(mains[:quotas.get("calib-repeat", 0)], len(items) + 1):
        items.append(dict(original, arm="calib-repeat", id=f"q{n:04d}", repeat_of=original["id"]))
    rng.shuffle(items)
    return items


def packet_prompt(items: list[dict], units_by_film: dict[str, list[dict]]) -> str:
    blocks = []
    for item in items:
        units = units_by_film[item["film"]]
        before, after = context(units, item["unit"])
        blocks.append(f"[{item['id']}]\n语境（前）：{before or '（无）'}\n日文原文：{units[item['unit']]['ref_ja']}\n"
                      f"语境（后）：{after or '（无）'}\nA：{item['a'] or '（空）'}\nB：{item['b'] or '（空）'}")
    return "\n\n".join(blocks)


def penalty(errors: list[dict]) -> int:
    return sum(SEVERITY[e["severity"]] for e in errors)


def judge(plan_path: Path, units_by_film: dict[str, list[dict]], out_dir: Path, limit: int | None = None) -> int:
    """按包判分，已有结果的包跳过；配额耗尽返回 75。"""
    from experiments.translation_v3.judge import CliBackend, JudgeBlocked, JudgeInvalid, JudgeTransient
    items = json.loads(plan_path.read_text(encoding="utf-8"))["items"]
    backend = CliBackend(system_prompt=SYSTEM_PROMPT, schema=RESPONSE_SCHEMA)
    out_dir.mkdir(parents=True, exist_ok=True)
    packets = [items[i:i + PACKET_SIZE] for i in range(0, len(items), PACKET_SIZE)]
    done = 0
    for n, packet in enumerate(packets, 1):
        path = out_dir / f"packet-{n:03d}.json"
        if path.exists():
            continue
        if limit is not None and done >= limit:
            break
        prompt = packet_prompt(packet, units_by_film)
        for attempt in range(3):
            try:
                structured, meta = backend(prompt)
                if {r["id"] for r in structured["items"]} != {i["id"] for i in packet}:
                    raise JudgeInvalid("item ids differ")
                break
            except JudgeBlocked as exc:
                (out_dir / "blocked.json").write_text(json.dumps({"packet": n, "error": str(exc)}), encoding="utf-8")
                print(f"blocked at packet {n}")
                return 75
            except (JudgeTransient, JudgeInvalid) as exc:
                print(f"packet {n} attempt {attempt + 1}: {exc}")
        else:
            continue
        path.write_text(json.dumps({"profile": PROFILE, "items": [i["id"] for i in packet], "result": structured,
                                    "meta": meta}, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"packet {n}/{len(packets)} ok ({meta.get('wall_seconds', 0):.0f}s, ${meta.get('total_cost_usd')})",
              flush=True)
    return 0


def collect(plan_path: Path, out_dir: Path) -> list[dict]:
    """把判分结果映射回 x（参考源）／y（对比方）两侧。"""
    items = {i["id"]: i for i in json.loads(plan_path.read_text(encoding="utf-8"))["items"]}
    rows = []
    for path in sorted(out_dir.glob("packet-*.json")):
        for result in json.loads(path.read_text(encoding="utf-8"))["result"]["items"]:
            item = items[result["id"]]
            x_errors, y_errors = ((result["errors_a"], result["errors_b"]) if item["x_side"] == "A"
                                  else (result["errors_b"], result["errors_a"]))
            preference = result["preference"]
            winner = "tie" if preference == "tie" else ("x" if preference == item["x_side"] else "y")
            rows.append({**{k: item[k] for k in ("id", "arm", "bucket", "film", "unit", "seed_index")},
                         "repeat_of": item.get("repeat_of"), "x_errors": x_errors, "y_errors": y_errors,
                         "px": penalty(x_errors), "py": penalty(y_errors), "winner": winner})
    return rows


def mean(values: list) -> float | None:
    return sum(values) / len(values) if values else None


def category_counts(errors: list[dict]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    for e in errors:
        row = counts.setdefault(e["category"], {s: 0 for s in SEVERITY})
        row[e["severity"]] += 1
    return counts


def ratio(sample: dict[str, list[dict]], bucket_units: dict[str, int], buckets: tuple[str, ...]) -> float | None:
    """Σ N_b·mean(py−px)_b ／ Σ N_b·mean(py)_b；分母取全部受判桶。"""
    excess = total = 0.0
    for b, rows in sample.items():
        if not rows:
            continue
        n = bucket_units.get(b, 0)
        total += n * mean([r["py"] for r in rows])
        if b in buckets:
            excess += n * mean([r["py"] - r["px"] for r in rows])
    return excess / total if total else None


def estimate(rows: list[dict], bucket_units: dict[str, int], draws: int = 4000, seed: int = 0) -> dict:
    """分桶外推 ASR 带来的中文错误占比 r（main 臂；N_b 为两部单元数）；bootstrap 在桶内按条目重抽。
    r_all 含 exact 桶（cue 切分与采样差异也算 STT 侧），r_text 只算 light＋heavy＋missed。"""
    main = {b: [r for r in rows if r["arm"] == "main" and r["bucket"] == b] for b in JUDGED_BUCKETS}
    rng = random.Random(seed)
    out = {}
    for name, buckets in (("r_all", JUDGED_BUCKETS), ("r_text", ("light", "heavy", "missed"))):
        stats = sorted(v for v in (ratio({b: [rng.choice(rs) for _ in rs] for b, rs in main.items()},
                                         bucket_units, buckets) for _ in range(draws)) if v is not None)
        out[name] = {"point": ratio(main, bucket_units, buckets),
                     "ci90": [stats[int(0.05 * len(stats))], stats[int(0.95 * len(stats)) - 1]],
                     "ci95": [stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]]}
    out["buckets"] = {b: {"n": len(rs), "units_total": bucket_units.get(b, 0),
                          "mean_px": mean([r["px"] for r in rs]), "mean_py": mean([r["py"] for r in rs]),
                          "pref_x": mean([r["winner"] == "x" for r in rs]),
                          "pref_y": mean([r["winner"] == "y" for r in rs]),
                          "tie": mean([r["winner"] == "tie" for r in rs]),
                          "x_categories": category_counts([e for r in rs for e in r["x_errors"]]),
                          "y_categories": category_counts([e for r in rs for e in r["y_errors"]])}
                      for b, rs in main.items()}
    return out


def calibration(rows: list[dict]) -> dict:
    by_id = {r["id"]: r for r in rows}
    same = [r for r in rows if r["arm"] == "calib-same"]
    seed = [r for r in rows if r["arm"] == "calib-seed"]
    repeat = [(r, by_id[r["repeat_of"]]) for r in rows if r["arm"] == "calib-repeat" and r["repeat_of"] in by_id]
    return {
        "same": {"n": len(same), "tie": mean([r["winner"] == "tie" for r in same]),
                 "pref_x": mean([r["winner"] == "x" for r in same]),
                 "penalty_equal": mean([r["px"] == r["py"] for r in same]),
                 "mean_abs_penalty_diff": mean([abs(r["px"] - r["py"]) for r in same])},
        "seed": {"n": len(seed), "pref_x": mean([r["winner"] == "x" for r in seed]),
                 "pref_y": mean([r["winner"] == "y" for r in seed]), "tie": mean([r["winner"] == "tie" for r in seed]),
                 "mean_delta": mean([r["py"] - r["px"] for r in seed]), "mean_px": mean([r["px"] for r in seed])},
        "repeat": {"n": len(repeat), "winner_agree": mean([a["winner"] == b["winner"] for a, b in repeat]),
                   "mean_abs_diff_px": mean([abs(a["px"] - b["px"]) for a, b in repeat]),
                   "mean_abs_diff_py": mean([abs(a["py"] - b["py"]) for a, b in repeat]),
                   "mean_abs_diff_delta": mean([abs((a["py"] - a["px"]) - (b["py"] - b["px"])) for a, b in repeat])},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ASR 源 vs 参考源翻译对比（票据 02）")
    sub = parser.add_subparsers(dest="command", required=True)
    units = sub.add_parser("units", help="生成单元与分桶")
    units.add_argument("--film", required=True)
    units.add_argument("--reference", type=Path, required=True, help="kototoki_eval 参考 JSON（spans 与 SRT 1:1）")
    units.add_argument("--asr-ja", type=Path, required=True)
    units.add_argument("--clean-zh", type=Path, nargs="+", required=True)
    units.add_argument("--asr-zh", type=Path, nargs="+", required=True)
    units.add_argument("--out", type=Path, required=True)
    plan = sub.add_parser("plan", help="抽样配对并写判分计划（只写一次，已存在拒绝覆盖）")
    plan.add_argument("--units", type=Path, nargs="+", required=True)
    plan.add_argument("--quota", nargs=2, action="append", metavar=("ARM_OR_BUCKET", "N"), required=True)
    plan.add_argument("--seed", type=int, default=20261016)
    plan.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("judge", help="判分（消耗 Claude 配额；退出码 75＝配额耗尽）")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--units", type=Path, nargs="+", required=True)
    run.add_argument("--out-dir", type=Path, required=True)
    run.add_argument("--limit", type=int)
    est = sub.add_parser("estimate", help="校准与 r 的区间估计")
    est.add_argument("--plan", type=Path, required=True)
    est.add_argument("--units", type=Path, nargs="+", required=True)
    est.add_argument("--out-dir", type=Path, required=True)
    est.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "units":
        built = build_units(args.film, load_reference(args.reference), read_srt(args.asr_ja),
                            [read_srt(p) for p in args.clean_zh], [read_srt(p) for p in args.asr_zh])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            for unit in built:
                handle.write(json.dumps(asdict(unit), ensure_ascii=False) + "\n")
        print(json.dumps(bucket_table(built), ensure_ascii=False))
        return 0
    units_by_film = {}
    for path in args.units:
        rows = read_units(path)
        units_by_film[rows[0]["film"]] = rows
    if args.command == "plan":
        if args.out.exists():
            raise SystemExit(f"{args.out} exists; plans are written once")
        items = plan_items(units_by_film, {k: int(v) for k, v in args.quota}, args.seed)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"profile": PROFILE, "seed": args.seed, "light_max": LIGHT_MAX,
                                        "quota": dict(args.quota), "items": items}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"{len(items)} items, {-(-len(items) // PACKET_SIZE)} packets")
        return 0
    if args.command == "judge":
        return judge(args.plan, units_by_film, args.out_dir, args.limit)
    import hashlib
    rows = collect(args.plan, args.out_dir)
    totals: dict[str, int] = {}
    for film_units in units_by_film.values():
        for unit in film_units:
            totals[unit["bucket"]] = totals.get(unit["bucket"], 0) + 1
    report = {"profile": PROFILE, "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
              "judged_items": len(rows), "bucket_units": totals, "calibration": calibration(rows),
              "estimate": estimate(rows, totals)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"calibration": report["calibration"],
                      "r": {k: report["estimate"][k] for k in ("r_all", "r_text")}}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
