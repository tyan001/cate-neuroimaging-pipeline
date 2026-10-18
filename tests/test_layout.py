from datetime import date

import pytest

from cate.layout import Dataset, NoMri, OverOneYear, Pair, Tie


def touch(root, *relpaths):
    """Create empty files (and their folders) under ``root``."""
    for relpath in relpaths:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def mkdirs(root, *relpaths):
    for relpath in relpaths:
        (root / relpath).mkdir(parents=True, exist_ok=True)


def subject_ids(dataset):
    return [s.id for s in dataset.subjects()]


def test_subjects_are_folders_except_logs_fs_logs_and_hidden(tmp_path):
    mkdirs(tmp_path, "990001", "990002", "logs", "fs_logs", ".snapshot")
    touch(tmp_path, "README.txt")
    assert subject_ids(Dataset(tmp_path)) == ["990001", "990002"]


def only_subject(root):
    (subject,) = Dataset(root).subjects()
    return subject


def test_sessions_are_eight_digit_folders(tmp_path):
    mkdirs(tmp_path, "990001/20250412", "990001/20250605", "990001/logs",
           "990001/2025041", "990001/backup_20250412", "990001/202504120")
    sessions = only_subject(tmp_path).sessions()
    assert [s.date for s in sessions] == [date(2025, 4, 12), date(2025, 6, 5)]


def test_mri_only_session(tmp_path):
    touch(tmp_path, "990001/20250412/anat/990001-20250412_T1w.nii")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri.path == tmp_path / "990001/20250412/anat/990001-20250412_T1w.nii"
    assert session.mri.name.scan_type == "T1w"
    assert session.pet is None
    assert session.recon_folder == tmp_path / "990001/20250412/freesurfer741/990001-20250412_T1w"


def test_pet_only_session(tmp_path):
    touch(tmp_path, "990003/20250602/pet/990003-20250602_PET.nii",
          "990003/20250602/ct/990003-20250602_CT.nii")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri is None
    assert session.recon_folder is None
    assert session.pet.path == tmp_path / "990003/20250602/pet/990003-20250602_PET.nii"


def test_session_with_mri_and_pet(tmp_path):
    touch(tmp_path, "990002/20250519/anat/990002-20250519_T1w.nii",
          "990002/20250519/pet/990002-20250519_PET.nii")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri.name.filename == "990002-20250519_T1w.nii"
    assert session.pet.name.filename == "990002-20250519_PET.nii"


def test_cormprage_used_when_there_is_no_t1w(tmp_path):
    touch(tmp_path, "900041/20200224/anat/900041-20200224_CorMPRAGE.nii")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri.name.filename == "900041-20200224_CorMPRAGE.nii"
    assert session.recon_folder == tmp_path / "900041/20200224/freesurfer741/900041-20200224_CorMPRAGE"


def test_t1w_preferred_over_cormprage(tmp_path):
    touch(tmp_path, "900041/20200224/anat/900041-20200224_CorMPRAGE.nii",
          "900041/20200224/anat/900041-20200224_T1w.nii")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri.name.scan_type == "T1w"


@pytest.mark.parametrize("pet", ["_PET.nii", "_PET_256.nii", "_PET_128a.nii", "_PET_BIG.nii"])
def test_pet_variant_suffixes_recognized(tmp_path, pet):
    touch(tmp_path, f"110001/20200310/pet/110001-20200310{pet}")
    (session,) = only_subject(tmp_path).sessions()
    assert session.pet.name.filename == f"110001-20200310{pet}"


def test_only_nii_files_count(tmp_path):
    touch(tmp_path, "990002/20250519/anat/990002-20250519_T1w.json",
          "990002/20250519/anat/990002-20250519_T1w.nii.gz",
          "990002/20250519/pet/990002-20250519_PET.json",
          "990002/20250519/pet/notes.txt")
    (session,) = only_subject(tmp_path).sessions()
    assert (session.mri, session.pet) == (None, None)
    assert Dataset(tmp_path).problems() == []


def assert_one_problem_session(root, session_relpath, *files_named):
    """The Session is excluded, and the Dataset reports exactly one problem naming each file."""
    subject = only_subject(root)
    assert [s.path for s in subject.sessions()] == [root / "990001/20250605"]
    (problem,) = Dataset(root).problems()
    assert problem.path == root / session_relpath
    for filename in files_named:
        assert filename in problem.reason


GOOD_SESSION = "990001/20250605/anat/990001-20250605_T1w.nii"


def test_two_mris_is_a_problem(tmp_path):
    touch(tmp_path, GOOD_SESSION,
          "990001/20250412/anat/990001-20250412_T1w.nii",
          "990001/20250412/anat/990001-20250412_T1w_rerun.nii")
    assert_one_problem_session(tmp_path, "990001/20250412",
                               "990001-20250412_T1w.nii", "990001-20250412_T1w_rerun.nii")


def test_two_cormprage_without_t1w_is_a_problem(tmp_path):
    touch(tmp_path, GOOD_SESSION,
          "990001/20250412/anat/990001-20250412_CorMPRAGE.nii",
          "990001/20250412/anat/990001-20250412_CorMPRAGE_2.nii")
    assert_one_problem_session(tmp_path, "990001/20250412", "990001-20250412_CorMPRAGE_2.nii")


def test_two_pets_is_a_problem(tmp_path):
    touch(tmp_path, GOOD_SESSION,
          "990001/20250412/pet/990001-20250412_PET.nii",
          "990001/20250412/pet/990001-20250412_PET_256.nii")
    assert_one_problem_session(tmp_path, "990001/20250412",
                               "990001-20250412_PET.nii", "990001-20250412_PET_256.nii")


def test_scan_dated_differently_from_its_session_is_a_problem(tmp_path):
    touch(tmp_path, GOOD_SESSION, "990001/20250412/pet/990001-20240101_PET.nii")
    assert_one_problem_session(tmp_path, "990001/20250412", "990001-20240101_PET.nii")


@pytest.mark.parametrize("bad_name", ["anat/990001_T1w.nii", "pet/990001-2025041_PET.nii"])
def test_scan_name_that_does_not_parse_is_a_problem(tmp_path, bad_name):
    touch(tmp_path, GOOD_SESSION, f"990001/20250412/{bad_name}")
    assert_one_problem_session(tmp_path, "990001/20250412", bad_name.split("/")[1])


def test_problem_session_is_excluded_whole(tmp_path):
    # the good MRI is not reported either, because the PET breaks a rule
    touch(tmp_path, GOOD_SESSION,
          "990001/20250412/anat/990001-20250412_T1w.nii",
          "990001/20250412/pet/990001-20250412_PET.nii",
          "990001/20250412/pet/990001-20250412_PET_256.nii")
    assert_one_problem_session(tmp_path, "990001/20250412")


def test_dataset_lists_problems_from_every_subject(tmp_path):
    touch(tmp_path,
          "990001/20250412/pet/990001-20250412_PET.nii",
          "990001/20250412/pet/990001-20250412_PET_256.nii",
          "990002/20250519/anat/990002-20240519_T1w.nii")
    paths = [p.path for p in Dataset(tmp_path).problems()]
    assert paths == [tmp_path / "990001/20250412", tmp_path / "990002/20250519"]


def test_eight_digit_folder_that_is_not_a_date_is_a_problem(tmp_path):
    touch(tmp_path, GOOD_SESSION)
    mkdirs(tmp_path, "990001/20251399")
    assert_one_problem_session(tmp_path, "990001/20251399")


def test_upper_case_extension_does_not_count(tmp_path):
    touch(tmp_path, "990001/20250412/anat/990001-20250412_T1w.NII")
    (session,) = only_subject(tmp_path).sessions()
    assert session.mri is None


def test_session_holding_mri_and_pet_pairs_with_itself(tmp_path):
    touch(tmp_path, "990002/20250519/anat/990002-20250519_T1w.nii",
          "990002/20250519/pet/990002-20250519_PET.nii")
    (pair,) = only_subject(tmp_path).pairings()
    assert isinstance(pair, Pair)
    assert pair.pet.path == tmp_path / "990002/20250519/pet/990002-20250519_PET.nii"
    assert pair.mri.path == tmp_path / "990002/20250519/anat/990002-20250519_T1w.nii"
    assert pair.gap_days == 0
    assert pair.recon_folder == tmp_path / "990002/20250519/freesurfer741/990002-20250519_T1w"
    assert pair.folder_name == "990002_pet_20250519_mri_20250519"
    assert pair.folder == tmp_path / "990002/20250519/suvr/990002-20250519_PET/990002_pet_20250519_mri_20250519"


def test_pet_pairs_with_closer_mri_dated_after_it_from_another_session(tmp_path):
    touch(tmp_path, "990003/20250101/anat/990003-20250101_T1w.nii",
          "990003/20250602/pet/990003-20250602_PET_256.nii",
          "990003/20250605/anat/990003-20250605_T1w.nii")
    (pair,) = only_subject(tmp_path).pairings()
    assert isinstance(pair, Pair)
    assert pair.mri.name.filename == "990003-20250605_T1w.nii"
    assert pair.gap_days == 3
    assert pair.recon_folder == tmp_path / "990003/20250605/freesurfer741/990003-20250605_T1w"
    assert pair.folder == (tmp_path / "990003/20250602/suvr/990003-20250602_PET_256"
                           / "990003_pet_20250602_256_mri_20250605")


def test_mri_365_days_away_still_pairs(tmp_path):
    touch(tmp_path, "1/20200101/anat/1-20200101_T1w.nii",
          "1/20201231/pet/1-20201231_PET.nii")  # 2020 is a leap year: 365 days later
    (result,) = only_subject(tmp_path).pairings()
    assert isinstance(result, Pair)
    assert result.gap_days == 365


def test_mri_366_days_away_is_over_one_year(tmp_path):
    touch(tmp_path, "1/20200101/anat/1-20200101_T1w.nii",
          "1/20210101/pet/1-20210101_PET.nii",
          "1/20230101/anat/1-20230101_T1w.nii")
    (result,) = only_subject(tmp_path).pairings()
    assert isinstance(result, OverOneYear)
    assert result.pet.name.filename == "1-20210101_PET.nii"
    assert result.closest_mri.name.filename == "1-20200101_T1w.nii"
    assert result.gap_days == 366


def test_subject_with_no_mri_gives_no_mri(tmp_path):
    touch(tmp_path, "1/20210101/pet/1-20210101_PET.nii")
    (result,) = only_subject(tmp_path).pairings()
    assert result == NoMri(only_subject(tmp_path).sessions()[0].pet)


def test_mri_in_a_problem_session_is_not_paired_with(tmp_path):
    touch(tmp_path, "1/20210101/pet/1-20210101_PET.nii",
          "1/20210105/anat/1-20210105_T1w.nii",
          "1/20210105/anat/1-20210105_T1w_2.nii")
    (result,) = only_subject(tmp_path).pairings()
    assert isinstance(result, NoMri)


def test_two_equally_close_mris_is_a_tie_problem(tmp_path):
    touch(tmp_path, "1/20200101/anat/1-20200101_T1w.nii",
          "1/20200110/pet/1-20200110_PET.nii",
          "1/20200119/anat/1-20200119_T1w.nii")
    subject = only_subject(tmp_path)
    (result,) = subject.pairings()
    assert isinstance(result, Tie)
    assert [m.name.filename for m in result.mris] == ["1-20200101_T1w.nii", "1-20200119_T1w.nii"]
    assert result.gap_days == 9
    (problem,) = Dataset(tmp_path).problems()
    assert problem.path == tmp_path / "1/20200110/pet/1-20200110_PET.nii"
    assert "1-20200101_T1w.nii" in problem.reason and "1-20200119_T1w.nii" in problem.reason


def test_each_pet_gets_one_result_in_date_order(tmp_path):
    touch(tmp_path, "1/20200101/anat/1-20200101_T1w.nii",
          "1/20200101/pet/1-20200101_PET.nii",
          "1/20220101/pet/1-20220101_PET.nii")
    results = only_subject(tmp_path).pairings()
    assert [(type(r), r.pet.name.date) for r in results] == [
        (Pair, date(2020, 1, 1)), (OverOneYear, date(2022, 1, 1))]


def test_existing_pair_folders_listed_with_their_dates_and_gap(tmp_path):
    pet_folder = "990003/20250602/suvr/990003-20250602_PET"
    mkdirs(tmp_path,
           f"{pet_folder}/990003_pet_20250602_mri_20250605/res",
           f"{pet_folder}/990003_pet_20250602_mri_20220101_CorMPRAGE",
           f"{pet_folder}/logs",
           "990003/20250602/suvr/logs",
           "990003/20250605/anat")
    touch(tmp_path, "990003/20250602/suvr/logs/suvr_setup_20250602.log",
          f"{pet_folder}/990003_pet_20250602_mri_20250605.txt")
    folders = only_subject(tmp_path).existing_pair_folders()
    assert [(f.path, f.pet_date, f.mri_date, f.gap_days) for f in folders] == [
        (tmp_path / pet_folder / "990003_pet_20250602_mri_20220101_CorMPRAGE",
         date(2025, 6, 2), date(2022, 1, 1), 1248),
        (tmp_path / pet_folder / "990003_pet_20250602_mri_20250605",
         date(2025, 6, 2), date(2025, 6, 5), 3),
    ]


def test_existing_pair_folders_listed_even_in_a_problem_session(tmp_path):
    # existing results are never hidden: they are listed whatever the Session's state
    touch(tmp_path, "1/20200110/pet/1-20200110_PET.nii", "1/20200110/pet/1-20200110_PET_2.nii")
    mkdirs(tmp_path, "1/20200110/suvr/1-20200110_PET/1_pet_20200110_mri_20200101")
    (folder,) = only_subject(tmp_path).existing_pair_folders()
    assert folder.name.subject == "1"


def test_pair_folder_built_by_a_pair_is_listed_as_existing(tmp_path):
    touch(tmp_path, "990002/20250519/anat/990002-20250519_T1w.nii",
          "990002/20250519/pet/990002-20250519_PET_256.nii")
    subject = only_subject(tmp_path)
    (pair,) = subject.pairings()
    pair.folder.mkdir(parents=True)
    (folder,) = subject.existing_pair_folders()
    assert (folder.path, folder.gap_days) == (pair.folder, 0)
