"""Keep tests/fixtures/ingest_data_manifest.txt in sync with testdata/ingest_data."""

import sys

import pytest

from manifest_data import MANIFEST, REPO_ROOT, manifest_paths

sys.path.insert(0, str(MANIFEST.parent))
import update_manifest  # noqa: E402

TESTDATA = REPO_ROOT / "testdata" / "ingest_data"


def test_manifest_is_not_empty():
    paths = manifest_paths()
    assert any(p.startswith("MRI/") for p in paths)
    assert any(p.startswith("PET/") for p in paths)


@pytest.mark.skipif(not TESTDATA.is_dir(), reason="testdata/ is gitignored; only checked locally")
def test_manifest_matches_testdata():
    assert manifest_paths() == update_manifest.scan(TESTDATA), (
        "testdata/ingest_data changed: run python3 tests/fixtures/update_manifest.py"
    )
