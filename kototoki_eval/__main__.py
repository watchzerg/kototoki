"""Private JSON report command; never prints full transcripts to console."""

import argparse
import json
import math
from pathlib import Path

from .scoring import evaluate


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "infinity" if value > 0 else "nonfinite"
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def validate_output_path(output: Path, inputs: tuple[Path, ...], root: Path | None = None) -> Path:
    """Keep private outputs below project .local and preserve existing evidence."""
    private_root = ((root or Path(__file__).resolve().parents[1]) / ".local").resolve()
    resolved = output.resolve()
    if not resolved.is_relative_to(private_root) or resolved == private_root:
        raise ValueError("Private evaluation output must be under this project's .local directory")
    if any(resolved == value.resolve() for value in inputs):
        raise ValueError("Evaluation output cannot overwrite input")
    if resolved.exists():
        raise FileExistsError("Evaluation output already exists; select a new run identity")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = validate_output_path(args.output, (args.reference, args.transcript))
    source = json.loads(args.reference.read_text(encoding="utf-8-sig"))
    candidate = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    result = evaluate(source, candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(json_safe(result), ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps({"reference_kind": result["reference_kind"], "text": result["text"],
                      "timing": json_safe(result["timing"])}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
