#!/usr/bin/env python3

import os
import sys
import subprocess
import datetime
import argparse
from pathlib import Path
import multiprocessing
import time
from functools import partial
import queue
import threading
import traceback

def check_freesurfer():
    """Check if FreeSurfer is properly initialized."""
    if not os.environ.get('FREESURFER_HOME'):
        print("ERROR: FreeSurfer environment is not initialized.")
        print("Please run 'source $FREESURFER_HOME/SetUpFreeSurfer.sh' before executing this script.")
        return False
    
    # Check if required commands exist
    try:
        subprocess.run(['which', 'mri_convert'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(['which', 'mris_convert'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print("ERROR: mri_convert or mris_convert not found.")
        print("Please make sure FreeSurfer is properly installed and in your PATH.")
        return False
    
    return True

def convert_mri_files(mri_dir, output_dir, log_queue, force=False):
    """Convert MGZ files to NIfTI format."""
    mri_files = ["T1.mgz", "aparc+aseg.mgz", "brain.mgz", "wm.mgz"]
    success_count = 0
    already_converted = 0
    
    for mri_file in mri_files:
        input_path = os.path.join(mri_dir, mri_file)
        if not os.path.isfile(input_path):
            log_queue.put(f"  Warning: {mri_file} not found in {mri_dir}")
            continue
        
        output_filename = f"{os.path.splitext(mri_file)[0]}.nii"
        output_path = os.path.join(output_dir, output_filename)
        
        # Check if output file already exists
        if os.path.isfile(output_path) and not force:
            already_converted += 1
            continue
        
        log_queue.put(f"  Converting {mri_file} to {output_filename}")
        
        try:
            subprocess.run(['mri_convert', input_path, output_path], 
                           check=True, 
                           stdout=subprocess.PIPE, 
                           stderr=subprocess.PIPE)
            success_count += 1
            log_queue.put(f"    Success: {output_path}")
        except subprocess.CalledProcessError as e:
            log_queue.put(f"    Failed to convert {mri_file}: {e}")
    
    return success_count, already_converted

def convert_surf_files(surf_dir, output_dir, log_queue, force=False):
    """Convert surface files to GIFTI format."""
    surf_files = ["lh.pial", "lh.white", "rh.pial", "rh.white"]
    success_count = 0
    already_converted = 0
    
    for surf_file in surf_files:
        input_path = os.path.join(surf_dir, surf_file)
        if not os.path.isfile(input_path):
            log_queue.put(f"  Warning: {surf_file} not found in {surf_dir}")
            continue
        
        output_filename = f"{surf_file}.gii"
        output_path = os.path.join(output_dir, output_filename)
        
        # Check if output file already exists
        if os.path.isfile(output_path) and not force:
            already_converted += 1
            continue
        
        log_queue.put(f"  Converting {surf_file} to {output_filename}")
        
        try:
            subprocess.run(['mris_convert', '-ot', 'nii', input_path, output_path], 
                           check=True, 
                           stdout=subprocess.PIPE, 
                           stderr=subprocess.PIPE)
            success_count += 1
            log_queue.put(f"    Success: {output_path}")
        except subprocess.CalledProcessError as e:
            log_queue.put(f"    Failed to convert {surf_file}: {e}")
    
    return success_count, already_converted

def process_subject(subject_data, log_queue, force=False):
    """Process a single subject in parallel."""
    fs_dir, subject_dir, output_path, force = subject_data
    
    try:
        subject_path = os.path.join(fs_dir, subject_dir)
        subject_name = os.path.basename(subject_path)
        
        # Create output directories for this subject, maintaining original folder name
        # subject_output = os.path.join(output_path, subject_name)
        mri_output = os.path.join(output_path, "mri")
        surf_output = os.path.join(output_path, "surf")
        
        os.makedirs(mri_output, exist_ok=True)
        os.makedirs(surf_output, exist_ok=True)
        
        failures = 0
        new_conversions = 0
        already_converted = 0
        
        # Process MRI files
        mri_dir = os.path.join(subject_path, "mri")
        if os.path.isdir(mri_dir):
            mri_success, mri_already = convert_mri_files(mri_dir, mri_output, log_queue, force)
            already_converted += mri_already
            new_conversions += mri_success
            if mri_success + mri_already < 4:  # Not all MRI files were converted successfully
                failures += (4 - mri_success - mri_already)
        else:
            log_queue.put(f"  Warning: MRI directory not found for {subject_name}")
        
        # Process surface files
        surf_dir = os.path.join(subject_path, "surf")
        if os.path.isdir(surf_dir):
            surf_success, surf_already = convert_surf_files(surf_dir, surf_output, log_queue, force)
            already_converted += surf_already
            new_conversions += surf_success
            if surf_success + surf_already < 4:  # Not all surface files were converted successfully
                failures += (4 - surf_success - surf_already)
        else:
            log_queue.put(f"  Warning: Surface directory not found for {subject_name}")
        
        # Only log completion message if any new conversions were made
        if new_conversions > 0:
            log_queue.put(f"Processing subject: {subject_name}")
            log_queue.put(f"  Completed processing for {subject_name}: {new_conversions} new files, {already_converted} previously converted\n")
        
        return (new_conversions > 0, new_conversions, already_converted, failures)  # (worked_on, new_count, already_count, failure_count)
    
    except Exception as e:
        log_queue.put(f"ERROR processing {subject_dir}: {e}")
        log_queue.put(traceback.format_exc())
        return (False, 0, 0, 8)  # Count all possible conversions as failures

def log_writer(log_queue, log_file):
    """Thread function to write logs from queue to file."""
    with open(log_file, 'a') as f:
        while True:
            try:
                message = log_queue.get()
                if message == "DONE":
                    break
                print(message)
                f.write(message + '\n')
                f.flush()
                log_queue.task_done()
            except Exception as e:
                print(f"Error in log writer: {e}")
                continue

def process_specific_subject(subject_path, output_folder_name, force_reconversion, log_queue):
    """Process a single specific subject."""
    # Check if the path is actually a subject directory within freesurfer741
    subject_name = os.path.basename(subject_path)
    parent_dir = os.path.dirname(subject_path)
    parent_name = os.path.basename(parent_dir)
    
    if parent_name != "freesurfer741":
        log_queue.put(f"ERROR: {subject_path} is not a subject directory within a freesurfer741 directory")
        return False
    
    # Create output directory as sibling to freesurfer741
    fs_dir = parent_dir
    grandparent_dir = os.path.dirname(parent_dir)
    output_path = os.path.join(grandparent_dir, output_folder_name)
    os.makedirs(output_path, exist_ok=True)
    
    # Process the subject
    subject_dir = subject_name
    subject_data = (fs_dir, subject_dir, output_path, force_reconversion)
    result = process_subject(subject_data, log_queue)
    
    return result

def main():
    parser = argparse.ArgumentParser(description='Convert FreeSurfer files to NIfTI and GIFTI formats')
    parser.add_argument('path', help='Path to the ADRC directory or a specific subject directory')
    parser.add_argument('--output_name', help='Name of the output folder (sibling to freesurfer741)', default='sitedata_mri')
    parser.add_argument('--cores', type=int, help='Number of parallel processes to use', default=1)
    parser.add_argument('--force', action='store_true', help='Force reconversion even if output files already exist')
    
    args = parser.parse_args()
    
    input_path = args.path
    output_folder_name = args.output_name
    num_processes = args.cores or max(1, multiprocessing.cpu_count() - 1)  # Default: Use all cores except one
    force_reconversion = args.force
    
    # Check if FreeSurfer is initialized
    if not check_freesurfer():
        sys.exit(1)
    
    # Determine if this is a specific subject or a general ADRC path
    is_specific_subject = False
    if os.path.basename(os.path.dirname(input_path)) == "freesurfer741":
        is_specific_subject = True
    
    # Set up log directory
    if is_specific_subject:
        # For a specific subject, place logs in the grandparent directory
        base_log_dir = os.path.join(os.path.dirname(os.path.dirname(input_path)), "conversion_logs")
    else:
        # For ADRC path, place logs in the ADRC directory
        base_log_dir = os.path.join(input_path, "conversion_logs")
    
    os.makedirs(base_log_dir, exist_ok=True)
    
    # Create log file
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(base_log_dir, f"conversion_log_{timestamp}.log")
    
    # Initialize log queue for inter-process communication
    log_queue = multiprocessing.Manager().Queue()
    
    # Start log writer thread
    log_writer_thread = threading.Thread(target=log_writer, args=(log_queue, log_file))
    log_writer_thread.daemon = True
    log_writer_thread.start()
    
    # Write initial log info
    start_time = datetime.datetime.now()
    log_queue.put(f"Starting FreeSurfer conversion process at {start_time}")
    log_queue.put(f"Input path: {input_path}")
    log_queue.put(f"Output folder name: {output_folder_name}")
    
    # Process either a specific subject or scan for all subjects
    results = []
    if is_specific_subject:
        log_queue.put(f"Processing specific subject: {os.path.basename(input_path)}")
        log_queue.put(f"Force reconversion: {force_reconversion}")
        log_queue.put("")
        
        # Process the specific subject
        result = process_specific_subject(input_path, output_folder_name, force_reconversion, log_queue)
        results = [result]
    else:
        log_queue.put(f"Scanning for all subjects in ADRC path")
        log_queue.put(f"Using {num_processes} parallel processes")
        log_queue.put(f"Force reconversion: {force_reconversion}")
        log_queue.put("")
        
        # Collect all subjects to process
        all_subjects = []
        
        for root, dirs, _ in os.walk(input_path):
            if "freesurfer741" in dirs:
                fs_dir = os.path.join(root, "freesurfer741")
                
                # Create output directory as sibling to freesurfer741
                parent_dir = os.path.dirname(fs_dir)
                output_path = os.path.join(parent_dir, output_folder_name)
                os.makedirs(output_path, exist_ok=True)
                
                # Get subject directories
                for subject_dir in [d for d in os.listdir(fs_dir) if os.path.isdir(os.path.join(fs_dir, d))]:
                    all_subjects.append((fs_dir, subject_dir, output_path))
        
        log_queue.put(f"Found {len(all_subjects)} subjects to process")
        
        # Add force flag to subject data
        all_subjects = [(fs_dir, subject_dir, output_path, force_reconversion) for fs_dir, subject_dir, output_path in all_subjects]
        
        # Process subjects in parallel
        with multiprocessing.Pool(processes=num_processes) as pool:
            process_func = partial(process_subject, log_queue=log_queue)
            results = pool.map(process_func, all_subjects)
    
    # Calculate statistics
    if is_specific_subject:
        subject_count = 1
        worked_on_count = 1 if results[0][0] else 0
        new_conversions = results[0][1]
        already_converted = results[0][2]
        failure_count = results[0][3]
    else:
        subject_count = len(all_subjects)
        worked_on_count = sum(1 for r in results if r[0])
        new_conversions = sum(r[1] for r in results)
        already_converted = sum(r[2] for r in results)
        failure_count = sum(r[3] for r in results)
    
    # Print summary
    end_time = datetime.datetime.now()
    elapsed_time = end_time - start_time
    
    summary = [
        f"",
        f"Conversion process completed at {end_time}",
        f"Total execution time: {elapsed_time}"
    ]
    
    if is_specific_subject:
        subject_name = os.path.basename(input_path)
        summary.append(f"Subject: {subject_name}")
        summary.append(f"New file conversions: {new_conversions}")
        summary.append(f"Already converted files (skipped): {already_converted}")
        summary.append(f"Failed file conversions: {failure_count}")
    else:
        summary.append(f"Total subjects found: {subject_count}")
        summary.append(f"Subjects worked on (had new conversions): {worked_on_count}")
        summary.append(f"New file conversions: {new_conversions}")
        summary.append(f"Already converted files (skipped): {already_converted}")
        summary.append(f"Failed file conversions: {failure_count}")
    
    summary.append(f"See {log_file} for details")
    
    for line in summary:
        log_queue.put(line)
    
    # Signal log writer to finish
    log_queue.put("DONE")
    log_writer_thread.join()
    
    print(f"\nConversion complete! Log file: {log_file}")

if __name__ == "__main__":
    main()