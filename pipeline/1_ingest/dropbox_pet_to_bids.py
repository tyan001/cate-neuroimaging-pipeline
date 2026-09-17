import argparse
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

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

    # a delivery with a new PET/CT file name: add a substring for this run
    python3 dropbox_pet_to_bids.py /batch/PET --pet-pattern PET_200 --ct-pattern CT_Brain
    
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

# --------------------------------------------------------------------------- file patterns
# Case-insensitive substrings matched against each .nii filename. When a delivery names its
# files differently, add the new substring here (or pass --pet-pattern / --ct-pattern).
#
# Order is priority: if a session folder has several matching files, the one matching the
# earliest pattern is used. A file that matches a CT pattern is never taken as the PET.
PET_PATTERNS = [
    "mean_5mmblur",
    "PET_6mmblur",
    "PET_3mmblur",
    "PET_256",
    "PET_128",       # PET_128, PET_128a
]
CT_PATTERNS = [
    "amyloid_pet_ct",
    "pet_ct",
    "amyloid_ct",    # 900195-01_01012024.Amyloid_CT.nii
]


def matching_pattern(filename, patterns):
    """Index of the first pattern found in filename (case-insensitive), or None."""
    name = filename.lower()
    for i, pattern in enumerate(patterns):
        if pattern.lower() in name:
            return i
    return None


def best_match(files, patterns, exclude=()):
    """
    The file matching the highest-priority pattern, or None.

    Ties go to the file nearest the session folder, then to the first name alphabetically,
    so the choice doesn't depend on directory listing order.
    """
    ranked = []
    for path in files:
        rank = matching_pattern(path.name, patterns)
        if rank is not None and matching_pattern(path.name, exclude) is None:
            ranked.append((rank, len(path.parts), path.name, path))
    return min(ranked)[-1] if ranked else None


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


def is_pet_file(filename, logger, pet_patterns=None, ct_patterns=None):
    """
    Check if a filename is a PET scan file based on PET_PATTERNS.
    
    Args:
        filename (str): The filename to check
        logger (logging.Logger): Logger to track operations
        pet_patterns (list, optional): Substrings to use instead of PET_PATTERNS
        ct_patterns (list, optional): Substrings to use instead of CT_PATTERNS
        
    Returns:
        bool: True if the file is a PET scan (and not a CT), False otherwise
    """
    pet_patterns = PET_PATTERNS if pet_patterns is None else pet_patterns
    if is_ct_file(filename, logger, ct_patterns):
        return False
    rank = matching_pattern(filename, pet_patterns)
    if rank is None:
        return False
    logger.debug(f"Identified {filename} as a PET file (matches pattern '{pet_patterns[rank]}')")
    return True


def is_ct_file(filename, logger, ct_patterns=None):
    """
    Check if a filename is a CT scan file based on CT_PATTERNS.
    
    Args:
        filename (str): The filename to check
        logger (logging.Logger): Logger to track operations
        ct_patterns (list, optional): Substrings to use instead of CT_PATTERNS
        
    Returns:
        bool: True if the file is a CT scan, False otherwise
    """
    ct_patterns = CT_PATTERNS if ct_patterns is None else ct_patterns
    rank = matching_pattern(filename, ct_patterns)
    if rank is None:
        return False
    logger.debug(f"Identified {filename} as a CT file (matches pattern '{ct_patterns[rank]}')")
    return True


def restructure_files(source_dir, target_dir, logger, pet_patterns=None, ct_patterns=None):
    """
    Restructure PET scan files into a standardized directory structure
    based on folder names.
    
    Args:
        source_dir (str): Path to the source directory containing PET_* folders
        target_dir (str): Path to the target directory where restructured files will be stored
        logger (logging.Logger): Logger to track operations
        pet_patterns (list, optional): PET filename substrings, in priority order (default PET_PATTERNS)
        ct_patterns (list, optional): CT filename substrings, in priority order (default CT_PATTERNS)
                                  
    Returns:
        dict: A dictionary mapping subject IDs to their file information
    """
    pet_patterns = PET_PATTERNS if pet_patterns is None else pet_patterns
    ct_patterns = CT_PATTERNS if ct_patterns is None else ct_patterns
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
    logger.info(f"PET patterns: {', '.join(pet_patterns)}")
    logger.info(f"CT patterns: {', '.join(ct_patterns)}")
        
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
        process_subject_folder(subfolder, subject_id, scandate, total_subjects, adrc_dir, logger,
                               pet_patterns, ct_patterns)
    
    return total_subjects


def process_subject_folder(folder_path, subject_id, scandate, subjects_dict, adrc_dir, logger,
                           pet_patterns=None, ct_patterns=None):
    """
    Process a single subject folder containing .nii files.
    
    Args:
        folder_path (Path): Path object pointing to the subject folder
        subject_id (str): The subject ID
        scandate (str): The parsed scandate string
        subjects_dict (dict): Dictionary of subject information
        adrc_dir (Path): Path object pointing to the target ADRC directory
        logger (logging.Logger): Logger to track operations
        pet_patterns (list, optional): PET filename substrings, in priority order (default PET_PATTERNS)
        ct_patterns (list, optional): CT filename substrings, in priority order (default CT_PATTERNS)
    """
    pet_patterns = PET_PATTERNS if pet_patterns is None else pet_patterns
    ct_patterns = CT_PATTERNS if ct_patterns is None else ct_patterns

    # Get all .nii files in the folder
    nii_files = sorted(folder_path.glob('**/*.nii'))
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
    if not subjects_dict[subject_id]['PET']:
        pet_path = best_match(nii_files, pet_patterns, exclude=ct_patterns)
        if pet_path:
            subjects_dict[subject_id]['PET'] = (pet_path, scandate)
            logger.info(f"Found PET file for {subject_id}: {pet_path}")

    if not subjects_dict[subject_id]['CT']:
        ct_path = best_match(nii_files, ct_patterns)
        if ct_path:
            subjects_dict[subject_id]['CT'] = (ct_path, scandate)
            logger.info(f"Found CT file for {subject_id}: {ct_path}")
    
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
        log_unmatched(nii_files, "PET", logger)
    
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
        log_unmatched(nii_files, "CT", logger)


def log_unmatched(nii_files, kind, logger):
    """List the .nii files that were looked at, so a new naming scheme is easy to spot."""
    if not nii_files:
        return
    names = ", ".join(p.name for p in nii_files)
    flag = "--pet-pattern" if kind == "PET" else "--ct-pattern"
    logger.warning(f"  .nii files in folder: {names}")
    logger.warning(f"  If one of these is the {kind}, add a substring of its name with {flag} "
                   f"or to {kind}_PATTERNS")


def main():
    """
    Main entry point for the script.
    
    Parses command-line arguments and initiates the file restructuring process.
    """
    parser = argparse.ArgumentParser(description="Restructure PET scan files based on folder names")
    parser.add_argument("source_dir", help="Source directory containing PET_* folders")
    parser.add_argument("--target_dir", help="Target directory for restructured files (default is sibling to source_dir)", default=None)
    parser.add_argument("--pet-pattern", action="append", default=[], metavar="SUBSTRING",
                        help="Extra PET filename substring, tried after the built-in ones (repeatable)")
    parser.add_argument("--ct-pattern", action="append", default=[], metavar="SUBSTRING",
                        help="Extra CT filename substring, tried after the built-in ones (repeatable)")
    args = parser.parse_args()
    pet_patterns = PET_PATTERNS + args.pet_pattern
    ct_patterns = CT_PATTERNS + args.ct_pattern
    
    
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
    
    subjects = restructure_files(args.source_dir, args.target_dir, logger, pet_patterns, ct_patterns)
    
    # Log summary information
    logger.info("=" * 80)
    logger.info("Reorganization complete!")
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