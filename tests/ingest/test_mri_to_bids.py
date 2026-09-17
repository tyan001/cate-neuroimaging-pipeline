"""Tests for pipeline/1_ingest/dropbox_mri_to_bids.py."""

import subprocess
import sys
from pathlib import Path

import pytest

import dropbox_mri_to_bids as mri

SCRIPT = Path(mri.__file__)

# Every MRI session in the fixture -> (subject_id, YYYYMMDD)
FIXTURE_SESSIONS = {
    "MRI_710216-06_11112024": ("710216", "20241111"),
    "MRI_720546-03_03282025": ("720546", "20250328"),
    "MRI_720619-01_01312025": ("720619", "20250131"),
    "MRI_930019-C2_07042025": ("930019", "20250704"),
    "MRI_930118-01_12132025": ("930118", "20251213"),
    "MRI_930119-C1_11082025": ("930119", "20251108"),
    "MRI_930120-01_09192025": ("930120", "20250919"),
    "MRI_930122-D1_09122025": ("930122", "20250912"),
    "MRI_930123-C1_05032025": ("930123", "20250503"),
}


def rel_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- parse_folder_name

@pytest.mark.parametrize("folder, expected", sorted(FIXTURE_SESSIONS.items()))
def test_parse_fixture_folder_names(folder, expected, logger):
    assert mri.parse_folder_name(folder, logger) == expected


@pytest.mark.parametrize("folder, expected", [
    ("MRI_110001_01022023", ("110001", "20230102")),      # session is optional for MRI
    ("MRI_110001-01_01022023", ("110001", "20230102")),
    ("MRI_320001-D1_12312025", ("320001", "20251231")),
])
def test_parse_folder_name_variants(folder, expected, logger):
    assert mri.parse_folder_name(folder, logger) == expected


@pytest.mark.parametrize("folder", [
    "PET_110001-01_01022023",   # wrong modality
    "110001-01_01022023",       # prefix missing (prefix.py not run)
    "MRI_110001-01_2023",       # date too short
    "MRI_110001-01",            # no date
    "notes",
])
def test_parse_folder_name_rejects(folder, logger):
    assert mri.parse_folder_name(folder, logger) is None


# --------------------------------------------------------------------------- get_modality_from_filename

@pytest.mark.parametrize("filename, expected", [
    ("720619-01_01312025.T1.nii", "T1"),
    ("720619-01_01312025.MB_DTI_AP.nii", "MB_DTI_AP"),
    ("720619-01_01312025.T2GRE_ph.nii", "T2GRE_ph"),
    ("110001-01_01022023.Cor_MPRAGE.nii", "Cor_MPRAGE"),
    ("20250131120000_720619-01_Sagittal_3D_FLAIR_(MSV22).nii", None),  # no ".<modality>." part
    ("720619-01_01312025.DTI1000.bval", None),
])
def test_get_modality_from_filename(filename, expected, logger):
    assert mri.get_modality_from_filename(filename, logger) == expected


# --------------------------------------------------------------------------- restructure_files on the fixture

@pytest.fixture
def converted(ingest_data, tmp_path, logger):
    target = tmp_path / "batch"
    subjects = mri.restructure_files(ingest_data / "MRI", target, logger)
    return ingest_data / "MRI", target / "ADRC", subjects


def test_all_fixture_subjects_processed(converted):
    _, _, subjects = converted
    assert sorted(subjects) == sorted(s for s, _ in FIXTURE_SESSIONS.values())


@pytest.mark.parametrize("folder", sorted(FIXTURE_SESSIONS))
def test_anat_is_session_t1(converted, folder):
    source, adrc, _ = converted
    subj, date = FIXTURE_SESSIONS[folder]
    anat = adrc / subj / date / "anat"
    assert [p.name for p in anat.iterdir()] == [f"{subj}-{date}_T1w.nii"]
    # content is the source's relative path -> proves which file was copied
    src_t1 = next((source / folder).glob("*.T1.nii"))
    assert (anat / f"{subj}-{date}_T1w.nii").read_text() == src_t1.read_text()


@pytest.mark.parametrize("folder", sorted(FIXTURE_SESSIONS))
def test_modalities_is_full_copy_of_session(converted, folder):
    source, adrc, _ = converted
    subj, date = FIXTURE_SESSIONS[folder]
    assert rel_files(adrc / subj / date / "modalities") == rel_files(source / folder)


def test_output_tree_has_only_expected_dirs(converted):
    _, adrc, _ = converted
    date_dirs = sorted(str(p.relative_to(adrc)) for p in adrc.glob("*/*"))
    assert date_dirs == sorted(f"{s}/{d}" for s, d in FIXTURE_SESSIONS.values())
    for d in adrc.glob("*/*"):
        assert sorted(p.name for p in d.iterdir()) == ["anat", "modalities"]


def test_source_is_untouched(ingest_data, tmp_path, logger):
    before = rel_files(ingest_data)
    mri.restructure_files(ingest_data / "MRI", tmp_path / "batch", logger)
    assert rel_files(ingest_data) == before


def test_rerun_is_idempotent(ingest_data, tmp_path, logger):
    target = tmp_path / "batch"
    mri.restructure_files(ingest_data / "MRI", target, logger)
    first = rel_files(target)
    mri.restructure_files(ingest_data / "MRI", target, logger)
    assert rel_files(target) == first


# --------------------------------------------------------------------------- synthetic edge cases

def test_cor_mprage_fallback(make_tree, tmp_path, logger):
    src = make_tree("MRI", [
        "MRI_110001-01_01022023/110001-01_01022023.Cor_MPRAGE.nii",
        "MRI_110001-01_01022023/110001-01_01022023.T2.nii",
    ])
    mri.restructure_files(src, tmp_path / "out", logger)
    anat = tmp_path / "out/ADRC/110001/20230102/anat"
    assert [p.name for p in anat.iterdir()] == ["110001-20230102_CorMPRAGE.nii"]


def test_t1_preferred_over_cor_mprage(make_tree, tmp_path, logger):
    src = make_tree("MRI", [
        "MRI_110001-01_01022023/110001-01_01022023.Cor_MPRAGE.nii",
        "MRI_110001-01_01022023/110001-01_01022023.T1.nii",
    ])
    mri.restructure_files(src, tmp_path / "out", logger)
    anat = tmp_path / "out/ADRC/110001/20230102/anat"
    assert [p.name for p in anat.iterdir()] == ["110001-20230102_T1w.nii"]


def test_no_anat_candidate_leaves_anat_empty(make_tree, tmp_path, logger, caplog):
    src = make_tree("MRI", ["MRI_110001-01_01022023/110001-01_01022023.T2.nii"])
    mri.restructure_files(src, tmp_path / "out", logger)
    session = tmp_path / "out/ADRC/110001/20230102"
    assert list((session / "anat").iterdir()) == []
    assert [p.name for p in (session / "modalities").iterdir()] == ["110001-01_01022023.T2.nii"]
    assert "No T1 or Cor_MPRAGE file found for subject 110001" in caplog.text


def test_unparseable_and_non_mri_folders_skipped(make_tree, tmp_path, logger):
    src = make_tree("MRI", [
        "MRI_110001-01_01022023/110001-01_01022023.T1.nii",
        "MRI_garbage/x.T1.nii",
        "110002-01_01022023/110002-01_01022023.T1.nii",   # missing MRI_ prefix
        "stray_file.txt",
    ])
    subjects = mri.restructure_files(src, tmp_path / "out", logger)
    assert list(subjects) == ["110001"]
    assert [p.name for p in (tmp_path / "out/ADRC").iterdir()] == ["110001"]


def test_empty_source_returns_empty(tmp_path, logger):
    (tmp_path / "MRI").mkdir()
    assert mri.restructure_files(tmp_path / "MRI", tmp_path / "out", logger) == {}
    assert (tmp_path / "out/ADRC").is_dir()


@pytest.mark.xfail(strict=True, reason="T1 is latched per subject, not per session (see 1_ingest/README.md)")
def test_multi_session_subject_gets_each_sessions_t1(make_tree, tmp_path, logger):
    src = make_tree("MRI", [
        "MRI_110001-01_01022023/110001-01_01022023.T1.nii",
        "MRI_110001-02_06152024/110001-02_06152024.T1.nii",
    ])
    mri.restructure_files(src, tmp_path / "out", logger)
    adrc = tmp_path / "out/ADRC/110001"
    for date, src_name in [("20230102", "MRI_110001-01_01022023/110001-01_01022023.T1.nii"),
                           ("20240615", "MRI_110001-02_06152024/110001-02_06152024.T1.nii")]:
        anat_file = adrc / date / "anat" / f"110001-{date}_T1w.nii"
        assert anat_file.is_file()
        assert anat_file.read_text() == src_name


# --------------------------------------------------------------------------- CLI

def test_cli_end_to_end(ingest_data, tmp_path):
    target = tmp_path / "batch"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(ingest_data / "MRI"), "--target_dir", str(target)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"Processed {len(FIXTURE_SESSIONS)} subjects" in result.stderr
    logs = list((target / "logs/mri_bids_logs").glob("mri_bids_batch_*.log"))
    assert len(logs) == 1
    assert "Reorganization complete!" in logs[0].read_text()
    assert len(list((target / "ADRC").glob("*/*/anat/*_T1w.nii"))) == len(FIXTURE_SESSIONS)


def test_cli_default_target_is_source_parent(ingest_data):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(ingest_data / "MRI")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (ingest_data / "ADRC/710216/20241111/anat/710216-20241111_T1w.nii").is_file()
    assert (ingest_data / "logs/mri_bids_logs").is_dir()
