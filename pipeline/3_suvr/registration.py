import os
import logging
import argparse
from pathlib import Path
from datetime import datetime
import subprocess
from typing import List, Tuple, Dict, Optional
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from tqdm import tqdm


def setup_logging(base_dir: Path) -> logging.Logger:
    """Configure logging settings."""
    try:
        logs_dir = base_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_filename = f"pet_registration_{date_str}.log"
        log_path = logs_dir / log_filename

        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            handlers=[
                logging.FileHandler(str(log_path)),
                logging.StreamHandler()
            ]
        )
        
        logger = logging.getLogger(__name__)
        logger.info(f"Log file created at: {log_path}")
        return logger
        
    except Exception as e:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        logger = logging.getLogger(__name__)
        logger.error(f"Error setting up logging: {str(e)}")
        return logger


def parse_nifti_filename(filename: str) -> Tuple[str, str, str, Optional[str]]:
    """
    Parse the NIfTI filename format: subjID-scandate_modality[_info].nii
    Returns tuple of (subject_id, scan_date, modality, additional_info)
    """
    # Remove .nii extension
    base_name = filename.replace('.nii', '')
    
    try:
        # Split by hyphen to get subjID and the rest
        parts = base_name.split('-', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid filename format: {filename}. Expected format: subjID-scandate_modality[_info].nii")
        
        subject_id = parts[0]
        
        # Now split the second part by underscore
        remaining_parts = parts[1].split('_')
        
        # First part should be the scan date
        scan_date = remaining_parts[0]
        
        # Second part should be the modality (e.g., PET)
        modality = remaining_parts[1]
        
        # Any additional parts are considered extra info
        additional_info = None
        if len(remaining_parts) > 2:
            additional_info = '_'.join(remaining_parts[2:])
            
        return subject_id, scan_date, modality, additional_info
        
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid filename format: {filename}. Expected format: subjID-scandate_modality[_info].nii")


def find_mri_directories(suvr_dir: Path) -> List[Tuple[Path, Path, Path]]:
    """Find all MRI directories that contain both MRI and PET files.
    Returns list of tuples (subdir, mri_file, pet_file)"""
    result = []
    
    # Look for directories matching pattern pet_*_mri_*
    for subdir in suvr_dir.iterdir():
        if subdir.is_dir() and "_pet_" in subdir.name and "_mri_" in subdir.name:
            mri_dir = subdir / "MRI"
            if mri_dir.exists():
                # Find MRI files (T1w or CorMPRAGE)
                mri_files = []
                for pattern in ["*T1w*.nii", "*CorMPRAGE*.nii"]:
                    mri_files.extend(list(mri_dir.glob(pattern)))
                
                # Find PET files
                pet_files = list(mri_dir.glob("*PET*.nii"))
                
                # If we have both MRI and PET files, add them to our result
                if mri_files and pet_files:
                    for mri_file in mri_files:
                        for pet_file in pet_files:
                            # Skip files with "aparc" or "aseg" in the name
                            if not ('aparc' in mri_file.name.lower() or 'aseg' in mri_file.name.lower()):
                                result.append((subdir, mri_file, pet_file))
    
    return result


def run_flirt_registration(
    pet_file: Path,
    ref_file: Path,
    output_file: Path,
    logger: logging.Logger
) -> bool:
    """Run FSL FLIRT registration between PET and reference image."""
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "flirt",
            "-in", str(pet_file),
            "-ref", str(ref_file),
            "-out", str(output_file),
            "-omat", str(output_file.with_suffix('.mat')),
            "-bins", "256",
            "-cost", "corratio",
            "-searchrx", "-90", "90",
            "-searchry", "-90", "90",
            "-searchrz", "-90", "90",
            "-dof", "12",
            "-interp", "trilinear"
        ]

        env = os.environ.copy()
        env.setdefault('FSLDIR', '/usr/local/fsl')
        env['PATH'] = f"{env.get('PATH', '')}:{env['FSLDIR']}/bin"
        env['FSLOUTPUTTYPE'] = 'NIFTI'
        
        logger.info(f"Running registration command:\n{' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.error(f"Registration failed with error:\n{result.stderr}")
            return False

        logger.info("Registration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        return False


def process_suvr_directory(suvr_dir: Path) -> bool:
    """Process all registrations for a SUVR directory."""
    try:
        # Set up logging
        logger = setup_logging(suvr_dir)
        logger.info(f"Processing SUVR directory: {suvr_dir}")

        # Find all MRI directories with MRI and PET files
        mri_combinations = find_mri_directories(suvr_dir)
        if not mri_combinations:
            logger.error("No MRI directories with PET files found")
            return False

        successful_registrations = 0
        failed_registrations = 0

        # Process each MRI directory
        for suvr_subdir, mri_file, pet_file in mri_combinations:
            logger.info(f"\nProcessing registrations for directory: {suvr_subdir.name}")
            
            # Create register_scan directory
            register_scan_dir = suvr_subdir / "register_scan"
            register_scan_dir.mkdir(exist_ok=True)

            try:
                # Get subject IDs and dates from filenames
                pet_subj_id, pet_date, pet_modality, pet_additional_info = parse_nifti_filename(pet_file.name)
                mri_subj_id, mri_date, mri_modality, mri_additional_info = parse_nifti_filename(mri_file.name)
                
                # Create output filename: petID-petDate_reg_mriID-mriDate_mriModality.nii
                # Include additional info if present
                output_filename = f"{pet_subj_id}-{pet_date}"
                if pet_additional_info:
                    output_filename += f"_{pet_additional_info}"
                    
                output_filename += f"_reg_{mri_subj_id}-{mri_date}_{mri_modality}"
                if mri_additional_info:
                    output_filename += f"_{mri_additional_info}"
                    
                output_filename += ".nii"
                output_path = register_scan_dir / output_filename

                logger.info(f"\nProcessing registration:")
                logger.info(f"- PET: {pet_file}")
                logger.info(f"- Reference: {mri_file}")
                logger.info(f"- Output: {output_path}")

                # Skip if output already exists
                if output_path.exists():
                    logger.info("Registration output already exists, skipping...")
                    successful_registrations += 1
                    continue

                # Verify PET file exists
                if not pet_file.exists():
                    logger.error(f"PET file not found: {pet_file}")
                    failed_registrations += 1
                    continue

                # Run registration
                if run_flirt_registration(pet_file, mri_file, output_path, logger):
                    successful_registrations += 1
                else:
                    failed_registrations += 1

            except ValueError as ve:
                logger.error(f"Error with filename format: {str(ve)}")
                failed_registrations += 1
            except Exception as e:
                logger.error(f"Error processing registration: {str(e)}")
                failed_registrations += 1

        # Log summary
        logger.info(f"\nRegistration Summary:")
        logger.info(f"- Successful: {successful_registrations}")
        logger.info(f"- Failed: {failed_registrations}")
        
        return successful_registrations > 0

    except Exception as e:
        if 'logger' not in locals():
            logger = logging.getLogger()
            logging.basicConfig(level=logging.INFO)
        logger.error(f"Error processing SUVR directory: {str(e)}")
        return False
    
def find_suvr_folders(subject_path: Path) -> Dict[str, List[Path]]:
    """
    Find all SUVR folders under the given subject path, organized by date.
    Returns a dictionary with dates as keys and lists of SUVR folder paths as values.
    """
    suvr_folders = {}
    
    try:
        # Walk through all subdirectories
        for date_dir in subject_path.iterdir():
            if not date_dir.is_dir():
                continue
                
            # Look for 'suvr' folder in each date directory
            suvr_path = date_dir / 'suvr'
            if suvr_path.exists() and suvr_path.is_dir():
                date = date_dir.name
                if date not in suvr_folders:
                    suvr_folders[date] = []
                suvr_folders[date].append(suvr_path)
    
    except Exception as e:
        logging.error(f"Error finding SUVR folders: {str(e)}")
    
    return suvr_folders


def list_suvr_subfolders(suvr_path: Path) -> List[Path]:
    """List all valid SUVR subfolders (containing MRI directories with PET files)."""
    subfolders = []
    
    try:
        for item in suvr_path.iterdir():
            if item.is_dir() and "_PET" in item.name:
                # Look for directories matching pattern pet_*_mri_* 
                # This should work with the extended pattern with additional info as well
                for subdir in item.iterdir():
                    if subdir.is_dir() and "_pet_" in subdir.name.lower() and "_mri_" in subdir.name.lower():
                        mri_dir = subdir / "MRI"
                        if mri_dir.exists():
                            # Check if MRI has PET files
                            pet_files = list(mri_dir.glob("*PET*.nii"))
                            if pet_files:
                                subfolders.append(item)
                                break
    except Exception as e:
        logging.error(f"Error listing SUVR subfolders: {str(e)}")
    
    return subfolders


def process_subject(subject_path: Path) -> bool:
    """
    Process all SUVR folders for a single subject non-interactively.
    
    Args:
        subject_path: Path to the subject directory
        
    Returns:
        bool: True if processing was successful, False otherwise
    """
    print(f"Processing subject: {subject_path.name}")
    
    # Find all SUVR folders
    suvr_folders = find_suvr_folders(subject_path)
    if not suvr_folders:
        print(f"No SUVR folders found for subject: {subject_path.name}")
        return False
    
    # Process all dates
    all_subfolders = []
    
    for date, suvr_paths in suvr_folders.items():
        print(f"Found date: {date} with {len(suvr_paths)} SUVR folder(s)")
        
        # Collect all valid subfolders for processing
        for suvr_path in suvr_paths:
            subfolders = list_suvr_subfolders(suvr_path)
            if subfolders:
                all_subfolders.extend(subfolders)
                print(f"  - Found {len(subfolders)} valid PET folders in {suvr_path}")
    
    if not all_subfolders:
        print(f"No valid SUVR subfolders found for subject: {subject_path.name}")
        return False
    
    print(f"Processing {len(all_subfolders)} PET folders for subject {subject_path.name}")
    
    # Process all subfolders sequentially
    success = True
    for subfolder in all_subfolders:
        print(f"Processing {subfolder}...")
        result = process_suvr_directory(subfolder)
        if not result:
            success = False
    
    return success


def process_subjects_parallel(subject_paths: List[Path], max_workers: int) -> bool:
    """
    Process multiple subjects in parallel, with one core per subject.
    
    Args:
        subject_paths: List of paths to subject directories
        max_workers: Maximum number of subjects to process in parallel
        
    Returns:
        bool: True if all processing was successful, False otherwise
    """
    success = True
    
    # Use ProcessPoolExecutor to process subjects in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for subject_path in subject_paths:
            # Submit each subject for processing
            future = executor.submit(process_subject, subject_path)
            futures.append((subject_path, future))
        
        # Monitor progress
        for subject_path, future in tqdm(futures, desc="Processing subjects"):
            try:
                result = future.result()
                if not result:
                    success = False
                    print(f"Processing failed for subject: {subject_path.name}")
            except Exception as e:
                success = False
                print(f"Error processing subject {subject_path.name}: {str(e)}")
    
    return success


def process_all_subjects(base_path: Path, num_cores: int = 1) -> bool:
    """
    Process all subjects in the given base path.
    
    Args:
        base_path: Path to the directory containing subject directories
        num_cores: Number of subjects to process in parallel (1 core per subject)
        
    Returns:
        bool: True if all processing was successful, False otherwise
    """
    # Find all subject directories
    subject_dirs = [d for d in base_path.iterdir() if d.is_dir()]
    
    if not subject_dirs:
        print(f"No subject directories found in {base_path}")
        return False
    
    print(f"Found {len(subject_dirs)} subject directories")
    
    # Determine the number of workers (subjects to process in parallel)
    if num_cores <= 1:
        # Process sequentially
        overall_success = True
        for i, subject_dir in enumerate(subject_dirs, 1):
            print(f"\nProcessing subject {i}/{len(subject_dirs)}: {subject_dir.name}")
            success = process_subject(subject_dir)
            if not success:
                overall_success = False
        return overall_success
    else:
        # Process subjects in parallel (1 core per subject)
        max_workers = min(num_cores, len(subject_dirs))
        print(f"Processing {len(subject_dirs)} subjects using {max_workers} parallel workers (1 core per subject)")
        return process_subjects_parallel(subject_dirs, max_workers)


def main():
    """Main function for the non-interactive PET registration tool."""
    parser = argparse.ArgumentParser(description="Non-Interactive PET Registration Tool")
    parser.add_argument("subject_path", help="Path to subject directory or base directory with multiple subjects")
    parser.add_argument("--cores", type=int, default=4, help="Number of subjects to process in parallel (1 core per subject)")
    parser.add_argument("--single", action="store_true", help="Process a single subject (default: process all subjects)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()

    # Set up logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    subject_path = Path(args.subject_path)
    if not subject_path.exists():
        print(f"Subject directory not found: {subject_path}")
        return 1

    # Time the execution
    start_time = datetime.now()
    print(f"Starting registration process at {start_time}")
    
    # Determine if we're processing a single subject or all subjects
    if args.single:
        print(f"Processing single subject: {subject_path}")
        success = process_subject(subject_path)
    else:
        print(f"Processing all subjects in: {subject_path}")
        success = process_all_subjects(subject_path, args.cores)
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    if success:
        print(f"\nProcessing completed successfully in {duration}!")
        return 0
    else:
        print(f"\nProcessing completed with some failures in {duration}. Check the logs for details.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())