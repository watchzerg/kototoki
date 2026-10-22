"""v10 supplementary (ticket 16): D2 name-table injection on dev, the clean-source guard of §4.4 ("D2 也可在 dev 补做").

Each dev work gets a table from the product names stage itself (``kototoki.names.table.build_table``, imported, not
changed): the work's dev scenes in scene order as one document (cue index 1..N, no time axis), the product names
seed, on the Qwen server with the names context (the server arguments are the same as Q0's). The tables are flattened
like ``asr10.name_tables`` (every form of every entity) into ``qwen_options.names`` with the window filter.
Tables are transcript content: they stay under ``.local`` and are not printed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import atomic_write_json, read_json

from .brief10 import dev_lines
from .v10 import V10_ROOT

NAMES_SEED = 20261019  # product config names.seed


def document(lines: list[str]):
    from kototoki.srt import SourceCue, SourceDocument
    from experiments.translation_v3.common import sha256_bytes
    texts = [t for t in lines if t]  # scene separators are dropped; names prompts carry no scene structure
    cues = tuple(SourceCue(id=f"c{i}", ordinal=i, index=i, index_text=str(i), time_line="", start_ms=0, end_ms=0,
                           text=t) for i, t in enumerate(texts, 1))
    return SourceDocument(source_sha256=sha256_bytes("\n".join(texts).encode()), cues=cues, encoding="utf-8")


def build(*, root: Path = V10_ROOT, port: int = 8080, break_stale_lock: bool = False) -> dict[str, Any]:
    """GPU: one product-stage table per dev work -> ``E/dev-name-tables.json``."""
    from kototoki.names.table import CONTEXT_SIZE, build_table
    recipe = R.compose("names-server", "qwen-wide", qwen_options={"context": CONTEXT_SIZE})
    run_dir = root / "E" / "session-names-dev"
    index = len(list((run_dir / "runtime").glob("session-*"))) + 1 if (run_dir / "runtime").is_dir() else 1
    factory = qwen.session_factory(root, "names-dev", recipe, port=port, break_stale_lock=break_stale_lock)
    out: dict[str, Any] = {"seed": NAMES_SEED, "tables": {}, "meta": {}}
    started = time.perf_counter()
    with factory(run_dir, index) as handle:
        client = handle.client
        for work, lines in sorted(dev_lines().items()):
            result = build_table(document(lines), client.chat_completion, lambda t: len(client.tokenize(t)),
                                 NAMES_SEED)
            out["tables"][work] = result.payload
            out["meta"][work] = {"status": result.status, "entries": len(result.payload.get("entries", []))}
    out["wall_seconds"] = time.perf_counter() - started
    atomic_write_json(root / "E" / "dev-name-tables.json", out)
    return {"works": len(out["tables"]), "wall_seconds": out["wall_seconds"], "meta": out["meta"]}


def injection_tables(root: Path = V10_ROOT) -> dict[str, list[dict[str, str]]]:
    """{work: [{source: form.ja, translation: form.zh}]} for ``qwen_options.names`` (works with an empty table are
    left out)."""
    out = {}
    for work, table in read_json(root / "E" / "dev-name-tables.json")["tables"].items():
        rows, seen = [], set()
        for entity in table.get("entries", []):
            for form in entity["forms"]:
                if form["ja"] not in seen and form["ja"].strip() and form["zh"].strip():
                    seen.add(form["ja"])
                    rows.append({"source": form["ja"], "translation": form["zh"]})
        if rows:
            out[work] = rows
    return out
