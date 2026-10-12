"""Write a new private report for explicit root harness manifest paths."""
import argparse
import json
from pathlib import Path

from .report import build_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('manifests', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    target = args.output.resolve()
    if not target.is_relative_to(root / '.local') or target.exists():
        parser.error('Choose a new private project .local output path.')
    if target in [path.resolve() for path in args.manifests]:
        parser.error('Output cannot overwrite an input manifest.')
    report = build_report(args.manifests)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'output': str(target), 'counts': report['counts'], 'quality_ranking': 'not_performed'}))


if __name__ == '__main__':
    main()
