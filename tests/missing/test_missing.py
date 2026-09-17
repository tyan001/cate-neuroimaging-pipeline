"""Tests for pipeline/7_DirectoryStats: the scan inventory and the find_missing.py report.

No FreeSurfer, FSL or imaging data needed: the trees are built from empty files (see conftest.py).
What process_missing.py runs is covered in test_process_missing.py.
"""

import sys
from pathlib import Path

import pytest

STATS_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "7_DirectoryStats"
sys.path.insert(0, str(STATS_DIR))

# inventory.py imports the PET/MRI layout helpers from pipeline/3_suvr/dev/OOP, which is not part
# of the repo, so these tests only run where that code is present (not in CI or a fresh clone).
try:
    import find_missing  # noqa: E402
    import inventory  # noqa: E402
    from inventory import MriState, PetState  # noqa: E402
except ImportError as exc:
    pytest.skip(f"needs the SUVR layout code: {exc}", allow_module_level=True)


def states(records):
    # 900008 has two files with the same name; it gets its own test.
    return {r.scan.name: r.state for r in records if r.subject != "900008"}


def test_mri_states(adrc):
    mri, _ = inventory.inventory(adrc)
    assert states(mri) == {
        "900001-20240101_T1w.nii": MriState.NO_FREESURFER,
        "900003-20230101_T1w.nii": MriState.NO_HIPPOCAMPUS,
        "900004-20220101_T1w.nii": MriState.COMPLETE,
        "900005-20210101_T1w.nii": MriState.RECON_FAILED,
        "900005-20220101_T1w.nii": MriState.RECON_INCOMPLETE,
        "900006-20150101_T1w.nii": MriState.COMPLETE,
        "900006-20240601_T1w.nii": MriState.COMPLETE,
        "900007-20200101_CorMPRAGE.nii": MriState.COMPLETE,
    }
    killed = next(r for r in mri if r.scan.name == "900005-20220101_T1w.nii")
    assert "IsRunning" in killed.detail


def test_pet_states(adrc):
    _, pet = inventory.inventory(adrc)
    assert states(pet) == {
        "900001-20240110_PET.nii": PetState.WAITING_FOR_FREESURFER,
        "900002-20240301_PET.nii": PetState.WAITING_FOR_MRI,
        "900003-20230105_PET_256.nii": PetState.NO_SUVR,  # hippocampus is not needed for SUVR
        "900004-20220201_PET.nii": PetState.COMPLETE,
        "900006-20240501_PET.nii": PetState.NO_SUVR,
        "900007-20200202_PET.nii": PetState.INCOMPLETE_SUVR,
        "900007_20200303_PET.nii": PetState.BAD_NAME,
    }
    by_name = {r.scan.name: r for r in pet}
    newer = by_name["900006-20240501_PET.nii"]
    assert newer.mri.name == "900006-20240601_T1w.nii"
    assert "also paired with 900006_pet_20240501_mri_20150101" in newer.detail
    assert by_name["900003-20230105_PET_256.nii"].pair.pair_dir_name == "900003_pet_20230105_256_mri_20230101"


def test_wrong_session(adrc):
    mri, pet = inventory.inventory(adrc, ["900008"])
    assert [(r.session, r.scan.name, r.state) for r in mri] == [
        ("20230101", "900008-20230101_T1w.nii", MriState.COMPLETE),
        ("20240101", "900008-20230101_T1w.nii", MriState.WRONG_SESSION),
        ("20240101", "900008-20240101_T1w.nii", MriState.NO_FREESURFER),
    ]
    assert [(r.scan.name, r.state) for r in pet] == [
        ("900008-20230105_PET.nii", PetState.WRONG_SESSION),
        ("900008-20240101_PET.nii", PetState.WAITING_FOR_FREESURFER),
    ]
    # the stray copy is never picked as a PET's MRI
    assert pet[1].mri == adrc / "900008/20240101/anat/900008-20240101_T1w.nii"


def test_subject_filter(adrc):
    mri, pet = inventory.inventory(adrc, ["900002"])
    assert mri == [] and [r.subject for r in pet] == ["900002"]
    with pytest.raises(FileNotFoundError):
        inventory.inventory(adrc, ["999999"])


def test_find_missing_csv(adrc, tmp_path, capsys):
    out = tmp_path / "report" / "missing.csv"
    assert find_missing.main(["--root", str(adrc), "--csv", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0] == ",".join(find_missing.CSV_FIELDS)
    assert len(lines) == 1 + 11 + 9
    assert "would run: 3 MRI, 3 PET (+2 PET waiting on their MRI's recon-all)" in capsys.readouterr().out


def test_find_missing_root_from_env(adrc, monkeypatch, capsys):
    monkeypatch.setenv("ADRC_ROOT", str(adrc))
    assert find_missing.main(["--subject", "900004"]) == 0
    assert f"Root: {adrc}" in capsys.readouterr().out


def test_find_missing_needs_root(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADRC_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc:
        find_missing.main([])
    assert exc.value.code == 2
    assert "--root is required" in capsys.readouterr().err
    assert find_missing.main(["--root", str(tmp_path / "nope")]) == 1
