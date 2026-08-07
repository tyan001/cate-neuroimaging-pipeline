import re
import shutil
import logging
from pathlib import Path
import argparse
import os
from datetime import datetime

"""
PET Folder Structure Reorganizer

This script reorganizes PET scan folders into a standardized directory structure.
It parses folder names in the format PET_subjID-session_MMDDYYYY to extract
subject IDs and scandates, then organizes files by subject with proper PET and CT
directories.

Added logging functionality to track all file operations.

Usage:
    python script_name.py /path/to/source_dir --target_dir /path/to/output
    example: python3 dropbox_pet_to_bids.py /batch/PET --target_dir batch/
    
    If target_dir is not specified, it will create a sibling directory to source_dir
    named "[source_dir_parent]" (e.g., if source_dir is /batch/PET, target_dir will be /batch)

Input files structure:

📦/batch/PET (/path/to/source_dir)
 ┣ 📂PET_subjid01-session_MMDDYYYY
 ┃ ┣ 📜subjid01-session_MMDDYYYY_mean_5mmblur.nii
 ┃ ┣ 📜subjid01-session_MMDDYYYY.Amyloid_PET_CT.nii
 ┃ ┣ 📜(Other files)
 ┣ 📂PET_subjid02-session_MMDDYYYY
 ┃ ┣ 📜subjid02-session_MMDDYYYY_mean_5mmblur.nii
 ┃ ┣ 📜subjid02-session_MMDDYYYY.Amyloid_PET_CT.nii
 ┃ ┣ 📜(Other files)

Each subject's data will be organized as:

batch/📦ADRC (/path/to/output)/ADRC
┣ 📂subjid01
┃ ┣ 📂YYYYMMDD
┃ ┃ ┣ 📂pet
┃ ┃ ┃ ┗ 📜subjid01-YYYYMMDD_PET.nii
┃ ┃ ┣ 📂ct
┃ ┃ ┃ ┗ 📜subjid01-YYYYMMDD_CT.nii
┣ 📂subjid02
┃ ┣ 📂YYYYMMDD
┃ ┃ ┣ 📂pet
┃ ┃ ┃ ┗ 📜subjid02-YYYYMMDD_PET.nii
┃ ┃ ┣ 📂ct
┃ ┃ ┃ ┗ 📜subjid02-YYYYMMDD_CT.nii
"""

def setup_logging(target_dir):
    """
    Set up logging to file and console
    
    Args:
        target_dir (str): The target directory where the log file will be created
        
    Returns:
        logging.Logger: Configured logger
    """
    log_dir = Path(f"{target_dir}/logs/pet_bids_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    target_name = Path(target_dir).name
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"pet_bids_{target_name}_{timestamp}.log"
    
    # Configure logger
    logger = logging.getLogger("PETReorganizer")
    logger.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Format - without timestamps
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def parse_folder_name(folder_name, logger):
    """
    Parse a medical scan folder name in the format: PET_subjID-session_MMDDYYYY
    
    Args:
        folder_name (str): The folder name to parse
        logger (logging.Logger): Logger to track operations
        
    Returns:
        tuple or None: A tuple of (subject_id, scandate) if parsing succeeds,
                      None otherwise
                      
    Examples:
        >>> parse_folder_name("PET_ADRC-01_01022023", logger)
        ('ADRC', '20230102')
        >>> parse_folder_name("PET_ADRC-C1_01022023", logger)
        ('ADRC', '20230102')
    """
    pattern = r"PET_(.*?)-([A-Za-z0-9]+)_(\d{2})(\d{2})(\d{4})"
    match = re.match(pattern, folder_name)
    
    if not match:
        logger.warning(f"Failed to parse folder name: {folder_name}")
        return None
    
    subj_base, session, month, day, year = match.groups()
    subject_id = f"{subj_base}"
    scandate = f"{year}{month}{day}"
    
    logger.info(f"Parsed folder '{folder_name}' to subject_id='{subject_id}', session='{session}', scandate='{scandate}'")
    return (subject_id, scandate)


def is_pet_file(filename, logger):
    """
    Check if a filename is a PET scan file based on common patterns.
    
    Args:
        filename (str): The filename to check
        logger (logging.Logger): Logger to track operations
        
    Returns:
        bool: True if the file is a PET scan, False otherwise
    """
    pet_patterns = ["mean_5mmblur", "PET_6mmblur", "PET_3mmblur", "PET_256"]
    for pattern in pet_patterns:
        if pattern.lower() in filename.lower():
            logger.debug(f"Identified {filename} as a PET file (matches pattern '{pattern}')")
            return True
    return False


def is_ct_file(filename, logger):
    """
    Check if a filename is a CT scan file based on common patterns.
    
    Args:
        filename (str): The filename to check
        logger (logging.Logger): Logger to track operations
        
    Returns:
        bool: True if the file is a CT scan, False otherwise
    """
    ct_patterns = ["amyloid_pet_ct", "pet_ct"]
    for pattern in ct_patterns:
        if pattern.lower() in filename.lower():
            logger.debug(f"Identified {filename} as a CT file (matches pattern '{pattern}')")
            return True
    return False


def restructure_files(source_dir, target_dir, logger):
    """
    Restructure PET scan files into a standardized directory structure
    based on folder names.
    
    Args:
        source_dir (str): Path to the source directory containing PET_* folders
        target_dir (str): Path to the target directory where restructured files will be stored
        logger (logging.Logger): Logger to track operations
                                  
    Returns:
        dict: A dictionary mapping subject IDs to their file information
    """
    source_path = Path(source_dir)
    target_path = Path(target_dir)
    adrc_dir = target_path / "ADRC"
    adrc_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created ADRC directory: {adrc_dir}")
    
    # Get all immediate subfolders that match the PET_* pattern
    subfolders = [f for f in source_path.iterdir() if f.is_dir() and f.name.startswith("PET_")]
    if not subfolders:
        logger.warning(f"No PET_* subfolders found in {source_dir}")
        return {}
    
    logger.info(f"Found {len(subfolders)} PET_* subfolders in {source_dir}")
        
    total_subjects = {}
    # Process each subfolder
    for subfolder in subfolders:
        logger.info(f"Processing folder: {subfolder.name}")
        result = parse_folder_name(subfolder.name, logger)
        
        if not result:
            logger.warning(f"Could not parse folder name: {subfolder.name}. Skipping.")
            continue
            
        subject_id, scandate = result
        
        # Initialize subject entry if it doesn't exist
        if subject_id not in total_subjects:
            total_subjects[subject_id] = {'folders': [], 'PET': None, 'CT': None}
            logger.info(f"Added new subject: {subject_id}")
        
        # Store folder information
        total_subjects[subject_id]['folders'].append((subfolder, scandate))
        
        # Process files in the folder
        process_subject_folder(subfolder, subject_id, scandate, total_subjects, adrc_dir, logger)
    
    return total_subjects


def process_subject_folder(folder_path, subject_id, scandate, subjects_dict, adrc_dir, logger):
    """
    Process a single subject folder containing .nii files.
    
    Args:
        folder_path (Path): Path object pointing to the subject folder
        subject_id (str): The subject ID
        scandate (str): The parsed scandate string
        subjects_dict (dict): Dictionary of subject information
        adrc_dir (Path): Path object pointing to the target ADRC directory
        logger (logging.Logger): Logger to track operations
    """
    # Get all .nii files in the folder
    nii_files = list(folder_path.glob('**/*.nii'))
    logger.info(f"Found {len(nii_files)} .nii files in {folder_path}")
    
    # Create subject directory structure
    subj_dir = adrc_dir / subject_id
    subj_scandate_dir = subj_dir / scandate
    subj_pet_dir = subj_scandate_dir / "pet"
    subj_ct_dir = subj_scandate_dir / "ct"
    
    # Create directories with proper parent directories first
    subj_dir.mkdir(exist_ok=True)
    subj_scandate_dir.mkdir(exist_ok=True)
    subj_pet_dir.mkdir(exist_ok=True)
    subj_ct_dir.mkdir(exist_ok=True)
    
    logger.info(f"Created directory structure for {subject_id}/{scandate}")
    
    
    # Find PET and CT files
    for file_path in nii_files:
        filename = file_path.name
        logger.debug(f"Examining file: {filename}")
        
        # Check if file is a PET scan
        if not subjects_dict[subject_id]['PET'] and is_pet_file(filename, logger):
            subjects_dict[subject_id]['PET'] = (file_path, scandate)
            logger.info(f"Found PET file for {subject_id}: {file_path}")
                
        # Check if file is a CT scan
        if not subjects_dict[subject_id]['CT'] and is_ct_file(filename, logger):
            subjects_dict[subject_id]['CT'] = (file_path, scandate)
            logger.info(f"Found CT file for {subject_id}: {file_path}")
    
    # Process PET directory
    pet_file = subjects_dict[subject_id]['PET']
    if pet_file:
        file_path, file_scandate = pet_file
        
        # Apply standardized name
        new_filename = f"{subject_id}-{file_scandate}_PET.nii"
        
        # Copy to pet directory
        target_pet_file = subj_pet_dir / new_filename
        try:
            shutil.copy2(file_path, target_pet_file)
            logger.info(f"RENAMED: {file_path} -> {target_pet_file} (PET scan)")
        except Exception as e:
            logger.error(f"Error copying PET file: {e}")
    else:
        logger.warning(f"No PET file found for subject {subject_id}")
    
    # Process CT directory
    ct_file = subjects_dict[subject_id]['CT']
    if ct_file:
        file_path, file_scandate = ct_file
        
        # Apply standardized name
        new_filename = f"{subject_id}-{file_scandate}_CT.nii"
        
        # Copy to ct directory
        target_ct_file = subj_ct_dir / new_filename
        try:
            shutil.copy2(file_path, target_ct_file)
            logger.info(f"RENAMED: {file_path} -> {target_ct_file} (CT scan)")
        except Exception as e:
            logger.error(f"Error copying CT file: {e}")
    else:
        logger.warning(f"No CT file found for subject {subject_id}")


def main():
    """
    Main entry point for the script.
    
    Parses command-line arguments and initiates the file restructuring process.
    """
    parser = argparse.ArgumentParser(description="Restructure PET scan files based on folder names")
    parser.add_argument("source_dir", help="Source directory containing PET_* folders")
    parser.add_argument("--target_dir", help="Target directory for restructured files (default is sibling to source_dir)", default=None)
    args = parser.parse_args()
    
    
    # If target_dir is not specified, use a sibling directory to source_dir
    if args.target_dir is None:
        source_path = Path(args.source_dir)
        # Get parent directory of source_dir and create target_dir as a sibling
        args.target_dir = str(source_path.parent)
        print(f"No target directory specified. Using: {args.target_dir}")
    
    # Set up logging
    logger = setup_logging(args.target_dir)
    
    logger.info("=" * 80)
    logger.info(f"Starting PET reorganization from {args.source_dir} to {args.target_dir}")
    logger.info("=" * 80)
    
    subjects = restructure_files(args.source_dir, args.target_dir, logger)
    
    # Log summary information
    logger.info("=" * 80)
    logger.info(f"Reorganization complete!")
    logger.info(f"Processed {len(subjects)} subjects")
    if subjects:
        logger.info(f"Subject IDs: {', '.join(sorted(subjects.keys()))}")
    
    # Add file operations summary to log file
    logger.info("FILE OPERATIONS SUMMARY")
    logger.info(f"Source directory: {args.source_dir}")
    logger.info(f"Target directory: {args.target_dir}")
    logger.info(f"Subjects processed: {len(subjects)}")
    if subjects:
        logger.info(f"Subject IDs: {', '.join(sorted(subjects.keys()))}")
    
    logger.info("=" * 80)


if __name__ == "__main__":
    main()