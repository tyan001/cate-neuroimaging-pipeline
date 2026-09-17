#!/usr/bin/env python3
"""
Bulk-add a modality prefix (e.g. 'MRI_', 'PET_') to immediate subfolder names. Needed
for sites that deliver without the modality prefix (for us, the 320 UF subjects).
Skips any subfolder that already has the prefix, so it's safe to re-run.

Usage:
    python3 prefix.py /path/to/MRI --prefix MRI_ --dry-run   # preview
    python3 prefix.py /path/to/MRI --prefix MRI_             # apply
    python3 prefix.py /path/to/PET --prefix PET_             # different modality
"""

import argparse
import os


def rename_folders_with_prefix(parent_dir, prefix="MRI_", dry_run=False):
    """
    Rename all subfolders in a given directory by adding a prefix to their names.
    
    This utility helps standardize folder naming conventions, particularly useful
    for organizing medical imaging or other datasets where consistent naming
    is important. The script only affects immediate subfolders of the parent
    directory and skips any folders that already have the specified prefix.
    
    Args:
        parent_dir (str): Path to the parent directory containing subfolders to rename
        prefix (str, optional): Prefix to add to folder names. Defaults to "MRI_"
        dry_run (bool, optional): If True, only show what would be done without 
                                  making actual changes. Useful for previewing
                                  the renaming operation. Defaults to False
    
    Returns:
        None
        
    Prints:
        - Number of folders found in the directory
        - Number of folders that already have the prefix
        - Results of each rename operation (success or failure)
        - Summary of changes made
        
    Example:
        >>> rename_folders_with_prefix("/path/to/scans", "MRI_", dry_run=True)
        Found 5 subfolders in /path/to/scans
        2 folders already have the prefix 'MRI_'
        Would rename: patient001 -> MRI_patient001
        Would rename: patient002 -> MRI_patient002
        Would rename: patient003 -> MRI_patient003
    """
    # Get all immediate subfolders in the parent directory
    try:
        items = os.listdir(parent_dir)
        folders = [item for item in items if os.path.isdir(os.path.join(parent_dir, item))]
        
        if not folders:
            print(f"No subfolders found in {parent_dir}")
            return
            
        print(f"Found {len(folders)} subfolders in {parent_dir}")
        
        # Count folders that already have the prefix
        already_prefixed = sum(1 for folder in folders if folder.startswith(prefix))
        if already_prefixed > 0:
            print(f"{already_prefixed} folders already have the prefix '{prefix}'")
        
        # Rename each subfolder
        renamed_count = 0
        for folder in folders:
            old_path = os.path.join(parent_dir, folder)
            
            # Skip folders that already have the prefix
            if folder.startswith(prefix):
                continue
                
            new_name = f"{prefix}{folder}"
            new_path = os.path.join(parent_dir, new_name)
            
            if dry_run:
                print(f"Would rename: {folder} -> {new_name}")
            else:
                try:
                    os.rename(old_path, new_path)
                    print(f"Renamed: {folder} -> {new_name}")
                    renamed_count += 1
                except Exception as e:
                    print(f"Error renaming {folder}: {e}")
        
        if not dry_run:
            print(f"\nSuccessfully renamed {renamed_count} folders")
        
    except Exception as e:
        print(f"Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Rename subfolders by adding a prefix")
    parser.add_argument("directory", help="Parent directory containing subfolders to rename")
    parser.add_argument("--prefix", default="MRI_", help="Prefix to add to folder names (default: MRI_)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    
    args = parser.parse_args()
    
    # Check if the directory exists
    if not os.path.exists(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        return
    
    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        return
    
    rename_folders_with_prefix(args.directory, args.prefix, args.dry_run)

if __name__ == "__main__":
    main()