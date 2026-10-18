"""
FreeSurfer recon-all pipeline.

Runs `recon-all -all` for every anat/*.nii scan found under a BIDS-style directory,
writing each subject's output to <subjectID>/<Session>/freesurfer741/<anat-stem>/.

This is the FreeSurfer half of the pipeline in mri_processing.py, split out on its
own so it can change independently of the hippocampus step (hippocampus_pipeline.py).
run_pipeline.py chains the two together, running this one first.

    nohup python3 freesurfer_pipeline.py /data > freesurfer.log 2>&1 &
"""
from pathlib import Path
import multiprocessing as mp
import os
import argparse
import subprocess
import time
import socket
from functools import partial

from pipeline_common import setup_logger, find_nii_paths, freesurfer_dir_for


def process_subject_freesurfer(subject_path, logger):
    """
    Run recon-all for a single subject.

    Args:
        subject_path (Path): Path to the .nii file to process
        logger (Logger): Logger object for logging messages

    Returns:
        dict: subject, fs_success, fs_time, fs_path (the SUBJECTS_DIR holding this
              subject's recon-all output, needed by the hippocampus step)
    """
    subject = subject_path.stem
    fs_path = freesurfer_dir_for(subject_path)
    fs_path.mkdir(exist_ok=True)

    result = {'subject': subject, 'fs_success': False, 'fs_time': 0, 'fs_path': fs_path}

    fs_cmd = f'recon-all -i {subject_path} -subjid {subject} -sd {fs_path} -all'
    logger.info(f"Running FreeSurfer: {fs_cmd}")

    start = time.time()
    return_code = subprocess.run(fs_cmd, shell=True).returncode
    result['fs_time'] = time.time() - start
    result['fs_success'] = return_code == 0

    if result['fs_success']:
        logger.info(f"FreeSurfer processing for {subject} completed successfully in {result['fs_time']:.2f} seconds")
    else:
        logger.error(f"FreeSurfer processing for {subject} failed with return code {return_code}")

    return result


def run_freesurfer_pipeline(directory, cores, logger):
    """Find every anat/*.nii under `directory` and run recon-all across them in parallel."""
    nii_paths = find_nii_paths(directory)
    logger.info(f"Found {len(nii_paths)} .nii files for FreeSurfer processing")

    pool = mp.Pool(processes=cores)
    process_func = partial(process_subject_freesurfer, logger=logger)
    results = pool.map(process_func, nii_paths)
    pool.close()
    pool.join()

    return results


def main():
    parser = argparse.ArgumentParser(description='Run FreeSurfer recon-all across subjects.')
    parser.add_argument('directory', type=str, help='Path to the BIDS directory.')
    args = parser.parse_args()

    container_name = os.getenv('CONTAINER_NAME', socket.gethostname())
    cores = int(os.getenv('CPU_CORES', 1))

    log_dir = Path(args.directory) / 'fs_logs'
    logger = setup_logger('freesurfer_pipeline', log_dir / f'{container_name}.log')

    logger.info(f"Starting FreeSurfer processing with {cores} cores")
    results = run_freesurfer_pipeline(args.directory, cores, logger)

    total = len(results)
    success = sum(1 for r in results if r['fs_success'])
    failed = [r['subject'] for r in results if not r['fs_success']]
    total_time = sum(r['fs_time'] for r in results)

    logger.info("=== FREESURFER SUMMARY ===")
    logger.info(f"FreeSurfer successful: {success}/{total}")
    if failed:
        logger.info(f"Failed subjects: {', '.join(failed)}")
    logger.info(f"Total FreeSurfer processing time: {total_time:.2f} seconds")
    if total > 0:
        logger.info(f"Average FreeSurfer time per subject: {total_time/total:.2f} seconds")
    logger.info("=== FREESURFER PROCESSING COMPLETE ===")


if __name__ == '__main__':
    main()
