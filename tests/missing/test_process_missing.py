"""Tests for pipeline/7_DirectoryStats/process_missing.py: which scans each stage is handed.

process_missing.py imports the FreeSurfer and SUVR stage code from the dev/ and OOP/ folders, which
.gitignore excludes, so this module is skipped wherever that code is absent (CI, a fresh clone).
The inventory and find_missing tests next door do not need it and always run.
"""

import sys
from pathlib import Path

import pytest

STATS_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "7_DirectoryStats"
sys.path.insert(0, str(STATS_DIR))

# process_missing.py imports the FreeSurfer and SUVR stage code from pipeline/2_freesurfer/dev and
# pipeline/3_suvr/dev/OOP, neither of which is part of the repo.
try:
    import inventory  # noqa: E402
    import process_missing  # noqa: E402
except ImportError as exc:
    # inventory.add_code_dir raises a plain ImportError naming the folders it looked in, so
    # pytest.importorskip would re-raise it rather than skip; catch it here instead.
    pytest.skip(f"needs the FreeSurfer/SUVR stage code: {exc}", allow_module_level=True)

Stage, Status = process_missing.Stage, process_missing.Status


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


