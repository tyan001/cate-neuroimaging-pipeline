"""Tests for pipeline/7_DirectoryStats/directory_data_count.py."""

import sys
from pathlib import Path

import pytest

STATS_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "7_DirectoryStats"
sys.path.insert(0, str(STATS_DIR))

import directory_data_count as ddc  # noqa: E402


def touch(root, *rel_paths):
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


@pytest.fixture
def nwsi(tmp_path):
    root = tmp_path / "NWSI"
    touch(
        root / "ADRC",
        "900001/20240101/anat/900001-20240101_T1w.nii",
        "900001/20240101/modalities/900001-20240101_FLAIR.nii",
        "900001/20240110/pet/900001-20240110_PET.nii",
        "900001/20240110/ct/900001-20240110_CT.nii",
        "900002/20230101/anat/900002-20230101_T1w.nii",
        "900002/20230101/pet/900002-20230101_PET.nii",
        "900002/logs/anat",  # a file, not a folder
        "900003/anat/stray.nii",  # wrong depth
    )
    (root / "ADRC/notes.txt").touch()
    (root / "freesurfer_link").mkdir()
    (root / "freesurfer_link/900001-20240101_T1w").symlink_to(root / "ADRC/900001/20240101/anat")
    (root / "freesurfer_link/900002-20230101_T1w").symlink_to(root / "ADRC/900002/20230101/freesurfer741/gone")
    return root


def test_count_adrc_folders(nwsi):
    assert ddc.count_adrc_folders(nwsi / "ADRC") == {"anat": 2, "ct": 1, "pet": 2, "modalities": 1}


def test_count_links(nwsi):
    assert ddc.count_links(nwsi / "freesurfer_link") == (2, 1)


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["directory_data_count.py", *argv])
    ddc.main()


def test_main(nwsi, monkeypatch, capsys):
    monkeypatch.delenv("ADRC_ROOT", raising=False)
    run(monkeypatch, "-i", str(nwsi))
    out = capsys.readouterr().out
    assert "Subjects in ADRC: 3" in out
    assert "  anat              2" in out
    assert "freesurfer_link       2  (broken links: 1)" in out
    assert "suvr_link        missing" in out


def test_main_uses_env(nwsi, monkeypatch, capsys):
    monkeypatch.setenv("ADRC_ROOT", str(nwsi))
    run(monkeypatch)
    assert f"NWSI root: {nwsi}" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["-i", "{tmp}"]])
def test_main_errors(tmp_path, monkeypatch, argv):
    monkeypatch.delenv("ADRC_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, *[a.format(tmp=tmp_path) for a in argv])
    assert exc.value.code == 2  # -i is required without $ADRC_ROOT; no ADRC folder under it
