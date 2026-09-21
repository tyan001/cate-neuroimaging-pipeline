"""Tests for mri_site_data.py --status.

The status report never runs FreeSurfer, so trees of small files are enough: only the presence
and mtimes of the source/output files decide a scan's state.
"""

import csv
import os
import sys
from pathlib import Path

import pytest

AGG_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "5_aggregate"
sys.path.insert(0, str(AGG_DIR))

import mri_site_data as msd  # noqa: E402

SiteDataState = msd.SiteDataState


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or rel)
    return p


def make_recon(root, subject="900401", session="20240101", scan="900401-20240101_T1w"):
    """A complete freesurfer741 recon: the 8 files a conversion reads."""
    recon = root / subject / session / "freesurfer741" / scan
    for name in msd.MRI_FILES:
        write(recon, f"mri/{name}")
    for name in msd.SURF_FILES:
        write(recon, f"surf/{name}")
    return recon


def convert_all(recon, output, only=None, age=0):
    """Create the outputs a conversion would produce, `age` seconds newer than their sources."""
    for source, dest, _command in msd.expected_pairs(str(recon), str(output)):
        if only is not None and os.path.basename(dest) not in only:
            continue
        if not os.path.isfile(source):  # a real conversion skips these too
            continue
        p = Path(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dest)
        stamp = os.path.getmtime(source) + age
        os.utime(p, (stamp, stamp))
    return output


def status_of(recon, output):
    return msd.scan_status(recon.name, str(recon), str(output))


# --- scan_status ---------------------------------------------------------------------------------


def test_not_started(tmp_path):
    recon = make_recon(tmp_path)
    record = status_of(recon, tmp_path / "sitedata_mri")
    assert record.state is SiteDataState.NOT_STARTED
    assert (record.converted, record.pending, record.to_convert) == (0, 8, 8)


def test_complete(tmp_path):
    recon = make_recon(tmp_path)
    output = convert_all(recon, tmp_path / "sitedata_mri", age=10)
    record = status_of(recon, output)
    assert record.state is SiteDataState.COMPLETE
    assert (record.converted, record.to_convert) == (8, 0)
    assert record.detail == ""


def test_complete_when_output_and_source_share_an_mtime(tmp_path):
    """Equal mtimes must not read as stale, or every scan looks like it needs redoing."""
    recon = make_recon(tmp_path)
    output = convert_all(recon, tmp_path / "sitedata_mri", age=0)
    assert status_of(recon, output).state is SiteDataState.COMPLETE


def test_partial(tmp_path):
    recon = make_recon(tmp_path)
    output = convert_all(recon, tmp_path / "sitedata_mri", only={"T1.nii", "brain.nii"}, age=10)
    record = status_of(recon, output)
    assert record.state is SiteDataState.PARTIAL
    assert (record.converted, record.pending, record.to_convert) == (2, 6, 6)
    assert "wm.nii" in record.detail


def test_stale_when_the_recon_is_rerun(tmp_path):
    """A recon rewritten after conversion leaves derivatives that would otherwise look done."""
    recon = make_recon(tmp_path)
    output = convert_all(recon, tmp_path / "sitedata_mri", age=10)
    assert status_of(recon, output).state is SiteDataState.COMPLETE

    source = recon / "mri" / "T1.mgz"
    fresh = os.path.getmtime(source) + 3600
    os.utime(source, (fresh, fresh))

    record = status_of(recon, output)
    assert record.state is SiteDataState.STALE
    assert (record.converted, record.stale, record.to_convert) == (7, 1, 1)
    assert "T1.nii" in record.detail


def test_no_source_outranks_a_finished_conversion(tmp_path):
    """A recon missing wm.mgz can never reach complete, so a rerun must not be implied."""
    recon = make_recon(tmp_path)
    (recon / "mri" / "wm.mgz").unlink()
    output = convert_all(recon, tmp_path / "sitedata_mri", age=10)

    record = status_of(recon, output)
    assert record.state is SiteDataState.NO_SOURCE
    assert (record.converted, record.no_source, record.to_convert) == (7, 1, 0)
    assert "wm.mgz" in record.detail


# --- the report agrees with the conversion --------------------------------------------------------


@pytest.mark.parametrize("age, force, expected", [(10, False, False), (-10, False, True), (10, True, True)])
def test_needs_conversion_matches_the_status_rule(tmp_path, age, force, expected):
    recon = make_recon(tmp_path)
    output = convert_all(recon, tmp_path / "sitedata_mri", age=age)
    source, dest, _command = msd.expected_pairs(str(recon), str(output))[0]

    assert msd.needs_conversion(source, dest, force) is expected
    # A scan is reported as needing work exactly when its files do.
    assert (status_of(recon, output).to_convert > 0) is (expected and not force)


def test_needs_conversion_when_output_is_absent(tmp_path):
    recon = make_recon(tmp_path)
    source, dest, _command = msd.expected_pairs(str(recon), str(tmp_path / "sitedata_mri"))[0]
    assert msd.needs_conversion(source, dest) is True


# --- farm walking ---------------------------------------------------------------------------------


@pytest.fixture
def farm(tmp_path):
    """A symlink farm over two recons, as freesurfer_symlink.py builds it."""
    root = tmp_path / "ADRC"
    done = make_recon(root, "900401", "20240101", "900401-20240101_T1w")
    convert_all(done, done.parent.parent / "sitedata_mri", age=10)
    make_recon(root, "900402", "20200101", "900402-20200101_CorMPRAGE")

    target = tmp_path / "freesurfer_link"
    target.mkdir()
    for recon in sorted(root.glob("*/*/freesurfer741/*")):
        (target / recon.name).symlink_to(recon)
    write(tmp_path, "freesurfer_link/stray.txt")
    return target


def test_find_subjects_resolves_links_and_creates_nothing(farm, tmp_path):
    warnings = []
    subjects = msd.find_subjects(str(farm), "sitedata_mri", warn=warnings.append)

    assert [scan for _fs, scan, _out in subjects] == [
        "900401-20240101_T1w", "900402-20200101_CorMPRAGE"]
    # Output paths are siblings of the real freesurfer741, not of the farm link.
    assert [Path(out) for _fs, _scan, out in subjects] == [
        tmp_path / "ADRC/900401/20240101/sitedata_mri",
        tmp_path / "ADRC/900402/20200101/sitedata_mri"]
    assert any("stray.txt" in w for w in warnings)
    assert not (tmp_path / "ADRC/900402/20200101/sitedata_mri").exists()


def test_status_reports_both_scans_and_writes_csv(farm, tmp_path, capsys, monkeypatch):
    csv_path = tmp_path / "done.csv"
    monkeypatch.setattr(sys, "argv", ["mri_site_data.py", str(farm), "--status", "--all",
                                      "--csv", str(csv_path)])
    assert msd.main() == 0

    out = capsys.readouterr().out
    assert "complete         1" in out
    assert "not_started      1" in out
    assert "A rerun would convert 8 file(s) across 1 scan(s); --force would redo all 16." in out

    rows = {r["scan"]: r for r in csv.DictReader(csv_path.open())}
    assert rows["900401-20240101_T1w"]["state"] == "complete"
    assert rows["900402-20200101_CorMPRAGE"]["state"] == "not_started"
    assert rows["900402-20200101_CorMPRAGE"]["pending"] == "8"


def test_forecast_counts_files_a_no_source_scan_can_still_convert(tmp_path, capsys):
    """The 7 convertible files of a no_source scan are still work a rerun does."""
    recon = make_recon(tmp_path)
    (recon / "mri" / "wm.mgz").unlink()
    record = status_of(recon, tmp_path / "sitedata_mri")
    assert record.state is SiteDataState.NO_SOURCE
    assert record.to_convert == 7

    msd.report_status([record], "sitedata_mri")
    assert "convert 7 file(s) across 1 scan(s); --force would redo all 7." in capsys.readouterr().out


def test_status_needs_no_freesurfer(farm, monkeypatch):
    """--status must work off-cluster, so it must not call check_freesurfer()."""
    monkeypatch.delenv("FREESURFER_HOME", raising=False)
    monkeypatch.setattr(msd, "check_freesurfer", lambda: pytest.fail("check_freesurfer() called"))
    monkeypatch.setattr(sys, "argv", ["mri_site_data.py", str(farm), "--status"])
    assert msd.main() == 0


def test_status_on_one_scan_through_its_farm_link(farm, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mri_site_data.py", str(farm / "900401-20240101_T1w"),
                                      "--status", "--all"])
    assert msd.main() == 0
    out = capsys.readouterr().out
    assert "=== 1 scan(s)" in out
    assert "900401-20240101_T1w   8/8 converted" in out


def test_csv_without_status_is_rejected(farm, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mri_site_data.py", str(farm), "--csv", "x.csv"])
    with pytest.raises(SystemExit) as exc:
        msd.main()
    assert exc.value.code == 2
