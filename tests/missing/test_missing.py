"""Tests for pipeline/7_DirectoryStats (find_missing / process_missing): inventory statuses and what process_missing.py runs.

No FreeSurfer, FSL or imaging data needed: trees are built from empty files and the external
steps are replaced with fakes.
"""

import sys
from pathlib import Path

import pytest

MISSING_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "7_DirectoryStats"
sys.path.insert(0, str(MISSING_DIR))

import find_missing  # noqa: E402
import inventory  # noqa: E402
import process_missing  # noqa: E402
from inventory import MriState, PetState  # noqa: E402

Stage, Status = process_missing.Stage, process_missing.Status


def touch(root, *rel_paths):
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def recon(root, subject, date, stem=None, hippo=True):
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
    assert find_missing.main([str(adrc), "--csv", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0] == ",".join(find_missing.CSV_FIELDS)
    assert len(lines) == 1 + 11 + 9
    assert "would run: 3 MRI, 3 PET (+2 PET waiting on their MRI's recon-all)" in capsys.readouterr().out


def test_dry_run_changes_nothing(adrc, capsys):
    before = sorted(adrc.rglob("*"))
    assert process_missing.main(["all", str(adrc), "--dry-run"]) == 0
    assert sorted(adrc.rglob("*")) == before
    out = capsys.readouterr().out
    assert "MRI: 3 scan(s)" in out
    assert "PET after the MRI step: 2 scan(s)" in out
    assert "900002-20240301_PET.nii   waiting_for_mri" in out


def test_process_mri_runs_recon_then_hippocampus(adrc, monkeypatch):
    calls = []

    def fake_fs(scan, log):
        calls.append(("recon", scan.name))
        return {"fs_success": True, "fs_path": scan.parent.parent / "freesurfer741"}

    def fake_hc(subject, fs_path, log):
        calls.append(("hippo", subject, fs_path.relative_to(adrc).as_posix()))
        return {"hc_success": True}

    monkeypatch.setattr(process_missing, "process_subject_freesurfer", fake_fs)
    monkeypatch.setattr(process_missing, "process_subject_hippocampus", fake_hc)
    mri, _ = inventory.inventory(adrc, ["900001", "900003", "900004", "900005"])
    todo = [r for r in mri if r.state in inventory.MRI_TODO]
    assert process_missing.run_mri(todo, cores=1, run_hippocampus=True, log_file=None) == 0
    assert sorted(calls) == [
        ("hippo", "900001-20240101_T1w", "900001/20240101/freesurfer741"),
        ("hippo", "900003-20230101_T1w", "900003/20230101/freesurfer741"),
        ("recon", "900001-20240101_T1w.nii"),
    ]


def test_process_mri_skips_hippocampus_after_failed_recon(adrc, monkeypatch):
    monkeypatch.setattr(process_missing, "process_subject_freesurfer",
                        lambda scan, log: {"fs_success": False, "fs_path": None})
    monkeypatch.setattr(process_missing, "process_subject_hippocampus",
                        lambda *a: pytest.fail("hippocampus should not run"))
    mri, _ = inventory.inventory(adrc, ["900001"])
    assert process_missing.run_mri(mri, cores=1, run_hippocampus=True, log_file=None) == 1


class Recorder(Stage):
    """Stands in for a SUVR stage; records which tasks it was given."""

    def __init__(self, name, fail=()):
        self.name, self.fail, self.seen = name, set(fail), []

    def tasks(self, subject):
        raise AssertionError("SelectedTasks must not ask the inner stage for tasks")

    def log_file(self, task):
        return Path("/dev/null")

    def process(self, task, log):
        self.seen.append(task.label)
        if task.label in self.fail:
            raise RuntimeError("boom")
        return Status.DONE


def test_run_suvr_only_touches_selected_pairs(adrc, monkeypatch):
    prepare = Recorder("prepare", fail={"900007-20200202_PET.nii x 900007-20200101_CorMPRAGE.nii"})
    register = Recorder("register")
    quantify = Recorder("quantify")
    monkeypatch.setattr(process_missing, "PrepareStage", lambda: prepare)
    monkeypatch.setattr(process_missing, "RegisterStage", lambda: register)
    monkeypatch.setattr(process_missing, "QuantifyStage", lambda tracers, lut: quantify)

    _, pet = inventory.inventory(adrc)
    assert process_missing.run_suvr(adrc, pet, cores=1, compound=None, lut=None) == 1

    assert sorted(prepare.seen) == [
        "900003-20230105_PET_256.nii x 900003-20230101_T1w.nii",
        "900006-20240501_PET.nii x 900006-20240601_T1w.nii",
        "900007-20200202_PET.nii x 900007-20200101_CorMPRAGE.nii",
    ]
    done = ["900003_pet_20230105_256_mri_20230101", "900006_pet_20240501_mri_20240601"]
    assert sorted(register.seen) == done  # the failed prepare is not carried forward
    assert sorted(quantify.seen) == done
