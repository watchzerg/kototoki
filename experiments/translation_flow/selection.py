"""Freeze small source-only development and confirmation selections."""

import argparse
import hashlib
import json
from pathlib import Path


def freeze(dev: Path, expanded: Path, output: Path) -> None:
    """Select without inspecting references, judgments, or translation outputs."""
    output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in dev.read_text(encoding="utf-8-sig").splitlines() if line]
    p0_ids = ["03-1-1", "08-1-1", "M01-1", "M04-1"]
    p1_ids = ["03-1-2", "03-1-3", "08-1-2", "08-1-3", "M01-4", "M01-7", "M04-4", "M04-7"]
    by_id = {row["id"]: row for row in rows}
    selections = {"p0": [by_id[key] for key in p0_ids], "p1": [by_id[key] for key in p1_ids]}
    extra = [json.loads(line) for line in expanded.read_text(encoding="utf-8-sig").splitlines() if line]
    confirmation = []
    for prefix in ("H30-W03_", "H30-W08_", "H30-M01-", "H30-M04-"):
        eligible = [row for row in extra if row["id"].startswith(prefix)]
        eligible.sort(key=lambda row: hashlib.sha256(("hy30-flow-confirm-20261007|" + row["id"]).encode()).hexdigest())
        if len(eligible) < 3:
            raise ValueError(f"Insufficient confirmation source groups: {prefix}")
        confirmation.extend(eligible[:3])
    selections["confirmation"] = confirmation
    manifest = {
        "selection_version": "source-only-small-v1", "seed": "hy30-flow-confirm-20261007",
        "selection_basis": "Predeclared work and window IDs for development; SHA256 order per work for confirmation, no reference or candidate access.",
        "limitations": "All works and expanded windows participated in earlier model selection. Confirmation is independent of this round's tuning, not unseen model-selection data.",
        "source_files": {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in (dev, expanded)},
        "sets": {},
    }
    for name, selected in selections.items():
        path = output / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected), encoding="utf-8")
        manifest["sets"][name] = {"ids": [row["id"] for row in selected], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "windows": len(selected)}
    (output / "selection.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--expanded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    freeze(args.dev, args.expanded, args.output)
