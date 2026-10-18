"""
Combined FreeSurfer + hippocampus pipeline.

For each subject, runs freesurfer_pipeline.py's recon-all step immediately
followed by hippocampus_pipeline.py's segmentHA_T1.sh step, so each subject is
fully processed before starting the next one. Multiple subjects can still be
processed in parallel based on the CPU_CORES environment variable.

The two stages live in freesurfer_pipeline.py and hippocampus_pipeline.py so
either can change independently; this script only wires them together in the
right order (FreeSurfer, then hippocampus) and passes the right SUBJECTS_DIR
path between them.

    nohup python3 run_pipeline.py /data > processing.log 2>&1 &
"""
from pathlib import Path
import multiprocessing as mp
import os
import argparse
import socket
from functools import partial

from pipeline_common import setup_logger, find_nii_paths
from freesurfer_pipeline import process_subject_freesurfer
from hippocampus_pipeline import process_subject_hippocampus, run_hippocampus_pipeline


def process_subject_complete(subject_path, logger):
    """
    Process a single subject completely: FreeSurfer, then (if it succeeds) hippocampus.

    Args:
        subject_path (Path): Path to the .nii file to process
        logger (Logger): Logger object for logging messages

    Returns:
        dict: subject, fs_success, hc_success, fs_time, hc_time, total_time
    """
    subject = subject_path.stem
    logger.info(f"Starting complete processing for subject: {subject}")

    fs_result = process_subject_freesurfer(subject_path, logger)

    result = {
        'subject': subject,
        'fs_success': fs_result['fs_success'],
        'hc_success': False,
        'fs_time': fs_result['fs_time'],
        'hc_time': 0,
    }

    if fs_result['fs_success']:
        # fs_path is the SUBJECTS_DIR that recon-all just wrote `subject` into -
        # pass it straight through so the hippocampus step targets the same directory.
        hc_result = process_subject_hippocampus(subject, fs_result['fs_path'], logger)
        result['hc_success'] = hc_result['hc_success']
        result['hc_time'] = hc_result['hc_time']
    else:
        logger.error(f"Skipping hippocampus segmentation for {subject} due to FreeSurfer failure")

    result['total_time'] = result['fs_time'] + result['hc_time']
    logger.info(f"Complete processing for {subject} finished in {result['total_time']:.2f} seconds")
    return result


def main():
    parser = argparse.ArgumentParser(description='Run FreeSurfer then hippocampus segmentation for each subject.')
    parser.add_argument('directory', type=str, help='Path to the BIDS directory.')
    parser.add_argument('--hc-only', action='store_true', help='Run only the hippocampus segmentation step on existing FreeSurfer results.')
    args = parser.parse_args()

    container_name = os.getenv('CONTAINER_NAME', socket.gethostname())
    cores = int(os.getenv('CPU_CORES', 1))

    log_dir = Path(args.directory) / 'fs_logs'
    logger = setup_logger('run_pipeline', log_dir / f'{container_name}.log')

    logger.info(f"Starting MRI processing with {cores} cores")

    if args.hc_only:
        logger.info("=== RUNNING HIPPOCAMPUS SEGMENTATION ONLY ===")
        results = run_hippocampus_pipeline(args.directory, logger)
    else:
        logger.info("=== STARTING COMPLETE SUBJECT PROCESSING ===")
        nii_paths = find_nii_paths(args.directory)
        logger.info(f"Found {len(nii_paths)} .nii files for processing")

        pool = mp.Pool(processes=cores)
        process_func = partial(process_subject_complete, logger=logger)
        results = pool.map(process_func, nii_paths)
        pool.close()
        pool.join()

    total_subjects = len(results)
    hc_success_count = sum(1 for r in results if r['hc_success'])
    failed_hc = [r['subject'] for r in results if not r['hc_success']] if args.hc_only \
        else [r['subject'] for r in results if r['fs_success'] and not r['hc_success']]
    total_hc_time = sum(r['hc_time'] for r in results)

    logger.info("=== PROCESSING SUMMARY ===")
    logger.info(f"Total subjects processed: {total_subjects}")

    if not args.hc_only:
        fs_success_count = sum(1 for r in results if r['fs_success'])
        failed_fs = [r['subject'] for r in results if not r['fs_success']]
        total_fs_time = sum(r['fs_time'] for r in results)
        total_time = sum(r['total_time'] for r in results)

        logger.info(f"FreeSurfer successful: {fs_success_count}/{total_subjects}")
        if failed_fs:
            logger.info(f"Failed FreeSurfer subjects: {', '.join(failed_fs)}")
        logger.info(f"Total FreeSurfer processing time: {total_fs_time:.2f} seconds")
        if total_subjects > 0:
            logger.info(f"Average FreeSurfer time per subject: {total_fs_time/total_subjects:.2f} seconds")

        logger.info(f"Hippocampus segmentation successful: {hc_success_count}/{fs_success_count}")
        if failed_hc:
            logger.info(f"Failed hippocampus subjects: {', '.join(failed_hc)}")
        logger.info(f"Total hippocampus segmentation time: {total_hc_time:.2f} seconds")
        if fs_success_count > 0:
            logger.info(f"Average hippocampus time per subject: {total_hc_time/fs_success_count:.2f} seconds")

        logger.info(f"Total processing time: {total_time:.2f} seconds")
        if total_subjects > 0:
            logger.info(f"Average total time per subject: {total_time/total_subjects:.2f} seconds")
    else:
        logger.info(f"Hippocampus segmentation successful: {hc_success_count}/{total_subjects}")
        if failed_hc:
            logger.info(f"Failed hippocampus subjects: {', '.join(failed_hc)}")
        logger.info(f"Total hippocampus segmentation time: {total_hc_time:.2f} seconds")
        if total_subjects > 0:
            logger.info(f"Average hippocampus time per subject: {total_hc_time/total_subjects:.2f} seconds")

    logger.info("=== MRI PROCESSING COMPLETE ===")


if __name__ == '__main__':
    main()
