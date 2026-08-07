#!/usr/bin/env python
"""
Script to find all 'anat' folders, check NIFTI files within them,
and record files where the matrix dimensions are the same in all three axes.
"""

import os
import csv
import nibabel as nib
import argparse

def find_anat_folders(root_dir):
    """Find all folders named 'anat' under the given root directory"""
    anat_folders = []
    for dirpath, dirnames, _ in os.walk(root_dir):
        if 'anat' in dirnames:
            anat_folders.append(os.path.join(dirpath, 'anat'))
    return anat_folders

def check_nifti_dimensions(anat_folders):
    """
    Check all NIFTI files in the found anat folders and record those 
    where the matrix dimensions are the same in all three axes
    """
    isotropic_matrix_files = []
    
    for folder in anat_folders:
        for file in os.listdir(folder):
            if file.endswith('.nii') or file.endswith('.nii.gz'):
                file_path = os.path.join(folder, file)
                try:
                    img = nib.load(file_path)
                    matrix_dims = img.header.get_data_shape()
                    
                    # Check if all three dimensions are equal
                    if len(matrix_dims) >= 3:
                        is_isotropic = matrix_dims[0] == matrix_dims[1] == matrix_dims[2]
                        
                        if is_isotropic:
                            isotropic_matrix_files.append({
                                'filename': file,
                                'path': file_path,
                                'matrix_size': matrix_dims[0]  # Same in all 3 dimensions
                            })
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
    
    return isotropic_matrix_files

def write_to_csv(isotropic_files, output_file):
    """Write the list of files with isotropic matrix dimensions to a CSV file"""
    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['filename', 'path', 'matrix_size']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for file_info in isotropic_files:
            writer.writerow(file_info)

def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Find NIFTI files with isotropic matrix dimensions')
    parser.add_argument('root_dir', help='Root directory to start the search')
    parser.add_argument('--output', '-o', default='isotropic_matrix_files.csv',
                        help='Output CSV file (default: isotropic_matrix_files.csv)')
    
    args = parser.parse_args()
    
    # Find all anat folders
    print(f"Searching for 'anat' folders under {args.root_dir}...")
    anat_folders = find_anat_folders(args.root_dir)
    print(f"Found {len(anat_folders)} 'anat' folders")
    
    # Check NIFTI files
    print("Checking NIFTI file matrix dimensions...")
    isotropic_files = check_nifti_dimensions(anat_folders)
    print(f"Found {len(isotropic_files)} NIFTI files with isotropic matrix dimensions")
    
    # Write results to CSV
    write_to_csv(isotropic_files, args.output)
    print(f"Results written to {args.output}")

if __name__ == "__main__":
    main()