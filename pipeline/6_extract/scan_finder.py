#!/usr/bin/env python3
"""
Scan Finder Script

This script provides functions to find T1w and PET scan files based on patient ID and scan dates.
The input date format is MM/DD/YYYY, which gets converted to YYYYMMDD to match the ADRC folder structure.

Author: GitHub Copilot
Date: October 1, 2025
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# Root of the organized dataset (see docs/04-data-organization.md).
# Override per-call with the base_path argument, on the CLI with -f/--folder,
# or globally by exporting ADRC_ROOT.
DEFAULT_ADRC_ROOT = os.environ.get("ADRC_ROOT", "")


def convert_date_format(date_str: str) -> str:
    """
    Convert date from MM/DD/YYYY format to YYYYMMDD format.
    
    Args:
        date_str (str): Date in MM/DD/YYYY format
        
    Returns:
        str: Date in YYYYMMDD format
        
    Raises:
        ValueError: If date format is invalid
        
    Example:
        >>> convert_date_format("01/15/2020")
        '20200115'
    """
    try:
        # Parse the MM/DD/YYYY format
        date_obj = datetime.strptime(date_str, "%m/%d/%Y")
        # Convert to YYYYMMDD format
        return date_obj.strftime("%Y%m%d")
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected MM/DD/YYYY, got: {date_str}") from e


def find_t1w_scan(patient_id: str, scan_date: str, base_path: str = DEFAULT_ADRC_ROOT) -> Optional[str]:
    """
    Find the T1w scan file for a given patient ID and scan date.
    
    Args:
        patient_id (str): Patient ID (e.g., "110001")
        scan_date (str): Scan date in MM/DD/YYYY format
        base_path (str): Base path to the ADRC folder
        
    Returns:
        Optional[str]: Full path to the T1w scan file if found, None otherwise
        
    Example:
        >>> find_t1w_scan("110001", "01/15/2020")
        '/data/ADRC/110001/20200115/anat/110001-20200115_T1w.nii'
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
            print(f"T1w scan not found: {full_path}")
            return None
            
    except ValueError as e:
        print(f"Error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while searching for T1w scan: {e}")
        return None


def find_pet_scan(patient_id: str, scan_date: str, base_path: str = DEFAULT_ADRC_ROOT) -> Optional[str]:
    """
    Find the PET scan file for a given patient ID and scan date.
    
    Args:
        patient_id (str): Patient ID (e.g., "110002")
        scan_date (str): Scan date in MM/DD/YYYY format
        base_path (str): Base path to the ADRC folder
        
    Returns:
        Optional[str]: Full path to the PET scan file if found, None otherwise
        
    Example:
        >>> find_pet_scan("110002", "03/10/2020")
        '/data/ADRC/110002/20200310/pet/110002-20200310_PET.nii'
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
            print(f"PET scan not found: {full_path}")
            return None
            
    except ValueError as e:
        print(f"Error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while searching for PET scan: {e}")
        return None


def list_available_dates(patient_id: str, base_path: str = DEFAULT_ADRC_ROOT) -> List[str]:
    """
    List all available scan dates for a given patient ID.
    
    Args:
        patient_id (str): Patient ID (e.g., "110001")
        base_path (str): Base path to the ADRC folder
        
    Returns:
        List[str]: List of available dates in MM/DD/YYYY format
        
    Example:
        >>> list_available_dates("110001")
        ['01/15/2020', '03/10/2020', '07/22/2021']
    """
    try:
        patient_path = Path(base_path) / patient_id
        
        if not patient_path.exists():
            print(f"Patient folder not found: {patient_path}")
            return []
        
        dates = []
        for item in patient_path.iterdir():
            if item.is_dir() and item.name != "logs":
                try:
                    # Convert YYYYMMDD to MM/DD/YYYY
                    date_obj = datetime.strptime(item.name, "%Y%m%d")
                    formatted_date = date_obj.strftime("%m/%d/%Y")
                    dates.append(formatted_date)
                except ValueError:
                    # Skip folders that don't match YYYYMMDD format
                    continue
        
        return sorted(dates)
        
    except Exception as e:
        print(f"Error listing dates for patient {patient_id}: {e}")
        return []


def find_scan_by_type(patient_id: str, scan_date: str, scan_type: str, base_path: str = DEFAULT_ADRC_ROOT) -> Optional[str]:
    """
    Generic function to find scans by type (T1w or PET).
    
    Args:
        patient_id (str): Patient ID
        scan_date (str): Scan date in MM/DD/YYYY format
        scan_type (str): Either "T1w" or "PET"
        base_path (str): Base path to the ADRC folder
        
    Returns:
        Optional[str]: Full path to the scan file if found, None otherwise
    """
    if scan_type.upper() == "T1W":
        return find_t1w_scan(patient_id, scan_date, base_path)
    elif scan_type.upper() == "PET":
        return find_pet_scan(patient_id, scan_date, base_path)
    else:
        print(f"Unsupported scan type: {scan_type}. Use 'T1w' or 'PET'")
        return None


def main():
    """
    Command-line interface for the scan finder functions.
    """
    parser = argparse.ArgumentParser(
        description="Find T1w and PET scan files based on patient ID and scan date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --folder /path/to/scans --patient 110001 --date 01/15/2020 --type T1w
  %(prog)s -f /data/ADRC -p 110002 -d 03/10/2020 -t PET
  %(prog)s --folder /path/to/scans --patient 110001 --list-dates
        """
    )
    
    parser.add_argument(
        '-f', '--folder', 
        required=True,
        help='Base folder path to search for scans (e.g., /data/ADRC)'
    )
    
    parser.add_argument(
        '-p', '--patient',
        required=True,
        help='Patient ID (e.g., 110001)'
    )
    
    parser.add_argument(
        '-d', '--date',
        help='Scan date in MM/DD/YYYY format (e.g., 01/15/2020)'
    )
    
    parser.add_argument(
        '-t', '--type',
        choices=['T1w', 'PET', 't1w', 'pet'],
        help='Type of scan to find (T1w or PET)'
    )
    
    parser.add_argument(
        '--list-dates',
        action='store_true',
        help='List all available scan dates for the patient'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.list_dates and (not args.date or not args.type):
        parser.error("Either --list-dates must be specified, or both --date and --type are required")
    
    # Check if folder exists
    if not Path(args.folder).exists():
        print(f"Error: Folder does not exist: {args.folder}")
        sys.exit(1)
    
    if args.list_dates:
        # List available dates
        print(f"Searching for available dates for patient {args.patient} in {args.folder}")
        dates = list_available_dates(args.patient, args.folder)
        
        if dates:
            print(f"\nAvailable scan dates for patient {args.patient}:")
            for i, date in enumerate(dates, 1):
                print(f"  {i}. {date}")
        else:
            print(f"No scan dates found for patient {args.patient}")
            sys.exit(1)
    
    else:
        # Find specific scan
        scan_type = args.type.upper()
        print(f"Searching for {scan_type} scan for patient {args.patient} on {args.date} in {args.folder}")
        
        if scan_type == "T1W":
            result = find_t1w_scan(args.patient, args.date, args.folder)
        elif scan_type == "PET":
            result = find_pet_scan(args.patient, args.date, args.folder)
        
        if result:
            print(f"\n✅ {scan_type} scan found:")
            print(f"   {result}")
        else:
            print(f"\n❌ {scan_type} scan not found for patient {args.patient} on {args.date}")
            sys.exit(1)


if __name__ == "__main__":
    main()