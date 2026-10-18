from datetime import date

import pytest

from cate.names import (
    NameParseError,
    ScanName,
    pair_folder_name,
    parse_pair_folder_name,
    parse_pet_folder_name,
    parse_scan_name,
    pet_folder_name,
)


def test_scan_name_parts():
    name = parse_scan_name("990002-20250519_T1w.nii")
    assert name == ScanName("990002", date(2025, 5, 19), "T1w", None)


def test_scan_name_with_extra():
    assert parse_scan_name("900001-20240809_PET_256.nii").extra == "256"
    assert parse_scan_name("110015-20150527_PET_128_a.nii").extra == "128_a"


@pytest.mark.parametrize("bad", [
    "nodash_T1w.nii",              # no subject-date separator
    "990001-20250412.nii",         # no scan type
    "990001-20250412_T1w.nii.gz",  # not .nii
    "-20250412_T1w.nii",           # empty subject
    "990001-20250412__T1w.nii",    # empty part
])
def test_bad_scan_name_is_a_parse_error(bad):
    with pytest.raises(NameParseError):
        parse_scan_name(bad)


@pytest.mark.parametrize("bad_date", ["2025041", "202504120", "2025041a", "20251301", "20250230"])
def test_date_that_is_not_eight_valid_digits_is_a_parse_error(bad_date):
    with pytest.raises(NameParseError):
        parse_scan_name(f"990001-{bad_date}_T1w.nii")


@pytest.mark.parametrize("filename", [
    "990002-20250519_T1w.nii",
    "900041-20200224_CorMPRAGE.nii",
    "900001-20240809_PET_256.nii",
    "110015-20150527_PET_128_a.nii",
])
def test_scan_name_round_trip(filename):
    assert parse_scan_name(filename).filename == filename


def test_scan_name_builds_its_stem():
    assert ScanName("990002", date(2025, 5, 19), "PET", "256").stem == "990002-20250519_PET_256"


@pytest.mark.parametrize("pet, mri, folder", [
    # examples/processed_batch_tree.txt
    ("990002-20250519_PET.nii", "990002-20250519_T1w.nii", "990002_pet_20250519_mri_20250519"),
    ("990003-20250602_PET.nii", "990003-20250605_T1w.nii", "990003_pet_20250602_mri_20250605"),
    # the formats prepare_suvr_folder.py writes today
    ("900001-20240809_PET_256.nii", "900001-20240828_T1w.nii", "900001_pet_20240809_256_mri_20240828"),
    ("900041-20160408_PET.nii", "900041-20200224_CorMPRAGE.nii", "900041_pet_20160408_mri_20200224_CorMPRAGE"),
    ("900041-20160408_PET_a.nii", "900041-20200224_T1w_x.nii", "900041_pet_20160408_a_mri_20200224_x"),
])
def test_pair_folder_name_matches_todays_format(pet, mri, folder):
    assert pair_folder_name(parse_scan_name(pet), parse_scan_name(mri)) == folder


@pytest.mark.parametrize("pet, folder", [
    ("990002-20250519_PET.nii", "990002-20250519_PET"),
    ("900001-20240809_PET_256.nii", "900001-20240809_PET_256"),
])
def test_pet_folder_name_matches_todays_format(pet, folder):
    assert pet_folder_name(parse_scan_name(pet)) == folder


@pytest.mark.parametrize("folder", [
    "990002_pet_20250519_mri_20250519",
    "990003_pet_20250602_mri_20250605",
    "900001_pet_20240809_256_mri_20240828",
    "900041_pet_20160408_mri_20200224_CorMPRAGE",
    "900041_pet_20160408_a_mri_20200224_x",
    "900041_pet_20160408_128_a_mri_20200224_CorMPRAGE_x",
])
def test_pair_folder_name_round_trip(folder):
    assert parse_pair_folder_name(folder).name == folder


def test_pair_folder_name_gives_dates_and_gap():
    parsed = parse_pair_folder_name("900041_pet_20160408_256_mri_20200224_CorMPRAGE")
    assert parsed.subject == "900041"
    assert parsed.pet_date == date(2016, 4, 8)
    assert parsed.mri_date == date(2020, 2, 24)
    assert parsed.gap_days == 1417


def test_gap_is_the_same_when_mri_comes_first():
    assert parse_pair_folder_name("1_pet_20200110_mri_20200101").gap_days == 9


@pytest.mark.parametrize("bad", [
    "990002-20250519_PET",               # a PET folder, not a Pair folder
    "990002_pet_20250519",               # no MRI part
    "990002_pet_2025051_mri_20250519",   # short date
    "990002_pet_20250519_mri_20251399",  # invalid date
    "logs",
])
def test_bad_pair_folder_name_is_a_parse_error(bad):
    with pytest.raises(NameParseError):
        parse_pair_folder_name(bad)


@pytest.mark.parametrize("folder", ["990002-20250519_PET", "900001-20240809_PET_256"])
def test_pet_folder_name_round_trip(folder):
    assert pet_folder_name(parse_pet_folder_name(folder)) == folder


@pytest.mark.parametrize("bad", ["logs", "990002-20250519_T1w", "990002-20250519_PET.nii"])
def test_bad_pet_folder_name_is_a_parse_error(bad):
    with pytest.raises(NameParseError):
        parse_pet_folder_name(bad)
