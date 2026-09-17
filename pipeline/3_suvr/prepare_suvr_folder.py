import os
import logging
import argparse
import shutil
from datetime import datetime
from pathlib import Path
import subprocess
import re
from typing import Optional, List, Tuple, Dict
import sys
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm  # For progress bars

""""
# Use all available cores (minus one) in default mode (subjects in parallel)
python prepare_suvr_folder.py /path/to/subjects

# Process a single subject using 4 cores for PET-MRI combinations
python prepare_suvr_folder.py /path/to/subjects --single-subject SUB001 --cores 4

# Process all subjects using exactly 8 cores
python prepare_suvr_folder.py /path/to/subjects --cores 8

# Disable parallel processing entirely
python prepare_suvr_folder.py /path/to/subjects --disable-parallel
"""

def setup_logging(suvr_dir: Path, pet_date: str) -> logging.Logger:
    """Configure logging settings in the SUVR/logs directory."""
    log_dir = suvr_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"suvr_setup_{pet_date}_{timestamp}.log"
    log_path = log_dir / log_filename

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.FileHandler(str(log_path)), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


# Add a function to get the optimal number of workers
def get_optimal_workers(requested_workers: Optional[int] = None) -> int:
    """
    Determine the optimal number of worker processes.
    
    Args:
        requested_workers: User-requested number of workers, or None for auto-detection
        
    Returns:
        int: Number of worker processes to use
    """
    available_cpus = multiprocessing.cpu_count()
    
    # If no specific number requested, use available CPUs minus 1 (leave one for system)
    if requested_workers is None:
        return max(1, available_cpus - 1)
    
    # If specific number requested, cap it at available CPUs
    return min(max(1, requested_workers), available_cpus)


# Modify the argument parser to include multiprocessing options
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated SUVR setup for neuroimaging analysis"
    )
    parser.add_argument(
        "base_path", help="Path to the directory containing subject directories"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--single-subject", help="Process only the specified subject ID"
    )
    
    # Add multiprocessing options
    parser.add_argument(
        "--cores", type=int, help="Number of CPU cores to use for parallel processing (default: auto-detect)"
    )
    parser.add_argument(
        "--disable-parallel", action="store_true", 
        help="Disable parallel processing and run sequentially"
    )
    parser.add_argument(
        "--parallel-mode", choices=["subjects", "combinations"], default="subjects",
        help="Parallelization mode: 'subjects' processes different subjects in parallel, "
             "'combinations' processes PET-MRI combinations in parallel (default: subjects)"
    )

    return parser.parse_args()

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


def find_dates_with_pet(subject_path: Path) -> List[Path]:
    """Find all date directories that contain a pet folder."""
    pet_dates = []
    for date_dir in subject_path.iterdir():
        if date_dir.is_dir() and (date_dir / "pet").exists():
            pet_dates.append(date_dir)
    return sorted(pet_dates)


def find_pet_scans(pet_path: Path) -> List[Path]:
    """Find all PET scans in the directory."""
    # Find all files ending in .nii that have modality "PET" in the name
    pet_files = [f for f in pet_path.glob("*.nii") if "_PET" in f.name]
    return sorted(pet_files)


def find_closest_mri(pet_scan: Path, mri_files: List[Path]) -> Optional[Path]:
    """
    Pick the MRI file whose scan date is closest to the PET scan's date.
    Ties (equal distance) resolve to whichever MRI comes first in mri_files
    (mri_files is sorted, so this is deterministic).
    """
    try:
        _, pet_date_str, _, _ = parse_nifti_filename(pet_scan.name)
        pet_date = datetime.strptime(pet_date_str, "%Y%m%d")
    except ValueError as e:
        logging.error(str(e))
        return None

    best_mri = None
    best_delta = None
    for mri_file in mri_files:
        try:
            _, mri_date_str, _, _ = parse_nifti_filename(mri_file.name)
            mri_date = datetime.strptime(mri_date_str, "%Y%m%d")
        except ValueError as e:
            logging.error(str(e))
            continue

        delta = abs((mri_date - pet_date).days)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_mri = mri_file

    return best_mri


def find_mri_files(subject_path: Path) -> List[Path]:
    """
    Find all MRI files in anat directories.
    Looks for both T1w and CorMPRAGE variants.
    """
    mri_files = []
    try:
        for anat_dir in subject_path.rglob("anat"):
            # Look for both T1w and CorMPRAGE MRI files
            for mri_pattern in ["*T1w*", "*CorMPRAGE*"]:
                mri_files.extend(list(anat_dir.glob(f"{mri_pattern}.nii")))
    except Exception as e:
        logging.error(f"Error finding MRI files: {str(e)}")
    return sorted(mri_files)  # Sort files for consistent ordering


def run_mri_convert(input_path: Path, output_path: Path, out_type: str = "nii", orientation: str = "RAS") -> bool:
    """Convert MRI files using FreeSurfer's mri_convert."""
    try:
        if not input_path.exists():
            logging.error(f"Input file not found: {input_path}")
            return False

        freesurfer_home = Path(os.environ.get("FREESURFER_HOME", "/usr/local/freesurfer"))
        if not freesurfer_home.exists():
            raise EnvironmentError(
                f"FreeSurfer installation not found at {freesurfer_home}. "
                "Set FREESURFER_HOME to your FreeSurfer 7 install directory."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "mri_convert",
            "-ot", out_type,
            "--out_orientation", orientation,
            str(input_path),
            str(output_path),
        ]

        env = os.environ.copy()
        env["FREESURFER_HOME"] = str(freesurfer_home)

        logging.info(f"- Running conversion command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

        logging.info(f"- Successfully converted {input_path} to {output_path.name}")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"Error running mri_convert: {e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Error in mri_convert: {str(e)}")
        return False
    
def process_freesurfer_stats(mri_dir: Path, fs_stats_dir: Path, subject: str, mri_prefix: str) -> bool:
    """Process FreeSurfer statistics files."""
    try:
        stats_configs = [
            {
                "name": "aparcstatsVolumLeft",
                "command": ["aparcstats2table", "--subjects", subject, "--hemi", "lh", "--meas", "volume"],
                "output_suffix": f"{mri_prefix}_aparcstatsVolumLeft.csv",
            },
            {
                "name": "aparcstatsVolumRight",
                "command": ["aparcstats2table", "--subjects", subject, "--hemi", "rh", "--meas", "volume"],
                "output_suffix": f"{mri_prefix}_aparcstatsVolumRight.csv",
            },
            {
                "name": "asegVolume",
                "command": ["asegstats2table", "--subjects", subject, "-m", "volume"],
                "output_suffix": f"{mri_prefix}_asegVolume.csv",
            },
        ]

        for config in stats_configs:
            stats_file = fs_stats_dir / config["output_suffix"].replace(f"{mri_prefix}_", "")
            output_file = mri_dir / config["output_suffix"]
            
            if output_file.exists():
                logging.info(f"Stats file already exists: {output_file}")
                continue

            if stats_file.exists():
                with stats_file.open("r") as src, output_file.open("w") as dst:
                    content = src.read().replace("\t", ",")
                    dst.write(content)
                logging.info(f"Copied and formatted stats file: {output_file}")
            else:
                temp_output = mri_dir / config["output_suffix"].replace(f"{mri_prefix}_", "")
                cmd = config["command"] + ["--tablefile", str(temp_output)]

                env = os.environ.copy()
                if "FREESURFER_HOME" not in env:
                    env["FREESURFER_HOME"] = "/usr/local/freesurfer"
                env["SUBJECTS_DIR"] = str(fs_stats_dir.parent.parent)

                logging.info(f"- Running FreeSurfer command: {' '.join(cmd)}")
                result = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

                with temp_output.open("r") as f:
                    content = f.read()
                with output_file.open("w") as f:
                    f.write(content.replace("\t", ","))
                
                temp_output.unlink()
                logging.info(f"- Generated stats file: {output_file}")

        logging.info(f"Successfully processed all FreeSurfer stats for {subject}")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"FreeSurfer command failed: {e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Error processing FreeSurfer stats: {str(e)}")
        return False


def create_suvr_structure(pet_file: Path, mri_path: Path, suvr_base_dir: Path) -> Optional[Path]:
    """Create SUVR directory structure for analysis and copy PET directly to MRI folder."""
    try:
        # Extract information from filenames using new format
        try:
            pet_subj_id, pet_date, _, pet_additional_info = parse_nifti_filename(pet_file.name)
            mri_subj_id, mri_date, _, mri_additional_info = parse_nifti_filename(mri_path.name)
        except ValueError as e:
            logging.error(str(e))
            return None

        # Determine MRI type
        is_cormprage = "CorMPRAGE" in mri_path.name
        mri_type_suffix = "_CorMPRAGE" if is_cormprage else ""
        
        # Create directory structure with additional info if available
        pet_folder_name = f"{pet_subj_id}-{pet_date}_PET"
        if pet_additional_info:
            pet_folder_name = f"{pet_folder_name}_{pet_additional_info}"
            
        pet_specific_dir = suvr_base_dir / pet_folder_name
        
        # Create combo directory name
        combo_dir_name = f"{pet_subj_id}_pet_{pet_date}"
        if pet_additional_info:
            combo_dir_name = f"{combo_dir_name}_{pet_additional_info}"
            
        combo_dir_name = f"{combo_dir_name}_mri_{mri_date}{mri_type_suffix}"
        if mri_additional_info:
            combo_dir_name = f"{combo_dir_name}_{mri_additional_info}"
            
        combo_dir = pet_specific_dir / combo_dir_name
        
        if combo_dir.exists():
            logging.info(f"Directory already exists: {combo_dir}")
            return pet_specific_dir
        
        # Create subdirectories
        subdirs = ["MRI", "res"]
        for subdir in subdirs:
            (combo_dir / subdir).mkdir(parents=True, exist_ok=True)
            logging.info(f"Created directory: {combo_dir / subdir}")

        # Process FreeSurfer files
        try:
            anat_dir = mri_path.parent
            base_dir = anat_dir.parent
            fs_base_dir = base_dir / "freesurfer741"
            mri_name_no_ext = mri_path.stem
            fs_mri_dir = fs_base_dir / mri_name_no_ext / "mri"
            fs_stats_dir = fs_base_dir / mri_name_no_ext / "stats"
            dest_dir = combo_dir / "MRI"

            if fs_mri_dir.exists():
                # Convert FreeSurfer files
                # Use the full MRI filename stem as prefix
                mri_prefix = mri_path.stem
                
                files_to_convert = [
                    ("T1.mgz", mri_path.name),
                    ("aparc+aseg.mgz", f"{mri_prefix}_aparc+aseg.nii"),
                ]

                conversion_success = True
                logging.info(f"Converting FreeSurfer files for {mri_path.name}")
                for input_name, output_name in files_to_convert:
                    input_path = fs_mri_dir / input_name
                    output_path = dest_dir / output_name
                    
                    # Run conversion and capture result
                    
                    conversion_result = run_mri_convert(input_path, output_path)
                    if not conversion_result:
                        conversion_success = False
                
                # Only proceed with stats if conversion was successful
                if conversion_success:
                    # Process FreeSurfer stats
                    logging.info(f"Processing FreeSurfer stats for {mri_path.name}")
                    stats_result = process_freesurfer_stats(dest_dir, fs_stats_dir, mri_name_no_ext, mri_path.stem)
                    if not stats_result:
                        logging.warning("FreeSurfer stats processing completed with errors")
                else:
                    logging.warning("Skipping FreeSurfer stats processing due to conversion failures")
                
                # Copy PET file directly to MRI folder using the original filename
                pet_dest_path = dest_dir / pet_file.name
                
                # Check if PET file already exists in the target location
                if pet_dest_path.exists():
                    logging.info(f"PET file already exists in MRI folder: {pet_dest_path}")
                else:
                    # Copy PET file to MRI folder
                    shutil.copy2(pet_file, pet_dest_path)
                    logging.info(f"Copied {pet_file.name} to MRI folder: {pet_dest_path}") 
                
                # Create a register_scan folder for the processed results
                register_scan_dir = combo_dir / "register_scan"
                register_scan_dir.mkdir(exist_ok=True)
                logging.info(f"Created register_scan directory at: {register_scan_dir}")
                
            else:
                logging.warning(f"FreeSurfer mri directory not found at: {fs_mri_dir}")

        except Exception as convert_error:
            logging.error(f"Error during FreeSurfer processing: {str(convert_error)}")

        return pet_specific_dir

    except Exception as e:
        logging.error(f"Error creating directory structure: {str(e)}")
        return None

def process_pet_mri_combination(
    pet_scan: Path, 
    mri_file: Path, 
    suvr_dir: Path,
    verbose: bool = False
) -> Dict[str, bool]:
    """
    Process a single PET scan with a single MRI file.
    
    Args:
        pet_scan: Path to the PET scan file
        mri_file: Path to the MRI file
        suvr_dir: Path to the SUVR directory
        verbose: Whether to print verbose output
        
    Returns:
        Dictionary with status information
    """
    result = {
        "pet_scan": str(pet_scan),
        "mri_file": str(mri_file),
        "success": False,
        "error": None
    }
    
    try:
        pet_subj_id, pet_date, _, _ = parse_nifti_filename(pet_scan.name)
        mri_subj_id, mri_date, _, _ = parse_nifti_filename(mri_file.name)
        mri_type = "CorMPRAGE" if "CorMPRAGE" in mri_file.name else "T1w"
        
        # Setup logging for this specific combination
        logger = setup_logging(suvr_dir, pet_date)
        log_prefix = f"[PET:{pet_scan.name} - MRI:{mri_file.name}]"
        logger.info(f"{log_prefix} Processing combination")
        
        # Create SUVR structure for this combination
        suvr_result = create_suvr_structure(pet_scan, mri_file, suvr_dir)
        
        if suvr_result:
            logger.info(f"{log_prefix} Successfully created/updated SUVR structure")
            result["success"] = True
        else:
            error_msg = f"Failed to create/update SUVR structure"
            logger.error(f"{log_prefix} {error_msg}")
            result["error"] = error_msg
            
    except Exception as e:
        result["error"] = str(e)
        # Don't log here as logging setup might be part of the exception
        if verbose:
            print(f"Error processing {pet_scan.name} with {mri_file.name}: {str(e)}")
    
    return result


def process_subject(
    subject_path: Path, 
    verbose: bool = False,
    parallel: bool = False,
    max_workers: Optional[int] = None
) -> Dict[str, int]:
    """
    Process a single subject directory by finding all PET scans and MRI files
    and creating SUVR directory structures for each.

    Args:
        subject_path: Path to the subject directory
        verbose: Whether to print verbose output
        parallel: Whether to process PET-MRI combinations in parallel
        max_workers: Maximum number of worker processes to use if parallel is True
        
    Returns:
        Dictionary with counts of successful and failed processing
    """
    results = {
        "pet_dates_found": 0,
        "pet_scans_found": 0,
        "mri_files_found": 0,
        "successful_structures": 0,
        "failed_structures": 0,
    }

    if verbose:
        print(f"\nProcessing subject: {subject_path.name}")

    # Find all date directories with PET scans
    date_dirs = find_dates_with_pet(subject_path)
    results["pet_dates_found"] = len(date_dirs)

    if not date_dirs:
        if verbose:
            print(f"No directories with PET scans found for {subject_path.name}")
        return results

    # Find all MRI files for this subject
    mri_files = find_mri_files(subject_path)
    results["mri_files_found"] = len(mri_files)

    if not mri_files:
        if verbose:
            print(f"No MRI files found for {subject_path.name}")
        return results
    
    # Collect all PET-MRI combinations to process
    combinations = []
    
    for date_dir in date_dirs:
        # Find PET scans in this date directory
        pet_dir = date_dir / "pet"
        pet_scans = find_pet_scans(pet_dir)
        
        if not pet_scans:
            if verbose:
                print(f"No PET scans found in {pet_dir}")
            continue
            
        results["pet_scans_found"] += len(pet_scans)
        
        # Create SUVR directory if it doesn't exist
        suvr_dir = date_dir / "suvr"
        suvr_dir.mkdir(exist_ok=True)
        
        # Pair each PET scan with its closest-dated MRI only
        for pet_scan in pet_scans:
            closest_mri = find_closest_mri(pet_scan, mri_files)
            if closest_mri is None:
                if verbose:
                    print(f"No matching MRI date found for {pet_scan.name}")
                continue
            combinations.append((pet_scan, closest_mri, suvr_dir))
    
    total_combinations = len(combinations)
    if verbose:
        print(f"Found {total_combinations} PET-MRI combinations to process")
    
    if total_combinations == 0:
        return results
    
    # Process all combinations either sequentially or in parallel
    if parallel and max_workers:
        # Process in parallel
        worker_count = get_optimal_workers(max_workers)
        if verbose:
            print(f"Processing {total_combinations} combinations in parallel with {worker_count} workers")
        
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            # Submit all tasks
            futures = [
                executor.submit(process_pet_mri_combination, pet, mri, suvr, verbose)
                for pet, mri, suvr in combinations
            ]
            
            # Process results as they complete, with a progress bar
            for future in tqdm(as_completed(futures), total=len(futures), 
                              desc=f"Processing {subject_path.name}"):
                try:
                    result = future.result()
                    if result["success"]:
                        results["successful_structures"] += 1
                    else:
                        results["failed_structures"] += 1
                        if verbose:
                            print(f"Error: {result['error']}")
                except Exception as e:
                    results["failed_structures"] += 1
                    if verbose:
                        print(f"Worker exception: {str(e)}")
    else:
        # Process sequentially
        if verbose:
            print(f"Processing {total_combinations} combinations sequentially")
            
        for pet_scan, mri_file, suvr_dir in tqdm(combinations, 
                                                desc=f"Processing {subject_path.name}"):
            result = process_pet_mri_combination(pet_scan, mri_file, suvr_dir, verbose)
            if result["success"]:
                results["successful_structures"] += 1
            else:
                results["failed_structures"] += 1
                if verbose and result["error"]:
                    print(f"Error: {result['error']}")
    
    return results

def process_all_subjects(
    base_path: Path, 
    verbose: bool = False,
    parallel_subjects: bool = False,
    parallel_combinations: bool = False,
    max_workers: Optional[int] = None
) -> Dict[str, int]:
    """
    Process all subject directories in the given base path.

    Args:
        base_path: Path to the directory containing subject directories
        verbose: Whether to print verbose output
        parallel_subjects: Whether to process subjects in parallel
        parallel_combinations: Whether to process PET-MRI combinations in parallel within each subject
        max_workers: Maximum number of worker processes to use
        
    Returns:
        Dictionary with counts of processed subjects and structures
    """
    overall_results = {
        "subjects_found": 0,
        "subjects_processed": 0,
        "subjects_with_errors": 0,
        "total_pet_dates": 0,
        "total_pet_scans": 0,
        "total_mri_files": 0,
        "total_successful_structures": 0,
        "total_failed_structures": 0,
    }

    # Find all subject directories (assuming they are direct subdirectories)
    subject_dirs = [d for d in base_path.iterdir() if d.is_dir()]
    overall_results["subjects_found"] = len(subject_dirs)

    if not subject_dirs:
        print(f"No subject directories found in {base_path}")
        return overall_results

    print(f"Found {len(subject_dirs)} subject directories")
    
    # Process subjects either sequentially or in parallel
    if parallel_subjects and max_workers:
        worker_count = get_optimal_workers(max_workers)
        print(f"Processing {len(subject_dirs)} subjects in parallel with {worker_count} workers")
        
        # Each worker will process combinations sequentially or in parallel based on parallel_combinations
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            # Submit all tasks
            futures = []
            for subject_dir in subject_dirs:
                future = executor.submit(
                    process_subject, 
                    subject_dir, 
                    verbose, 
                    parallel_combinations,  # Whether to parallelize combinations
                    max_workers if parallel_combinations else None
                )
                futures.append((subject_dir, future))
            
            # Process results with a progress bar
            for subject_dir, future in tqdm(futures, total=len(futures), desc="Processing subjects"):
                try:
                    results = future.result()
                    
                    # Update overall results
                    overall_results["subjects_processed"] += 1
                    overall_results["total_pet_dates"] += results["pet_dates_found"]
                    overall_results["total_pet_scans"] += results["pet_scans_found"]
                    overall_results["total_mri_files"] += results["mri_files_found"]
                    overall_results["total_successful_structures"] += results["successful_structures"]
                    overall_results["total_failed_structures"] += results["failed_structures"]
                    
                    if results["failed_structures"] > 0:
                        overall_results["subjects_with_errors"] += 1
                        
                    if verbose:
                        print(f"\nResults for {subject_dir.name}:")
                        print(f"  PET dates found: {results['pet_dates_found']}")
                        print(f"  PET scans found: {results['pet_scans_found']}")
                        print(f"  MRI files found: {results['mri_files_found']}")
                        print(f"  Successful structures: {results['successful_structures']}")
                        print(f"  Failed structures: {results['failed_structures']}")
                        
                except Exception as e:
                    overall_results["subjects_with_errors"] += 1
                    print(f"Error processing subject {subject_dir.name}: {str(e)}")
    else:
        # Process subjects sequentially, but may process combinations in parallel
        for i, subject_dir in enumerate(subject_dirs, 1):
            print(f"\nProcessing subject {i}/{len(subject_dirs)}: {subject_dir.name}")
            
            try:
                results = process_subject(
                    subject_dir, 
                    verbose, 
                    parallel_combinations,  # Whether to parallelize combinations
                    max_workers if parallel_combinations else None
                )
                
                # Update overall results
                overall_results["subjects_processed"] += 1
                overall_results["total_pet_dates"] += results["pet_dates_found"]
                overall_results["total_pet_scans"] += results["pet_scans_found"]
                overall_results["total_mri_files"] += results["mri_files_found"]
                overall_results["total_successful_structures"] += results["successful_structures"]
                overall_results["total_failed_structures"] += results["failed_structures"]
                
                if results["failed_structures"] > 0:
                    overall_results["subjects_with_errors"] += 1
                
                # Print summary for this subject
                print(f"  PET dates found: {results['pet_dates_found']}")
                print(f"  PET scans found: {results['pet_scans_found']}")
                print(f"  MRI files found: {results['mri_files_found']}")
                print(f"  Successful structures: {results['successful_structures']}")
                print(f"  Failed structures: {results['failed_structures']}")
                
            except Exception as e:
                overall_results["subjects_with_errors"] += 1
                print(f"Error processing subject {subject_dir.name}: {str(e)}")
    
    return overall_results


def main():
    """Main function for SUVR folder preparation with parallel processing support."""
    args = parse_arguments()
    
    base_path = Path(args.base_path)
    if not base_path.exists():
        print(f"Base path not found: {base_path}")
        return 1

    # Determine parallel processing settings
    parallel_processing = not args.disable_parallel
    max_workers = args.cores
    
    if parallel_processing:
        worker_count = get_optimal_workers(max_workers)
        print(f"Parallel processing enabled with {worker_count} worker processes")
        print(f"Parallelization mode: {args.parallel_mode}")
    else:
        print("Parallel processing disabled - running sequentially")
    
    start_time = datetime.now()

    if args.single_subject:
        # Process a single subject
        subject_path = base_path / args.single_subject
        if not subject_path.exists():
            print(f"Subject path not found: {subject_path}")
            return 1

        print(f"Processing single subject: {args.single_subject}")
        
        # For single subjects, we can only parallelize combinations
        parallel_combinations = parallel_processing
        
        results = process_subject(
            subject_path, 
            args.verbose, 
            parallel=parallel_combinations, 
            max_workers=max_workers
        )

        print("\nSingle Subject Processing Summary:")
        print(f"PET dates found: {results['pet_dates_found']}")
        print(f"PET scans found: {results['pet_scans_found']}")
        print(f"MRI files found: {results['mri_files_found']}")
        print(f"Successful structures: {results['successful_structures']}")
        print(f"Failed structures: {results['failed_structures']}")

    else:
        # Process all subjects
        print(f"Processing all subjects in: {base_path}")
        
        # Determine which parallel mode to use
        parallel_subjects = parallel_processing and args.parallel_mode == "subjects"
        parallel_combinations = parallel_processing and args.parallel_mode == "combinations"
        
        overall_results = process_all_subjects(
            base_path, 
            args.verbose, 
            parallel_subjects=parallel_subjects,
            parallel_combinations=parallel_combinations,
            max_workers=max_workers
        )

        # Print overall summary
        print("\nOverall Processing Summary:")
        print(f"Subjects found: {overall_results['subjects_found']}")
        print(f"Subjects processed: {overall_results['subjects_processed']}")
        print(f"Subjects with errors: {overall_results['subjects_with_errors']}")
        print(f"Total PET dates found: {overall_results['total_pet_dates']}")
        print(f"Total PET scans found: {overall_results['total_pet_scans']}")
        print(f"Total MRI files found: {overall_results['total_mri_files']}")
        print(
            f"Total successful structures: {overall_results['total_successful_structures']}"
        )
        print(f"Total failed structures: {overall_results['total_failed_structures']}")

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"\nTotal processing time: {duration}")

    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Required for Windows when using multiprocessing
    sys.exit(main())