#!/usr/bin/env python3
"""
Batch Scan Copy Script

This script processes a CSV file containing patient IDs and scan dates,
finds the corresponding scan files (T1w or PET), and copies them to a destination folder.

Expected CSV format:
- First column: Patient ID (e.g., "110001")
- Second column: Scan date in MM/DD/YYYY format (e.g., "01/15/2020")

Author: GitHub Copilot
Date: October 1, 2025
"""

import sys
import argparse
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
import pandas as pd


def convert_date_format(date_str: str) -> str:
    """
    Convert date from MM/DD/YYYY format to YYYYMMDD format.
    
    Args:
        date_str (str): Date in MM/DD/YYYY format
        
    Returns:
        str: Date in YYYYMMDD format
        
    Raises:
        ValueError: If date format is invalid
    """
    try:
        date_obj = datetime.strptime(date_str, "%m/%d/%Y")
        return date_obj.strftime("%Y%m%d")
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected MM/DD/YYYY, got: {date_str}") from e


def find_t1w_scan(patient_id: str, scan_date: str, base_path: str) -> Optional[str]:
    """
    Find the T1w scan file for a given patient ID and scan date.
    
    Args:
        patient_id (str): Patient ID (e.g., "110001")
        scan_date (str): Scan date in MM/DD/YYYY format
        base_path (str): Base path to the scan folder
        
    Returns:
        Optional[str]: Full path to the T1w scan file if found, None otherwise
    """
    try:
        # Convert date format
        formatted_date = convert_date_format(scan_date)
        
        # Construct the expected path
        scan_path = Path(base_path) / patient_id / formatted_date / "anat"
        expected_filename = f"{patient_id}-{formatted_date}_T1w.nii"
        full_path = scan_path / expected_filename
        
        # Check if the file exists
        if full_path.exists():
            return str(full_path)
        else:
            return None
            
    except ValueError as e:
        print(f"Error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while searching for T1w scan: {e}")
        return None


def find_pet_scan(patient_id: str, scan_date: str, base_path: str) -> Optional[str]:
    """
    Find the PET scan file for a given patient ID and scan date.
    
    Args:
        patient_id (str): Patient ID (e.g., "110002")
        scan_date (str): Scan date in MM/DD/YYYY format
        base_path (str): Base path to the scan folder
        
    Returns:
        Optional[str]: Full path to the PET scan file if found, None otherwise
    """
    try:
        # Convert date format
        formatted_date = convert_date_format(scan_date)
        
        # Construct the expected path
        scan_path = Path(base_path) / patient_id / formatted_date / "pet"
        expected_filename = f"{patient_id}-{formatted_date}_PET.nii"
        full_path = scan_path / expected_filename
        
        # Check if the file exists
        if full_path.exists():
            return str(full_path)
        else:
            return None
            
    except ValueError as e:
        print(f"Error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while searching for PET scan: {e}")
        return None


def find_scan(patient_id: str, scan_date: str, base_path: str, scan_type: str) -> Optional[str]:
    """
    Find a scan file based on the scan type.
    
    Args:
        patient_id (str): Patient ID
        scan_date (str): Scan date in MM/DD/YYYY format
        base_path (str): Base path to the scan folder
        scan_type (str): Either "t1w" or "pet"
        
    Returns:
        Optional[str]: Full path to the scan file if found, None otherwise
    """
    if scan_type.lower() == "t1w":
        return find_t1w_scan(patient_id, scan_date, base_path)
    elif scan_type.lower() == "pet":
        return find_pet_scan(patient_id, scan_date, base_path)
    else:
        raise ValueError(f"Invalid scan type: {scan_type}. Must be 't1w' or 'pet'")


def copy_scan_file(source_path: str, dest_folder: str, preserve_structure: bool = False) -> str:
    """
    Copy a scan file to the destination folder.
    
    Args:
        source_path (str): Path to the source file
        dest_folder (str): Destination folder path
        preserve_structure (bool): If True, preserve the original folder structure
        
    Returns:
        str: Path to the copied file
    """
    source = Path(source_path)
    dest_dir = Path(dest_folder)
    
    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    if preserve_structure:
        # Extract patient_id and date from the source path
        # Expected structure: .../patient_id/YYYYMMDD/scan_type/filename
        parts = source.parts
        if len(parts) >= 3:
            patient_id = parts[-4]
            scan_date = parts[-3]
            scan_type = parts[-2]
            
            # Create subdirectory structure in destination
            subdir = dest_dir / patient_id / scan_date / scan_type
            subdir.mkdir(parents=True, exist_ok=True)
            dest_path = subdir / source.name
        else:
            dest_path = dest_dir / source.name
    else:
        dest_path = dest_dir / source.name
    
    # Copy the file
    shutil.copy2(source, dest_path)
    return str(dest_path)


def process_csv(csv_file: str, source_folder: str, dest_folder: str, scan_type: str, 
                preserve_structure: bool = False, verbose: bool = False) -> List[Tuple[str, str, str, str]]:
    """
    Process the CSV file and copy scan files.
    
    Args:
        csv_file (str): Path to the CSV file
        source_folder (str): Source folder containing scans
        dest_folder (str): Destination folder for copied scans
        scan_type (str): Type of scan to copy ("t1w" or "pet")
        preserve_structure (bool): Whether to preserve folder structure
        verbose (bool): Enable verbose output
        
    Returns:
        List[Tuple[str, str, str, str]]: List of (patient_id, scan_date, status, path) tuples
    """
    try:
        # Read CSV file
        df = pd.read_csv(csv_file)
        
        if df.shape[1] < 2:
            raise ValueError("CSV file must have at least 2 columns (patient_id, scan_date)")
        
        # Get the first two columns
        patient_ids = df.iloc[:, 0].astype(str)
        scan_dates = df.iloc[:, 1].astype(str)
        
        results = []
        total_scans = len(patient_ids)
        found_count = 0
        copied_count = 0
        
        if verbose:
            print(f"Processing {total_scans} scans from {csv_file}")
            print(f"Scan type: {scan_type.upper()}")
            print(f"Source folder: {source_folder}")
            print(f"Destination folder: {dest_folder}")
            print(f"Preserve structure: {preserve_structure}")
            print("-" * 50)
        
        for i, (patient_id, scan_date) in enumerate(zip(patient_ids, scan_dates), 1):
            try:
                # Clean up patient_id (remove any decimal points if it was read as float)
                patient_id = str(patient_id).split('.')[0]
                
                if verbose:
                    print(f"[{i}/{total_scans}] Processing patient {patient_id}, date {scan_date}")
                
                # Find the scan file
                scan_path = find_scan(patient_id, scan_date, source_folder, scan_type)
                
                if scan_path:
                    found_count += 1
                    if verbose:
                        print(f"  ✅ Found: {scan_path}")
                    
                    try:
                        # Copy the file
                        copied_path = copy_scan_file(scan_path, dest_folder, preserve_structure)
                        copied_count += 1
                        results.append((patient_id, scan_date, "copied", copied_path))
                        
                        if verbose:
                            print(f"  📋 Copied to: {copied_path}")
                    
                    except Exception as e:
                        print(f"  ❌ Error copying file: {e}")
                        results.append((patient_id, scan_date, "copy_failed", scan_path))
                
                else:
                    if verbose:
                        print(f"  ❌ Not found")
                    results.append((patient_id, scan_date, "not_found", ""))
            
            except Exception as e:
                print(f"  ❌ Error processing patient {patient_id}: {e}")
                results.append((patient_id, scan_date, "error", ""))
        
        # Print summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Total patients processed: {total_scans}")
        print(f"Scans found: {found_count}")
        print(f"Scans successfully copied: {copied_count}")
        print(f"Scans not found: {total_scans - found_count}")
        print(f"Copy failures: {found_count - copied_count}")
        
        return results
        
    except Exception as e:
        print(f"Error processing CSV file: {e}")
        sys.exit(1)


def save_results_report(results: List[Tuple[str, str, str, str]], output_file: str):
    """
    Save the processing results to a CSV report.
    
    Args:
        results: List of (patient_id, scan_date, status, path) tuples
        output_file: Path to save the report
    """
    df_results = pd.DataFrame(results, columns=['patient_id', 'scan_date', 'status', 'path'])
    df_results.to_csv(output_file, index=False)
    print(f"\n📊 Results report saved to: {output_file}")


def main():
    """
    Command-line interface for batch scan copying.
    """
    parser = argparse.ArgumentParser(
        description="Process CSV file to find and copy scan files (T1w or PET)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -i scans.csv -s /data/ADRC -d /tmp/copied_scans -t t1w
  %(prog)s -i patients.csv -s /path/to/scans -d /output -t pet --preserve-structure -v
  
CSV Format:
  The CSV file should have at least 2 columns:
  - Column 1: Patient ID (e.g., 110001)
  - Column 2: Scan date in MM/DD/YYYY format (e.g., 01/15/2020)
  
Expected source folder structure:
  {source}/{patient_id}/{YYYYMMDD}/anat/{patient_id}-{YYYYMMDD}_T1w.nii    (for T1w)
  {source}/{patient_id}/{YYYYMMDD}/pet/{patient_id}-{YYYYMMDD}_PET.nii     (for PET)
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='Input CSV file containing patient IDs and scan dates'
    )
    
    parser.add_argument(
        '-s', '--source',
        required=True,
        help='Source folder path containing the scan files'
    )
    
    parser.add_argument(
        '-d', '--destination',
        required=True,
        help='Destination folder path to copy the scan files'
    )
    
    parser.add_argument(
        '-t', '--type',
        choices=['t1w', 'pet'],
        required=True,
        help='Type of scan to copy (t1w or pet)'
    )
    
    parser.add_argument(
        '--preserve-structure',
        action='store_true',
        help='Preserve the original folder structure in destination'
    )
    
    parser.add_argument(
        '-r', '--report',
        help='Save processing results to a CSV report file'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Validate input files and folders
    csv_path = Path(args.input)
    if not csv_path.exists():
        print(f"Error: CSV file does not exist: {args.input}")
        sys.exit(1)
    
    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: Source folder does not exist: {args.source}")
        sys.exit(1)
    
    # Process the CSV file
    results = process_csv(
        args.input,
        args.source,
        args.destination,
        args.type,
        args.preserve_structure,
        args.verbose
    )
    
    # Save results report if requested
    if args.report:
        save_results_report(results, args.report)


if __name__ == "__main__":
    main()