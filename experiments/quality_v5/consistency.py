"""跨批一致性指标（票据 04）：同一作品内，日文人名／专名在中文译文里的译法是否一致。

只看日文源与中文译文，不需要中文参考、不调用模型：
1. 术语候选从日文抽：片假名极大串（≥3 字），以及"汉字名＋敬称"里的汉字名；作品内出现于 ≥3 条 cue。
2. 每个术语的主译法 R1 从译文数据推出：出现该术语的 cue 的中文里，支持最多的"特异"n-gram。
3. 每次出现分 main（含 R1）／alt（含替代译法或 R1 的近形变体）／missing（省略，不计）。
不一致率 = alt / (main + alt)，作品内按出现合并，类别内作品等权。

命令（仓库根目录）：
  python -X utf8 -m experiments.quality_v5.consistency v4 --recipes b10-joint tctx10 ... [--out FILE]
  python -X utf8 -m experiments.quality_v5.consistency srt --pair NAME JA.srt ZH.srt [...] [--out FILE]
"""

import argparse
import json
import random
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

V4_ROOT = Path(".local/translation-evaluation/hy30-flow-v4")
DEV_SEEDS = (20261011, 20261012, 20261013)
REPLICATE_SEEDS = (20261021, 20261022, 20261023)

KATAKANA = re.compile(r"[ァ-ヺー・]+")
HONORIFIC_NAME = re.compile(r"([一-龯々]{1,4})(?:さん|くん|君|ちゃん|様|さま|先輩|先生|殿)")
CJK_RUN = re.compile(r"[一-鿿·・]+")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")
MIN_CUES = 3
NGRAM_MIN, NGRAM_MAX = 2, 6
# 敬称前的单字常是亲属称谓或泛指，不是人名
NOT_NAMES = set("姉兄母父叔伯奥皆嫁婿娘息爺婆王神殿様諸貴皇")
# n-gram 首尾若是虚词，多半带进了相邻语境（"的玩家"／"玩家的"）；结尾是中文敬称时去掉敬称再比
EDGE_STOP = set("的了是把到个这那也在和与吧呢吗啊将被给对为从向让很就都还又说要有不没我你他她它们")
ZH_HONORIFICS = ("大人", "小姐", "同学", "先生", "前辈", "姐姐", "哥哥", "酱", "君", "桑", "殿下", "阁下", "老师")


@dataclass
class TermResult:
    term: str
    occurrences: int
    main: int
    alt: int
    missing: int
    rendering: str | None
    alternatives: list[str] = field(default_factory=list)
    alt_examples: list[dict] = field(default_factory=list)  # 供人工／裁判复核：{index, rendering}


def extract_terms(ja_texts: list[str]) -> dict[str, list[int]]:
    """术语 → 出现的 cue 下标（升序、去重）。只保留出现于 ≥ MIN_CUES 条 cue 的术语。"""
    hits: dict[str, set[int]] = defaultdict(set)
    honorific_only: set[str] = set()
    for index, text in enumerate(ja_texts):
        for run in KATAKANA.findall(text):
            run = run.strip("ー・")
            if len(run.replace("・", "")) >= 3:
                hits[run].add(index)
        for name in HONORIFIC_NAME.findall(text):
            if name in NOT_NAMES:
                continue
            hits[name].add(index)
            if len(name) == 1:
                honorific_only.add(name)
    for name in [t for t in hits if HONORIFIC_NAME.fullmatch(t + "さん") and t not in honorific_only]:
        # ≥2 字的汉字名：作品内不带敬称的出现也计
        hits[name].update(i for i, text in enumerate(ja_texts) if name in text)
    # 去掉总是作为更长术语一部分出现的短术语（例如 "ルシル" 只在 "マルシル" 里）
    terms = {t: s for t, s in hits.items() if len(s) >= MIN_CUES}
    for term in list(terms):
        if any(term != other and term in other and terms[term] <= terms[other] for other in terms):
            del terms[term]
    return {t: sorted(s) for t, s in terms.items()}


def zh_grams(text: str) -> set[str]:
    for honorific in ZH_HONORIFICS:
        text = text.replace(honorific, " ")
    grams = {w.lower() for w in LATIN_WORD.findall(text)}
    for run in CJK_RUN.findall(text):
        for n in range(NGRAM_MIN, NGRAM_MAX + 1):
            for i in range(len(run) - n + 1):
                gram = run[i:i + n]
                if gram[0] not in EDGE_STOP and gram[-1] not in EDGE_STOP:
                    grams.add(gram)
    return grams


def edit_distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def variant_in(rendering: str, text: str) -> str | None:
    """text 中与 rendering 长度相差 ≤1、编辑距离为 1 的子串（音译变体，如 亚丝娜／亚斯娜）；R1 短于 3 字时不找。"""
    if len(rendering) < 3:
        return None
    limit = 1
    for honorific in ZH_HONORIFICS:
        text = text.replace(honorific, " ")
    for n in (len(rendering), len(rendering) - 1, len(rendering) + 1):
        for i in range(len(text) - n + 1):
            piece = text[i:i + n]
            if piece != rendering and CJK_RUN.fullmatch(piece) and edit_distance(piece, rendering) <= limit:
                return piece
    return None


def overlaps(a: str, b: str) -> bool:
    """两个译法共享 ≥2 字的子串即视为同一译法（"防止公会"／"两个公会"），子串关系同理。"""
    if a in b or b in a:
        return True
    return any(a[i:i + 2] in b for i in range(len(a) - 1))


def analyze_term(term: str, occurrence_zh: list[str], background_grams: dict[str, int]) -> TermResult:
    """occurrence_zh：该术语出现的各 cue 的中文；background_grams：作品内不含该术语的 cue 中各 n-gram 的出现 cue 数。"""
    grams = [zh_grams(text) for text in occurrence_zh]
    support: dict[str, int] = defaultdict(int)
    for gs in grams:
        for g in gs:
            support[g] += 1
    specific = {g: k for g, k in support.items() if k >= 2 and background_grams.get(g, 0) <= max(2, 0.5 * k)}
    if not specific:
        return TermResult(term, len(occurrence_zh), 0, 0, len(occurrence_zh), None)
    rendering = max(specific, key=lambda g: (specific[g], len(g), g))
    if any(g != rendering and g in rendering and k >= specific[rendering] and g not in specific
           for g, k in support.items()):
        # R1 的核心（如"网球"之于"打网球"）支持不少于 R1 却不特异：术语是普通名词，R1 只是带了语境字，不计
        return TermResult(term, len(occurrence_zh), 0, 0, len(occurrence_zh), None)
    without = [i for i, gs in enumerate(grams) if rendering not in gs]
    alternatives = []
    for g, k in sorted(specific.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
        if overlaps(g, rendering) or any(overlaps(g, a) for a in alternatives):
            continue
        alone = sum(1 for i in without if g in grams[i])
        if alone >= 2 and (k - alone) <= 0.25 * k and background_grams.get(g, 0) == 0:
            alternatives.append(g)
    main = alt = missing = 0
    examples = []
    for index, (text, gs) in enumerate(zip(occurrence_zh, grams)):
        if rendering in gs:
            main += 1
            continue
        found = next((a for a in alternatives if a in gs), None) or variant_in(rendering, text.lower())
        if found:
            alt += 1
            examples.append({"index": index, "rendering": found})
        else:
            missing += 1
    return TermResult(term, len(occurrence_zh), main, alt, missing, rendering, alternatives, examples)


def analyze_work(cues: list[tuple[str, str]]) -> list[TermResult]:
    """cues：一部作品按时间顺序的 (日文, 中文)。返回计入的术语（main+alt ≥ 2）。"""
    ja = [c[0] for c in cues]
    zh = [c[1] for c in cues]
    all_grams = [zh_grams(text) for text in zh]
    results = []
    for term, indices in extract_terms(ja).items():
        inside = set(indices)
        background: dict[str, int] = defaultdict(int)
        for i, gs in enumerate(all_grams):
            if i not in inside:
                for g in gs:
                    background[g] += 1
        result = analyze_term(term, [zh[i] for i in indices], background)
        for example in result.alt_examples:
            example["cue"] = indices[example.pop("index")]
        if result.main + result.alt >= 2:
            results.append(result)
    return results


def work_summary(results: list[TermResult]) -> dict:
    main = sum(r.main for r in results)
    alt = sum(r.alt for r in results)
    return {"terms": len(results), "main": main, "alt": alt,
            "missing": sum(r.missing for r in results),
            "inconsistency": alt / (main + alt) if main + alt else None,
            "terms_with_alt": sum(1 for r in results if r.alt)}


def category_means(works: dict[str, dict], categories: dict[str, str]) -> dict:
    by_category: dict[str, list[float]] = defaultdict(list)
    for work, summary in works.items():
        if summary["inconsistency"] is not None:
            by_category[categories[work]].append(summary["inconsistency"])
    out = {c: sum(v) / len(v) for c, v in by_category.items()}
    if len(out) > 1:
        out["overall"] = sum(out.values()) / len(out)
    return out


def bootstrap_delta(a: dict[str, list[TermResult]], b: dict[str, list[TermResult]], categories: dict[str, str],
                    draws: int = 2000, seed: int = 0) -> dict:
    """b − a 的不一致率差（类别内作品等权、类别等权）；作品内按术语成对重抽（术语集合由日文决定，两边相同）。"""
    rng = random.Random(seed)
    paired = {}
    for work in a:
        terms_b = {r.term: r for r in b.get(work, [])}
        pairs = [(r, terms_b[r.term]) for r in a[work] if r.term in terms_b]
        if pairs:
            paired[work] = pairs

    def delta(sample: dict[str, list]) -> float | None:
        values: dict[str, list[float]] = defaultdict(list)
        for work, pairs in sample.items():
            ma = sum(p[0].main for p in pairs); aa = sum(p[0].alt for p in pairs)
            mb = sum(p[1].main for p in pairs); ab = sum(p[1].alt for p in pairs)
            if ma + aa and mb + ab:
                values[categories[work]].append(ab / (mb + ab) - aa / (ma + aa))
        means = [sum(v) / len(v) for v in values.values() if v]
        return sum(means) / len(means) if means else None

    point = delta(paired)
    stats = []
    for _ in range(draws):
        sample = {w: [rng.choice(p) for _ in p] for w, p in paired.items()}
        value = delta(sample)
        if value is not None:
            stats.append(value)
    stats.sort()
    mean = sum(stats) / len(stats)
    se = (sum((x - mean) ** 2 for x in stats) / (len(stats) - 1)) ** 0.5
    return {"delta": point, "se": se, "ci90": [stats[int(0.05 * len(stats))], stats[int(0.95 * len(stats)) - 1]],
            "paired_terms": sum(len(p) for p in paired.values())}


# ---------- 数据加载 ----------

def load_set(root: Path, set_name: str) -> list[dict]:
    with open(root / "sets" / set_name / "scenes.jsonl", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_v4_translations(root: Path, recipe: str, seeds: tuple[int, ...], set_name: str = "dev") -> dict[str, str]:
    translations: dict[str, str] = {}
    for seed in seeds:
        scenes = root / "runs" / f"{recipe}__s{seed}__{set_name}" / "scenes"
        for path in sorted(scenes.glob("*.json")):
            translations.update(json.loads(path.read_text(encoding="utf-8")).get("translations") or {})
    return translations


def load_reference(root: Path, set_name: str = "dev") -> dict[str, str]:
    path = root / "evaluation-only" / set_name / "reference" / "cues.jsonl"
    with open(path, encoding="utf-8") as handle:
        return {row["id"]: row["zh"] for row in map(json.loads, handle) if row}


def works_from_set(scenes: list[dict], translations: dict[str, str]) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    works: dict[str, list[tuple[str, str]]] = defaultdict(list)
    categories = {}
    for scene in sorted(scenes, key=lambda s: (s["work_id"], s["source_id"], s["first_srt_number"])):
        categories[scene["work_id"]] = scene["category"]
        works[scene["work_id"]].extend((cue["text"], translations.get(cue["id"], "")) for cue in scene["cues"])
    return dict(works), categories


SRT_BLOCK = re.compile(r"\d+\s*\n[\d:,]+ --> [\d:,]+\s*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def read_srt_texts(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return [block.strip().replace("\n", " ") for block in SRT_BLOCK.findall(text + "\n\n")]


def analyze_set(works: dict[str, list[tuple[str, str]]], categories: dict[str, str]) -> dict:
    results = {w: analyze_work(c) for w, c in works.items()}
    summaries = {w: work_summary(r) for w, r in results.items()}
    return {"results": results, "works": summaries, "categories": category_means(summaries, categories)}


def to_json(analysis: dict) -> dict:
    return {"works": analysis["works"], "categories": analysis["categories"],
            "terms": {w: [asdict(r) for r in rs] for w, rs in analysis["results"].items()}}


PRECISION_PROFILE = "v5-consistency-check-v1"
PRECISION_PROMPT = """你是日译中字幕的术语一致性审核员。每个条目给出：一部作品里的一个日文术语（人名、专名或术语）、
自动指标认定的"主译法"及一条使用主译法的例句，以及一条被指标标为"译法不一致"的例句和被认为是替代译法的字符串。
请判断被标记的例句里，该日文术语是否确实被译成了与主译法不同的写法或译名（观众会看到同一对象有两种叫法），
还是误报（被标记的字符串其实不是该术语的译文、两者只是语境字词不同、或该句其实沿用了主译法／省略了术语）。
只依据给出的文字判断，逐条输出 verdict（inconsistent 或 false_alarm）与一句中文理由。"""
PRECISION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "verdict", "reason"],
        "properties": {"id": {"type": "string"}, "verdict": {"enum": ["inconsistent", "false_alarm"]},
                       "reason": {"type": "string"}}}}}}


def precision_items(analyses: dict[str, tuple[dict, dict[str, list[tuple[str, str]]]]], size: int, seed: int,
                    exclude: set[tuple[str, str, str]] = frozenset()) -> list[dict]:
    """从各 run 的 alt 出现里抽样（按 (作品, 术语, 替代译法) 去重），附主译法例句。"""
    pool = {}
    for run, (analysis, works) in sorted(analyses.items()):
        for work, results in sorted(analysis["results"].items()):
            cues = works[work]
            for result in results:
                indices = extract_terms([c[0] for c in cues])[result.term]
                main_cue = next(i for i in indices if result.rendering in zh_grams(cues[i][1]))
                for example in result.alt_examples:
                    key = (work, result.term, example["rendering"])
                    pool.setdefault(key, {"run": run, "work": work, "term": result.term, "rendering": result.rendering,
                                          "main_ja": cues[main_cue][0], "main_zh": cues[main_cue][1],
                                          "alt": example["rendering"], "alt_ja": cues[example["cue"]][0],
                                          "alt_zh": cues[example["cue"]][1]})
    keys = sorted(k for k in pool if k not in exclude)
    random.Random(seed).shuffle(keys)
    return [{"id": f"c{n:02d}", **pool[k]} for n, k in enumerate(keys[:size], 1)]


def precision_prompt(items: list[dict]) -> str:
    lines = []
    for item in items:
        lines.append(f"[{item['id']}] 术语：{item['term']}　主译法：{item['rendering']}\n"
                     f"  主译法例句：日「{item['main_ja']}」→ 中「{item['main_zh']}」\n"
                     f"  被标记例句：日「{item['alt_ja']}」→ 中「{item['alt_zh']}」　被认为的替代译法：{item['alt']}")
    return "\n\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="跨批一致性指标（离线）")
    sub = parser.add_subparsers(dest="command", required=True)
    v4 = sub.add_parser("v4", help="v4 dev run：每个配方合并 3 个 seed，与第一个配方配对比较")
    v4.add_argument("--root", type=Path, default=V4_ROOT)
    v4.add_argument("--set", dest="set_name", choices=("dev", "confirm"), default="dev")
    v4.add_argument("--recipes", nargs="+", required=True,
                    help="配方名；后缀 @rep 用 dev 重复 seed，#SEED 只用该 seed（confirm 每个 seed 覆盖全集）；reference 表示参考中文")
    v4.add_argument("--out", type=Path)
    precision = sub.add_parser("precision", help="抽样 alt 出现，用 Claude 判断是否真的不一致（消耗配额）")
    precision.add_argument("--root", type=Path, default=V4_ROOT)
    precision.add_argument("--recipes", nargs="+", required=True)
    precision.add_argument("--size", type=int, default=30)
    precision.add_argument("--seed", type=int, default=20261016)
    precision.add_argument("--exclude", type=Path, nargs="*", default=[], help="已判过的 precision 报告，其条目不再抽")
    precision.add_argument("--out", type=Path, required=True)
    srt = sub.add_parser("srt", help="成对的 ja.srt／zh.srt（同条目数），每对视为一部作品")
    srt.add_argument("--pair", nargs=3, action="append", metavar=("NAME", "JA", "ZH"), required=True)
    srt.add_argument("--category", default="film")
    srt.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.command == "precision":
        import hashlib
        from experiments.translation_v3.judge import CliBackend, JudgeBlocked
        scenes = load_set(args.root, "dev")
        analyses = {}
        for name in args.recipes:
            recipe, _, tag = name.partition("@")
            translations = load_v4_translations(args.root, recipe, REPLICATE_SEEDS if tag == "rep" else DEV_SEEDS)
            works, categories = works_from_set(scenes, translations)
            analyses[name] = (analyze_set(works, categories), works)
        exclude = {(i["work"], i["term"], i["alt"]) for path in args.exclude
                   for i in json.loads(path.read_text(encoding="utf-8"))["items"]}
        items = precision_items(analyses, args.size, args.seed, exclude)
        prompt = precision_prompt(items)
        try:
            structured, meta = CliBackend(system_prompt=PRECISION_PROMPT, schema=PRECISION_SCHEMA)(prompt)
        except JudgeBlocked:
            print("judge blocked (quota)")
            return 75
        verdicts = {v["id"]: v for v in structured["items"]}
        for item in items:
            item.update(verdicts.get(item["id"], {"verdict": None, "reason": None}))
        judged = [i for i in items if i["verdict"]]
        hits = sum(1 for i in judged if i["verdict"] == "inconsistent")
        report = {"profile": PRECISION_PROFILE,
                  "system_prompt_sha256": hashlib.sha256(PRECISION_PROMPT.encode("utf-8")).hexdigest(),
                  "recipes": args.recipes, "seed": args.seed, "items": items, "judged": len(judged),
                  "precision": hits / len(judged) if judged else None, "meta": meta}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"judged": len(judged), "inconsistent": hits, "precision": report["precision"],
                          "cost_usd": meta.get("total_cost_usd")}))
        return 0
    if args.command == "v4":
        scenes = load_set(args.root, args.set_name)
        analyses = {}
        for name in args.recipes:
            if name == "reference":
                translations = load_reference(args.root, args.set_name)
            elif "#" in name:
                recipe, _, seed = name.partition("#")
                translations = load_v4_translations(args.root, recipe, (int(seed),), args.set_name)
            else:
                recipe, _, tag = name.partition("@")
                translations = load_v4_translations(args.root, recipe, REPLICATE_SEEDS if tag == "rep" else DEV_SEEDS)
            works, categories = works_from_set(scenes, translations)
            analyses[name] = analyze_set(works, categories)
        control = args.recipes[0]
        report = {"control": control, "recipes": {}}
        for name, analysis in analyses.items():
            entry = {"categories": analysis["categories"], "works": analysis["works"]}
            if name != control:
                entry["delta_vs_control"] = bootstrap_delta(analyses[control]["results"], analysis["results"], categories)
            report["recipes"][name] = entry
            print(name, json.dumps(entry["categories"]), json.dumps(entry.get("delta_vs_control", {})))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            report["terms"] = {n: to_json(a)["terms"] for n, a in analyses.items()}
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        works, categories = {}, {}
        for name, ja_path, zh_path in args.pair:
            ja, zh = read_srt_texts(Path(ja_path)), read_srt_texts(Path(zh_path))
            if len(ja) != len(zh):
                raise SystemExit(f"{name}: cue count differs ({len(ja)} vs {len(zh)})")
            works[name], categories[name] = list(zip(ja, zh)), args.category
        analysis = analyze_set(works, categories)
        for name, summary in analysis["works"].items():
            print(name, json.dumps(summary))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(to_json(analysis), ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
