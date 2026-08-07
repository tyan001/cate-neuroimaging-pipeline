from pathlib import Path
import multiprocessing as mp
import os
import argparse
import time
import logging
import socket
from functools import partial


"""
    Subject-by-Subject Complete Processing:

    Each subject now undergoes FreeSurfer processing immediately followed by hippocampal segmentation
    This ensures each subject is fully processed before starting the next one
    Multiple subjects can still be processed in parallel based on the number of cores


    Simplified Command-Line Options:

    Default mode: Complete processing for each subject
    --hc-only: Only run hippocampal segmentation on existing FreeSurfer results                                                                             


    Improved Logging:

    Each subject's full progress is logged together
    Clear processing times for each step and total time per subject
    -----------------------------------------------------------------------
    How It Works

    The script finds all .nii files in the specified directory structure.
    For each subject:

    Runs FreeSurfer processing
    If FreeSurfer succeeds, immediately runs hippocampal segmentation
    Records timing and success status for both steps


    Multiple subjects can be processed in parallel (based on CPU_CORES environment variable), but each individual subject's processing is sequential (FreeSurfer then hippocampus).

    
    nohup python3 mri_processing.py data/ADRC/ > processing.log 2>&1 &
    """

def setup_logger(log_file):
    """Set up a logger that writes to both console and file."""
    log_dir = log_file.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("mri_processing")
    logger.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(log_file)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

def find_nii_paths(root_dir):
    """
    Find all .nii files located in 'anat' folders within the given directory structure.

    This function traverses through a directory structure that follows the pattern:
    root_dir/subjectID/Session/anat/*.nii

    Args:
        root_dir (str): The path to the root directory to start the search from.

    Returns:
        list: A list of Path objects, where each is the full path to a .nii file
              found in an 'anat' folder.
    """
    root_path = Path(root_dir)
    nii_files = []
    
    # Walk through the directory structure
    for path in root_path.rglob('*'):
        # Check if we're in an 'anat' folder
        if path.parent.name == 'anat' and path.suffix == '.nii':
            nii_files.append(path)
    
    return nii_files

def process_subject_complete(subject_path, logger):
    """
    Process a single subject completely - first FreeSurfer, then hippocampus segmentation.
    
    Args:
        subject_path (Path): Path to the .nii file to process
        logger (Logger): Logger object for logging messages
        
    Returns:
        dict: Dictionary containing processing results and timings
    """
    subject = subject_path.stem
    result = {
        'subject': subject,
        'fs_success': False,
        'hc_success': False,
        'fs_time': 0,
        'hc_time': 0,
        'total_time': 0
    }
    
    start_total = time.time()
    logger.info(f"Starting complete processing for subject: {subject}")
    
    # Step 1: FreeSurfer processing
    fs_start = time.time()
    fs_path = subject_path.parent.parent / 'freesurfer741'
    fs_path.mkdir(exist_ok=True)
    fs_subject_dir = fs_path / subject
    
    # Build and execute the recon-all command
    fs_cmd = f'recon-all -i {subject_path} -subjid {subject} -sd {fs_path} -all'
    logger.info(f"Running FreeSurfer: {fs_cmd}")
    
    fs_return_code = os.system(fs_cmd)
    fs_end = time.time()
    
    result['fs_success'] = fs_return_code == 0
    result['fs_time'] = fs_end - fs_start
    
    if result['fs_success']:
        logger.info(f"FreeSurfer processing for {subject} completed successfully in {result['fs_time']:.2f} seconds")
        
        # Step 2: Hippocampus segmentation (only if FreeSurfer was successful)
        hc_start = time.time()
        
        # Build and execute the hippocampus segmentation command
        hc_cmd = f'segmentHA_T1.sh {subject} {fs_path}'
        logger.info(f"Running Hippocampus segmentation: {hc_cmd}")
        
        hc_return_code = os.system(hc_cmd)
        hc_end = time.time()
        
        result['hc_success'] = hc_return_code == 0
        result['hc_time'] = hc_end - hc_start
        
        if result['hc_success']:
            logger.info(f"Hippocampus segmentation for {subject} completed successfully in {result['hc_time']:.2f} seconds")
        else:
            logger.error(f"Hippocampus segmentation for {subject} failed with return code {hc_return_code}")
    else:
        logger.error(f"FreeSurfer processing for {subject} failed with return code {fs_return_code}")
        logger.error(f"Skipping hippocampus segmentation for {subject} due to FreeSurfer failure")
    
    end_total = time.time()
    result['total_time'] = end_total - start_total
    
    logger.info(f"Complete processing for {subject} finished in {result['total_time']:.2f} seconds")
    return result

def process_existing_subjects(root_dir, logger):
    """
    Find existing FreeSurfer directories and process them with hippocampus segmentation.
    
    Args:
        root_dir (str): The root directory to search for FreeSurfer directories
        logger (Logger): Logger object for logging messages
        
    Returns:
        list: List of processing results
    """
    results = []
    
    # Find existing FreeSurfer directories
    fs_dirs = [p for p in Path(root_dir).glob("*/*/freesurfer741/*") 
              if p.is_dir() and p.name != 'fsaverage']
    
    logger.info(f"Found {len(fs_dirs)} existing FreeSurfer directories")
    
    for fs_dir in fs_dirs:
        subject = fs_dir.stem
        result = {
            'subject': subject,
            'fs_success': True,  # Assuming existing directory means success
            'hc_success': False,
            'fs_time': 0,
            'hc_time': 0,
            'total_time': 0
        }
        
        # Process with hippocampus segmentation
        start_time = time.time()
        hc_cmd = f'segmentHA_T1.sh {subject} {fs_dir.parent}'
        logger.info(f"Running Hippocampus segmentation: {hc_cmd}")
        
        hc_return_code = os.system(hc_cmd)
        end_time = time.time()
        
        result['hc_success'] = hc_return_code == 0
        result['hc_time'] = end_time - start_time
        result['total_time'] = result['hc_time']
        
        if result['hc_success']:
            logger.info(f"Hippocampus segmentation for {subject} completed successfully in {result['hc_time']:.2f} seconds")
        else:
            logger.error(f"Hippocampus segmentation for {subject} failed with return code {hc_return_code}")
        
        results.append(result)
    
    return results

def main():
    parser = argparse.ArgumentParser(description='Process MRI data using FreeSurfer and Hippocampus segmentation.')
    parser.add_argument('directory', type=str, help='Path to the BIDS directory.')
    parser.add_argument('--hc-only', action='store_true', help='Run only the Hippocampus segmentation step on existing FreeSurfer results.')
    args = parser.parse_args()
    
    # Set up environment
    container_name = os.getenv('CONTAINER_NAME', socket.gethostname())
    cores = int(os.getenv('CPU_CORES', 1))
    
    # Configure logging
    log_dir = Path(args.directory) / 'fs_logs'
    log_file = log_dir / f'{container_name}.log'
    global logger
    logger = setup_logger(log_file)
    
    logger.info(f"Starting MRI processing with {cores} cores")
    logger.info(f"Log file: {log_file}")
    
    if args.hc_only:
        # Only run hippocampus segmentation on existing FreeSurfer results
        logger.info("=== RUNNING HIPPOCAMPUS SEGMENTATION ONLY ===")
        results = process_existing_subjects(args.directory, logger)
    else:
        # Run complete processing for each subject (FreeSurfer followed by hippocampus)
        logger.info("=== STARTING COMPLETE SUBJECT PROCESSING ===")
        
        # Find all .nii files
        nii_paths = find_nii_paths(args.directory)
        logger.info(f"Found {len(nii_paths)} .nii files for processing")
        
        # Process each subject completely
        pool = mp.Pool(processes=cores)
        process_func = partial(process_subject_complete, logger=logger)
        results = pool.map(process_func, nii_paths)
        pool.close()
        pool.join()
    
    # Generate summary statistics
    total_subjects = len(results)
    fs_success_count = sum(1 for r in results if r['fs_success'])
    hc_success_count = sum(1 for r in results if r['hc_success'])
    
    total_fs_time = sum(r['fs_time'] for r in results)
    total_hc_time = sum(r['hc_time'] for r in results)
    total_time = sum(r['total_time'] for r in results)
    
    failed_fs = [r['subject'] for r in results if not r['fs_success']]
    failed_hc = [r['subject'] for r in results if r['fs_success'] and not r['hc_success']]
    
    # Log summary
    logger.info("=== PROCESSING SUMMARY ===")
    logger.info(f"Total subjects processed: {total_subjects}")
    
    if not args.hc_only:
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
    
    logger.info("=== MRI PROCESSING COMPLETE ===")

if __name__ == '__main__':
    main()