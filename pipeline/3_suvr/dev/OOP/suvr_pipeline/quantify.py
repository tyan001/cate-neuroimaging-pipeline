"""Per-ROI SUV -> SUVR -> Centiloid.

Numerics deliberately mirror suvr.py term for term (same accumulation order), so results are
bit-identical to the implementation the published numbers came from.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import nibabel as nib  # type: ignore
import numpy as np
import pandas as pd

from .tracer import Tracer

log = logging.getLogger(__name__)

# FreesurferLUTR.txt lives in pipeline/3_suvr, beside the original scripts; also accept a copy
# next to run_suvr.py (OOP/).
_LUT_NAME = "FreesurferLUTR.txt"
_HERE = Path(__file__).resolve().parent
DEFAULT_LUT = next(
    (d / _LUT_NAME for d in (_HERE.parent, _HERE.parent.parent) if (d / _LUT_NAME).exists()),
    _HERE.parent.parent / _LUT_NAME,
)

# aseg column name -> label
CEREBELLUM_WHOLE = {
    "Left-Cerebellum-White-Matter": 7,
    "Left-Cerebellum-Cortex": 8,
    "Right-Cerebellum-White-Matter": 46,
    "Right-Cerebellum-Cortex": 47,
}
CEREBELLUM_GM = {"Left-Cerebellum-Cortex": 8, "Right-Cerebellum-Cortex": 47}


@dataclass(frozen=True)
class CorticalRegion:
    """A named composite of Desikan-Killiany parcels, pooled volume-weighted."""

    name: str
    left: Tuple[int, ...]
    right: Tuple[int, ...]

    def hemisphere(self, side: str) -> Tuple[int, ...]:
        return self.left if side == "Left" else self.right


# Their union is the "Global" composite used for Centiloid.
GLOBAL_REGIONS = (
    CorticalRegion("AnteriorCingulate", (1026, 1002), (2026, 2002)),
    CorticalRegion("PosteriorCingulate", (1023, 1010), (2023, 2010)),
    CorticalRegion(
        "Frontal",
        (1003, 1012, 1014, 1018, 1019, 1020, 1027, 1028, 1032),
        (2003, 2012, 2014, 2018, 2019, 2020, 2027, 2028, 2032),
    ),
    CorticalRegion("Temporal", (1030, 1015), (2030, 2015)),
    CorticalRegion("Parietal", (1008, 1025, 1029, 1031), (2008, 2025, 2029, 2031)),
)

# Column order of the *_suvr_combined_cerebellum[_gm].csv outputs.
COMBINED_COLUMNS = [
    "AnteriorCingulateLeft", "AnteriorCingulateRight",
    "PosteriorCingulateLeft", "PosteriorCingulateRight",
    "FrontalLeft", "FrontalRight",
    "TemporalLeft", "TemporalRight",
    "ParietalLeft", "ParietalRight",
    "AnteriorCingulate", "PosteriorCingulate",
    "Frontal", "Temporal", "Parietal",
    "TotalLeft", "TotalRight", "Total",
    "GlobalLeft", "GlobalRight", "Global",
]


class RoiTable:
    """FreeSurfer label -> name lookup (FreesurferLUTR.txt, 116 rows)."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.labels = frame["ROI"].values
        self.names = frame["Name"]
        self._index: Dict[int, int] = {}
        for i, label in enumerate(self.labels):
            self._index.setdefault(int(label), i)

    @classmethod
    def load(cls, path: Path = DEFAULT_LUT) -> "RoiTable":
        if not path.exists():
            raise FileNotFoundError(f"FreeSurfer lookup table not found at {path}")
        return cls(pd.read_csv(path, header=None, names=["ROI", "Name"]))

    def __len__(self) -> int:
        return len(self.labels)

    def index(self, label: int) -> int:
        return self._index[label]

    def name(self, label: int) -> str:
        return self.names.iloc[self.index(label)]


class VolumeTables:
    """The three FreeSurfer volume CSVs prepared into a pair's MRI/ folder."""

    FILES = {
        "subcortical": "asegVolume",
        "cortical_left": "aparcstatsVolumLeft",
        "cortical_right": "aparcstatsVolumRight",
    }

    def __init__(self, subcortical: pd.DataFrame, cortical_left: pd.DataFrame, cortical_right: pd.DataFrame):
        self.subcortical = subcortical
        self.cortical_left = cortical_left
        self.cortical_right = cortical_right

    @classmethod
    def load(cls, mri_dir: Path, prefix: str) -> "VolumeTables":
        frames = {}
        for key, suffix in cls.FILES.items():
            frame = pd.read_csv(mri_dir / f"{prefix}_{suffix}.csv")
            if frame.empty:
                raise ValueError(f"Empty data in {key}")
            frames[key] = frame
        return cls(**frames)

    def aseg(self, column: str) -> float:
        """Subcortical volume by exact aseg column name; raises KeyError if absent."""
        return float(self.subcortical[column].iloc[0])

    def for_label(self, label: int, rois: RoiTable) -> float:
        """Volume of any LUT label, or 0.0 (with a warning) if the tables don't have it."""
        name = rois.name(label)
        if label < 1000:
            table, column = self.subcortical, name.replace(" ", "-")
        elif label < 2000:
            table, column = self.cortical_left, f"lh_{name[7:]}_volume"   # ctx-lh-X
        else:
            table, column = self.cortical_right, f"rh_{name[7:]}_volume"  # ctx-rh-X
        if column not in table.columns:
            # FreeSurfer's DK atlas has no corpus callosum parcel, so 1004/2004 are always absent.
            level = logging.DEBUG if "corpuscallosum" in column else logging.WARNING
            log.log(level, "No volume column %s for ROI %s; weighting it as 0", column, label)
            return 0.0
        return float(table[column].iloc[0])


@dataclass
class SuvrResult:
    min: float
    max: float
    suv_mean: np.ndarray
    suv_median: np.ndarray
    suv_sum: np.ndarray
    suv_cer: float
    suv_cer_gm: float
    suvr: np.ndarray            # per LUT row, whole-cerebellum reference
    regional: Dict[str, float]  # COMBINED_COLUMNS -> SUVR


class _Pool:
    """Running volume-weighted sum."""

    __slots__ = ("weighted", "volume")

    def __init__(self):
        self.weighted = 0.0
        self.volume = 0.0

    def add(self, value: float, volume: float) -> None:
        self.weighted += value * volume
        self.volume += volume

    def merge(self, other: "_Pool") -> None:
        self.weighted += other.weighted
        self.volume += other.volume

    def mean(self) -> float:
        return self.weighted / self.volume if self.volume > 0 else 0.0

    @staticmethod
    def pooled(a: "_Pool", b: "_Pool") -> float:
        total = a.volume + b.volume
        return (a.weighted + b.weighted) / total if total > 0 else 0.0


class SuvrCalculator:
    def __init__(self, rois: RoiTable, regions: Sequence[CorticalRegion] = GLOBAL_REGIONS):
        self.rois = rois
        self.regions = regions

    def compute_files(self, pet_path: Path, aparc_path: Path, volumes: VolumeTables) -> SuvrResult:
        pet = nib.load(pet_path).get_fdata()
        aparc = nib.load(aparc_path).get_fdata()
        if pet.shape != aparc.shape:
            raise ValueError(
                f"PET {pet.shape} and aparc+aseg {aparc.shape} are on different grids -- "
                "was the PET registered to this T1?"
            )
        return self.compute(pet, aparc, volumes)

    def compute(self, pet: np.ndarray, aparc: np.ndarray, volumes: VolumeTables) -> SuvrResult:
        mask = aparc != 0
        labels = aparc[mask]
        values = pet[mask]

        n = len(self.rois)
        suv_med, suv_avr, suv_sum = np.zeros(n), np.zeros(n), np.zeros(n)
        for i, label in enumerate(self.rois.labels):
            vals = values[labels == label]
            if len(vals) > 0:
                suv_med[i] = np.median(vals)
                suv_avr[i] = np.mean(vals)
                suv_sum[i] = np.sum(vals)

        suv_cer = self._reference(suv_avr, volumes, CEREBELLUM_WHOLE)
        suv_cer_gm = self._reference(suv_avr, volumes, CEREBELLUM_GM)
        suvr = suv_avr / suv_cer if suv_cer > 0 else np.zeros_like(suv_avr)

        return SuvrResult(
            min=np.min(values), max=np.max(values),
            suv_mean=suv_avr, suv_median=suv_med, suv_sum=suv_sum,
            suv_cer=suv_cer, suv_cer_gm=suv_cer_gm,
            suvr=suvr, regional=self._regional(suvr, volumes),
        )

    def _reference(self, suv_avr: np.ndarray, volumes: VolumeTables, parts: Dict[str, int]) -> float:
        pool = _Pool()
        for column, label in parts.items():
            pool.add(suv_avr[self.rois.index(label)], volumes.aseg(column))
        return pool.mean()

    def _regional(self, suvr: np.ndarray, volumes: VolumeTables) -> Dict[str, float]:
        out: Dict[str, float] = {}
        global_pools = {"Left": _Pool(), "Right": _Pool()}

        for region in self.regions:
            pools = {}
            for side in ("Left", "Right"):
                pool = pools[side] = _Pool()
                for label in region.hemisphere(side):
                    idx = self.rois.index(label)
                    vol = volumes.for_label(label, self.rois)
                    if np.isfinite(suvr[idx]):
                        pool.add(suvr[idx], vol)
                out[f"{region.name}{side}"] = pool.mean()
            out[region.name] = _Pool.pooled(pools["Left"], pools["Right"])
            for side in ("Left", "Right"):
                global_pools[side].merge(pools[side])

        out["GlobalLeft"] = global_pools["Left"].mean()
        out["GlobalRight"] = global_pools["Right"].mean()
        out["Global"] = _Pool.pooled(global_pools["Left"], global_pools["Right"])

        # Total: every cortical parcel in the LUT.
        total = {"Left": _Pool(), "Right": _Pool()}
        for i, label in enumerate(self.rois.labels):
            if 1000 < label < 2000:
                side = "Left"
            elif label > 2000:
                side = "Right"
            else:
                continue
            if np.isfinite(suvr[i]):
                total[side].add(suvr[i], volumes.for_label(label, self.rois))
        out["TotalLeft"] = total["Left"].mean()
        out["TotalRight"] = total["Right"].mean()
        out["Total"] = _Pool.pooled(total["Left"], total["Right"])
        return out


class ResultWriter:
    """Writes res/ in exactly the file layout downstream aggregation expects."""

    def __init__(self, rois: RoiTable):
        self.rois = rois

    def write(self, result: SuvrResult, out_dir: Path, name: str, pid: str, tracer: Tracer) -> List[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []

        for suffix, value in [
            ("max", result.max), ("min", result.min),
            ("suv_cer", result.suv_cer), ("suv_cer_gm", result.suv_cer_gm),
        ]:
            path = out_dir / f"{name}_{suffix}"
            path.write_text(str(value))
            written.append(path)

        for suffix, values in [
            ("mean_suv", result.suv_mean),
            ("median_suv", result.suv_median),
            ("total_suv", result.suv_sum),
        ]:
            path = out_dir / f"{name}_{suffix}.csv"
            self._roi_frame(values).to_csv(path, index=False)
            written.append(path)

        gm_rescaled = [v * result.suv_cer / result.suv_cer_gm for v in result.suvr]
        for suffix, values in [("suvr_cerebellum", result.suvr), ("suvr_cerebellum_gm", gm_rescaled)]:
            frame = self._roi_frame(values).set_index("ROI").T
            frame.insert(0, "PID", ["N/A", pid])
            path = out_dir / f"{name}_{suffix}.csv"
            frame.to_csv(path, index=False)
            written.append(path)

        regional = [result.regional.get(col, 0.0) for col in COMBINED_COLUMNS]
        gm_factor = result.suv_cer / result.suv_cer_gm if result.suv_cer_gm > 0 else 1.0
        for suffix, values in [
            ("suvr_combined_cerebellum", regional),
            ("suvr_combined_cerebellum_gm", [v * gm_factor for v in regional]),
        ]:
            global_suvr = values[COMBINED_COLUMNS.index("Global")]
            header = ["PID", "Compound", "Centiloid"] + COMBINED_COLUMNS
            row = [pid, tracer.name, tracer.centiloid(global_suvr)] + values
            path = out_dir / f"{name}_{suffix}.csv"
            pd.DataFrame([header, row]).to_csv(path, index=False, header=False)
            written.append(path)

        return written

    def _roi_frame(self, values) -> pd.DataFrame:
        return pd.DataFrame({"ROI": self.rois.frame["ROI"], "Name": self.rois.names, "Value": values})
