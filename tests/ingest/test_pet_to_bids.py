"""Tests for pipeline/1_ingest/dropbox_pet_to_bids.py."""

import subprocess
import sys
from pathlib import Path

import pytest

import dropbox_mri_to_bids as mri
import dropbox_pet_to_bids as pet

SCRIPT = Path(pet.__file__)

# PET session -> (subject_id, YYYYMMDD, expected PET source, expected CT source)
FIXTURE_SESSIONS = {
    "PET_720471-04_01152025": ("720471", "20250115",
                               "720471-04_01152025.Amyloid_PET_256.nii",
                               "720471-04_01152025.Amyloid_PET_CT.nii"),
    "PET_720619-01_11152024": ("720619", "20241115",
                               "720619-01_11152024.Amyloid_PET_256.nii",
                               "720619-01_11152024.Amyloid_PET_CT.nii"),
    "PET_930019-C2_06022025": ("930019", "20250602",
                               "930019-C2_06022025.Amyloid_PET_3mmblur.nii",
                               "930019-C2_06022025.Amyloid_PET_CT.nii"),
    "PET_930119-C1_11092025": ("930119", "20251109",
                               "930119-C1_11092025.Amyloid_PET_3mmblur.nii",
                               "930119-C1_11092025.Amyloid_PET_CT.nii"),
    # has original/ and UF_recon/ subfolders; only the top-level mean_5mmblur should be picked
    "PET_930120-01_09202025": ("930120", "20250920",
                               "930120-01_09202025_mean_5mmblur.nii",
                               "930120-01_09202025.Amyloid_PET_CT.nii"),
    "PET_930123-C1_05032025": ("930123", "20250503",
                               "930123-C1_05032025.Amyloid_PET_3mmblur.nii",
                               "930123-C1_05032025.Amyloid_PET_CT.nii"),
}


def rel_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- parse_folder_name

@pytest.mark.parametrize("folder, expected", sorted((k, v[:2]) for k, v in FIXTURE_SESSIONS.items()))
def test_parse_fixture_folder_names(folder, expected, logger):
    assert pet.parse_folder_name(folder, logger) == expected


@pytest.mark.parametrize("folder", [
    "PET_900011_01022023",      # PET requires a session, unlike MRI
    "MRI_900011-01_01022023",
    "900011-01_01022023",
    "PET_900011-01_2023",
])
def test_parse_folder_name_rejects(folder, logger):
    assert pet.parse_folder_name(folder, logger) is None


# --------------------------------------------------------------------------- file classifiers

@pytest.mark.parametrize("filename, is_pet, is_ct", [
    ("x.Amyloid_PET_256.nii", True, False),
    ("x.Amyloid_PET_3mmblur.nii", True, False),
    ("x.amyloid_pet_6mmblur.nii", True, False),          # case-insensitive
    ("x_mean_5mmblur.nii", True, False),
    ("x.Amyloid_PET_CT.nii", False, True),
    ("x_PET_CT.nii", False, True),
    ("x_mean_UF_PROTOCOL_5mmblur.nii", False, False),
    ("x_PET_BRAIN_AC.nii", False, False),
    ("900021-02_10142025.Amyloid_PET_128a.nii", True, False),   # batch87
    ("x.Amyloid_PET_128.nii", True, False),
    ("900022-01_01012024.Amyloid_CT.nii", False, True),         # batch87
    ("x.T1.nii", False, False),
])
def test_classifiers(filename, is_pet, is_ct, logger):
    assert pet.is_pet_file(filename, logger) is is_pet
    assert pet.is_ct_file(filename, logger) is is_ct


def test_custom_patterns(logger):
    assert pet.is_pet_file("x_PET_200.nii", logger) is False
    assert pet.is_pet_file("x_PET_200.nii", logger, pet_patterns=["pet_200"]) is True
    assert pet.is_ct_file("x_CT_Brain.nii", logger, ct_patterns=["CT_Brain"]) is True


def test_ct_match_is_never_pet(logger):
    # a broad PET substring would also hit the CT file
    assert pet.is_pet_file("x.Amyloid_PET_CT.nii", logger, pet_patterns=["_PET"]) is False


def test_best_match_uses_pattern_order_then_depth(tmp_path):
    files = [tmp_path / "s/a_PET_256.nii", tmp_path / "s/b_mean_5mmblur.nii",
             tmp_path / "s/sub/a_mean_5mmblur.nii", tmp_path / "s/x_PET_CT.nii"]
    assert pet.best_match(files, pet.PET_PATTERNS).name == "b_mean_5mmblur.nii"
    assert pet.best_match(files, ["PET_256", "mean_5mmblur"]).name == "a_PET_256.nii"
    assert pet.best_match(files, ["_PET"], exclude=pet.CT_PATTERNS).name == "a_PET_256.nii"
    assert pet.best_match(files, ["nothing"]) is None


# --------------------------------------------------------------------------- restructure_files on the fixture

@pytest.fixture
def converted(ingest_data, tmp_path, logger):
    target = tmp_path / "batch"
    subjects = pet.restructure_files(ingest_data / "PET", target, logger)
    return ingest_data / "PET", target / "ADRC", subjects


def test_all_fixture_subjects_processed(converted):
    _, _, subjects = converted
    assert sorted(subjects) == sorted(v[0] for v in FIXTURE_SESSIONS.values())


@pytest.mark.parametrize("folder", sorted(FIXTURE_SESSIONS))
def test_pet_and_ct_selected(converted, folder):
    _, adrc, _ = converted
    subj, date, pet_src, ct_src = FIXTURE_SESSIONS[folder]
    session = adrc / subj / date
    assert sorted(p.name for p in session.iterdir()) == ["ct", "pet"]
    assert [p.name for p in (session / "pet").iterdir()] == [f"{subj}-{date}_PET.nii"]
    assert [p.name for p in (session / "ct").iterdir()] == [f"{subj}-{date}_CT.nii"]
    # content is the source's relative path -> proves which file was copied
    assert (session / "pet" / f"{subj}-{date}_PET.nii").read_text() == f"PET/{folder}/{pet_src}"
    assert (session / "ct" / f"{subj}-{date}_CT.nii").read_text() == f"PET/{folder}/{ct_src}"


def test_source_is_untouched(ingest_data, tmp_path, logger):
    before = rel_files(ingest_data)
    pet.restructure_files(ingest_data / "PET", tmp_path / "batch", logger)
    assert rel_files(ingest_data) == before


def test_rerun_is_idempotent(ingest_data, tmp_path, logger):
    target = tmp_path / "batch"
    pet.restructure_files(ingest_data / "PET", target, logger)
    first = rel_files(target)
    pet.restructure_files(ingest_data / "PET", target, logger)
    assert rel_files(target) == first


def test_mri_and_pet_share_one_adrc_tree(ingest_data, tmp_path, logger):
    """Both converters write into the same batch; same-day scans merge into one date folder."""
    target = tmp_path / "batch"
    mri.restructure_files(ingest_data / "MRI", target, logger)
    pet.restructure_files(ingest_data / "PET", target, logger)
    adrc = target / "ADRC"
    # 930123: MRI and PET on the same day
    assert sorted(p.name for p in (adrc / "930123/20250503").iterdir()) == ["anat", "ct", "modalities", "pet"]
    # 720619: MRI and PET on different days
    assert sorted(p.name for p in (adrc / "720619").iterdir()) == ["20241115", "20250131"]
    # 720471: PET only
    assert sorted(p.name for p in (adrc / "720471/20250115").iterdir()) == ["ct", "pet"]


# --------------------------------------------------------------------------- synthetic edge cases

def test_nii_gz_is_ignored(make_tree, tmp_path, logger):
    src = make_tree("PET", [
        "PET_900031-C1_01022023/900031-C1_01022023_aPET_mean_3mmblur_T1_space.nii.gz",
        "PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_CT.nii",
    ])
    pet.restructure_files(src, tmp_path / "out", logger)
    session = tmp_path / "out/ADRC/900031/20230102"
    assert list((session / "pet").iterdir()) == []
    assert [p.name for p in (session / "ct").iterdir()] == ["900031-20230102_CT.nii"]


def test_no_matches_leaves_empty_dirs(make_tree, tmp_path, logger, caplog):
    src = make_tree("PET", ["PET_900031-C1_01022023/900031-C1_01022023_PET_BRAIN_AC.nii"])
    pet.restructure_files(src, tmp_path / "out", logger)
    session = tmp_path / "out/ADRC/900031/20230102"
    assert list((session / "pet").iterdir()) == []
    assert list((session / "ct").iterdir()) == []
    assert "No PET file found for subject 900031" in caplog.text
    assert "No CT file found for subject 900031" in caplog.text


def test_unparseable_and_non_pet_folders_skipped(make_tree, tmp_path, logger):
    src = make_tree("PET", [
        "PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_256.nii",
        "PET_900032_01022023/900032_01022023.Amyloid_PET_256.nii",   # no session
        "MRI_900033-C1_01022023/900033-C1_01022023.T1.nii",
    ])
    subjects = pet.restructure_files(src, tmp_path / "out", logger)
    assert list(subjects) == ["900031"]


def test_batch87_names(make_tree, tmp_path, logger):
    """PET_128a and Amyloid_CT deliveries (batch87) were skipped before these patterns existed."""
    src = make_tree("PET", [
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_CT.json",
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_CT.nii",
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_PET_128a.json",
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_PET_128a.nii",
    ])
    pet.restructure_files(src, tmp_path / "out", logger)
    session = tmp_path / "out/ADRC/900022/20240101"
    assert (session / "pet/900022-20240101_PET.nii").read_text() == \
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_PET_128a.nii"
    assert (session / "ct/900022-20240101_CT.nii").read_text() == \
        "PET_900022-01_01012024/900022-01_01012024.Amyloid_CT.nii"


def test_extra_patterns_and_miss_warning(make_tree, tmp_path, logger, caplog):
    src = make_tree("PET", ["PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_200.nii"])
    pet.restructure_files(src, tmp_path / "a", logger)
    assert "900031-C1_01022023.Amyloid_PET_200.nii" in caplog.text   # listed in the miss warning
    assert "--pet-pattern" in caplog.text

    pet.restructure_files(src, tmp_path / "b", logger, pet_patterns=pet.PET_PATTERNS + ["PET_200"])
    assert (tmp_path / "b/ADRC/900031/20230102/pet/900031-20230102_PET.nii").is_file()


def test_cli_pattern_flags(make_tree, tmp_path):
    src = make_tree("PET", [
        "PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_200.nii",
        "PET_900031-C1_01022023/900031-C1_01022023.CT_Brain.nii",
    ])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(src), "--target_dir", str(tmp_path / "out"),
         "--pet-pattern", "PET_200", "--ct-pattern", "CT_Brain"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    session = tmp_path / "out/ADRC/900031/20230102"
    assert [p.name for p in (session / "pet").iterdir()] == ["900031-20230102_PET.nii"]
    assert [p.name for p in (session / "ct").iterdir()] == ["900031-20230102_CT.nii"]


def test_empty_source_returns_empty(tmp_path, logger):
    (tmp_path / "PET").mkdir()
    assert pet.restructure_files(tmp_path / "PET", tmp_path / "out", logger) == {}


@pytest.mark.xfail(strict=True, reason="PET/CT are latched per subject, not per session")
def test_multi_session_subject_gets_each_sessions_pet(make_tree, tmp_path, logger):
    src = make_tree("PET", [
        "PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_256.nii",
        "PET_900031-C2_06152024/900031-C2_06152024.Amyloid_PET_256.nii",
    ])
    pet.restructure_files(src, tmp_path / "out", logger)
    adrc = tmp_path / "out/ADRC/900031"
    for date, src_name in [("20230102", "PET_900031-C1_01022023/900031-C1_01022023.Amyloid_PET_256.nii"),
                           ("20240615", "PET_900031-C2_06152024/900031-C2_06152024.Amyloid_PET_256.nii")]:
        pet_file = adrc / date / "pet" / f"900031-{date}_PET.nii"
        assert pet_file.is_file()
        assert pet_file.read_text() == src_name


# --------------------------------------------------------------------------- CLI

def test_cli_end_to_end(ingest_data, tmp_path):
    target = tmp_path / "batch"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(ingest_data / "PET"), "--target_dir", str(target)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"Processed {len(FIXTURE_SESSIONS)} subjects" in result.stderr
    logs = list((target / "logs/pet_bids_logs").glob("pet_bids_batch_*.log"))
    assert len(logs) == 1
    assert "Reorganization complete!" in logs[0].read_text()
    assert len(list((target / "ADRC").glob("*/*/pet/*_PET.nii"))) == len(FIXTURE_SESSIONS)
    assert len(list((target / "ADRC").glob("*/*/ct/*_CT.nii"))) == len(FIXTURE_SESSIONS)
