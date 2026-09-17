"""Shared fixtures for the 7_DirectoryStats tests: a small ADRC tree of empty files.

The stage scripts are imported by module name, so the folder holding them goes on sys.path once,
here, rather than in every test module.
"""

import sys
from pathlib import Path

import pytest

STATS_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "7_DirectoryStats"
sys.path.insert(0, str(STATS_DIR))


def touch(root, *rel_paths):
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def recon(root, subject, date, stem=None, hippo=True):
    # Imported here, not at module scope: inventory.py needs the 3_suvr/dev/OOP code, which is not
    # in the repo, and this file must stay importable for test_directory_data_count.py.
    import inventory

    stem = stem or f"{subject}-{date}_T1w"
    base = f"{subject}/{date}/freesurfer741/{stem}"
    outputs = list(inventory.RECON_OUTPUTS) + (list(inventory.HIPPO_OUTPUTS) if hippo else [])
    touch(root, *[f"{base}/{o}" for o in outputs])


def suvr_result(root, subject, pet_date, mri_date):
    pair = f"{subject}_pet_{pet_date}_mri_{mri_date}"
    touch(root, f"{subject}/{pet_date}/suvr/{subject}-{pet_date}_PET/{pair}/res/{pair}_suvr_combined_cerebellum.csv")


@pytest.fixture
def adrc(tmp_path):
    root = tmp_path / "ADRC"
    touch(
        root,
        # 900001: MRI never processed; PET waits on it
        "900001/20240101/anat/900001-20240101_T1w.nii",
        "900001/20240110/pet/900001-20240110_PET.nii",
        # 900002: PET only
        "900002/20240301/pet/900002-20240301_PET.nii",
        # 900003: MRI done, hippocampus missing; PET never paired
        "900003/20230101/anat/900003-20230101_T1w.nii",
        "900003/20230105/pet/900003-20230105_PET_256.nii",
        # 900004: everything done
        "900004/20220101/anat/900004-20220101_T1w.nii",
        "900004/20220201/pet/900004-20220201_PET.nii",
        # 900005: failed recon, and a recon killed part way
        "900005/20210101/anat/900005-20210101_T1w.nii",
        "900005/20210101/freesurfer741/900005-20210101_T1w/scripts/recon-all.error",
        "900005/20220101/anat/900005-20220101_T1w.nii",
        "900005/20220101/freesurfer741/900005-20220101_T1w/mri/T1.mgz",
        "900005/20220101/freesurfer741/900005-20220101_T1w/scripts/IsRunning.lh+rh",
        # 900006: PET paired long ago with an old MRI; a closer MRI has since been processed
        "900006/20150101/anat/900006-20150101_T1w.nii",
        "900006/20240601/anat/900006-20240601_T1w.nii",
        "900006/20240501/pet/900006-20240501_PET.nii",
        # 900007: pair folder started but no result; plus a badly named PET
        "900007/20200101/anat/900007-20200101_CorMPRAGE.nii",
        "900007/20200202/pet/900007-20200202_PET.nii",
        "900007/20200202/suvr/900007-20200202_PET/900007_pet_20200202_mri_20200101_CorMPRAGE/MRI/x.nii",
        "900007/20200303/pet/900007_20200303_PET.nii",
        # 900008: the 2023 scan was also copied into the 2024 session (ingest bug); stray PET too
        "900008/20230101/anat/900008-20230101_T1w.nii",
        "900008/20240101/anat/900008-20230101_T1w.nii",
        "900008/20240101/anat/900008-20240101_T1w.nii",
        "900008/20240101/pet/900008-20240101_PET.nii",
        "900008/20240101/pet/900008-20230105_PET.nii",
        # not subjects
        "logs/mri_bids_logs/batch1.log",
        "fs_logs/host.log",
    )
    recon(root, "900003", "20230101", hippo=False)
    recon(root, "900004", "20220101")
    suvr_result(root, "900004", "20220201", "20220101")
    recon(root, "900006", "20150101")
    recon(root, "900006", "20240601")
    suvr_result(root, "900006", "20240501", "20150101")
    recon(root, "900007", "20200101", stem="900007-20200101_CorMPRAGE")
    recon(root, "900008", "20230101")
    return root


