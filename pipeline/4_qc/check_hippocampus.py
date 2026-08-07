import argparse
from pathlib import Path

def check_hippocampus_done(base_dir):
    """
    Check for hippocampal-subfields-T1.log files in the specified directory.

    This function searches for 'hippocampal-subfields-T1.log' files within the FreeSurfer
    subject directories. It prints the locations where the log file is found and where it's missing.

    Args:
        base_dir (str or Path): The base directory to search for FreeSurfer subject data.

    Returns:
        None

    Prints:
        - A message for each directory containing the hippocampal-subfields-T1.log file.
        - A message for each directory missing the hippocampal-subfields-T1.log file.
        - The total number of directories checked and how many have completed processing.
    """
    
    base_path = Path(base_dir)
    log_files = list(base_path.glob('*/*/freesurfer741/*/scripts/hippocampal-subfields-T1.log'))
    
    completed_dirs = set()
    for log_file in log_files:
        subject_dir = log_file.parents[4]  # Navigate up to the subject directory
        completed_dirs.add(subject_dir)
        print(f"Hippocampal subfields processing completed: {subject_dir}")
    
    all_subject_dirs = set(path.parents[4] for path in base_path.glob('*/*/freesurfer741'))
    missing_dirs = all_subject_dirs - completed_dirs
    
    for dir in missing_dirs:
        print(f"Hippocampal subfields processing needed: {dir}")
    
    print(f"\nTotal directories checked: {len(all_subject_dirs)}")
    print(f"Directories with completed processing: {len(completed_dirs)}")
    print(f"Directories needing processing: {len(missing_dirs)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check for hippocampal-subfields-T1.log files in subject directories.")
    parser.add_argument("base_dir", help="Path to the FreeSurfer subjects directory")
    args = parser.parse_args()

    check_hippocampus_done(args.base_dir)