"""Where the ingest fixture manifest lives, and how to read it.

Imported by tests/conftest.py and tests/test_fixture_manifest.py. It lives here rather than in
conftest.py because a module imported as `conftest` is whichever conftest.py pytest loaded first,
so `from conftest import ...` breaks as soon as a second conftest.py exists (tests/missing/).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "fixtures" / "ingest_data_manifest.txt"


def manifest_paths():
    lines = MANIFEST.read_text().splitlines()
    return [line for line in lines if line and not line.startswith("#")]
