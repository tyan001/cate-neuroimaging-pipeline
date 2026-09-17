#!/usr/bin/env python3
"""
T1w Scan Finder Script

This script finds T1w scan files based on patient ID and scan dates.
The input date format is MM/DD/YYYY, which gets converted to YYYYMMDD to match the ADRC folder structure.

Author: GitHub Copilot
Date: October 1, 2025
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional


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


def main():
    """
    Command-line interface for T1w scan finder.
    """
    parser = argparse.ArgumentParser(
        description="Find T1w scan files based on patient ID and scan date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --folder /data/ADRC --patient 110001 --date 01/15/2020
  %(prog)s -f /path/to/scans -p 110001 -d 01/15/2020
  
Expected folder structure:
  {folder}/{patient_id}/{YYYYMMDD}/anat/{patient_id}-{YYYYMMDD}_T1w.nii
        """
    )
    
    parser.add_argument(
        '-f', '--folder', 
        required=True,
        help='Base folder path to search for T1w scans'
    )
    
    parser.add_argument(
        '-p', '--patient',
        required=True,
        help='Patient ID (e.g., 110001)'
    )
    
    parser.add_argument(
        '-d', '--date',
        required=True,
        help='Scan date in MM/DD/YYYY format (e.g., 01/15/2020)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Check if folder exists
    if not Path(args.folder).exists():
        print(f"Error: Folder does not exist: {args.folder}")
        sys.exit(1)
    
    if args.verbose:
        print(f"Searching for T1w scan:")
        print(f"  Folder: {args.folder}")
        print(f"  Patient: {args.patient}")
        print(f"  Date: {args.date}")
        print()
    
    # Find T1w scan
    result = find_t1w_scan(args.patient, args.date, args.folder)
    
    if result:
        if args.verbose:
            print("✅ T1w scan found:")
        print(result)
    else:
        if args.verbose:
            print(f"❌ T1w scan not found for patient {args.patient} on {args.date}")
            
            # Try to provide helpful information
            try:
                formatted_date = convert_date_format(args.date)
                expected_path = Path(args.folder) / args.patient / formatted_date / "anat"
                expected_file = f"{args.patient}-{formatted_date}_T1w.nii"
            except ValueError:
                # If date conversion fails, we can't provide expected path info
                sys.exit(1)
            
            print(f"\nExpected location:")
            print(f"  Directory: {expected_path}")
            print(f"  Filename: {expected_file}")
            
            if expected_path.exists():
                print(f"\n📁 Directory exists, but T1w file not found.")
                print("Files in anat directory:")
                for file_path in expected_path.iterdir():
                    print(f"  - {file_path.name}")
            else:
                print(f"\n📁 Directory does not exist: {expected_path}")
                patient_dir = Path(args.folder) / args.patient
                if patient_dir.exists():
                    print(f"Available scan dates for patient {args.patient}:")
                    for date_dir in sorted(patient_dir.iterdir()):
                        if date_dir.is_dir() and date_dir.name != "logs":
                            try:
                                date_obj = datetime.strptime(date_dir.name, "%Y%m%d")
                                formatted = date_obj.strftime("%m/%d/%Y")
                                print(f"  - {formatted} ({date_dir.name})")
                            except ValueError:
                                continue
        sys.exit(1)


if __name__ == "__main__":
    main()