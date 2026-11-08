"""v13: the names table built on Strata + Qwen3.8-Flash-Next (docs/research/2026-11-08-names-on-strata-v13.md).

S1 (``names-strata-v1``) is the product ``BUILD`` recipe unchanged except for what the engine forces (§4.0): the model
is Strata's ``qwen3.8-flash-next-iq3_s`` (plain ``strata launch``, Q2 start), the request carries no
``response_format`` (Strata would rewrite the prompt) and states ``enable_thinking: false``, and the prompt-budget
check counts the system and user texts with ``/v1/messages/count_tokens`` (no ``/tokenize`` on Strata). The table is
built by the product ``kototoki.names.table.build_table`` itself (imported, not changed) through two callbacks
(``NamesClient.chat`` / ``NamesClient.tokenize``); ``BUILD_RECIPE_HASH`` is untouched.

Layout under ``.local/names-on-strata-v13``:

* ``B/`` builds (ticket 02): ``B/product/<film>/name-table.json`` (first build, used), ``B/product-aa/<film>/...``
  (second build, A/A only), ``B/E/dev-name-tables.json`` (the v10 layout, so ``names11`` readers apply),
  ``B/build-report.json`` (counts only), ``B/gate.json``, ``B/runtime/`` (Strata session evidence);
* ``C/`` table quality (ticket 03): ``C/{27b,s1}/02-table-agreement.json`` (``names11.table_reference_agreement``),
  ``C/table-quality.json``;
* dev translation (ticket 04, v9/v11 layout): ``recipes/``, ``runs/<arm>__s<seed>__dev``, ``checks/``, ``summaries/``;
* product translation (ticket 05, ``asr10`` layout): ``E/root`` (recipes, ``translate-srt`` deliveries),
  ``E/zh/<arm>/<film>.s<seed>.zh.srt``, ``E/judge/<y>-vs-<x>/``.

Arms: T0 ``q2-names-27b`` = Q2 + the 27B tables (dev: v10 ``E/dev-name-tables.json``; product:
``.local/name-consistency-product``), T1 ``q2-names-s1`` = Q2 + the S1 tables; both written by ``write_q2`` (the
ADR-0017 rule: high entries only, ``filter: window``, ``strata_recipe_data(..., launch="default")``).

Tables and translations are transcript content: they stay under ``.local``; reports hold counts only.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import random
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from experiments.translation_v3 import strata
from experiments.translation_v3.common import REPO, atomic_write_json, read_json
from experiments.translation_v3.recipes import load_recipe

from . import asr10, names11, v9, v10, v11, v12
from .brief10 import dev_lines
from .names10 import NAMES_SEED, document

V13_ROOT = REPO / ".local/names-on-strata-v13"
B_ROOT = V13_ROOT / "B"
C_ROOT = V13_ROOT / "C"
E_ROOT = V13_ROOT / "E"
T0, T1 = "q2-names-27b", "q2-names-s1"
S1_NAME = "names-strata-v1"
MAIN_SEEDS = v9.MAIN_SEEDS
PRODUCT_SEEDS = v11.PRODUCT_SEEDS
FILMS = asr10.FILMS
PORT = 8080
BASE = f"http://127.0.0.1:{PORT}"
MIN_AVAILABLE_RAM_GIB = 52.0
# observed on the Q2 smokes of 2026-11-08 (kv int8, DFlash2); checked after the probe, part of the S1 identity
EXPECTED_KV = "int8"
COUNT_TOKENS = "/v1/messages/count_tokens"
GATE_MAX_FIRST_FAIL = 2
BOOT_DRAWS = 4000
# response keys Strata is known to return; anything else (a warning about an ignored field) is recorded
KNOWN_RESPONSE_KEYS = {"id", "object", "created", "model", "choices", "usage", "timings", "system_fingerprint"}


# --- S1 identity --------------------------------------------------------------------------------

def s1_recipe() -> dict[str, Any]:
    """The S1 build recipe: product ``BUILD`` without its llama.cpp model asset, plus the Strata identity and the
    request changes of §4.0."""
    from kototoki.names.recipes import BUILD
    return {"name": S1_NAME,
            "build": {k: v for k, v in BUILD.items() if k != "model_asset"},
            "model": strata.MODEL,
            "runtime": {"strata": strata.STRATA_VERSION, "engine_build": strata.ENGINE_BUILD,
                        "launch": strata.DEFAULT_LAUNCH, "resolved": dict(strata.DEFAULT_RESOLVED), "kv": EXPECTED_KV},
            "request": {"response_format": None, "chat_template_kwargs": {"enable_thinking": False},
                        "model": strata.MODEL},
            "prompt_budget_check": {"endpoint": COUNT_TOKENS, "segments": ["system", "user"], "sum": True,
                                    "fallback": "no precheck; usage.prompt_tokens recorded, over budget flagged"}}


def s1_hash() -> str:
    from kototoki.recipes import recipe_hash
    return recipe_hash(s1_recipe())


# --- Strata client for build_table ----------------------------------------------------------------

def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def strata_body(body: dict[str, Any]) -> dict[str, Any]:
    """The product request body (``table._request_body``) as S1 sends it: no ``response_format``, the Strata model,
    thinking stated off."""
    if (body.get("chat_template_kwargs") or {}).get("enable_thinking") is not False:
        raise ValueError("S1 requests must state enable_thinking: false")
    if type(body.get("seed")) is not int or body["seed"] <= 0:
        raise ValueError("Strata takes only a positive integer seed")
    return {k: v for k, v in body.items() if k != "response_format"} | {"model": strata.MODEL}


class NamesClient:
    """``chat`` / ``tokenize`` callbacks of ``build_table`` on Strata, recording counts per request (no text)."""

    def __init__(self, base: str = BASE, *, post: Callable[[str, dict, float], dict] = _post, timeout: float = 900.0):
        self.base, self.post, self.timeout = base, post, timeout
        self.requests: list[dict[str, Any]] = []
        self.counts: list[int] = []
        self.count_tokens_ok: bool | None = None
        self.count_tokens_error: str | None = None

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        sent = strata_body(body)
        from kototoki.names.table import SAMPLING
        record: dict[str, Any] = {"seed": sent["seed"], "keys": sorted(sent),
                                  "sampling": {k: sent.get(k) for k in SAMPLING}, "max_tokens": sent.get("max_tokens")}
        self.requests.append(record)
        started = perf_counter()
        try:
            response = self.post(self.base + "/v1/chat/completions", sent, self.timeout)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            record.update(seconds=perf_counter() - started, http_status=exc.code, error=detail[:300])
            raise
        record["seconds"] = perf_counter() - started
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content, reasoning = message.get("content"), message.get("reasoning_content")
        usage = response.get("usage") or {}
        record.update(finish_reason=choice.get("finish_reason"), prompt_tokens=usage.get("prompt_tokens"),
                      completion_tokens=usage.get("completion_tokens"),
                      content_chars=len(content) if isinstance(content, str) else None,
                      reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
                      think_tag=isinstance(content, str) and "<think>" in content,
                      error=None if response.get("error") is None else str(response["error"])[:300],
                      extra_response_keys=sorted(set(response) - KNOWN_RESPONSE_KEYS))
        return response

    def tokenize(self, text: str) -> int:
        """Tokens of one prompt segment by ``/v1/messages/count_tokens`` (rendered as one user message); when the
        endpoint is unusable, 0 from then on (no precheck, §4.0 fallback)."""
        if self.count_tokens_ok is False:
            return 0
        try:
            n = self.post(self.base + COUNT_TOKENS, {"model": strata.MODEL,
                                                     "messages": [{"role": "user", "content": text}]}, self.timeout)
            n = n["input_tokens"]
            if type(n) is not int:
                raise ValueError(f"input_tokens is {type(n).__name__}")
        except (HTTPError, URLError, KeyError, ValueError, TypeError) as exc:
            self.count_tokens_ok, self.count_tokens_error = False, f"{type(exc).__name__}: {exc}"[:300]
            return 0
        self.count_tokens_ok = True
        self.counts.append(n)
        return n


# --- building ------------------------------------------------------------------------------------

def build_record(result: Any, requests: list[dict[str, Any]], counts: list[int], seconds: float,
                 peak: dict[str, Any] | None, client: NamesClient) -> dict[str, Any]:
    """Counts of one build (no table content)."""
    from kototoki.names.table import PROMPT_BUDGET
    accepted = requests[result.attempts - 1] if result.status == "ok" and result.attempts else None
    prompt_tokens = (accepted or (requests[-1] if requests else {})).get("prompt_tokens")
    count = sum(counts) if counts else None
    return {"status": result.status, "reason": result.payload["build"]["reason"], "attempts": result.attempts,
            "first_attempt_failed": result.attempts > 1 or result.status == "failed",
            "entries": len(result.payload.get("entries", [])),
            "high_entries": sum(e["confidence"] == "high" for e in result.payload.get("entries", [])),
            "requests": requests, "count_tokens": count, "count_tokens_ok": client.count_tokens_ok,
            "count_tokens_error": client.count_tokens_error,
            "prompt_tokens": prompt_tokens,
            "prompt_tokens_minus_count": prompt_tokens - count if type(prompt_tokens) is int and count else None,
            "over_budget_by_usage": type(prompt_tokens) is int and prompt_tokens > PROMPT_BUDGET,
            "completion_tokens": (accepted or {}).get("completion_tokens"),
            "reasoning_chars": sum(r.get("reasoning_chars") or 0 for r in requests),
            "think_tags": sum(bool(r.get("think_tag")) for r in requests),
            "http_errors": sum("http_status" in r for r in requests),
            "seconds": round(seconds, 2), "build_seconds": result.seconds,
            "peak": peak}


def build_one(doc: Any, client: NamesClient, seed: int = NAMES_SEED, *, sampler: Callable[[], Any] | None = None
              ) -> tuple[Any, dict[str, Any]]:
    from kototoki.names.table import build_table
    first_request, first_count = len(client.requests), len(client.counts)
    s = sampler() if sampler else None
    if s is not None:
        s.start()
    started = perf_counter()
    try:
        result = build_table(doc, client.chat, client.tokenize, seed)
    finally:
        if s is not None:
            s.stop()
            s.sample()
    record = build_record(result, client.requests[first_request:], client.counts[first_count:],
                          perf_counter() - started, dict(s.peak) if s is not None else None, client)
    return result, record


def _product_table(film: str, result: Any) -> dict[str, Any]:
    from kototoki.srt import read_srt
    doc = read_srt(FILMS[film]["ja"])
    return {"identity": {"ja_srt_sha256": doc.source_sha256, "recipe_hash": s1_hash(), "seed": NAMES_SEED,
                         "recipe": S1_NAME}} | result.payload


def build_all(*, root: Path = B_ROOT, client: NamesClient | None = None,
              sampler: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Ticket 02 builds on the running Strata service: product HF-II / HF-III (first build used), the 15 dev works,
    then the product A/A second builds. Finished builds are kept (resume); the report holds counts only."""
    from kototoki.srt import read_srt
    client = client or NamesClient()
    report_path = root / "build-report.json"
    report: dict[str, Any] = read_json(report_path) if report_path.is_file() else {
        "recipe": S1_NAME, "recipe_hash": s1_hash(), "seed": NAMES_SEED, "builds": {}}

    def save() -> None:
        atomic_write_json(report_path, report)

    for kind in ("product", "dev", "product-aa"):
        if kind == "dev":
            out = root / "E" / "dev-name-tables.json"
            tables = read_json(out) if out.is_file() else {"seed": NAMES_SEED, "recipe_hash": s1_hash(),
                                                            "tables": {}, "meta": {}}
            for work, lines in sorted(dev_lines().items()):
                if work in tables["tables"]:
                    continue
                result, record = build_one(document(lines), client, sampler=sampler)
                tables["tables"][work] = result.payload
                tables["meta"][work] = {"status": result.status, "entries": record["entries"]}
                atomic_write_json(out, tables)
                report["builds"][f"dev/{work}"] = record
                save()
            continue
        for film in FILMS:
            out = root / kind / film / "name-table.json"
            if out.is_file():
                continue
            result, record = build_one(read_srt(FILMS[film]["ja"]), client, sampler=sampler)
            atomic_write_json(out, _product_table(film, result))
            report["builds"][f"{kind}/{film}"] = record
            save()
    return gate(report, root=root)


def gate(report: dict[str, Any], *, root: Path = B_ROOT) -> dict[str, Any]:
    """§4.2 feasibility gate over the 17 used builds (A/A second builds count for thinking and sampling only)."""
    used = {k: r for k, r in report["builds"].items() if not k.startswith("product-aa/")}
    every = list(report["builds"].values())
    requests = [q for r in every for q in r["requests"]]
    checks = {"all_ok": len(used) == 17 and all(r["status"] == "ok" for r in used.values()),
              "first_attempt_failures_ok": sum(r["first_attempt_failed"] for r in used.values()) <= GATE_MAX_FIRST_FAIL,
              "no_thinking_output": all((q.get("reasoning_chars") or 0) == 0 and not q.get("think_tag")
                                        for q in requests),
              "sampling_accepted": all("http_status" not in q and q.get("error") is None
                                       and not q.get("extra_response_keys") for q in requests)}
    out = {"builds_used": len(used), "builds_total": len(every), "requests": len(requests),
           "status": dict(Counter(r["status"] for r in used.values())),
           "first_attempt_failures": sum(r["first_attempt_failed"] for r in used.values()),
           "first_attempt_failure_reasons": [r["reason"] for r in used.values() if r["status"] != "ok"],
           "count_tokens_ok": sorted({str(r["count_tokens_ok"]) for r in every}),
           "prompt_minus_count": [r["prompt_tokens_minus_count"] for r in every],
           "over_budget_by_usage": sum(r["over_budget_by_usage"] for r in every),
           "checks": checks, "passed": all(checks.values())}
    atomic_write_json(root / "gate.json", out)
    return out


# --- the Strata session ---------------------------------------------------------------------------

def _llama_servers() -> list[str]:
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace").stdout
    return [line.split(",")[0].strip('"') for line in out.splitlines() if "llama" in line.lower()]


def preflight(*, cli: Callable[..., str] | None = None, ram: Callable[[], float | None] | None = None,
              lock: Path = REPO / ".local/gpu.lock", processes: Callable[[], list[str]] = _llama_servers
              ) -> dict[str, Any]:
    """§5 before every GPU ticket: no gpu.lock, no llama-server, no Strata launch, >= 52 GiB available RAM.
    Raises SystemExit (nothing is stopped or killed) when one fails."""
    from kototoki.translate import strata as P
    cli = cli or P.run_cli
    ram = ram or P.available_ram_gib
    found = {"gpu_lock": lock.is_file(), "llama_processes": processes(), "strata_running": P.running(cli),
             "available_ram_gib": ram()}
    problems = [k for k, bad in (("gpu_lock", found["gpu_lock"]), ("llama_processes", found["llama_processes"]),
                                 ("strata_running", found["strata_running"]),
                                 ("available_ram_gib", found["available_ram_gib"] is None
                                  or found["available_ram_gib"] < MIN_AVAILABLE_RAM_GIB)) if bad]
    if problems:
        raise SystemExit(f"preflight failed ({problems}): {found}")
    return found


@contextmanager
def serve(runtime_dir: Path) -> Iterator[Any]:
    """Preflight, then the product ``StrataServer`` (``strata launch --no-tui --model iq3_s``, identity check, expert
    arena locked in RAM or refused, ``--stop`` and VRAM release on exit). The research sessions inside take the GPU
    lock themselves."""
    from kototoki.translate.strata import StrataServer
    found = preflight()
    index = len(list(runtime_dir.glob("session-*"))) + 1 if runtime_dir.is_dir() else 1
    session = runtime_dir / f"session-{index:02d}"
    atomic_write_json(session / "preflight.json", found)
    with StrataServer(session) as server:
        observed = server.identity["strata"]
        if observed.get("kv") != EXPECTED_KV:
            raise SystemExit(f"Strata kv {observed.get('kv')!r} differs from {EXPECTED_KV!r} (S1 identity)")
        yield server


def run_builds(*, root: Path = B_ROOT) -> dict[str, Any]:
    """GPU ticket 02: start Strata, build every table, stop."""
    from kototoki.translate.strata import ResourceSampler, http_get
    from experiments.translation_v3.server import GpuLock
    with serve(root / "runtime"):
        lock = GpuLock("v13-names-build")
        lock.acquire()
        try:
            return build_all(root=root, sampler=lambda: ResourceSampler(BASE, http_get))
        finally:
            lock.release()


# --- table quality (ticket 03) ----------------------------------------------------------------------

def _boot_ci(works: list[str], stat: Callable[[list[str]], float | None], seed: str,
             draws: int = BOOT_DRAWS) -> list[float] | None:
    rng = random.Random(seed)
    values = []
    for _ in range(draws):
        v = stat([rng.choice(works) for _ in works])
        if v is not None:
            values.append(v)
    if not values:
        return None
    values.sort()
    return [values[int(0.05 * len(values))], values[min(len(values) - 1, int(0.95 * len(values)))]]


def agreement_stats(entries: list[dict[str, Any]], works: list[str]) -> dict[str, float | None]:
    """Occurrence-weighted agreement and the high entries' majority-disagree rate over the given works (repeats
    count again, as a bootstrap draw)."""
    by_work: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        if e["occurrences"]:
            by_work[e["work"]].append(e)
    rows = [e for w in works for e in by_work.get(w, [])]
    occ = sum(e["occurrences"] for e in rows)
    high = [e for e in rows if e["confidence"] == "high"]
    return {"agreement": sum(e["reference_agrees"] for e in rows) / occ if occ else None,
            "high_disagree": sum(e["agreement"] < 0.5 for e in high) / len(high) if high else None}


def zh_collisions(entries: list[dict[str, Any]]) -> int:
    """Entries whose Chinese (entry zh or a form zh) is also given to another entity of the same table — the
    "supporting character mapped to the lead's name" pattern of v11 ticket 02."""
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in entries:
        for z in {e["zh"], *(f["zh"] for f in e["forms"])} - {""}:
            owners[(e.get("work", ""), z)].add(e["entity_ja"])
    return sum(any(len(owners[(e.get("work", ""), z)]) > 1 for z in {e["zh"], *(f["zh"] for f in e["forms"])} - {""})
               for e in entries)


def _pairs(entries: list[dict[str, Any]], high_only: bool = False) -> dict[str, str]:
    out = {}
    for e in entries:
        if high_only and e["confidence"] != "high":
            continue
        for f in e["forms"]:
            if f["ja"].strip() and f["zh"].strip() and f["ja"] not in out:
                out[f["ja"]] = f["zh"]
    return out


def overlap(a: list[dict[str, Any]], b: list[dict[str, Any]], high_only: bool = False) -> dict[str, Any]:
    """ja→zh form overlap: Japanese forms in both tables, and how many of them carry the same Chinese."""
    pa, pb = _pairs(a, high_only), _pairs(b, high_only)
    both = pa.keys() & pb.keys()
    same = sum(pa[k] == pb[k] for k in both)
    union = len(pa.keys() | pb.keys())
    return {"forms_a": len(pa), "forms_b": len(pb), "ja_shared": len(both), "same_zh": same,
            "pair_jaccard": same / union if union else None, "same_zh_of_shared": same / len(both) if both else None}


def table_quality(*, root: Path = V13_ROOT) -> dict[str, Any]:
    """Ticket 03: dev S1 vs 27B against the reference Chinese (bootstrap by work) and the gate; product description."""
    reports = {}
    for arm, source in (("27b", v10.V10_ROOT), ("s1", root / "B")):
        names11.table_reference_agreement(source=source, out=root / "C" / arm)
        reports[arm] = read_json(root / "C" / arm / "02-table-agreement.json")
    works = sorted(reports["27b"]["works"])
    if works != sorted(reports["s1"]["works"]):
        raise ValueError("the two arms cover different dev works")
    stats = {arm: agreement_stats(r["entries"], works) for arm, r in reports.items()}

    def diff(key: str) -> Callable[[list[str]], float | None]:
        def f(ws: list[str]) -> float | None:
            a, b = agreement_stats(reports["s1"]["entries"], ws)[key], agreement_stats(reports["27b"]["entries"], ws)[key]
            return None if a is None or b is None else a - b
        return f

    agree_ci = _boot_ci(works, diff("agreement"), "v13-C-agreement")
    high_ci = _boot_ci(works, diff("high_disagree"), "v13-C-high")
    noninferior = agree_ci[0] >= -0.05 and high_ci[1] <= 0.05
    dev_tables = {"27b": names11.dev_tables(v10.V10_ROOT), "s1": names11.dev_tables(root / "B")}
    arms = {}
    for arm, r in reports.items():
        flat = [dict(e, work=w) for w, es in dev_tables[arm].items() for e in es]
        arms[arm] = {**{k: r["dev_total"][k] for k in ("entries", "with_occurrences", "majority_agree",
                                                      "majority_disagree", "occurrence_weighted_agreement",
                                                      "by_confidence", "by_kind", "katakana_form_share")},
                     "high_entries": sum(e["confidence"] == "high" for e in r["entries"]),
                     "kinds_all": dict(Counter(e["kind"] for e in r["entries"])),
                     "high_disagree_rate": stats[arm]["high_disagree"],
                     "zh_collision_entries": zh_collisions(flat),
                     "per_work": {w: {k: v[k] for k in ("entries", "majority_disagree", "occurrence_weighted_agreement")}
                                  for w, v in r["works"].items()}}
    product = {}
    for film in FILMS:
        t27 = read_json(FILMS[film]["table"])["entries"]
        s1 = read_json(root / "B" / "product" / film / "name-table.json")["entries"]
        aa = root / "B" / "product-aa" / film / "name-table.json"
        product[film] = {
            "27b": {"entries": len(t27), "high_entries": sum(e["confidence"] == "high" for e in t27),
                    "high_forms": len(_pairs(t27, True)), "zh_collision_entries": zh_collisions(t27)},
            "s1": {"entries": len(s1), "high_entries": sum(e["confidence"] == "high" for e in s1),
                   "high_forms": len(_pairs(s1, True)), "zh_collision_entries": zh_collisions(s1),
                   "kinds": dict(Counter(e["kind"] for e in s1))},
            "s1_vs_27b": overlap(s1, t27), "s1_vs_27b_high": overlap(s1, t27, True),
            "aa": overlap(s1, read_json(aa)["entries"]) if aa.is_file() else None,
            "aa_high": overlap(s1, read_json(aa)["entries"], True) if aa.is_file() else None}
    out = {"dev": {"works": len(works), "arms": arms,
                   "agreement_delta": stats["s1"]["agreement"] - stats["27b"]["agreement"], "agreement_ci90": agree_ci,
                   "high_disagree_delta": stats["s1"]["high_disagree"] - stats["27b"]["high_disagree"],
                   "high_disagree_ci90": high_ci,
                   "gate": {"noninferior": noninferior, "improved": noninferior and agree_ci[0] > 0,
                            "significantly_worse_block_d_e": agree_ci[1] < 0}},
           "product": product}
    atomic_write_json(root / "C" / "table-quality.json", out)
    return out


# --- recipes: any table -> Q2 ----------------------------------------------------------------------

def high_rows(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Injection rows of the Q1 rule: ``confidence: high`` entities, one row per form, deduplicated by ``ja``, forms
    with an empty ``ja`` or ``zh`` skipped (``names11.nstar_tables("high")`` / ``product_tables("high")``)."""
    rows, seen = [], set()
    for entity in entries:
        if entity["confidence"] != "high":
            continue
        for form in entity["forms"]:
            if form["ja"] not in seen and form["ja"].strip() and form["zh"].strip():
                seen.add(form["ja"])
                rows.append({"source": form["ja"], "translation": form["zh"]})
    return rows


def q2_data(tables: dict[str, list[dict[str, Any]]], name: str, comment: str, *, keep_empty: bool) -> dict[str, Any]:
    """The Q2 recipe file for name tables {work: entries}: the Q1 file (``qwen-wide`` + high rows, ``filter:
    window``) through ``v12.strata_recipe_data(..., launch="default")`` (ADR-0017). Dev leaves works without rows
    out (``nstar_tables``), the product keeps them (``product_tables``)."""
    rows = {w: high_rows(es) for w, es in sorted(tables.items())}
    rows = {w: r for w, r in rows.items() if r or keep_empty}
    q1 = {"name": name, "base": "qwen-wide", "comment": comment,
          "qwen_options": {"names": {"filter": "window", "tables": rows}}}
    return v12.strata_recipe_data(q1, name, comment, launch=strata.DEFAULT_LAUNCH)


def dev_entries(source: Path) -> dict[str, list[dict[str, Any]]]:
    return names11.dev_tables(source)


def product_entries(kind: str, *, root: Path = V13_ROOT) -> dict[str, list[dict[str, Any]]]:
    if kind == "27b":
        return {f: read_json(p["table"])["entries"] for f, p in FILMS.items()}
    return {f: read_json(root / "B" / "product" / f / "name-table.json")["entries"] for f in FILMS}


def write_recipes(*, root: Path = V13_ROOT) -> dict[str, str]:
    """T0 / T1 dev recipes (``recipes/``) and product recipes (``E/root/recipes/``); returns their hashes."""
    for arm, dev_src, prod_kind, what in ((T0, v10.V10_ROOT, "27b", "27B tables (control)"),
                                          (T1, root / "B", "s1", "S1 Strata tables (candidate)")):
        v12._write_once(root / "recipes" / f"{arm}.json", q2_data(
            dev_entries(dev_src), arm, f"v13 {arm}: Q2 + {what}, dev", keep_empty=False))
        v12._write_once(root / "E/root/recipes" / f"{arm}.json", q2_data(
            product_entries(prod_kind, root=root), arm, f"v13 {arm}: Q2 + {what}, product", keep_empty=True))
    return {f"dev/{a}": load_recipe(a, root).recipe_hash for a in (T0, T1)} | {
        f"product/{a}": load_recipe(a, root / "E/root").recipe_hash for a in (T0, T1)}


# --- translation (tickets 04 / 05) ----------------------------------------------------------------------

def run_dev(*, root: Path = V13_ROOT, seeds: tuple[int, ...] = MAIN_SEEDS) -> dict[str, Any]:
    """GPU ticket 04: start Strata, the 6 dev runs (T0 then T1 per seed; finished runs resume as complete), stop."""
    out = {}
    with serve(root / "runtime-dev"):
        for seed in seeds:
            for arm in (T0, T1):
                out[f"{arm}__s{seed}"] = v9.generate(arm, seed, root=root)
    return out


def run_product(*, root: Path = E_ROOT, seeds: tuple[int, ...] = PRODUCT_SEEDS) -> dict[str, Any]:
    """GPU ticket 05: start Strata, translate-srt for every seed x film x arm (written SRTs are kept), stop."""
    from experiments.translation_v3 import cli
    out = {}
    with serve(root / "runtime"):
        for seed in seeds:
            for film, paths in FILMS.items():
                for arm in (T0, T1):
                    dst = asr10.zh_path(arm, film, seed, root)
                    if dst.is_file():
                        out[f"{arm}.{film}.s{seed}"] = "kept"
                        continue
                    code = cli.main(["--root", str(root / "root"), "translate-srt", "--srt", str(paths["ja"]),
                                     "--recipe", arm, "--seed", str(seed), "--out", str(dst), "--work-id", film])
                    out[f"{arm}.{film}.s{seed}"] = code
    return out


def product(command: str, *, x: str = T0, y: str = T1, name: str | None = None) -> Any:
    """``asr10`` bound to the v13 product root and seeds (as ``v12.product``)."""
    root, seeds, arms = E_ROOT, PRODUCT_SEEDS, [x, y]
    if command == "plan":
        return str(asr10.plan(x, y, v11.PRODUCT_QUOTAS, root=root, seeds=seeds, skip_identical=True))
    if command == "judge":
        return asr10.judge(name or f"{y}-vs-{x}", root=root)
    if command == "estimate":
        return asr10.estimate(name or f"{y}-vs-{x}", root=root)
    if command == "inconsistency":
        return asr10.inconsistency(arms, root=root, seeds=seeds, name=name or "inconsistency")
    if command == "failures":
        return {a: asr10.delivery_failures(a, root=root, seeds=seeds) for a in arms}
    if command == "stats":
        return {a: v12.product_stats(a, root=root, seeds=seeds) for a in arms}
    raise ValueError(command)


def dev_gate(summary: dict[str, Any]) -> dict[str, Any]:
    """§4.4: non-inferior = both accuracy CI90 upper < 0.05 and both wrong-referent CI90 lower <= 0; improved =
    non-inferior and at least one accuracy CI90 upper < 0."""
    cats = ("anime_series", "animation_movie")
    acc = {c: summary["accuracy"][c][1] for c in cats}
    wr = {c: summary["wrong-referent"][c][1] for c in cats}
    noninferior = all(acc[c][1] < 0.05 for c in cats) and all(wr[c][0] <= 0 for c in cats)
    return {"accuracy_ci90": acc, "wrong_referent_ci90": wr, "noninferior": noninferior,
            "improved": noninferior and any(acc[c][1] < 0 for c in cats)}


def product_gate(estimate: dict[str, Any], inconsistency: dict[str, Any], failures: dict[str, Any]) -> dict[str, Any]:
    """§4.5: non-inferior = overall CI90 upper <= 0.05, no delivery failure (both arms), name-error difference CI90
    upper <= +0.005, candidate inconsistency <= control + 0.01; improved = non-inferior and overall upper < 0."""
    overall = estimate["buckets"]["all"]
    rate = {a: inconsistency[a]["mean_inconsistency"] for a in (T0, T1)}
    lost = {a: sum(v.values()) for a, v in failures.items()}
    checks = {"overall_upper": overall["ci90"][1] <= 0.05, "delivery_failures_zero": all(v == 0 for v in lost.values()),
              "name_error_upper": overall["name_error_delta_ci90"][1] <= 0.005,
              "inconsistency": rate[T1] <= rate[T0] + 0.01}
    return {"overall_ci90": overall["ci90"], "name_error_delta_ci90": overall["name_error_delta_ci90"],
            "inconsistency": rate, "delivery_failures": lost, "checks": checks, "noninferior": all(checks.values()),
            "improved": all(checks.values()) and overall["ci90"][1] < 0}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)
