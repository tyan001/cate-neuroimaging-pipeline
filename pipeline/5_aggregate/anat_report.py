#!/usr/bin/env python3
"""
MRI File Scanner and XLSX Exporter

This script scans a directory for 'anat' folders, finds MRI scans (.nii files) 
within them, and exports the information to an Excel file (XLSX) with columns for the 
full filename, SubjID, Scandate, and modality.
"""

import os
import re
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime


def find_anat_folders(root_dir):
    """Find all 'anat' folders within the root directory."""
    anat_folders = []
    
    # Walk through the directory tree
    for dirpath, dirnames, _ in os.walk(root_dir):
        # Check if 'anat' is in the current directory names
        if 'anat' in dirnames:
            anat_path = os.path.join(dirpath, 'anat')
            anat_folders.append(anat_path)
    
    return anat_folders


def extract_file_info(filename):
    """
    Extract SubjID, Scandate, and modality from the filename.
    Expected format: SubjID-scandate_modality.nii
    """
    # Remove .nii extension
    base_name = os.path.splitext(filename)[0]
    
    # Split on underscore to separate modality
    parts = base_name.split('_')
    
    if len(parts) != 2:
        # If the format doesn't match expectations, return None values
        return None, None, None
    
    id_date_part, modality = parts
    
    # Split the ID and date part on hyphen
    id_date_parts = id_date_part.split('-')
    
    if len(id_date_parts) != 2:
        # If the format doesn't match expectations, return None values
        return None, None, None
    
    subj_id, scandate = id_date_parts
    
    return subj_id, scandate, modality


def scan_mri_files(root_dir, output_xlsx):
    """
    Scan for MRI files in 'anat' folders and export info to Excel file.
    """
    # Find all anat folders
    anat_folders = find_anat_folders(root_dir)
    
    # Create a list to hold all the data
    data = []
    
    # Process each anat folder
    for folder in anat_folders:
        # List all .nii files in the folder
        nii_files = [f for f in os.listdir(folder) if f.endswith('.nii')]
        
        # Process each file
        for nii_file in nii_files:
            # Extract information from filename
            subj_id, scandate, modality = extract_file_info(nii_file)
            
            # Get full file path
            file_path = os.path.join(folder, nii_file)
            
            # Add to data list
            data.append({
                'Filename': nii_file,
                'SubjID': subj_id,
                'Scandate': scandate,
                'Modality': modality,
                'Filepath': file_path
            })
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    df.sort_values(['SubjID', 'Scandate'], inplace=True)
    
    # Export to Excel
    df.to_csv(output_xlsx, index=False)
    
    return len(anat_folders)


def main():
    # Get current date for filename
    current_date = datetime.now().strftime("%Y-%m-%d")
    default_filename = f"mri_scans_{current_date}.csv"
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Scan for MRI files in anat folders and export info to Excel')
    parser.add_argument('root_dir', help='Root directory to start searching from')
    parser.add_argument('-o', '--output', default=default_filename, 
                        help=f'Output Excel file (default: {default_filename})')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Convert to absolute path
    root_dir = os.path.abspath(args.root_dir)
    
    # Run the scanner
    print(f"Scanning for 'anat' folders in {root_dir}...")
    folder_count = scan_mri_files(root_dir, args.output)
    
    # Print summary
    print(f"Scan complete. Processed {folder_count} 'anat' folders.")
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()