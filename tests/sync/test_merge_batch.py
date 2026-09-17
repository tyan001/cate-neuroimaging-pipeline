"""Tests for sync/merge_batch.py. Uses the real rsync on trees of small files."""

import os
import shutil
import sys
from pathlib import Path

import pytest

SYNC_DIR = Path(__file__).resolve().parents[2] / "sync"
sys.path.insert(0, str(SYNC_DIR))

import merge_batch  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")

RECON = ["mri/T1.mgz", "mri/aparc+aseg.mgz", "stats/aseg.stats", "stats/lh.aparc.stats",
         "stats/rh.aparc.stats", "stats/hipposubfields.lh.T1.v22.stats",
         "stats/hipposubfields.rh.T1.v22.stats"]


def write(root, rel, text=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rel if text is None else text)
    return p


def recon(root, subj, date, files=RECON):
    for f in files:
        write(root, f"{subj}/{date}/freesurfer741/{subj}-{date}_T1w/{f}")


def pair(root, subj, pet_date, mri_date, done=True):
    name = f"{subj}_pet_{pet_date}_mri_{mri_date}"
    base = f"{subj}/{pet_date}/suvr/{subj}-{pet_date}_PET/{name}"
    write(root, f"{base}/MRI/{subj}-{mri_date}_T1w.nii")
    if done:
        write(root, f"{base}/res/{name}_suvr_combined_cerebellum.csv")


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink())


@pytest.fixture
def trees(tmp_path):
    batch = tmp_path / "batch90" / "ADRC"
    main = tmp_path / "NWSI" / "ADRC"
    main.mkdir(parents=True)

    # 900001: new subject, MRI + PET, all finished
    write(batch, "900001/20240101/anat/900001-20240101_T1w.nii")
    recon(batch, "900001", "20240101")
    write(batch, "900001/20240110/pet/900001-20240110_PET.nii")
    pair(batch, "900001", "20240110", "20240101")
    write(batch, "900001/logs/pet_suvr_processing_900001.log")
    # fsaverage link as recon-all leaves it
    fsavg = tmp_path / "freesurfer/subjects/fsaverage"
    write(fsavg, "surf/lh.white")
    os.symlink(fsavg, batch / "900001/20240101/freesurfer741/fsaverage")
    # a symlinked file is copied as a real file
    real = write(tmp_path, "elsewhere/ct.nii", "ct data")
    (batch / "900001/20240110/ct").mkdir()
    os.symlink(real, batch / "900001/20240110/ct/900001-20240110_CT.nii")

    # 900002: failed recon; unfinished SUVR; stray copy of another session's scan
    write(batch, "900002/20230101/anat/900002-20230101_T1w.nii")
    write(batch, "900002/20230101/freesurfer741/900002-20230101_T1w/scripts/recon-all.error")
    write(batch, "900002/20240101/anat/900002-20240101_T1w.nii")
    write(batch, "900002/20240101/anat/900002-20230101_T1w.nii")
    recon(batch, "900002", "20240101")
    write(batch, "900002/20240102/pet/900002-20240102_PET.nii")
    pair(batch, "900002", "20240102", "20240101", done=False)

    # 900003: session already in main (re-delivered); recon already there, one file differs
    for root in (batch, main):
        write(root, "900003/20200101/anat/900003-20200101_T1w.nii", "same scan")
        recon(root, "900003", "20200101")
    write(batch, "900003/20200101/modalities/notes.json", "new")
    write(main, "900003/20200101/modalities/notes.json", "old!")
    write(batch, "900003/20200101/freesurfer741/900003-20200101_T1w/stats/extra.stats")
    os.utime(main / "900003/20200101/anat/900003-20200101_T1w.nii", (0, 0))  # same content, other mtime

    # batch-level logs
    write(batch, "fs_logs/ADRC.log", "fs log")
    write(main, "logs/fs_logs/batch1.log", "older batch")
    return batch, main


def test_plan(trees):
    batch, main = trees
    plan = merge_batch.build_plan(batch, main)
    assert plan.batch == "batch90"
    assert sorted(plan.skipped) == [
        "900001/20240101/freesurfer741/fsaverage",
        "900002/20230101/freesurfer741/900002-20230101_T1w",
        "900002/20240101/anat/900002-20230101_T1w.nii",
        "900002/20240102/suvr/900002-20240102_PET/900002_pet_20240102_mri_20240101",
        "900003/20200101/freesurfer741/900003-20200101_T1w",
    ]
    assert plan.conflicts == ["900003/20200101/modalities/notes.json"]
    assert plan.same == 1
    assert sorted(plan.new_sessions) == ["900001/20240101", "900001/20240110",
                                         "900002/20230101", "900002/20240101", "900002/20240102"]
    assert [t for _, t in plan.logs] == ["logs/fs_logs/batch90.log"]
    assert not any(r.startswith("900003") for r in plan.copy)
    assert "900001/logs/pet_suvr_processing_900001.log" in plan.copy


def test_dry_run_copies_nothing(trees, capsys):
    batch, main = trees
    before = files(main)
    assert merge_batch.main([str(batch), "--dest", str(main)]) == 0
    assert files(main) == before
    out = capsys.readouterr().out
    assert "Dry run" in out and "recon_failed" in out


def test_execute(trees, capsys):
    batch, main = trees
    old_notes = (main / "900003/20200101/modalities/notes.json").read_text()
    assert merge_batch.main([str(batch), "--dest", str(main), "--execute"]) == 0
    assert "copied and verified" in capsys.readouterr().out
    got = set(files(main))

    # finished work is copied
    assert "900001/20240101/freesurfer741/900001-20240101_T1w/stats/aseg.stats" in got
    assert "900001/20240110/suvr/900001-20240110_PET/900001_pet_20240110_mri_20240101/res/" \
           "900001_pet_20240110_mri_20240101_suvr_combined_cerebellum.csv" in got
    ct = main / "900001/20240110/ct/900001-20240110_CT.nii"
    assert not ct.is_symlink() and ct.read_text() == "ct data"
    # scans with unfinished work are copied, the unfinished work is not
    assert "900002/20230101/anat/900002-20230101_T1w.nii" in got
    assert "900002/20240102/pet/900002-20240102_PET.nii" in got
    assert not any("/freesurfer741/900002-20230101_T1w/" in f for f in got)
    assert not any("900002_pet_20240102" in f for f in got)
    assert "900002/20240101/anat/900002-20230101_T1w.nii" not in got
    assert not any("fsaverage" in f for f in got)
    # nothing in main is replaced or merged into
    assert (main / "900003/20200101/modalities/notes.json").read_text() == old_notes
    assert "900003/20200101/freesurfer741/900003-20200101_T1w/stats/extra.stats" not in got
    # logs
    assert (main / "logs/fs_logs/batch90.log").read_text() == "fs log"
    assert (main / "logs/fs_logs/batch1.log").read_text() == "older batch"
    assert len(list((main / "logs/merge_logs").glob("batch90_*.log"))) == 1


def test_rerun_copies_nothing_new(trees):
    batch, main = trees
    assert merge_batch.main([str(batch), "--dest", str(main), "--execute"]) == 0
    plan = merge_batch.build_plan(batch, main)
    assert plan.copy == [] and plan.logs == []


def test_include_incomplete(trees):
    batch, main = trees
    plan = merge_batch.build_plan(batch, main, include_incomplete=True)
    assert "900002/20230101/freesurfer741/900002-20230101_T1w" not in plan.skipped
    assert "900002/20230101/freesurfer741/900002-20230101_T1w/scripts/recon-all.error" in plan.copy
    assert "900001/20240101/freesurfer741/fsaverage" in plan.skipped  # never copied


def test_batch_number_and_env(trees, monkeypatch):
    batch, main = trees
    processing = batch.parent.parent / "Processing"
    (processing / "Both").mkdir(parents=True)
    shutil.move(batch.parent, processing / "Both" / "batch90")
    monkeypatch.setenv("PROCESSING_ROOT", str(processing))
    monkeypatch.setenv("ADRC_ROOT", str(main))
    assert merge_batch.main(["90", "--execute"]) == 0
    assert (main / "900001/20240110/pet/900001-20240110_PET.nii").is_file()


@pytest.mark.parametrize("dest", ["same", "inside", "missing"])
def test_bad_destinations(trees, dest, capsys):
    batch, _ = trees
    target = {"same": batch, "inside": batch / "900001", "missing": batch.parent / "nope"}[dest]
    assert merge_batch.main([str(batch), "--dest", str(target), "--execute"]) == 1
