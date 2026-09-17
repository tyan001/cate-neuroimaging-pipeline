"""Shared fixtures for the pipeline test suite.

testdata/ingest_data holds empty placeholder files with real naming conventions (fake subject IDs
and shifted dates). testdata/ is gitignored, so its layout is committed as
tests/fixtures/ingest_data_manifest.txt and rebuilt per test from that. Every rebuilt file's
content is its own relative path, so a test can tell which source file a converter picked after
it has been copied and renamed.
"""

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INGEST_DIR = REPO_ROOT / "pipeline" / "1_ingest"
MANIFEST = Path(__file__).resolve().parent / "fixtures" / "ingest_data_manifest.txt"

# The pipeline stages are standalone scripts in digit-prefixed folders, not packages.
sys.path.insert(0, str(INGEST_DIR))


def manifest_paths():
    lines = MANIFEST.read_text().splitlines()
    return [line for line in lines if line and not line.startswith("#")]


def build_tree(root, rel_paths):
    """Create placeholder files under root; each file's content is its relative path."""
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)
    return root


@pytest.fixture
def ingest_data(tmp_path):
    """Fresh copy of the ingest fixture: <tmp>/ingest_data/{MRI,PET}/..."""
    return build_tree(tmp_path / "ingest_data", manifest_paths())


@pytest.fixture
def logger():
    """Quiet logger for calling converter functions directly."""
    log = logging.getLogger("tests.ingest")
    log.handlers[:] = [logging.NullHandler()]
    log.propagate = True  # keep caplog working
    log.setLevel(logging.DEBUG)
    return log


@pytest.fixture
def make_tree(tmp_path):
    """Build an ad-hoc source tree: make_tree("MRI", ["MRI_x-01_01022023/x.T1.nii", ...])."""
    def _make(name, rel_paths):
        return build_tree(tmp_path / name, rel_paths)
    return _make
