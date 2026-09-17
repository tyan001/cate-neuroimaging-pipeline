"""Tests for pipeline/1_ingest/download.py and unzip_files.sh. No network: curl is mocked."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import download

UNZIP_SCRIPT = Path(download.__file__).with_name("unzip_files.sh")


def write_csv(path, text):
    path.write_text(text)
    return path


def write_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name in members:
            zf.writestr(name, name)


@pytest.fixture
def fake_curl(monkeypatch):
    """Replace curl: writes a zip of '<name>.T1.nii' to the -o path; URLs containing 'fail' exit 22."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        out, url = Path(cmd[cmd.index("-o") + 1]), cmd[-1]
        if "fail" in url:
            return subprocess.CompletedProcess(cmd, 22, "", "curl: (22) 404")
        stem = out.stem.split("_", 1)[1]
        write_zip(out, [f"{stem}.T1.nii", f"{stem}.T2.nii"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(download.subprocess, "run", run)
    return calls


def test_downloads_and_extracts(tmp_path, fake_curl):
    csv = write_csv(tmp_path / "links.csv",
                    "name,link\n"
                    "MRI_930124-C1_03202025,https://example.org/a.zip?dl=1\n"
                    " MRI_930125-D1_01122026 , https://example.org/b.zip?dl=1 \n")
    download.download_from_csv(str(csv), "MRI", str(tmp_path / "batch"))

    out = tmp_path / "batch" / "MRI"
    assert sorted(p.name for p in out.iterdir()) == ["MRI_930124-C1_03202025", "MRI_930125-D1_01122026"]
    assert sorted(p.name for p in (out / "MRI_930124-C1_03202025").iterdir()) == [
        "930124-C1_03202025.T1.nii", "930124-C1_03202025.T2.nii",
    ]
    assert not list(out.glob("*.zip"))                      # archives removed
    assert fake_curl[1][-1] == "https://example.org/b.zip?dl=1"  # whitespace stripped


def test_failed_download_is_reported_and_skipped(tmp_path, fake_curl, capsys):
    csv = write_csv(tmp_path / "links.csv",
                    "name,link\n"
                    "PET_930019-C2_06022025,https://example.org/fail\n"
                    "PET_930119-C1_11092025,https://example.org/ok\n")
    download.download_from_csv(str(csv), "PET", str(tmp_path))

    assert "FAILED (exit 22)" in capsys.readouterr().out
    assert [p.name for p in (tmp_path / "PET").iterdir()] == ["PET_930119-C1_11092025"]


def test_default_output_is_cwd(tmp_path, fake_curl, monkeypatch):
    csv = write_csv(tmp_path / "links.csv", "name,link\nMRI_930124-C1_03202025,https://example.org/a\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    download.download_from_csv(str(csv), "MRI")
    assert (workdir / "MRI" / "MRI_930124-C1_03202025").is_dir()


@pytest.mark.parametrize("header", ["name,url", "subject,link", ""])
def test_rejects_csv_without_required_columns(tmp_path, fake_curl, header):
    csv = write_csv(tmp_path / "links.csv", f"{header}\n")
    with pytest.raises(ValueError, match="'name' and 'link'"):
        download.download_from_csv(str(csv), "MRI", str(tmp_path))
    assert fake_curl == []


def test_example_csv_is_valid(tmp_path, fake_curl):
    example = Path(download.__file__).parents[2] / "examples" / "dropbox_links.csv"
    download.download_from_csv(str(example), "MRI", str(tmp_path))
    assert fake_curl and all(cmd[0] == "curl" for cmd in fake_curl)


# --------------------------------------------------------------------------- unzip_files.sh

needs_unzip = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("unzip")),
                                 reason="bash and unzip required")


def run_unzip(*args):
    return subprocess.run(["bash", str(UNZIP_SCRIPT), *args], capture_output=True, text=True)


@needs_unzip
def test_unzip_extracts_each_zip_to_sibling_folder(tmp_path):
    write_zip(tmp_path / "PET_930120-01_09202025.zip",
              ["930120-01_09202025_mean_5mmblur.nii", "UF_recon/930120-01_09202025_mean_UF_PROTOCOL_5mmblur.nii"])
    write_zip(tmp_path / "PET_930123-C1_05032025.zip", ["930123-C1_05032025.Amyloid_PET_CT.nii"])

    result = run_unzip(str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "PET_930120-01_09202025/UF_recon/930120-01_09202025_mean_UF_PROTOCOL_5mmblur.nii").is_file()
    assert (tmp_path / "PET_930123-C1_05032025/930123-C1_05032025.Amyloid_PET_CT.nii").is_file()
    assert (tmp_path / "PET_930123-C1_05032025.zip").is_file()   # archives are kept


@needs_unzip
def test_unzip_usage_errors(tmp_path):
    assert run_unzip().returncode == 1
    assert run_unzip(str(tmp_path / "nope")).returncode == 1
    empty = run_unzip(str(tmp_path))
    assert empty.returncode == 1
    assert "No .zip files found" in empty.stdout
