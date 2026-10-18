import argparse
from pathlib import Path
from datetime import datetime
import logging
import sys

def setup_logger(log_file=None):
    """
    Set up logger with both stream and file handlers.
    
    This function creates a logger that outputs messages to both console and optionally
    to a file. Console output is formatted without timestamps, while file output includes
    just the message for cleaner logs.
    
    Args:
        log_file (str, optional): Path to log file. If None, only console logging is set up.
        
    Returns:
        logging.Logger: Configured logger instance with appropriate handlers.
    """
    # Create logger
    logger = logging.getLogger('freesurfer_check')
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers (to avoid duplicate logs)
    logger.handlers.clear()
    
    # Create formatters
    console_formatter = logging.Formatter('%(message)s')  # No timestamp for console
    file_formatter = logging.Formatter('%(message)s')  # No timestamp for file either
    
    # Create and add stream handler (console output)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(console_formatter)
    logger.addHandler(stream_handler)
    
    # Create and add file handler if log file specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger

def find_adrc_folders(base_dir):
    """
    Find all ADRC folders recursively within the specified base directory.

    This function searches through all subdirectories of the base directory to locate
    folders named 'ADRC'. The search is case-sensitive and will only match exact
    'ADRC' folder names.

    Args:
        base_dir (str or Path): The base directory to start the recursive search.

    Returns:
        list: List of Path objects pointing to found ADRC folders.
        
    """
    base_path = Path(base_dir)
    adrc_folders = sorted(base_path.glob('**/ADRC'))
    return adrc_folders

def get_subject_scan_dirs(adrc_dir):
    """
    Get all subject/scan directories within an ADRC directory.

    This function finds all directories that follow the expected structure of
    subject_id/scan_date within an ADRC directory. It only returns directories
    that match this exact depth pattern.

    Args:
        adrc_dir (Path): The ADRC directory to search for subject/scan directories.

    Returns:
        list: List of Path objects for directories matching the subject/scan pattern.
        
    """
    subject_scan_dirs = list(adrc_dir.glob('*/*'))
    return [d for d in subject_scan_dirs if d.is_dir() and len(d.parts) == len(adrc_dir.parts) + 2]

def check_incomplete_processing(adrc_dir):
    """
    Check for subjects with incomplete FreeSurfer or hippocampal processing.

    This function examines each subject/scan directory for four potential issues:
    1. Missing anat directory
    2. Missing freesurfer741 directory (only checked if anat exists)
    3. Presence of recon-all.error file indicating failed FreeSurfer processing
    4. Missing or incomplete hippocampal processing (checks for "Everything done!" in log)

    📦ADRC
    ┣ 📂900001
    ┃ ┗ 📂20200115101346
    ┃ ┃ ┣ 📂anat <--- [1] Check this first
    ┃ ┃ ┃ ┗ 📜900001-20200115_T1w.nii
    ┃ ┃ ┗ 📂freesurfer741 <--- [2] Only check if anat exists
    ┃ ┃ ┃ ┣ 📂900001-20200115_T1w
    ┃ ┃ ┃ ┃ ┗ 📜scripts
    ┃ ┃ ┃ ┃   ┗ 📜recon-all.error <--- [3]
    ┃ ┃ ┃ ┃   ┗ 📜hippocampal-subfields-T1.log <--- [4]
    
    Args:
        adrc_dir (Path): The ADRC directory containing subject/scan subdirectories.

    Returns:
        tuple: Four lists containing subject paths with different incomplete states:
            - List of subjects missing anat directory
            - List of subjects missing freesurfer741 directory
            - List of subjects with FreeSurfer errors
            - List of subjects with missing or incomplete hippocampal processing
    """
    subject_scan_dirs = get_subject_scan_dirs(adrc_dir)
    
    no_anat = []
    no_freesurfer = []
    incomplete_recon = []
    incomplete_hippo = []
    
    for subject_scan_dir in subject_scan_dirs:
        subject_name = subject_scan_dir.parts[-2]
        scan_date = subject_scan_dir.parts[-1]
        subject_path = f"{subject_name}/{scan_date}"
        
        # Check if anat directory exists
        anat_dir = subject_scan_dir / 'anat'
        if not anat_dir.exists():
            no_anat.append(subject_path)
            continue
        
        # Only check for freesurfer741 if anat exists
        freesurfer_dir = subject_scan_dir / 'freesurfer741'
        if not freesurfer_dir.exists():
            no_freesurfer.append(subject_path)
            continue
        
        # Check for recon-all.error and hippocampal log
        error_files = list(freesurfer_dir.glob('*/scripts/recon-all.error'))
        hippo_files = list(freesurfer_dir.glob('*/scripts/hippocampal-subfields-T1.log'))
        
        if error_files:
            incomplete_recon.append(subject_path)
            
        # Check hippocampal processing status
        if not hippo_files:
            incomplete_hippo.append(subject_path)
        else:
            # Check the content of hippocampal log for completion marker
            try:
                with open(hippo_files[0], 'r') as f:
                    # Read last 1000 characters to check for completion marker
                    f.seek(0, 2)  # Seek to end
                    file_size = f.tell()
                    seek_pos = max(0, file_size - 1000)
                    f.seek(seek_pos)
                    end_content = f.read()
                    
                    if "Everything done!" not in end_content:
                        incomplete_hippo.append(subject_path)
            except Exception as e:
                # If we can't read the file, consider it incomplete
                incomplete_hippo.append(subject_path)
                logging.warning(f"Error reading hippocampal log for {subject_path}: {str(e)}")
            
    return no_anat, no_freesurfer, incomplete_recon, incomplete_hippo

def main(base_dir, log_file=None):
    """
    Main function to identify and report incomplete FreeSurfer processing in ADRC folders.

    This function performs a comprehensive check of all ADRC folders under the specified
    base directory, identifying subjects with various types of incomplete processing and
    generating a detailed report.

    Args:
        base_dir (str or Path): The base directory to start searching for ADRC folders.
        log_file (str, optional): Path to save the log file. If None, only console output is generated.

    """
    # Set up logger
    logger = setup_logger(log_file)
    
    # Log initial information
    logger.info(f"FreeSurfer Processing Status Check")
    logger.info(f"Base Directory: {base_dir}\n")
    
    adrc_folders = find_adrc_folders(base_dir)
    
    if not adrc_folders:
        logger.info("No ADRC folders found.")
        return

    found_incomplete = False
    
    for adrc_folder in adrc_folders:
        no_anat, no_freesurfer, incomplete_recon, incomplete_hippo = check_incomplete_processing(adrc_folder)
        
        if no_anat or no_freesurfer or incomplete_recon or incomplete_hippo:
            found_incomplete = True
            logger.info(f"\nIncomplete processing in ADRC folder: {adrc_folder}")
            
            # if no_anat:
            #     no_anat = sorted(no_anat)
            #     logger.info("\nSubjects missing anat folder:")
            #     for subject_path in no_anat:
            #         logger.info(f"- {subject_path}")
            #     logger.info(f"Total subjects missing anat folder: {len(no_anat)}")
            
            if no_freesurfer:
                no_freesurfer = sorted(no_freesurfer)
                logger.info("\nSubjects with anat but missing freesurfer741 folder:")
                for subject_path in no_freesurfer:
                    logger.info(f"- {subject_path}")
                logger.info(f"Total subjects with anat but missing freesurfer741: {len(no_freesurfer)}")
            
            if incomplete_recon:
                incomplete_recon = sorted(incomplete_recon)
                logger.info("\nSubjects with FreeSurfer errors:")
                for subject_path in incomplete_recon:
                    logger.info(f"- {subject_path}")
                logger.info(f"Total subjects with FreeSurfer errors: {len(incomplete_recon)}")
            
            if incomplete_hippo:
                incomplete_hippo = sorted(incomplete_hippo)
                logger.info("\nSubjects missing hippocampal processing:")
                for subject_path in incomplete_hippo:
                    logger.info(f"- {subject_path}")
                logger.info(f"Total subjects missing hippocampal processing: {len(incomplete_hippo)}")
    
    if not found_incomplete:
        logger.info("\nAll subjects have completed processing in all ADRC folders.")

if __name__ == "__main__":
    
    """
        Example usage:
            python check_missing_processing.py /data_folder --log /data/logs/freesurfer_check.log
        
        This script will search for ADRC folders under /data_folder and check for incomplete
        FreeSurfer processing in all subjects. The results will be printed to console and
        saved to /data/logs/freesurfer_check.log.
            
    """
    
    
    parser = argparse.ArgumentParser(
        description="Find subjects with incomplete processing in ADRC folders."
    )
    parser.add_argument(
        "base_dir", 
        help="Base directory to start searching for ADRC folders"
    )
    parser.add_argument(
        "--log",
        help="Path to save the log file",
        default=None
    )
    args = parser.parse_args()
    
    main(args.base_dir, args.log)