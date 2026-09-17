import argparse
from pathlib import Path

def check_freesurfer_errors(base_dir):
    
    """
    Check for FreeSurfer error files in the specified directory.

    This function searches for 'recon-all.error' files within the FreeSurfer
    subject directories. It prints the locations of any error files found
    and provides a count of the total number of errors.

    Args:
        base_dir (str or Path): The base directory to search for FreeSurfer subject data.

    Returns:
        None

    Prints:
        - A message for each directory containing an error file.
        - The total number of error files found.
        - A message if no error files are found.
    """
    
    base_path = Path(base_dir)
    error_files = list(base_path.glob('*/*/freesurfer741/*/scripts/recon-all.error'))
    
    if not error_files:
        print("No error files found.")
        return

    print("Error files found in the following directories:")
    for error_file in error_files:
        subject_dir = error_file.parents[1] 
        subject_name = subject_dir.name
        print(f"{base_path / subject_name}")
    
    print(f"\nTotal error files found: {len(error_files)}")
    

def check_hippocampus_done(base_dir):
    
    """
    Check for FreeSurfer error files in the specified directory.

    This function searches for 'recon-all.error' files within the FreeSurfer
    subject directories. It prints the locations of any error files found
    and provides a count of the total number of errors.

    Args:
        base_dir (str or Path): The base directory to search for FreeSurfer subject data.

    Returns:
        None

    Prints:
        - A message for each directory containing an error file.
        - The total number of error files found.
        - A message if no error files are found.
    """
    
    base_path = Path(base_dir)
    error_files = list(base_path.glob('*/*/freesurfer741/*/scripts/hippocampal-subfields-T1.log'))
    
    if not error_files:
        print("No hippocampal-subfields-T1.log files found. Needs to be processed.")
        return

    print("Error files found in the following directories:")
    for error_file in error_files:
        subject_dir = error_file.parents[1] 
        subject_name = subject_dir.name
        print(f"{base_path / subject_name}")
    
    print(f"\nTotal error files found: {len(error_files)}")

if __name__ == "__main__":
    
    """
    FreeSurfer Error Checker

    This script checks for the presence of FreeSurfer error files (recon-all.error) in subject directories.
    It traverses through a specified base directory to locate and report on these error files.

    Functions:
        check_freesurfer_errors(base_dir: str or Path) -> None:
            Searches for FreeSurfer error files and prints the results.

    Arguments:
        base_dir (str or Path): The base directory containing FreeSurfer subject data.

    Output:
        - Prints the directories where error files were found.
        - Prints the total number of error files found.
        - If no error files are found, it prints a message indicating so.

    Note:
        This script assumes a specific directory structure:
        base_dir/subject_id/scan_date/freesurfer741/fs7_output/scripts/recon-all.error
        ex:
            ADRC/110001/20250303101346/freesurfer741/subjID_fs7_output_folder/scripts/recon-all.error
    Example:
        $ python check_error.py path/to/ADRC_FOLDER/
    """
    
    parser = argparse.ArgumentParser(description="Check for FreeSurfer error files in subject directories.")
    parser.add_argument("base_dir", help="Path to the FreeSurfer subjects directory")
    args = parser.parse_args()

    check_freesurfer_errors(args.base_dir)