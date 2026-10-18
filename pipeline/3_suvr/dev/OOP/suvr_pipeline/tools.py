"""Wrappers around the external binaries this stage shells out to."""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

from .layout import PARTIAL_MARKER


class ToolError(RuntimeError):
    pass


def partial_path(final: Path) -> Path:
    """``foo.nii`` -> ``foo.partial.nii``: where to write before an atomic rename."""
    return final.with_name(f"{final.stem}{PARTIAL_MARKER}{final.suffix.lstrip('.')}")


class ExternalTool:
    """Base class: builds an environment and runs commands, raising ToolError on failure."""

    def env(self) -> Dict[str, str]:
        return os.environ.copy()

    def run(self, cmd: Sequence[str], log: logging.Logger, extra_env: Dict[str, str] = None) -> str:
        env = self.env()
        env.update(extra_env or {})
        cmd = [str(c) for c in cmd]
        log.info("- Running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise ToolError(f"{cmd[0]} not found on PATH") from e
        if proc.returncode != 0:
            raise ToolError(f"{cmd[0]} exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout


@dataclass(frozen=True)
class FreeSurfer(ExternalTool):
    home: Path = field(default_factory=lambda: Path(os.environ.get("FREESURFER_HOME", "/usr/local/freesurfer")))

    def env(self) -> Dict[str, str]:
        if not self.home.exists():
            raise ToolError(
                f"FreeSurfer installation not found at {self.home}. "
                "Set FREESURFER_HOME to your FreeSurfer 7 install directory."
            )
        env = super().env()
        env["FREESURFER_HOME"] = str(self.home)
        return env

    def convert(self, src: Path, dst: Path, log: logging.Logger, orientation: str = "RAS") -> None:
        """mri_convert to NIfTI in a fixed orientation (so T1 and aparc+aseg share a voxel grid)."""
        if not src.exists():
            raise ToolError(f"Input file not found: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = partial_path(dst)
        self.run(["mri_convert", "-ot", "nii", "--out_orientation", orientation, src, tmp], log)
        tmp.replace(dst)

    def stats_table(self, command: List[str], subjects_dir: Path, dst: Path, log: logging.Logger) -> None:
        """Run an ``*stats2table`` command and write its table to ``dst`` as comma-separated."""
        tmp = partial_path(dst)
        try:
            self.run(command + ["--tablefile", tmp], log, {"SUBJECTS_DIR": str(subjects_dir)})
            dst.write_text(tmp.read_text().replace("\t", ","))
        finally:
            tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class Flirt(ExternalTool):
    """FSL FLIRT with the parameters the published results were validated against."""

    fsl_dir: Path = field(default_factory=lambda: Path(os.environ.get("FSLDIR", "/usr/local/fsl")))
    dof: int = 12
    cost: str = "corratio"
    bins: int = 256
    search_range: int = 90
    interp: str = "trilinear"

    def env(self) -> Dict[str, str]:
        env = super().env()
        env["FSLDIR"] = str(self.fsl_dir)
        env["PATH"] = f"{env.get('PATH', '')}:{self.fsl_dir}/bin"
        env["FSLOUTPUTTYPE"] = "NIFTI"
        return env

    def register(self, moving: Path, reference: Path, out: Path, log: logging.Logger) -> None:
        """Write ``out`` (.nii) and its matrix ``out.with_suffix('.mat')``; ``out`` appears last."""
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_img = partial_path(out)
        tmp_mat = tmp_img.with_suffix(".mat")
        r = str(self.search_range)
        cmd = [
            "flirt", "-in", moving, "-ref", reference, "-out", tmp_img, "-omat", tmp_mat,
            "-bins", self.bins, "-cost", self.cost,
            "-searchrx", f"-{r}", r, "-searchry", f"-{r}", r, "-searchrz", f"-{r}", r,
            "-dof", self.dof, "-interp", self.interp,
        ]
        try:
            self.run(cmd, log)
            tmp_mat.replace(out.with_suffix(".mat"))
            tmp_img.replace(out)
        finally:
            tmp_img.unlink(missing_ok=True)
            tmp_mat.unlink(missing_ok=True)
