#!/usr/bin/env python3
"""Regenerate ingest_data_manifest.txt from testdata/ingest_data.

testdata/ is gitignored, so CI rebuilds the ingest fixture tree from this manifest instead.
Run after adding, removing or renaming anything under testdata/ingest_data:

    python3 tests/fixtures/update_manifest.py
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTDATA = HERE.parents[1] / "testdata" / "ingest_data"
MANIFEST = HERE / "ingest_data_manifest.txt"

HEADER = """\
# File layout of testdata/ingest_data, one path per line (the files themselves are empty).
# testdata/ is gitignored; tests/conftest.py rebuilds this tree in a tmp dir for every test.
# Regenerate with: python3 tests/fixtures/update_manifest.py
"""


def scan(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


if __name__ == "__main__":
    paths = scan(TESTDATA)
    MANIFEST.write_text(HEADER + "\n".join(paths) + "\n")
    print(f"Wrote {len(paths)} paths to {MANIFEST}")
