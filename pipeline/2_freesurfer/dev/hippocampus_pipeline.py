"""
Hippocampal/amygdala subfield segmentation pipeline (segmentHA_T1.sh).

Runs on existing FreeSurfer `freesurfer741/<subject>` outputs. This is the
hippocampus half of the pipeline in mri_processing.py, split out on its own so
it can change independently of the FreeSurfer step (freesurfer_pipeline.py).
run_pipeline.py chains the two together, running this one second.

    nohup python3 hippocampus_pipeline.py /data > hippocampus.log 2>&1 &
"""
from pathlib import Path
import argparse
import os
import subprocess
import time
import socket

from pipeline_common import setup_logger


def process_subject_hippocampus(subject, fs_path, logger):
    """
    Run segmentHA_T1.sh for a single subject. More on the script here:
    https://surfer.nmr.mgh.harvard.edu/fswiki/HippocampalSubfieldsAndNucleiOfAmygdala

    Args:
        subject (str): FreeSurfer subject ID (the anat filename stem)
        fs_path (Path): SUBJECTS_DIR containing `subject`'s recon-all output
        logger (Logger): Logger object for logging messages

    Returns:
        dict: subject, hc_success, hc_time
    """
    result = {'subject': subject, 'hc_success': False, 'hc_time': 0}

    hc_cmd = f'segmentHA_T1.sh {subject} {fs_path}'
    logger.info(f"Running Hippocampus segmentation: {hc_cmd}")

    start = time.time()
    return_code = subprocess.run(hc_cmd, shell=True).returncode
    result['hc_time'] = time.time() - start
    result['hc_success'] = return_code == 0

    if result['hc_success']:
        logger.info(f"Hippocampus segmentation for {subject} completed successfully in {result['hc_time']:.2f} seconds")
    else:
        logger.error(f"Hippocampus segmentation for {subject} failed with return code {return_code}")

    return result


def find_existing_freesurfer_subjects(root_dir):
    """
    Find existing freesurfer741/<subject> recon-all directories under
    root_dir/subjectID/Session/.

    Returns:
        list[tuple[str, Path]]: (subject, fs_path) pairs, where fs_path is the
        SUBJECTS_DIR (the freesurfer741 directory) for that subject.
    """
    fs_dirs = [p for p in Path(root_dir).glob("*/*/freesurfer741/*")
               if p.is_dir() and p.name != 'fsaverage']
    return [(fs_dir.stem, fs_dir.parent) for fs_dir in fs_dirs]


def run_hippocampus_pipeline(directory, logger):
    """Run segmentHA_T1.sh on every existing FreeSurfer subject found under `directory`."""
    subjects = find_existing_freesurfer_subjects(directory)
    logger.info(f"Found {len(subjects)} existing FreeSurfer directories")

    return [process_subject_hippocampus(subject, fs_path, logger) for subject, fs_path in subjects]


def main():
    parser = argparse.ArgumentParser(description='Run hippocampal segmentation on existing FreeSurfer results.')
    parser.add_argument('directory', type=str, help='Path to the BIDS directory.')
    args = parser.parse_args()

    container_name = os.getenv('CONTAINER_NAME', socket.gethostname())

    log_dir = Path(args.directory) / 'fs_logs'
    logger = setup_logger('hippocampus_pipeline', log_dir / f'{container_name}.log')

    logger.info("Starting hippocampus segmentation on existing FreeSurfer results")
    results = run_hippocampus_pipeline(args.directory, logger)

    total = len(results)
    success = sum(1 for r in results if r['hc_success'])
    failed = [r['subject'] for r in results if not r['hc_success']]
    total_time = sum(r['hc_time'] for r in results)

    logger.info("=== HIPPOCAMPUS SUMMARY ===")
    logger.info(f"Hippocampus segmentation successful: {success}/{total}")
    if failed:
        logger.info(f"Failed subjects: {', '.join(failed)}")
    logger.info(f"Total hippocampus segmentation time: {total_time:.2f} seconds")
    if total > 0:
        logger.info(f"Average hippocampus time per subject: {total_time/total:.2f} seconds")
    logger.info("=== HIPPOCAMPUS PROCESSING COMPLETE ===")


if __name__ == '__main__':
    main()
