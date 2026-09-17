"""Tests for pipeline/6_extract/viewer.py: the JSON API, the volume payload and the HTTP handler.

Volumes are a few voxels across, written with nibabel, so values can be checked exactly after
the reorientation and uint16 packing the viewer does.
"""

import gzip
import json
import struct
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import nibabel as nib
import numpy as np
import pytest

EXTRACT_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "6_extract"
sys.path.insert(0, str(EXTRACT_DIR))

import viewer  # noqa: E402

T1 = "900951/20240101/anat/900951-20240101_T1w.nii"
T1_LAS = "900951/20240101/anat/900951-20240101_T2w.nii.gz"
ASEG = "900951/20240101/freesurfer741/900951-20240101_T1w/mri/aseg.mgz"
OVERLAY = "900951/20240101/freesurfer741/900951-20240101_T1w/surf/lh.thickness.mgh"
PET = "900951/20240110/pet/900951-20240110_PET.nii"
DYNAMIC = "900951/20240110/pet/900951-20240110_PET_dyn.nii"


def t1_data():
    return np.arange(4 * 5 * 6, dtype=np.int16).reshape(4, 5, 6)


def save(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.to_filename(path)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "ADRC"
    save(nib.Nifti1Image(t1_data(), np.diag([2.0, 2.0, 2.0, 1.0])), r / T1)
    (r / T1).with_suffix(".json").write_text(json.dumps({"RepetitionTime": 2.3, "EchoTime": 0.003}))
    save(nib.Nifti1Image(t1_data(), np.diag([-1.0, 1.0, 1.0, 1.0])), r / T1_LAS)

    aseg = np.zeros((6, 6, 6), dtype=np.int32)
    aseg[1, 1, 1], aseg[2, 2, 2], aseg[3, 3, 3], aseg[4, 4, 4] = 2, 17, 53, 1000
    save(nib.MGHImage(aseg, np.eye(4)), r / ASEG)
    save(nib.MGHImage(np.linspace(0, 3, 50, dtype=np.float32).reshape(50, 1, 1), np.eye(4)), r / OVERLAY)

    pet = np.linspace(0.0, 2.5, 27, dtype=np.float32).reshape(3, 3, 3)
    pet[0, 0, 0] = np.nan
    save(nib.Nifti1Image(pet, np.eye(4)), r / PET)
    (r / PET).with_suffix(".json").write_text("{not json")
    frames = np.stack([np.full((3, 3, 3), f, dtype=np.float32) for f in range(4)], axis=-1)
    save(nib.Nifti1Image(frames, np.eye(4)), r / DYNAMIC)

    (r / "900951/20240110/pet/900951-20240110_empty.nii").touch()
    (r / "900951/20240110/pet/900951-20240110_broken.nii").write_text("not a nifti")
    (r / "900952/20230101/anat").mkdir(parents=True)
    (r / "notes.txt").write_text("not a subject")
    viewer.load_frame.cache_clear()
    return r


def q(root, **kw):
    return {"root": str(root), **kw}


def decode(payload):
    (n,) = struct.unpack("<I", payload[:4])
    meta = json.loads(payload[4:4 + n])
    voxels = np.frombuffer(payload[4 + n:], dtype="<u2").reshape(meta["dims"])
    return meta, voxels * meta["scale"] + meta["offset"]


# --- paths -------------------------------------------------------------------------------------


def test_dataset_root(root, tmp_path):
    assert viewer.dataset_root(q(root)) == root
    assert viewer.dataset_root({"root": f"  {root}/900951/..  "}) == root
    for bad in ({}, {"root": ""}, {"root": str(tmp_path / "nope")}):
        with pytest.raises(viewer.NotFound):
            viewer.dataset_root(bad)


def test_safe_path(root):
    assert viewer.safe_path(root, T1) == root / T1
    assert viewer.safe_path(root, ".") == root
    assert viewer.safe_path(root, "../ADRC/notes.txt") == root / "notes.txt"  # normalises back inside
    (root.parent / "ADRC_other").mkdir()
    for rel in ["..", "900951/../../ADRC_other", "/etc", "900951/nope.nii"]:
        with pytest.raises(viewer.NotFound):
            viewer.safe_path(root, rel)


def test_locate(root):
    def locate(path):
        return viewer.api_locate({"path": str(path)})

    assert locate(root) == {"root": str(root), "subject": None, "date": None, "file": None}
    assert locate(root / "900951") == {"root": str(root), "subject": "900951", "date": None, "file": None}
    assert locate(root / "900951/20240110/pet") == {
        "root": str(root), "subject": "900951", "date": "20240110", "file": None}
    assert locate(root / T1)["file"] == T1
    assert locate(root / T1.replace(".nii", ".json"))["file"] is None
    with pytest.raises(viewer.NotFound):
        locate(root / "missing")
    with pytest.raises(viewer.NotFound, match="not inside"):
        locate(root / "notes.txt")


# --- browsing ----------------------------------------------------------------------------------


def test_roots(monkeypatch):
    monkeypatch.setattr(viewer, "ROOTS", ["/data/a"])
    assert viewer.api_roots({}) == {"roots": ["/data/a"]}


def test_subjects(root):
    assert viewer.api_subjects(q(root)) == {"root": str(root), "subjects": ["900951", "900952"]}


def test_subject(root):
    out = viewer.api_subject(q(root, id="900951"))
    assert [(s["date"], s["label"], s["modality"]) for s in out["sessions"]] == [
        ("20240101", "2024-01-01", "MRI"),
        ("20240110", "2024-01-10", "PET"),
    ]
    assert out["sessions"][0]["scans"] == {"t1w": [T1]}
    assert out["sessions"][1]["scans"] == {"pet": [PET, DYNAMIC]}
    assert out["sessions"][0]["folders"] == ["anat", "freesurfer741"]


@pytest.mark.parametrize("pid", ["", ".", "..", "../ADRC", "900951/20240101", "999999"])
def test_subject_rejects(root, pid):
    with pytest.raises(viewer.NotFound):
        viewer.api_subject(q(root, id=pid))


def test_session(root):
    out = viewer.api_session(q(root, id="900951", date="20240101"))
    assert [g["folder"] for g in out["groups"]] == ["anat", "freesurfer741/900951-20240101_T1w/mri",
                                                    "freesurfer741/900951-20240101_T1w/surf"]
    assert [f["path"] for f in out["groups"][0]["files"]] == [T1, T1_LAS]
    assert out["groups"][0]["files"][0]["size"] == (root / T1).stat().st_size
    with pytest.raises(viewer.NotFound):
        viewer.api_session(q(root, id="900951", date="../../.."))


# --- info --------------------------------------------------------------------------------------


def test_info_nifti(root):
    info = viewer.api_info(q(root, path=T1))
    assert info["format"] == "Nifti1Image"
    assert info["shape"] == [4, 5, 6] and info["frames"] == 1
    assert info["zooms"] == [2.0, 2.0, 2.0]
    assert info["dtype"] == "int16" and info["orientation"] == "RAS"
    assert info["sidecar"] == {"file": "900951-20240101_T1w.json",
                               "data": {"RepetitionTime": 2.3, "EchoTime": 0.003}}
    assert "scl_slope" not in info["header"]  # NaN is dropped, not sent as invalid JSON
    json.dumps(info, allow_nan=False)


def test_info_variants(root):
    assert viewer.api_info(q(root, path=T1_LAS))["orientation"] == "LAS"
    assert viewer.api_info(q(root, path=DYNAMIC))["frames"] == 4
    assert viewer.api_info(q(root, path=PET))["sidecar"]["error"]
    mgh = viewer.api_info(q(root, path=ASEG))
    assert mgh["format"] == "MGHImage" and set(mgh["header"]) <= {"tr", "flip_angle", "te", "ti"}


def test_info_unreadable(root):
    assert viewer.api_info(q(root, path="900951/20240110/pet/900951-20240110_empty.nii"))["error"] == \
        "File is empty (0 bytes)."
    broken = viewer.api_info(q(root, path="900951/20240110/pet/900951-20240110_broken.nii"))
    assert broken["error"].startswith("nibabel could not read")
    assert str(root) not in broken["error"]
    assert "Surface overlay (50 vertices)" in viewer.api_info(q(root, path=OVERLAY))["error"]


# --- volumes -----------------------------------------------------------------------------------


def test_volume_integer_is_exact(root):
    meta, data = decode(viewer.volume_payload(q(root, path=T1)))
    assert meta["dims"] == [4, 5, 6] and meta["zooms"] == [2.0, 2.0, 2.0]
    assert meta["scale"] == 1.0 and meta["offset"] == 0.0 and meta["max"] == 119.0
    assert meta["labels"] is None  # dense values: an image, not a label map
    np.testing.assert_array_equal(data, t1_data())


def test_volume_reoriented_to_ras(root):
    meta, data = decode(viewer.volume_payload(q(root, path=T1_LAS)))
    np.testing.assert_array_equal(data, t1_data()[::-1])
    assert np.allclose(np.array(meta["affine"])[:3, :3], np.eye(3))


def test_volume_label_map(root):
    meta, data = decode(viewer.volume_payload(q(root, path=ASEG)))
    assert meta["labels"] == [0, 2, 17, 53, 1000]
    assert data[2, 2, 2] == 17 and data[4, 4, 4] == 1000


def test_volume_float_with_nan(root):
    meta, data = decode(viewer.volume_payload(q(root, path=PET)))
    assert meta["nonfinite"] == 1
    assert meta["min"] == pytest.approx(2.5 / 26) and meta["max"] == pytest.approx(2.5)
    assert meta["scale"] == pytest.approx((meta["max"] - meta["min"]) / 65535)
    expected = np.linspace(0.0, 2.5, 27).reshape(3, 3, 3)
    np.testing.assert_allclose(data.ravel()[1:], expected.ravel()[1:], atol=1e-4)
    assert meta["window"][0] <= meta["window"][1]


@pytest.mark.parametrize("frame, value", [("0", 0.0), ("2", 2.0), ("99", 3.0), ("-5", 0.0), ("mean", 1.5)])
def test_volume_frames(root, frame, value):
    meta, data = decode(viewer.volume_payload(q(root, path=DYNAMIC, frame=frame)))
    assert meta["dims"] == [3, 3, 3]
    assert np.allclose(data, value)


# --- HTTP --------------------------------------------------------------------------------------


@pytest.fixture
def server():
    srv = viewer.ThreadingHTTPServer(("127.0.0.1", 0), viewer.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url, gzip_ok=False):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"} if gzip_ok else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, headers, body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, headers, body = e.code, e.headers, e.read()
    if headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return status, headers, body


def test_http_page_and_api(root, server):
    status, headers, body = get(server + "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert body == viewer.HTML.read_bytes()

    status, headers, body = get(f"{server}/api/subjects?{urlencode(q(root))}")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert json.loads(body)["subjects"] == ["900951", "900952"]


def test_http_volume_gzip(root, server):
    big = np.arange(12 ** 3, dtype=np.int16).reshape(12, 12, 12)  # above the 1 KB gzip threshold
    save(nib.Nifti1Image(big, np.eye(4)), root / "900952/20230101/anat/900952-20230101_T1w.nii")
    url = f"{server}/api/volume?{urlencode(q(root, path='900952/20230101/anat/900952-20230101_T1w.nii'))}"
    status, headers, body = get(url, gzip_ok=True)
    assert status == 200 and headers["Content-Encoding"] == "gzip"
    assert headers["Content-Type"] == "application/octet-stream"
    np.testing.assert_array_equal(decode(body)[1], big)
    assert "Content-Encoding" not in get(url)[1]


@pytest.mark.parametrize("path, status, message", [
    ("/api/subject?id=999999", 404, "Not found: subject 999999"),
    ("/api/subject", 404, "Not found: 'id'"),
    ("/api/info?path=../../etc/passwd", 404, "Not found"),
    ("/api/volume?path=900951/20240110/pet/900951-20240110_broken.nii", 500, "Error"),
])
def test_http_errors(root, server, path, status, message):
    sep = "&" if "?" in path else "?"
    got, _, body = get(f"{server}{path}{sep}{urlencode(q(root))}")
    assert got == status
    assert message in json.loads(body)["error"]


def test_http_unknown_route(server):
    assert get(server + "/api/nope")[0] == 404
