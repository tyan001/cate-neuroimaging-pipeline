"""Tests for pipeline/5_aggregate: freesurfer_symlink.py, suvr_symlink.py and prune_suvr_registrations.py.

All three only look at folder names, so trees of small files are enough.
"""

import logging
import sys
from pathlib import Path

import pytest

AGG_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "5_aggregate"
sys.path.insert(0, str(AGG_DIR))

import freesurfer_symlink  # noqa: E402
import prune_suvr_registrations as prune  # noqa: E402
import suvr_symlink  # noqa: E402


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or rel)
    return p


def links(target):
    return {p.name: p.resolve() for p in target.iterdir() if p.is_symlink()}


def run_main(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", [module.__name__, *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    return exc.value.code


# --- freesurfer_symlink.py ----------------------------------------------------------------------


@pytest.fixture
def fs_source(tmp_path):
    root = tmp_path / "ADRC"
    write(root, "900401/20240101/freesurfer741/900401-20240101_T1w/stats/aseg.stats")
    write(root, "900401/20240101/freesurfer741/fsaverage/surf/lh.white")
    write(root, "900401/20240101/freesurfer741/stray.txt")
    write(root, "900401/20240101/anat/900401-20240101_T1w.nii")
    write(root, "900402/20200101/freesurfer741/900402-20200101_CorMPRAGE/stats/aseg.stats")
    write(root, "900402/20210101/freesurfer741_t/900402-20210101_T1w/stats/aseg.stats")  # failed run
    return root


def test_fs_farm_creates_links(fs_source, tmp_path):
    target = tmp_path / "freesurfer_link"
    assert freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=False)
    assert links(target) == {
        "900401-20240101_T1w": fs_source / "900401/20240101/freesurfer741/900401-20240101_T1w",
        "900402-20200101_CorMPRAGE": fs_source / "900402/20200101/freesurfer741/900402-20200101_CorMPRAGE",
    }
    assert (target / "900401-20240101_T1w/stats/aseg.stats").is_file()


def test_fs_farm_rerun_and_summary(fs_source, tmp_path, caplog):
    target = tmp_path / "freesurfer_link"
    freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=False)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=False)
    assert "created:            0" in caplog.text
    assert "already up to date: 2" in caplog.text
    assert "sequence CorMPRAGE" in caplog.text


def test_fs_farm_other_dirname(fs_source, tmp_path):
    target = tmp_path / "link_t"
    freesurfer_symlink.build_farm(fs_source, target, "freesurfer741_t", dry_run=False, force=False)
    assert list(links(target)) == ["900402-20210101_T1w"]


def test_fs_farm_dry_run(fs_source, tmp_path, caplog):
    target = tmp_path / "freesurfer_link"
    with caplog.at_level(logging.INFO):
        assert freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=True, force=False)
    assert list(target.iterdir()) == []
    assert "[dry-run] would create" in caplog.text


def test_fs_farm_same_name_in_two_sessions(fs_source, tmp_path):
    # ingest bug: an older scan copied into a newer session is processed there under its old name
    write(fs_source, "900401/20250101/freesurfer741/900401-20240101_T1w/stats/aseg.stats")
    target = tmp_path / "freesurfer_link"
    assert not freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=False)
    assert links(target)["900401-20240101_T1w"] == fs_source / "900401/20240101/freesurfer741/900401-20240101_T1w"


def test_fs_farm_stale_link_needs_force(fs_source, tmp_path):
    target = tmp_path / "freesurfer_link"
    target.mkdir()
    old = write(tmp_path, "old_recon/stats/aseg.stats").parent.parent
    (target / "900401-20240101_T1w").symlink_to(old)
    real = fs_source / "900401/20240101/freesurfer741/900401-20240101_T1w"

    assert not freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=False)
    assert links(target)["900401-20240101_T1w"] == old

    assert freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=True, force=True)
    assert links(target)["900401-20240101_T1w"] == old

    assert freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=True)
    assert links(target)["900401-20240101_T1w"] == real


def test_fs_farm_never_replaces_real_dir(fs_source, tmp_path):
    target = tmp_path / "freesurfer_link"
    write(target, "900401-20240101_T1w/keep.txt")
    assert not freesurfer_symlink.build_farm(fs_source, target, "freesurfer741", dry_run=False, force=True)
    assert (target / "900401-20240101_T1w/keep.txt").is_file()
    assert not (target / "900401-20240101_T1w").is_symlink()


def test_fs_main(fs_source, tmp_path, monkeypatch):
    target = tmp_path / "freesurfer_link"
    assert run_main(freesurfer_symlink, monkeypatch, "--source", str(fs_source), "--target", str(target)) == 0
    assert len(links(target)) == 2
    assert run_main(freesurfer_symlink, monkeypatch, "--source", str(tmp_path / "nope"),
                    "--target", str(target)) == 1


# --- suvr_symlink.py ----------------------------------------------------------------------------


@pytest.fixture
def suvr_source(tmp_path):
    root = tmp_path / "ADRC"
    for pet in ["900501-20240110_PET", "900501-20240110_PET_256"]:
        write(root, f"900501/20240110/suvr/{pet}/900501_pet_20240110_mri_20240101/res/x.csv")
    write(root, "900501/20240110/suvr/logs/pet_registration.log")
    write(root, "900502/20230105/suvr/900502-20230105_PET/logs/pet_registration.log")
    write(root, "900502/20230105/suvr/odd_folder/readme.txt")
    write(root, "900502/20230105/suvr/notes.txt")
    return root


def test_suvr_farm(suvr_source, tmp_path, caplog):
    target = tmp_path / "suvr_link"
    with caplog.at_level(logging.INFO):
        assert suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=False, force=False)
    assert sorted(links(target)) == ["900501-20240110_PET", "900501-20240110_PET_256",
                                     "900502-20230105_PET", "odd_folder"]
    assert "did not contain '_PET'" in caplog.text and "odd_folder" in caplog.text
    assert (target / "900501-20240110_PET_256/900501_pet_20240110_mri_20240101/res/x.csv").is_file()


def test_suvr_farm_rerun_and_force(suvr_source, tmp_path):
    target = tmp_path / "suvr_link"
    suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=False, force=False)
    assert suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=False, force=False)

    (target / "900502-20230105_PET").unlink()
    (target / "900502-20230105_PET").symlink_to(tmp_path)
    assert not suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=False, force=False)
    assert suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=False, force=True)
    assert links(target)["900502-20230105_PET"] == suvr_source / "900502/20230105/suvr/900502-20230105_PET"


def test_suvr_farm_dry_run(suvr_source, tmp_path):
    target = tmp_path / "suvr_link"
    assert suvr_symlink.build_farm(suvr_source, target, "suvr", dry_run=True, force=False)
    assert list(target.iterdir()) == []


def test_suvr_main(suvr_source, tmp_path, monkeypatch):
    target = tmp_path / "suvr_link"
    assert run_main(suvr_symlink, monkeypatch, "--source", str(suvr_source), "--target", str(target)) == 0
    assert len(links(target)) == 4
    assert run_main(suvr_symlink, monkeypatch, "--source", str(tmp_path / "nope"), "--target", str(target)) == 1


# --- prune_suvr_registrations.py ----------------------------------------------------------------


def reg(root, subject, session, pet_dir, pet_token, mri, suffix=""):
    name = f"{subject}_pet_{pet_token}_mri_{mri}{suffix}"
    write(root, f"{subject}/{session}/suvr/{pet_dir}/{name}/res/{name}_suvr_combined_cerebellum.csv")
    return root / subject / session / "suvr" / pet_dir / name


@pytest.fixture
def pairs(tmp_path):
    root = tmp_path / "ADRC"
    r = {}
    # 900601: three MRIs; 20240201 is closest (31 days) to the PET
    for mri in ["20150101", "20240201", "20250101"]:
        r[f"900601_{mri}"] = reg(root, "900601", "20240101", "900601-20240101_PET", "20240101", mri)
    write(root, "900601/20240101/suvr/900601-20240101_PET/logs/pet_registration.log")
    # 900602: tie, 10 days either side
    for mri in ["20231222", "20240111"]:
        reg(root, "900602", "20240101", "900602-20240101_PET", "20240101", mri)
    # 900603: one registration only
    r["900603"] = reg(root, "900603", "20240101", "900603-20240101_PET", "20240101", "20240102")
    # 900604: non-date PET token and _CorMPRAGE suffix; the session name gives the PET date
    r["900604_near"] = reg(root, "900604", "20160601", "900604-20160601_PET_a", "9.Am2201", "20160610",
                           "_CorMPRAGE")
    r["900604_far"] = reg(root, "900604", "20160601", "900604-20160601_PET_a", "9.Am2201", "20100101",
                          "_CorMPRAGE")
    # 900605: an MRI token that is not a date
    for mri in ["20240102", "baseline"]:
        reg(root, "900605", "20240101", "900605-20240101_PET", "20240101", mri)
    return root, r


def test_prune_plan(pairs):
    root, r = pairs
    to_remove, kept, skipped = prune.plan(root, "suvr")
    assert sorted(to_remove) == sorted([r["900601_20150101"], r["900601_20250101"], r["900604_far"]])
    assert [(k, gap) for _, k, gap in kept] == [(r["900601_20240201"], 31), (r["900604_near"], 9)]
    reasons = {p.name: why for p, why in skipped}
    assert set(reasons) == {"900602-20240101_PET", "900605-20240101_PET"}
    assert reasons["900602-20240101_PET"].startswith("tie at 10 days")
    assert "unparseable MRI date" in reasons["900605-20240101_PET"]


def test_prune_unparseable_session(pairs):
    root, _ = pairs
    for mri in ["20240102", "20240301"]:
        reg(root, "900606", "baseline", "900606-baseline_PET", "20240101", mri)
    _, _, skipped = prune.plan(root, "suvr")
    assert any("unparseable PET date 'baseline'" in why for _, why in skipped)


def test_mri_date_of():
    assert prune.mri_date_of(Path("900601_pet_20240101_mri_20240201_CorMPRAGE")).strftime("%Y%m%d") == "20240201"
    assert prune.mri_date_of(Path("900601_pet_20240101")) is None


def test_prune_dry_run(pairs, monkeypatch, caplog):
    root, _ = pairs
    before = sorted(root.rglob("*"))
    monkeypatch.setattr(sys, "argv", ["prune", "--source", str(root)])
    with caplog.at_level(logging.INFO):
        prune.main()
    assert sorted(root.rglob("*")) == before
    assert "REMOVE 900601/20240101/suvr/900601-20240101_PET/900601_pet_20240101_mri_20150101" in caplog.text
    assert "dry run" in caplog.text


def test_prune_execute(pairs, monkeypatch):
    root, r = pairs
    monkeypatch.setattr(sys, "argv", ["prune", "--source", str(root), "--execute"])
    prune.main()
    assert not r["900601_20150101"].exists() and not r["900601_20250101"].exists()
    assert r["900601_20240201"].is_dir() and r["900603"].is_dir()
    assert (root / "900601/20240101/suvr/900601-20240101_PET/logs").is_dir()
    assert len(list((root / "900602/20240101/suvr/900602-20240101_PET").iterdir())) == 2


def test_prune_quarantine(pairs, tmp_path, monkeypatch):
    root, r = pairs
    quarantine = tmp_path / "suvr_pruned"
    monkeypatch.setattr(sys, "argv", ["prune", "--source", str(root), "--execute", "--quarantine", str(quarantine)])
    prune.main()
    moved = quarantine / r["900604_far"].relative_to(root)
    assert not r["900604_far"].exists()
    assert (moved / "res" / f"{moved.name}_suvr_combined_cerebellum.csv").is_file()
    assert len([p for p in quarantine.rglob("*") if p.name.endswith("_mri_20150101")]) == 1
