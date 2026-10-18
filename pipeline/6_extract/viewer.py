#!/usr/bin/env python3
"""Read-only browser viewer for the organized dataset.

Search a subject, pick a session, and inspect any volume in it (.nii, .nii.gz, .mgz) in three
orthogonal views with its header and JSON sidecar. Nothing is written or modified.

    python3 viewer.py --root /data/NWSI/ADRC                  # or export ADRC_ROOT
    python3 viewer.py --root /data/batch12/ADRC --root /data/NWSI/ADRC   # offer several
    python3 viewer.py --port 9000

The dataset can also be changed from the page: paste any path into the Dataset box. A dataset
folder, a subject or session folder, or a scan file all work; the page opens at that spot.

The server listens on localhost only. From a laptop, forward the port over SSH:

    ssh -L 8765:localhost:8765 user@server             # then open http://localhost:8765

Needs nibabel and numpy (already project dependencies).
"""

import argparse
import gzip
import json
import os
import re
import struct
import sys
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import nibabel as nib
import numpy as np
from nibabel.orientations import (
    aff2axcodes,
    apply_orientation,
    inv_ornt_aff,
    io_orientation,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scans import (  # noqa: E402
    ADRC_ROOT,
    VOLUME_SUFFIXES,
    list_sessions,
    list_subjects,
    pretty_date,
    session_volumes,
)

HTML = Path(__file__).resolve().parent / "viewer.html"
ROOTS: list[str] = []  # datasets offered in the page's Dataset box

# Above this many distinct integer values a volume is treated as an image, not a label map.
MAX_LABELS = 512
LABEL_NAME_HINTS = ("aseg", "aparc", "label", "seg", "mask")


class NotFound(Exception):
    pass


def dataset_root(q) -> Path:
    """The dataset folder a request refers to (every request names its own)."""
    text = q.get("root", "").strip()
    if not text:
        raise NotFound("no dataset folder chosen")
    root = Path(os.path.normpath(Path(text).expanduser().absolute()))
    if not root.is_dir():
        raise NotFound(f"dataset folder {root}")
    return root


def safe_path(root: Path, rel: str) -> Path:
    """Resolve a root-relative path, refusing anything that escapes the dataset root."""
    full = Path(os.path.normpath(root / rel))
    if (full != root and root not in full.parents) or not full.exists():
        raise NotFound(rel)
    return full


# --- API: browsing -------------------------------------------------------------------------------


def api_roots(_q):
    return {"roots": ROOTS}


def api_locate(q):
    """Split any pasted path into dataset root / subject / session / file.

    /data/ADRC                                   -> root only
    /data/ADRC/900001[/20200115[/anat/x.nii]]    -> root + subject [+ session [+ file]]
    """
    path = Path(os.path.normpath(Path(q.get("path", "").strip()).expanduser().absolute()))
    if not path.exists():
        raise NotFound(str(path))
    parts = path.parts
    for i in range(2, len(parts)):
        if re.fullmatch(r"\d{8}", parts[i]):
            root = Path(*parts[: i - 1])
            is_file = path.is_file() and path.name.endswith(VOLUME_SUFFIXES)
            return {"root": str(root), "subject": parts[i - 1], "date": parts[i],
                    "file": path.relative_to(root).as_posix() if is_file else None}
    if not path.is_dir():
        raise NotFound(f"{path} is not inside a <subject>/<YYYYMMDD> folder")
    # A subject folder holds date folders; a dataset root holds subject folders.
    if any(re.fullmatch(r"\d{8}", c.name) for c in path.iterdir() if c.is_dir()):
        return {"root": str(path.parent), "subject": path.name, "date": None, "file": None}
    return {"root": str(path), "subject": None, "date": None, "file": None}


def api_subjects(q):
    root = dataset_root(q)
    return {"root": str(root), "subjects": list_subjects(root)}


def api_subject(q):
    root = dataset_root(q)
    pid = q["id"].strip()
    if "/" in pid or pid in {"", ".", ".."} or not (root / pid).is_dir():
        raise NotFound(f"subject {pid}")
    sessions = []
    for s in list_sessions(root, pid):
        sessions.append({
            "date": s.date,
            "label": pretty_date(s.date),
            "modality": s.modality,
            "folders": s.subfolders,
            "scans": {k: [p.relative_to(root).as_posix() for p in v] for k, v in s.scans.items() if v},
        })
    return {"subject": pid, "sessions": sessions}


def api_session(q):
    root = dataset_root(q)
    session = safe_path(root, f"{q['id']}/{q['date']}")
    groups = session_volumes(root, session.parent.name, session.name)
    return {
        "groups": [
            {"folder": folder, "files": [
                {"path": p.relative_to(root).as_posix(), "name": p.name, "size": p.stat().st_size}
                for p in files
            ]}
            for folder, files in groups.items()
        ]
    }


# --- API: volumes --------------------------------------------------------------------------------


def _sidecar(path: Path):
    stem = path.name.split(".")[0]
    candidate = path.with_name(stem + ".json")
    if candidate.is_file():
        try:
            return {"file": candidate.name, "data": json.loads(candidate.read_text())}
        except (OSError, json.JSONDecodeError) as e:
            return {"file": candidate.name, "error": str(e)}
    return None


def _jsonable(value):
    """Header fields come back as 0-d numpy arrays, often holding bytes."""
    if isinstance(value, (np.ndarray, np.generic)):
        value = value.tolist()
    if isinstance(value, bytes):
        return value.decode("latin-1").rstrip("\x00")
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None  # JSON has no NaN; nibabel reports unset scl_slope as NaN
    return value


def api_info(q):
    path = safe_path(dataset_root(q), q["path"])
    stat = path.stat()
    info = {
        "path": q["path"],
        "name": path.name,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "sidecar": _sidecar(path),
    }
    if stat.st_size == 0:
        info["error"] = "File is empty (0 bytes)."
        return info
    try:
        img = nib.load(path)
    except Exception as e:  # noqa: BLE001 - nibabel raises many types for malformed files
        info["error"] = f"nibabel could not read this file: {e}".replace(str(path), path.name)
        return info

    hdr = img.header
    shape = img.shape
    if len(shape) >= 3 and sorted(shape[:3])[:2] == [1, 1] and path.suffix == ".mgh":
        info["error"] = (f"Surface overlay ({max(shape)} vertices), not a volume. "
                         "Open it on a surface in freeview.")
        return info
    info.update({
        "format": type(img).__name__,
        "shape": [int(n) for n in shape],
        "frames": int(np.prod(shape[3:])) if len(shape) > 3 else 1,
        "zooms": [round(float(z), 4) for z in hdr.get_zooms()],
        "dtype": str(hdr.get_data_dtype()),
        "orientation": "".join(aff2axcodes(img.affine)),
        "affine": np.round(img.affine, 4).tolist(),
    })
    fields = {}
    if isinstance(hdr, nib.Nifti1Header):
        for key in ("descrip", "aux_file", "intent_name", "qform_code", "sform_code",
                    "scl_slope", "scl_inter", "cal_min", "cal_max", "xyzt_units", "slice_code"):
            fields[key] = _jsonable(hdr[key])
        fields["units"] = " / ".join(u or "unknown" for u in hdr.get_xyzt_units())
    elif isinstance(hdr, nib.freesurfer.mghformat.MGHHeader):
        for key in ("tr", "flip_angle", "te", "ti"):
            fields[key] = _jsonable(hdr[key])
    info["header"] = {k: v for k, v in fields.items() if v not in ("", None)}
    return info


@lru_cache(maxsize=3)
def load_frame(path: str, mtime: float, frame: str) -> tuple[np.ndarray, np.ndarray]:
    """One 3D frame reoriented to RAS (x=L->R, y=P->A, z=I->S). Returns (data, affine)."""
    img = nib.load(path)
    dataobj = img.dataobj
    shape = img.shape
    if len(shape) < 3:
        data = np.asanyarray(dataobj).reshape(shape + (1,) * (3 - len(shape)))
    elif len(shape) == 3:
        data = np.asanyarray(dataobj)
    else:
        n = int(np.prod(shape[3:]))
        if frame == "mean":
            full = np.asanyarray(dataobj).reshape(shape[:3] + (n,))
            data = full.mean(axis=3, dtype=np.float32)
        else:
            idx = min(max(int(frame), 0), n - 1)
            unravelled = np.unravel_index(idx, shape[3:])
            data = np.asanyarray(dataobj[(Ellipsis, *unravelled)])
    ornt = io_orientation(img.affine)
    affine = img.affine @ inv_ornt_aff(ornt, data.shape)
    data = apply_orientation(data, ornt)
    return np.ascontiguousarray(data), affine


def volume_payload(q) -> bytes:
    """[uint32 json length][json meta][uint16 voxels, C order over (x, y, z)]"""
    path = safe_path(dataset_root(q), q["path"])
    data, affine = load_frame(str(path), path.stat().st_mtime, q.get("frame", "0"))

    finite = np.isfinite(data)
    vals = data[finite] if not finite.all() else data.ravel()
    lo = float(vals.min()) if vals.size else 0.0
    hi = float(vals.max()) if vals.size else 0.0

    is_int = np.issubdtype(data.dtype, np.integer) or (
        vals.size > 0 and np.array_equal(vals[::97], np.round(vals[::97]))
    )
    labels = None
    if is_int and hi - lo <= 65535:
        # Integer data is shipped exactly: stored = value - lo.
        scale = 1.0
        if len(np.unique(vals[::7])) <= MAX_LABELS:
            uniq = np.unique(vals)
            # An 8-bit image (FreeSurfer T1.mgz) also has <= 256 values, but uses most of its
            # range; segmentations are sparse (aparc+aseg: ~110 values spread over 0..2035).
            named = any(h in path.name.lower() for h in LABEL_NAME_HINTS)
            sparse = len(uniq) < 0.5 * (hi - lo + 1)
            if 2 < len(uniq) <= MAX_LABELS and (named or sparse):
                labels = [int(u) for u in uniq]
    else:
        scale = (hi - lo) / 65535 if hi > lo else 1.0

    q16 = np.zeros(data.shape, dtype=np.uint16)
    q16[finite] = np.clip(np.rint((data[finite] - lo) / scale), 0, 65535)

    nonzero = vals[vals != 0]
    sample = nonzero if nonzero.size else vals
    if sample.size > 2_000_000:
        sample = sample[:: sample.size // 1_000_000]
    p_lo, p_hi = (np.percentile(sample, [0.5, 99.5]) if sample.size else (lo, hi))

    meta = {
        "dims": list(data.shape),
        "zooms": [float(z) for z in np.linalg.norm(affine[:3, :3], axis=0)],
        "affine": affine.tolist(),
        "offset": lo,
        "scale": scale,
        "min": lo,
        "max": hi,
        "window": [float(p_lo), float(p_hi)],
        "labels": labels,
        "nonfinite": int((~finite).sum()),
        "mean": float(vals.mean()) if vals.size else 0.0,
    }
    head = json.dumps(meta).encode()
    return struct.pack("<I", len(head)) + head + q16.astype("<u2").tobytes()


# --- HTTP ----------------------------------------------------------------------------------------

ROUTES = {
    "/api/roots": api_roots,
    "/api/locate": api_locate,
    "/api/subjects": api_subjects,
    "/api/subject": api_subject,
    "/api/session": api_session,
    "/api/info": api_info,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                self._send(HTML.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/volume":
                self._send(volume_payload(q), "application/octet-stream")
            elif url.path in ROUTES:
                self._send(json.dumps(ROUTES[url.path](q)).encode(), "application/json")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (NotFound, KeyError) as e:
            self._send(json.dumps({"error": f"Not found: {e}"}).encode(), "application/json",
                       HTTPStatus.NOT_FOUND)
        except Exception as e:  # noqa: BLE001 - report any failure to the page instead of dropping the connection
            self.log_error("%s failed: %r", url.path, e)
            self._send(json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(),
                       "application/json", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK):
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=1)
            encoded = True
        else:
            encoded = False
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if encoded:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "/api/volume" in self.path or args[1:2] != ("200",):
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse and inspect T1w / PET / any volume by subject and session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="From a laptop: ssh -L 8765:localhost:8765 user@server, then open http://localhost:8765",
    )
    parser.add_argument("-r", "--root", action="append", default=[],
                        help="dataset folder to offer; repeatable (default: $ADRC_ROOT)")
    parser.add_argument("-p", "--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default localhost only; the viewer has no login)")
    args = parser.parse_args()

    for root in args.root or [ADRC_ROOT]:
        if not root:
            continue
        path = Path(root).expanduser().absolute()
        if not path.is_dir():
            sys.exit(f"Dataset folder does not exist: {path}")
        ROOTS.append(os.path.normpath(path))

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Datasets: " + (", ".join(ROOTS) or "none given; enter a folder in the page"))
    print(f"  open        http://localhost:{args.port}")
    print(f"  over SSH    ssh -L {args.port}:localhost:{args.port} {os.environ.get('USER', 'user')}@<this-host>")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
