"""Tests for pipeline/5_aggregate: suvr_stats_all.py and mri_stats_all.py.

The SUVR results are small CSVs written in the same layouts suvr.py produces. FreeSurfer's
asegstats2table / aparcstats2table are replaced by a fake script on PATH that writes a table in
the same tab-separated shape.
"""

import os
import stat
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

AGG_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "5_aggregate"
sys.path.insert(0, str(AGG_DIR))

import mri_stats_all  # noqa: E402
import suvr_stats_all  # noqa: E402
import suvr_symlink  # noqa: E402

ROIS = [("0", "Unknown"), ("2", "Left-Cerebral-White-Matter"), ("17", "Left-Hippocampus"),
        ("53", "Right-Hippocampus")]
COMBINED_COLS = ["Frontal", "Temporal", "Parietal", "Global"]


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def run_main(module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", [module.__name__, *argv])
    module.main()


# --- suvr_stats_all.py --------------------------------------------------------------------------


def suvr_pair(root, subject, pet_session, pet_dir, pair, mri_scan, compound, base):
    """Write the four SUVR result CSVs for one PET x MRI pair; values are derived from base."""
    res = f"{subject}/{pet_session}/suvr/{pet_dir}/{pair}/res"
    pid = f"{subject}-{pet_session}_reg_{mri_scan}.nii"
    for ref, offset in [("cerebellum", 0.0), ("cerebellum_gm", 0.1)]:
        suvr = [round(base + offset + i / 10, 3) for i in range(len(COMBINED_COLS))]
        write(root, f"{res}/{pair}_suvr_combined_{ref}.csv",
              f"PID,Compound,Centiloid,{','.join(COMBINED_COLS)}\n"
              f"{pid},{compound},{round(100 * (base + offset) - 90, 3)},{','.join(map(str, suvr))}\n")
        values = ["0.0"] + [str(round(base + offset + i / 100, 3)) for i in range(1, len(ROIS))]
        write(root, f"{res}/{pair}_suvr_{ref}.csv",
              "PID," + ",".join(n for n, _ in ROIS) + "\n"
              "N/A," + ",".join(name for _, name in ROIS) + "\n"
              f"{pid}," + ",".join(values) + "\n")
    write(root, f"{res}/{pair}_mean_suv.csv", "ROI,Name,Value\n0,Unknown,0.0\n")


@pytest.fixture
def suvr_farm(tmp_path):
    root = tmp_path / "ADRC"
    suvr_pair(root, "900701", "20240110", "900701-20240110_PET", "900701_pet_20240110_mri_20240101",
              "900701-20240101_T1w", "Neuraceq", 1.2)
    suvr_pair(root, "900701", "20240110", "900701-20240110_PET", "900701_pet_20240110_mri_20200101",
              "900701-20200101_T1w", "Neuraceq", 1.1)
    suvr_pair(root, "900702", "20160601", "900702-20160601_PET_256", "900702_pet_20160601_256_mri_20160605",
              "900702-20160605_T1w", "Amyvid", 1.5)
    suvr_pair(root, "900703", "20160301", "900703-20160301_PET", "900703_pet_9.Am2201_mri_20160310_CorMPRAGE",
              "900703-20160310_CorMPRAGE", "Amyvid", 0.9)
    # registration started, no results yet
    write(root, "900704/20250101/suvr/900704-20250101_PET/900704_pet_20250101_mri_20250102/res/"
                "900704_pet_20250101_mri_20250102_mean_suv.csv", "ROI,Name,Value\n")
    write(root, "900704/20250101/suvr/900704-20250101_PET/logs/pet_registration.log")
    farm = tmp_path / "suvr_link"
    assert suvr_symlink.build_farm(root, farm, "suvr", dry_run=False, force=False)
    return farm


@pytest.mark.parametrize("name, expected", [
    ("900701_pet_20240110_mri_20240101", ("900701", "20240110", None, "20240101", None)),
    ("900702_pet_20160601_256_mri_20160605", ("900702", "20160601", "256", "20160605", None)),
    ("900703_pet_9.Am2201_mri_20160310_CorMPRAGE", ("900703", "9.Am2201", None, "20160310", "CorMPRAGE")),
    ("900704_pet_20250101_128_a_mri_20250102_T1w_x", ("900704", "20250101", "128_a", "20250102", "T1w_x")),
    ("res", (None, None, None, None, None)),
])
def test_parse_combo(name, expected):
    assert tuple(suvr_stats_all.parse_combo(name).values()) == expected


def test_read_combined_layout(suvr_farm):
    csv = next(suvr_farm.glob("900701-20240110_PET/*_20240101/res/*_suvr_combined_cerebellum.csv"))
    df = suvr_stats_all.read_summary_csv(csv)
    assert list(df.columns) == ["PID", "Compound", "Centiloid", *COMBINED_COLS]
    assert df.loc[0, "Compound"] == "Neuraceq"
    assert df.loc[0, "Centiloid"] == pytest.approx(30.0)


def test_read_per_region_layout(suvr_farm):
    csv = next(suvr_farm.glob("900701-20240110_PET/*_20240101/res/*_suvr_cerebellum_gm.csv"))
    df = suvr_stats_all.read_summary_csv(csv)
    assert list(df.columns) == ["PID"] + [name for _, name in ROIS]
    assert len(df) == 1
    assert df.loc[0, "PID"] == "900701-20240110_reg_900701-20240101_T1w.nii"
    assert df.loc[0, "Left-Hippocampus"] == pytest.approx(1.32)
    assert all(pd.api.types.is_float_dtype(df[name]) for _, name in ROIS)


def test_find_res_csvs_matches_exact_pattern(suvr_farm, capsys):
    found = suvr_stats_all.find_res_csvs(suvr_farm, "suvr_cerebellum")
    assert len(found) == 4
    assert all(p.name.endswith("_suvr_cerebellum.csv") for p in found)
    assert "no '*suvr_cerebellum*.csv'" in capsys.readouterr().out  # 900704 has no results


def test_find_res_csvs_skips_broken_link(suvr_farm, capsys):
    (suvr_farm / "900799-20240101_PET").symlink_to(suvr_farm.parent / "gone")
    assert len(suvr_stats_all.find_res_csvs(suvr_farm, "suvr_combined_cerebellum")) == 4
    assert "skipping 900799-20240101_PET" in capsys.readouterr().out


def test_aggregate_combined(suvr_farm):
    df = suvr_stats_all.aggregate(suvr_farm, "suvr_combined_cerebellum_gm")
    assert list(df.columns[:6]) == [*suvr_stats_all.ID_COLS, "PID"]
    assert list(zip(df.subject_id, df.pet_date, df.mri_date, strict=True)) == [
        ("900701", "20240110", "20200101"),
        ("900701", "20240110", "20240101"),
        ("900702", "20160601", "20160605"),
        ("900703", "9.Am2201", "20160310"),
    ]
    assert df.pet_info.tolist()[2] == "256"
    assert df.mri_info.tolist()[3] == "CorMPRAGE"
    assert df.Compound.tolist() == ["Neuraceq", "Neuraceq", "Amyvid", "Amyvid"]
    assert df.Global.tolist() == pytest.approx([1.5, 1.6, 1.9, 1.3])


def test_aggregate_skips_empty_and_missing(suvr_farm, tmp_path, capsys):
    csv = next(suvr_farm.glob("900702-*/*/res/*_suvr_combined_cerebellum.csv"))
    csv.write_text(f"PID,Compound,Centiloid,{','.join(COMBINED_COLS)}\n")
    df = suvr_stats_all.aggregate(suvr_farm, "suvr_combined_cerebellum")
    assert "900702" not in df.subject_id.tolist()
    assert "has no data rows" in capsys.readouterr().out
    assert suvr_stats_all.aggregate(suvr_farm, "suvr_nothing") is None


def test_suvr_main_writes_all_patterns(suvr_farm, tmp_path, monkeypatch, capsys):
    out = tmp_path / "suvr_csv"
    run_main(suvr_stats_all, monkeypatch, "-ld", str(suvr_farm), "-o", str(out))
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{p}.csv" for p in suvr_stats_all.ALL_PATTERNS)
    per_region = pd.read_csv(out / "suvr_cerebellum.csv", dtype={"subject_id": str})
    assert per_region.shape == (4, 5 + 1 + len(ROIS))
    assert per_region.subject_id.tolist() == ["900701", "900701", "900702", "900703"]
    assert "Wrote 4 CSVs" in capsys.readouterr().out


def test_suvr_main_single_pattern(suvr_farm, tmp_path, monkeypatch):
    out = tmp_path / "suvr_csv"
    run_main(suvr_stats_all, monkeypatch, "-ld", str(suvr_farm), "-o", str(out),
             "--pattern", "suvr_combined_cerebellum")
    assert [p.name for p in out.iterdir()] == ["suvr_combined_cerebellum.csv"]


def test_suvr_main_missing_farm(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_main(suvr_stats_all, monkeypatch, "-ld", str(tmp_path / "nope"), "-o", str(tmp_path / "out"))
    assert exc.value.code == 2


# --- mri_stats_all.py ---------------------------------------------------------------------------

HIPPO = "Hippocampal_tail {tail}\nCA1-body {ca1}\nWhole_hippocampus {whole}\n"
AMYG = "Lateral-nucleus {lat}\nWhole_amygdala {whole}\n"

# Stand-in for asegstats2table / aparcstats2table: checks the subjects exist under
# $SUBJECTS_DIR and writes a tab-separated table with FreeSurfer's first-column header.
FAKE_TOOL = textwrap.dedent("""\
    #!{python}
    import argparse, os, sys
    from pathlib import Path

    p = argparse.ArgumentParser()
    p.add_argument("--subjects", nargs="+", required=True)
    p.add_argument("--meas", default="volume")
    p.add_argument("--hemi")
    p.add_argument("--tablefile", required=True)
    p.add_argument("--statsfile", default="aseg.stats")
    p.add_argument("--skip", action="store_true")
    p.add_argument("--all-segs", action="store_true")
    a = p.parse_args()

    subjects_dir = Path(os.environ["SUBJECTS_DIR"])
    for s in a.subjects:
        if not (subjects_dir / s / "stats").is_dir():
            sys.exit(f"missing {{s}}")

    if Path(sys.argv[0]).name == "aparcstats2table":
        head = f"{{a.hemi}}.aparc.{{a.meas}}"
        cols = [f"{{a.hemi}}_bankssts_{{a.meas}}", f"{{a.hemi}}_cuneus_{{a.meas}}"]
        base = 2.0 if a.meas == "thickness" else 1000.0
    elif a.statsfile == "wmparc.stats":
        head, cols, base = "Measure:volume", ["wm-lh-bankssts", "wm-rh-bankssts"], 500.0
    else:
        head, cols, base = "Measure:volume", ["Left-Hippocampus", "Right-Hippocampus"], 3000.0
    lines = ["\\t".join([head] + cols)]
    for i, s in enumerate(a.subjects):
        lines.append("\\t".join([s] + [str(base + i + j / 10) for j in range(len(cols))]))
    Path(a.tablefile).write_text("\\n".join(lines) + "\\n")
""")


@pytest.fixture
def fs_farm(tmp_path):
    root = tmp_path / "ADRC"
    farm = tmp_path / "freesurfer_link"
    farm.mkdir()
    recons = {
        "900801-20240101_T1w": {"lh": (500, 120, 3400), "rh": (510, 125, 3450)},
        "900802-20200101_CorMPRAGE": {"lh": (480, 110, 3300)},  # right hemisphere missing
        "900803-20230101_T1w": {},  # recon done, segmentHA never ran
    }
    for name, hemis in recons.items():
        subject, rest = name.split("-", 1)
        recon = root / subject / rest[:8] / "freesurfer741" / name
        write(recon, "stats/aseg.stats")
        write(recon, "mri/aparc+aseg.mgz")
        for hemi, (tail, ca1, whole) in hemis.items():
            write(recon, f"mri/{hemi}.hippoSfVolumes-T1.v22.txt",
                  HIPPO.format(tail=tail, ca1=ca1, whole=whole)
                  + "writing to discreteLabelsMergedBodyHeadNoMLorGCDGResampledT1.mgz...\nEverything done!\n")
            write(recon, f"mri/{hemi}.amygNucVolumes-T1.v22.txt", AMYG.format(lat=whole / 5, whole=whole / 2))
        (farm / name).symlink_to(recon)
    write(root, "900804/20240101/freesurfer741/900804-20240101_T1w/scripts/recon-all.error")
    (farm / "900804-20240101_T1w").symlink_to(root / "900804/20240101/freesurfer741/900804-20240101_T1w")
    (farm / "900805-20240101_T1w").symlink_to(tmp_path / "gone")
    return farm


@pytest.fixture
def fake_freesurfer(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for tool in ("asegstats2table", "aparcstats2table"):
        path = bin_dir / tool
        path.write_text(FAKE_TOOL.format(python=sys.executable))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SUBJECTS_DIR", "unset")  # main() sets it; monkeypatch restores it
    return bin_dir


def test_find_farm_subjects(fs_farm, capsys):
    found = mri_stats_all.find_farm_subjects(fs_farm)
    assert [p.name for p in found] == ["900801-20240101_T1w", "900802-20200101_CorMPRAGE", "900803-20230101_T1w"]
    out = capsys.readouterr().out
    assert "skipping 900804-20240101_T1w (no stats/ dir)" in out
    assert "skipping 900805-20240101_T1w (broken symlink" in out


def test_add_ids():
    df = pd.DataFrame({"subject": ["900802-20200101_CorMPRAGE", "900801-20240101_T1w", "oddname"],
                       "x": [1, 2, 3]})
    out = mri_stats_all.add_ids(df)
    assert list(out.columns) == ["subject_id", "scan_date", "scan_type", "subject", "x"]
    assert out.subject.tolist() == ["900801-20240101_T1w", "900802-20200101_CorMPRAGE", "oddname"]
    assert out.scan_type.tolist()[:2] == ["T1w", "CorMPRAGE"]
    assert out.subject_id.isna().tolist() == [False, False, True]


def test_parse_hippo_file_skips_log_lines(fs_farm):
    parsed = mri_stats_all.parse_hippo_file(fs_farm / "900801-20240101_T1w/mri/lh.hippoSfVolumes-T1.v22.txt")
    assert parsed == {"Hippocampal_tail": 500.0, "CA1-body": 120.0, "Whole_hippocampus": 3400.0}


def test_build_subfield_table(fs_farm, capsys):
    subjects = mri_stats_all.find_farm_subjects(fs_farm)
    df = mri_stats_all.build_subfield_table(subjects, "{hemi}.hippoSfVolumes-*.txt", "hippoSfVolumes")
    assert df.subject.tolist() == ["900801-20240101_T1w", "900802-20200101_CorMPRAGE"]
    assert df.loc[0, "rh_CA1-body"] == 125.0
    assert pd.isna(df.loc[1, "rh_CA1-body"])
    assert "no hippoSfVolumes files for 900803-20230101_T1w" in capsys.readouterr().out
    assert mri_stats_all.build_subfield_table(subjects[2:], "{hemi}.hippoSfVolumes-*.txt", "x") is None


def test_run_table(tmp_path):
    write(tmp_path, "t.txt", "Measure:volume\tLeft-Hippocampus\n900801-20240101_T1w.nii\t3000.0\n")
    df = mri_stats_all.run_table("true", tmp_path, tmp_path / "t.txt")
    assert df.to_dict("records") == [{"subject": "900801-20240101_T1w", "Left-Hippocampus": 3000.0}]
    assert mri_stats_all.run_table("true", tmp_path, tmp_path / "never.txt") is None


def test_mri_main_with_fake_freesurfer(fs_farm, fake_freesurfer, tmp_path, monkeypatch, capsys):
    out = tmp_path / "mri_csv"
    run_main(mri_stats_all, monkeypatch, "-ld", str(fs_farm), "-o", str(out))
    assert os.environ["SUBJECTS_DIR"] == str(fs_farm.resolve())
    assert sorted(p.name for p in out.iterdir()) == [
        "amygdala.csv", "aparc_thickness.csv", "aparc_volume.csv", "aseg_stats.csv", "hippocampus.csv", "wmparc.csv",
    ]
    assert "Wrote 6 CSVs" in capsys.readouterr().out

    def read(name):
        return pd.read_csv(out / name, dtype={"subject_id": str, "scan_date": str})

    aseg = read("aseg_stats.csv")
    assert list(aseg.columns) == ["subject_id", "scan_date", "scan_type", "subject",
                                  "Left-Hippocampus", "Right-Hippocampus"]
    assert aseg.subject_id.tolist() == ["900801", "900802", "900803"]
    assert aseg.scan_date.tolist() == ["20240101", "20200101", "20230101"]

    thick = read("aparc_thickness.csv")
    assert list(thick.columns[4:]) == ["lh_bankssts_thickness", "lh_cuneus_thickness",
                                       "rh_bankssts_thickness", "rh_cuneus_thickness"]
    assert thick.lh_cuneus_thickness.tolist() == pytest.approx([2.1, 3.1, 4.1])

    assert read("wmparc.csv").shape == (3, 6)
    assert read("aparc_volume.csv").rh_bankssts_volume.tolist() == pytest.approx([1000.0, 1001.0, 1002.0])

    hippo = read("hippocampus.csv")
    assert hippo.subject.tolist() == ["900801-20240101_T1w", "900802-20200101_CorMPRAGE"]
    assert hippo["lh_Whole_hippocampus"].tolist() == [3400.0, 3300.0]
    assert read("amygdala.csv")["rh_Whole_amygdala"].tolist()[0] == 1725.0


def test_mri_main_without_freesurfer(fs_farm, tmp_path, monkeypatch, capsys):
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("SUBJECTS_DIR", "unset")
    out = tmp_path / "mri_csv"
    run_main(mri_stats_all, monkeypatch, "-ld", str(fs_farm), "-o", str(out))
    assert sorted(p.name for p in out.iterdir()) == ["amygdala.csv", "hippocampus.csv"]
    assert "aseg_stats.txt was not produced" in capsys.readouterr().out


def test_mri_main_empty_or_missing_farm(tmp_path, monkeypatch, capsys):
    farm = tmp_path / "freesurfer_link"
    farm.mkdir()
    out = tmp_path / "mri_csv"
    run_main(mri_stats_all, monkeypatch, "-ld", str(farm), "-o", str(out))
    assert "No valid recon subjects" in capsys.readouterr().out
    assert not out.exists()
    with pytest.raises(SystemExit) as exc:
        run_main(mri_stats_all, monkeypatch, "-ld", str(tmp_path / "nope"), "-o", str(out))
    assert exc.value.code == 2
