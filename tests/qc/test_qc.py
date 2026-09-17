"""Tests for pipeline/4_qc: recon-all / hippocampus status checks and the isotropic-matrix check.

The status checks only look at file names and log contents, so trees of small files are enough.
check_mprage.py reads NIfTI headers; it gets tiny synthetic volumes.
"""

import csv
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

QC_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "4_qc"
sys.path.insert(0, str(QC_DIR))

import check_hippocampus  # noqa: E402
import check_mprage  # noqa: E402
import check_mri_missing_processing as missing  # noqa: E402
import check_recon_all  # noqa: E402

HIPPO_LOG = "scripts/hippocampal-subfields-T1.log"
HIPPO_DONE = "writing to discreteLabelsMergedBodyHeadNoMLorGCDGResampledT1.mgz...\nEverything done!\nIt took 812.5 seconds\n"


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def fs(subject, date):
    return f"{subject}/{date}/freesurfer741/{subject}-{date}_T1w"


def nifti(path, shape):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4)).to_filename(path)
    return path


# --- check_mri_missing_processing.py ------------------------------------------------------------


@pytest.fixture
def adrc(tmp_path):
    root = tmp_path / "data" / "ADRC"
    # 900101: MRI never run through FreeSurfer; a PET-only session
    write(root, "900101/20240101/anat/900101-20240101_T1w.nii")
    write(root, "900101/20240110/pet/900101-20240110_PET.nii")
    # 900102: recon-all failed, so hippocampus never ran
    write(root, "900102/20230101/anat/900102-20230101_T1w.nii")
    write(root, f"{fs('900102', '20230101')}/scripts/recon-all.error")
    # 900103: everything done
    write(root, "900103/20220101/anat/900103-20220101_T1w.nii")
    write(root, f"{fs('900103', '20220101')}/{HIPPO_LOG}", "started\n" + HIPPO_DONE)
    # 900104: hippocampus killed part way; per-subject logs folder
    write(root, "900104/20210101/anat/900104-20210101_T1w.nii")
    write(root, f"{fs('900104', '20210101')}/{HIPPO_LOG}", "started\nstep 3 of 9\n")
    write(root, "900104/logs/pet_suvr_processing_900104.log")
    # 900105: marker present but followed by more than 1000 characters (only the tail is read)
    write(root, "900105/20200101/anat/900105-20200101_T1w.nii")
    write(root, f"{fs('900105', '20200101')}/{HIPPO_LOG}", HIPPO_DONE + "x" * 1200)
    return root


def test_check_incomplete_processing(adrc):
    no_anat, no_fs, bad_recon, bad_hippo = missing.check_incomplete_processing(adrc)
    assert sorted(no_anat) == ["900101/20240110", "900104/logs"]
    assert no_fs == ["900101/20240101"]
    assert bad_recon == ["900102/20230101"]
    assert sorted(bad_hippo) == ["900102/20230101", "900104/20210101", "900105/20200101"]


def test_subject_scan_dirs_ignores_files(adrc):
    write(adrc, "900101/notes.txt")
    dirs = missing.get_subject_scan_dirs(adrc)
    assert all(d.is_dir() for d in dirs)
    assert adrc / "900101/20240101" in dirs


def test_find_adrc_folders_needs_parent(adrc):
    assert missing.find_adrc_folders(adrc.parent) == [adrc]
    assert missing.find_adrc_folders(adrc) == []  # the ADRC folder itself is not matched


def test_main_report_and_log_file(adrc, tmp_path, capsys):
    done = tmp_path / "data" / "batch2" / "ADRC"
    write(done, "900106/20190101/anat/900106-20190101_T1w.nii")
    write(done, f"{fs('900106', '20190101')}/{HIPPO_LOG}", HIPPO_DONE)
    log = tmp_path / "logs" / "fs_check.log"

    missing.main(tmp_path / "data", str(log))

    out = capsys.readouterr().out
    assert out.count("Incomplete processing in ADRC folder") == 1
    assert f"Incomplete processing in ADRC folder: {adrc}" in out
    assert "- 900101/20240101" in out
    assert "Total subjects with FreeSurfer errors: 1" in out
    assert "Total subjects missing hippocampal processing: 3" in out
    assert "900104/logs" not in out  # the missing-anat list is not printed
    assert log.read_text() == out


def test_main_all_complete(tmp_path, capsys):
    root = tmp_path / "ADRC"
    write(root, "900106/20190101/anat/900106-20190101_T1w.nii")
    write(root, f"{fs('900106', '20190101')}/{HIPPO_LOG}", HIPPO_DONE)
    missing.main(tmp_path)
    assert "All subjects have completed processing" in capsys.readouterr().out


def test_main_no_adrc(tmp_path, capsys):
    missing.main(tmp_path)
    assert "No ADRC folders found." in capsys.readouterr().out


# --- check_hippocampus.py / check_recon_all.py --------------------------------------------------


@pytest.fixture
def fs_tree(tmp_path):
    root = tmp_path / "ADRC"
    write(root, f"{fs('900201', '20240101')}/{HIPPO_LOG}", HIPPO_DONE)
    write(root, f"{fs('900202', '20240101')}/mri/T1.mgz")
    write(root, f"{fs('900203', '20240101')}/scripts/recon-all.error")
    write(root, f"{fs('900203', '20180101')}/scripts/recon-all.error")
    return root


def test_hippocampus_lists_completed_subjects(fs_tree, capsys):
    check_hippocampus.check_hippocampus_done(fs_tree)
    out = capsys.readouterr().out
    assert f"Hippocampal subfields processing completed: {fs_tree / '900201'}" in out
    assert "Directories with completed processing: 1" in out


@pytest.mark.xfail(strict=True, reason="all_subject_dirs uses parents[4] of .../freesurfer741, "
                                       "which is two levels above the dataset root, not the subject")
def test_hippocampus_counts_subjects(fs_tree, capsys):
    check_hippocampus.check_hippocampus_done(fs_tree)
    out = capsys.readouterr().out
    assert "Total directories checked: 3" in out
    assert f"Hippocampal subfields processing needed: {fs_tree / '900202'}" in out


def test_recon_all_errors(fs_tree, capsys):
    check_recon_all.check_freesurfer_errors(fs_tree)
    out = capsys.readouterr().out
    assert "Total error files found: 2" in out
    assert "900203-20240101_T1w" in out and "900203-20180101_T1w" in out
    assert "900202" not in out


def test_recon_all_no_errors(tmp_path, capsys):
    write(tmp_path, f"{fs('900201', '20240101')}/mri/T1.mgz")
    check_recon_all.check_freesurfer_errors(tmp_path)
    assert capsys.readouterr().out == "No error files found.\n"


# --- check_mprage.py ----------------------------------------------------------------------------


@pytest.fixture
def anat_tree(tmp_path):
    root = tmp_path / "ADRC"
    nifti(root / "900301/20240101/anat/900301-20240101_T1w.nii", (8, 8, 8))
    nifti(root / "900301/20240101/anat/900301-20240101_T2w.nii.gz", (8, 8, 6))
    nifti(root / "900302/20240101/anat/900302-20240101_T1w.nii.gz", (6, 6, 6, 2))
    nifti(root / "900302/20240101/anat/900302-20240101_slice.nii", (8, 8))
    nifti(root / "900302/20240101/pet/900302-20240101_PET.nii", (8, 8, 8))  # not in anat
    write(root, "900303/20240101/anat/900303-20240101_T1w.nii", "not a nifti")
    write(root, "900303/20240101/anat/900303-20240101_T1w.json", "{}")
    return root


def test_find_anat_folders(anat_tree):
    found = sorted(check_mprage.find_anat_folders(anat_tree))
    assert found == [str(anat_tree / f"{s}/20240101/anat") for s in ("900301", "900302", "900303")]


def test_isotropic_files(anat_tree, capsys):
    files = check_mprage.check_nifti_dimensions(check_mprage.find_anat_folders(anat_tree))
    assert sorted((f["filename"], f["matrix_size"]) for f in files) == [
        ("900301-20240101_T1w.nii", 8),
        ("900302-20240101_T1w.nii.gz", 6),
    ]
    out = capsys.readouterr().out
    assert "Error processing" in out and "900303-20240101_T1w.nii" in out


def test_mprage_main_writes_csv(anat_tree, tmp_path, monkeypatch, capsys):
    out = tmp_path / "iso.csv"
    monkeypatch.setattr(sys, "argv", ["check_mprage.py", str(anat_tree), "-o", str(out)])
    check_mprage.main()
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert sorted(r["filename"] for r in rows) == ["900301-20240101_T1w.nii", "900302-20240101_T1w.nii.gz"]
    assert {r["matrix_size"] for r in rows} == {"8", "6"}
    assert "Found 3 'anat' folders" in capsys.readouterr().out
