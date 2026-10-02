"""Save a model file's tensor names and shapes as a detection test fixture.

Usage: python scripts/extract_header_fixture.py <model file> <fixture name> [--folder NAME]

Writes ``tests/fixtures/headers/<fixture name>.json.gz`` holding the tensor table, the trainer
metadata keys detection reads, and the current detection result as the expectation. Review the
expectation before committing: it records what the rules say today, not necessarily the truth.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hanakura.core.db import Database
from hanakura.core.detection import DetectionService
from hanakura.core.detection.header import read_header
from hanakura.core.detection.service import METADATA_KEYS_KEPT

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "headers"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("name")
    parser.add_argument("--folder", help="The folder the file was found in, kept as a note")
    args = parser.parse_args()

    header = read_header(args.path)
    result = DetectionService(Database(":memory:")).detect_header(header)
    fixture = {
        "source_file": args.path.name,
        "folder": args.folder,
        "format": header.format,
        "metadata": {k: v for k, v in header.metadata.items() if k in METADATA_KEYS_KEPT},
        "tensors": header.tensors,
        "expect": {"kind": result.kind, "base_model": result.base_model, "rule_id": result.rule_id},
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    target = FIXTURE_DIR / f"{args.name}.json.gz"
    with gzip.open(target, "wt", encoding="utf-8") as f:
        json.dump(fixture, f, separators=(",", ":"))
    print(f"{target} ({target.stat().st_size} bytes): {fixture['expect']}")


if __name__ == "__main__":
    main()
