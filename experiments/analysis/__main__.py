"""Write a fresh private comparison and print no source or hypothesis text."""

import argparse
import hashlib
import json
from pathlib import Path

from kototoki_eval.__main__ import json_safe, validate_output_path

from .aggregate import aggregate_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--paired-bootstrap", action="store_true")
    args = parser.parse_args()
    output = validate_output_path(args.output, (args.manifest,))
    data = args.manifest.read_bytes()
    manifest = json.loads(data.decode("utf-8-sig"))
    report = aggregate_manifest(manifest, base=args.manifest.resolve().parent,
                                bootstrap=args.paired_bootstrap)
    report["manifest_identity"] = {"path": str(args.manifest.resolve()), "sha256": hashlib.sha256(data).hexdigest()}
    inputs = [Path(artifact["path"]) for route in report["routes"]
              for record in route["scene_records"] for artifact in record["artifacts"]]
    validate_output_path(output, tuple(inputs))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(report), stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(json_safe({"manifest_id": report["manifest_id"], "ranking": "not_performed",
                               "routes": [{"route_id": route["route_id"], "configuration_id": route["configuration_id"],
                                           "summary": route["summary"]} for route in report["routes"]]}),
                     ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
