"""Tests for pipeline/1_ingest/prefix.py."""

import subprocess
import sys
from pathlib import Path

import prefix

SCRIPT = Path(prefix.__file__)


def names(path):
    return sorted(p.name for p in path.iterdir())


def test_adds_prefix_and_skips_already_prefixed(tmp_path):
    for d in ["930124-C1_03202025", "930125-D1_01122026", "MRI_930118-01_12132025"]:
        (tmp_path / d).mkdir()
    (tmp_path / "930124-C1_03202025" / "930124-C1_03202025.T1.nii").touch()
    (tmp_path / "readme.txt").touch()

    prefix.rename_folders_with_prefix(str(tmp_path), "MRI_")

    assert names(tmp_path) == [
        "MRI_930118-01_12132025", "MRI_930124-C1_03202025", "MRI_930125-D1_01122026", "readme.txt",
    ]
    assert names(tmp_path / "MRI_930124-C1_03202025") == ["930124-C1_03202025.T1.nii"]


def test_rerun_is_noop(tmp_path):
    (tmp_path / "930124-C1_03202025").mkdir()
    prefix.rename_folders_with_prefix(str(tmp_path), "PET_")
    prefix.rename_folders_with_prefix(str(tmp_path), "PET_")
    assert names(tmp_path) == ["PET_930124-C1_03202025"]


def test_dry_run_changes_nothing(tmp_path, capsys):
    (tmp_path / "930124-C1_03202025").mkdir()
    prefix.rename_folders_with_prefix(str(tmp_path), "MRI_", dry_run=True)
    assert names(tmp_path) == ["930124-C1_03202025"]
    assert "Would rename: 930124-C1_03202025 -> MRI_930124-C1_03202025" in capsys.readouterr().out


def test_prefixed_output_is_parseable_by_converter(tmp_path, logger):
    import dropbox_mri_to_bids as mri
    (tmp_path / "930124-C1_03202025").mkdir()
    prefix.rename_folders_with_prefix(str(tmp_path), "MRI_")
    (folder,) = tmp_path.iterdir()
    assert mri.parse_folder_name(folder.name, logger) == ("930124", "20250320")


def test_empty_dir(tmp_path, capsys):
    prefix.rename_folders_with_prefix(str(tmp_path))
    assert "No subfolders found" in capsys.readouterr().out


def test_cli_missing_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "nope")], capture_output=True, text=True,
    )
    assert "does not exist" in result.stdout


def test_cli_defaults_to_mri_prefix(tmp_path):
    (tmp_path / "930124-C1_03202025").mkdir()
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert names(tmp_path) == ["MRI_930124-C1_03202025"]
