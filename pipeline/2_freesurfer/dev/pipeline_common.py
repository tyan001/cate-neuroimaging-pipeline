"""Shared path/logging helpers for freesurfer_pipeline.py, hippocampus_pipeline.py,
and run_pipeline.py."""
from pathlib import Path
import logging


def setup_logger(name, log_file):
    """Set up a logger that writes to both console and file."""
    log_dir = log_file.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger


def find_nii_paths(root_dir):
    """
    Find all .nii files located in 'anat' folders within the given directory structure.

    Traverses root_dir/subjectID/Session/anat/*.nii

    Args:
        root_dir (str): The path to the root directory to start the search from.

    Returns:
        list[Path]: Full paths to .nii files found in 'anat' folders.
    """
    root_path = Path(root_dir)
    return [p for p in root_path.rglob('*') if p.parent.name == 'anat' and p.suffix == '.nii']


def freesurfer_dir_for(subject_path):
    """
    Given a subject's anat/*.nii path, return the freesurfer741 SUBJECTS_DIR for its session
    (root_dir/subjectID/Session/freesurfer741).
    """
    return subject_path.parent.parent / 'freesurfer741'
