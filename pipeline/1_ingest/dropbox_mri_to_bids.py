import re
import shutil
import logging
from pathlib import Path
import argparse
import os
from datetime import datetime

"""
MRI Folder Structure Reorganizer

This script reorganizes MRI scan folders into a standardized directory structure.
It parses folder names in the format MRI_subjID-session_MMDDYYYY to extract
subject IDs and scandates, then organizes files by subject with proper anatomical
and modality directories.

Added logging functionality to track all file operations.

Usage:
    python script_name.py /path/to/source_dir [--target_dir /path/to/output]
    example: python3 dropbox_mri_to_bids.py /batch/MRI
    
    If target_dir is not specified, it will create a sibling directory to source_dir
    named "[source_dir]_organized" (e.g., /batch/MRI_organized)

Input files structure:

📦/batch/MRI (/path/to/source_dir)
 ┣ 📂MRI_subjid01-session_MMDDYYYY
 ┃ ┣ 📜subjid01-session_MMDDYYYY.Cor_MPRAGE.nii
 ┃ ┣ 📜subjid01-session_MMDDYYYY.T1.nii
 ┃ ┣ 📜(Other files and modalities)
 ┣ 📂MRI_subjid02-session_MMDDYYYY
 ┃ ┣ 📜subjid02-session_MMDDYYYY.Cor_MPRAGE.nii
 ┃ ┣ 📜subjid02-session_MMDDYYYY.T1.nii
 ┃ ┣ 📜(Other files and modalities)

Each subject's data will be organized as:

batch/📦ADRC (/path/to/output)/ADRC
┣ 📂subjid01
┃ ┣ 📂YYYYMMDD
┃ ┃ ┣ 📂anat
┃ ┃ ┃ ┗ 📜subjid01-YYYYMMDD_T1w.nii or subjid01-YYYYMMDD_CorMPRAGE.nii (CorMPRAGE is the fallback if T1 don't exist)
┃ ┃ ┗ 📂modalities
┃ ┃ ┃ ┣ 📜[all original files]
┣ 📂subjid02
┃ ┣ 📂YYYYMMDD
┃ ┃ ┣ 📂anat
┃ ┃ ┃ ┗ 📜subjid02-YYYYMMDD_T1w.nii or subjid02-YYYYMMDD_CorMPRAGE.nii
┃ ┃ ┗ 📂modalities
┃ ┃ ┃ ┣ 📜[all original files]
"""

def setup_logging(target_dir):
    """
    Set up logging to file and console
    
    Args:
        target_dir (str): The target directory where the log file will be created
        
    Returns:
        logging.Logger: Configured logger
    """
    log_dir = Path(f"{target_dir}/logs/mri_bids_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    target_name = Path(target_dir).name
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"mri_bids_{target_name}_{timestamp}.log"
    
    # Configure logger
    logger = logging.getLogger("MRIReorganizer")
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
    Parse a medical scan folder name in the format: MRI_subjID-session_MMDDYYYY
    
    Args:
        folder_name (str): The folder name to parse
        logger (logging.Logger): Logger to track operations
        
    Returns:
        tuple or None: A tuple of (subject_id, scandate) if parsing succeeds,
                      None otherwise
                      
    Examples:
        >>> parse_folder_name("MRI_ADRC-01_01022023", logger)
        ('ADRC', '20230102')
    """
    
    
    # Regex pattern breakdown:
    # MRI_           - Literal "MRI_" prefix
    # (.*?)          - Group 1: Subject ID (non-greedy match of any chars)
    # (?:            - Start non-capturing group (optional session part)
    #   -            - Literal hyphen
    #   ([A-Za-z0-9]+) - Group 2: Session ID (letters/numbers)
    # )?             - End optional group (session may not exist)
    # _              - Literal underscore
    # (\d{2})        - Group 3: Month (exactly 2 digits)
    # (\d{2})        - Group 4: Day (exactly 2 digits)  
    # (\d{4})        - Group 5: Year (exactly 4 digits)
    #
    # Matches: MRI_110001-01_01022023 OR MRI_110001_01022023
    pattern = r"MRI_(.*?)(?:-([A-Za-z0-9]+))?_(\d{2})(\d{2})(\d{4})"
    # pattern = r"MRI_(.*?)-([A-Za-z0-9]+)_(\d{2})(\d{2})(\d{4})"
    match = re.match(pattern, folder_name)
    
    if not match:
        logger.warning(f"Failed to parse folder name: {folder_name}")
        return None
    
    subj_base, session, month, day, year = match.groups()
    subject_id = f"{subj_base}"
    scandate = f"{year}{month}{day}"

    logger.info(f"Parsed folder '{folder_name}' to subject_id='{subject_id}', session='{session}', scandate='{scandate}'")
    return (subject_id, scandate)


def get_modality_from_filename(filename, logger):
    """
    Extract the modality from a .nii filename
    
    Args:
        filename (str): The filename to extract modality from
        logger (logging.Logger): Logger to track operations
        
    Returns:
        str or None: The modality if found, None otherwise
    """
    pattern = r".*\.(.*)\.nii"
    match = re.match(pattern, filename)
    
    if match:
        modality = match.group(1)
        logger.debug(f"Extracted modality '{modality}' from filename '{filename}'")
        return modality
    
    logger.warning(f"Could not extract modality from filename '{filename}'")
    return None


def restructure_files(source_dir, target_dir, logger):
    """
    Restructure medical scan files into a standardized directory structure
    based on folder names.
    
    Args:
        source_dir (str): Path to the source directory containing medical scan folders
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
    
    # Get all immediate subfolders that match the MRI_* pattern
    subfolders = [f for f in source_path.iterdir() if f.is_dir() and f.name.startswith("MRI_")]
    if not subfolders:
        logger.warning(f"No MRI_* subfolders found in {source_dir}")
        return {}
    
    logger.info(f"Found {len(subfolders)} MRI_* subfolders in {source_dir}")
        
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
            total_subjects[subject_id] = {'folders': [], 'T1': None, 'Cor_MPRAGE': None}
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
    subj_anat_dir = subj_scandate_dir / "anat"
    subj_modalities_dir = subj_scandate_dir / "modalities" 
    
    # Create directories with proper parent directories first
    subj_dir.mkdir(exist_ok=True)
    subj_scandate_dir.mkdir(exist_ok=True)
    subj_anat_dir.mkdir(exist_ok=True)
    subj_modalities_dir.mkdir(exist_ok=True)
    
    logger.info(f"Created directory structure for {subject_id}/{scandate}")
    
    # Copy files to modalities directory
    file_copy_count = 0
    try:
        if list(subj_modalities_dir.iterdir()) == []:  # Only copy if directory is empty
            for item in folder_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, subj_modalities_dir / item.name)
                    logger.info(f"COPIED: {item} -> {subj_modalities_dir / item.name}")
                    file_copy_count += 1
                elif item.is_dir():
                    subdir_path = subj_modalities_dir / item.name
                    shutil.copytree(item, subdir_path)
                    subdir_files = list(Path(subdir_path).glob('**/*.*'))
                    logger.info(f"COPIED DIRECTORY: {item} -> {subdir_path} ({len(subdir_files)} files)")
                    file_copy_count += len(subdir_files)
            logger.info(f"Copied {file_copy_count} files to {subj_modalities_dir}")
        else:
            logger.warning(f"Directory {subj_modalities_dir} not empty. Skipping copy.")
    except Exception as e:
        logger.error(f"Error copying files to modalities directory: {e}")
    
    # Find T1 and Cor_MPRAGE files
    for file_path in nii_files:
        modality = get_modality_from_filename(file_path.name, logger)
        if not modality:
            continue
        
        # Track T1 and Cor_MPRAGE files
        if modality.lower() == "t1" and not subjects_dict[subject_id]['T1']:
            subjects_dict[subject_id]['T1'] = (file_path, scandate, modality)
            logger.info(f"Found T1 file for {subject_id}: {file_path}")
        elif modality.lower() == "cor_mprage" and not subjects_dict[subject_id]['Cor_MPRAGE']:
            subjects_dict[subject_id]['Cor_MPRAGE'] = (file_path, scandate, modality)
            logger.info(f"Found Cor_MPRAGE file for {subject_id}: {file_path}")
    
    # Process anat directory
    anat_file = subjects_dict[subject_id]['T1'] if subjects_dict[subject_id]['T1'] else subjects_dict[subject_id]['Cor_MPRAGE']
    if anat_file:
        file_path, file_scandate, modality = anat_file
        
        # Apply standardized modality name
        new_modality = "T1w" if modality.lower() == "t1" else "CorMPRAGE"
        new_filename = f"{subject_id}-{file_scandate}_{new_modality}.nii"
        
        # Copy to anat directory
        target_anat_file = subj_anat_dir / new_filename
        try:
            shutil.copy2(file_path, target_anat_file)
            used_type = "T1" if modality.lower() == "t1" else "Cor_MPRAGE"
            logger.info(f"RENAMED: {file_path} -> {target_anat_file} (used {used_type})")
        except Exception as e:
            logger.error(f"Error copying anat file: {e}")
    else:
        logger.warning(f"No T1 or Cor_MPRAGE file found for subject {subject_id}")


def main():
    """
    Main entry point for the script.
    
    Parses command-line arguments and initiates the file restructuring process.
    """
    parser = argparse.ArgumentParser(description="Restructure medical scan files based on folder names")
    parser.add_argument("source_dir", help="Source directory containing MRI_* folders")
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
    logger.info(f"Starting MRI reorganization from {args.source_dir} to {args.target_dir}")
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