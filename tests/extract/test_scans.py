"""Tests for pipeline/6_extract/scans.py: finding scans by subject and session date."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

EXTRACT_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "6_extract"
sys.path.insert(0, str(EXTRACT_DIR))

import scans  # noqa: E402

SCRIPT = EXTRACT_DIR / "scans.py"


def touch(root, *rel_paths):
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * 2048)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "ADRC"
    touch(
        r,
        "900901/20240101/anat/900901-20240101_T1w.nii",
        "900901/20240101/anat/900901-20240101_T1w.json",
        "900901/20240101/anat/900901-20240101_T2w.nii",
        "900901/20240101/freesurfer741/900901-20240101_T1w/mri/aparc+aseg.mgz",
        "900901/20240101/freesurfer741/900901-20240101_T1w/mri/T1.mgz",
        "900901/20240110/pet/900901-20240110_PET_256.nii",
        "900901/20240110/pet/900901-20240110_PET.nii",
        "900901/20240110/pet/900901-20240110_PET_a.nii.gz",
        "900901/20240110/pet/900901-20240110_PET.json",
        "900901/20240110/pet/900902-20240110_PET.nii",  # another subject's file
        "900901/20240110/ct/900901-20240110_CT.nii",
        "900901/logs/pet_suvr_processing_900901.log",
        "900902/20180101/anat/900902-20180101_CorMPRAGE.nii",
        "900903/20190101/pet/readme.txt",
        "logs/mri_bids_logs/batch1.log",
    )
    (r / "900903/20190102").mkdir()
    (r / "notes.txt").write_text("not a subject")
    return r


@pytest.mark.parametrize("text", ["01/10/2024", "20240110", "2024-01-10", " 1/10/2024 "])
def test_parse_date(text):
    assert scans.parse_date(text) == "20240110"


@pytest.mark.parametrize("text", ["10.01.2024", "2024/01/10", "13/01/2024", ""])
def test_parse_date_rejects(text):
    with pytest.raises(ValueError):
        scans.parse_date(text)


def test_small_helpers(tmp_path):
    assert scans.pretty_date("20240110") == "2024-01-10"
    assert scans.is_volume(Path("a.nii.gz")) and scans.is_volume(Path("T1.mgz"))
    assert not scans.is_volume(Path("a.json"))
    assert scans.resolve_root(tmp_path) == tmp_path


def test_resolve_root_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(scans, "ADRC_ROOT", "")
    with pytest.raises(SystemExit, match="No dataset root"):
        scans.resolve_root(None)
    monkeypatch.setattr(scans, "ADRC_ROOT", str(tmp_path))
    assert scans.resolve_root(None) == tmp_path
    with pytest.raises(SystemExit, match="does not exist"):
        scans.resolve_root(tmp_path / "nope")


def test_list_subjects(root):
    assert scans.list_subjects(root) == ["900901", "900902", "900903"]


def test_find_scans(root):
    pet = scans.find_scans(root, "900901", "20240110", "pet")
    assert [p.name for p in pet] == ["900901-20240110_PET.nii", "900901-20240110_PET_256.nii",
                                     "900901-20240110_PET_a.nii.gz"]
    assert [p.name for p in scans.find_scans(root, "900901", "20240101", "t1w")] == ["900901-20240101_T1w.nii"]
    assert [p.name for p in scans.find_scans(root, "900902", "20180101", "mprage")] == [
        "900902-20180101_CorMPRAGE.nii"]
    assert scans.find_scans(root, "900902", "20180101", "t1w") == []
    assert scans.find_scans(root, "900901", "20240101", "ct") == []  # no ct folder


def test_list_sessions(root):
    sessions = scans.list_sessions(root, "900901")
    assert [(s.date, s.modality, s.subfolders) for s in sessions] == [
        ("20240101", "MRI", ["anat", "freesurfer741"]),
        ("20240110", "PET", ["ct", "pet"]),
    ]
    assert [p.name for p in sessions[1].scans["ct"]] == ["900901-20240110_CT.nii"]
    assert [(s.date, s.modality) for s in scans.list_sessions(root, "900903")] == [
        ("20190101", "PET"),  # pet folder, no scan in it
        ("20190102", "?"),
    ]
    assert scans.list_sessions(root, "999999") == []


def test_session_volumes(root):
    groups = scans.session_volumes(root, "900901", "20240101")
    assert {k: [p.name for p in v] for k, v in groups.items()} == {
        "anat": ["900901-20240101_T1w.nii", "900901-20240101_T2w.nii"],
        "freesurfer741/900901-20240101_T1w/mri": ["T1.mgz", "aparc+aseg.mgz"],
    }


def cli(root, *args, env_root=True):
    env = {k: v for k, v in os.environ.items() if k != "ADRC_ROOT"}
    if env_root:
        env["ADRC_ROOT"] = str(root)
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_cli_lists_sessions(root):
    result = cli(root, "900901")
    assert result.returncode == 0
    assert "900901: 2 session(s)" in result.stdout
    assert "2024-01-10  PET  [ct, pet]" in result.stdout
    assert "pet    900901-20240110_PET_256.nii  (2.0 KB)" in result.stdout


def test_cli_session_and_type(root):
    result = cli(root, "900901", "01/10/2024")
    assert result.returncode == 0
    assert result.stdout.splitlines()[:2] == ["ct/", "    900901-20240110_CT.nii  (2.0 KB)"]
    assert ".json" not in result.stdout

    result = cli(root, "900901", "20240110", "-t", "pet")
    assert result.stdout.splitlines() == [
        str(root / "900901/20240110/pet" / name)
        for name in ["900901-20240110_PET.nii", "900901-20240110_PET_256.nii", "900901-20240110_PET_a.nii.gz"]
    ]


def test_cli_root_flag(root):
    result = cli(root, "900902", "--root", str(root), env_root=False)
    assert result.returncode == 0 and "CorMPRAGE" in result.stdout


@pytest.mark.parametrize("args, message", [
    (["999999"], "Subject 999999 not found"),
    (["900901", "02/30/2024"], "Unrecognized date"),
    (["900901", "20230101"], "No session 2023-01-01 for 900901. Available: 2024-01-01, 2024-01-10"),
    (["900901", "20240101", "-t", "ct"], "No ct scan in"),
])
def test_cli_errors(root, args, message):
    result = cli(root, *args)
    assert result.returncode == 1
    assert message in result.stderr


def test_cli_type_needs_date(root):
    result = cli(root, "900901", "-t", "pet")
    assert result.returncode == 2 and "--type needs a date" in result.stderr


def test_cli_no_root(root):
    result = cli(root, "900901", env_root=False)
    assert result.returncode == 1 and "No dataset root" in result.stderr
