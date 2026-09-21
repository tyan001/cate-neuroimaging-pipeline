#!/usr/bin/env python3
"""Convert FreeSurfer recons to the shareable NIfTI/GIFTI derivative in each session's sitedata_mri/.

    python3 mri_site_data.py /path/to/NWSI/freesurfer_link --cores 4 [--force]
    python3 mri_site_data.py /path/to/NWSI/freesurfer_link --status         # what is done, converts nothing
    python3 mri_site_data.py /path/to/NWSI/freesurfer_link --status --all --csv done.csv

--status answers "which scans has this already done?" without touching anything. It and the
conversion share scan_status()/needs_conversion(), so the report always matches what a rerun does.
A scan counts as converted only while its output is at least as new as the recon it came from; if
recon-all is rerun the derivative goes stale and both the report and a plain rerun will redo it.
"""

import argparse
import csv
import datetime
import enum
import multiprocessing
import os
import subprocess
import sys
import threading
import traceback
from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path

DEFAULT_LINK_DIR = "/mnt/backup/dev/NWSI/freesurfer_link"
FREESURFER_DIRNAME = "freesurfer741"

# Every file a full conversion produces, as (source, command).
MRI_CONVERT = ("mri_convert",)
SURF_CONVERT = ("mris_convert", "-ot", "nii")
MRI_FILES = ("T1.mgz", "aparc+aseg.mgz", "brain.mgz", "wm.mgz")
SURF_FILES = ("lh.pial", "lh.white", "rh.pial", "rh.white")
EXPECTED_OUTPUTS = len(MRI_FILES) + len(SURF_FILES)


class SiteDataState(enum.StrEnum):
    COMPLETE = "complete"
    STALE = "stale"
    PARTIAL = "partial"
    NOT_STARTED = "not_started"
    NO_SOURCE = "no_source"


STATE_ACTION = {
    SiteDataState.COMPLETE: "nothing to do",
    SiteDataState.STALE: "rerun: the recon changed after conversion",
    SiteDataState.PARTIAL: "rerun: converts the rest",
    SiteDataState.NOT_STARTED: "rerun: converts the whole scan",
    SiteDataState.NO_SOURCE: "manual: the recon has no such file, a rerun will not help",
}
CSV_FIELDS = ["scan", "state", "converted", "stale", "pending", "no_source", "detail", "recon", "output"]


@dataclass(frozen=True)
class SiteDataRecord:
    """What sitedata_mri/ holds for one recon, counted over the 8 expected outputs."""
    scan: str
    recon: str
    output: str
    state: SiteDataState
    converted: int = 0   # output present and at least as new as its source
    stale: int = 0       # output present but older than its source
    pending: int = 0     # source present, output absent
    no_source: int = 0   # source absent from the recon
    detail: str = ""

    @property
    def to_convert(self):
        """Files a rerun without --force would (re)convert."""
        return self.stale + self.pending


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


# ---- what a conversion would produce -----------------------------------


def expected_pairs(subject_path, output_path):
    """(source, destination, command) for every file a full conversion of this recon produces."""
    pairs = []
    for name in MRI_FILES:
        output_name = f"{os.path.splitext(name)[0]}.nii"
        pairs.append((os.path.join(subject_path, "mri", name),
                      os.path.join(output_path, "mri", output_name),
                      MRI_CONVERT))
    for name in SURF_FILES:
        pairs.append((os.path.join(subject_path, "surf", name),
                      os.path.join(output_path, "surf", f"{name}.gii"),
                      SURF_CONVERT))
    return pairs


def needs_conversion(input_path, output_path, force=False):
    """True when the output is absent or older than its source. The one rule --status also reads."""
    if force or not os.path.isfile(output_path):
        return True
    try:
        return os.path.getmtime(output_path) < os.path.getmtime(input_path)
    except OSError:
        return True


def scan_status(scan_name, subject_path, output_path):
    """Classify one recon's sitedata_mri/ without changing anything."""
    converted, stale, pending, missing = [], [], [], []

    for source, output, _command in expected_pairs(subject_path, output_path):
        if not os.path.isfile(source):
            missing.append(os.path.basename(source))
        elif not os.path.isfile(output):
            pending.append(os.path.basename(output))
        elif needs_conversion(source, output):
            stale.append(os.path.basename(output))
        else:
            converted.append(os.path.basename(output))

    # A missing source outranks the rest: it is the only state a rerun cannot clear.
    if missing:
        state = SiteDataState.NO_SOURCE
        detail = f"recon has no {', '.join(missing)}"
    elif not converted and not stale:
        state, detail = SiteDataState.NOT_STARTED, ""
    elif stale:
        state = SiteDataState.STALE
        detail = f"older than the recon: {', '.join(stale)}"
    elif pending:
        state = SiteDataState.PARTIAL
        detail = f"not converted yet: {', '.join(pending)}"
    else:
        state, detail = SiteDataState.COMPLETE, ""

    return SiteDataRecord(scan=scan_name, recon=subject_path, output=output_path, state=state,
                          converted=len(converted), stale=len(stale), pending=len(pending),
                          no_source=len(missing), detail=detail)


# ---- conversion --------------------------------------------------------


def convert_files(pairs, log_queue, force=False):
    """Convert every (source, destination) that is missing or out of date."""
    success_count = 0
    already_converted = 0

    for input_path, output_path, command in pairs:
        if not os.path.isfile(input_path):
            log_queue.put(f"  Warning: {os.path.basename(input_path)} not found in {os.path.dirname(input_path)}")
            continue

        if not needs_conversion(input_path, output_path, force):
            already_converted += 1
            continue

        log_queue.put(f"  Converting {os.path.basename(input_path)} to {os.path.basename(output_path)}")

        try:
            subprocess.run([*command, input_path, output_path],
                           check=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            success_count += 1
            log_queue.put(f"    Success: {output_path}")
        except subprocess.CalledProcessError as e:
            log_queue.put(f"    Failed to convert {os.path.basename(input_path)}: {e}")

    return success_count, already_converted


def process_subject(subject_data, log_queue, force=False):
    """Process a single subject in parallel."""
    fs_dir, subject_dir, output_path, force = subject_data

    try:
        subject_path = os.path.join(fs_dir, subject_dir)
        subject_name = os.path.basename(subject_path)

        os.makedirs(os.path.join(output_path, "mri"), exist_ok=True)
        os.makedirs(os.path.join(output_path, "surf"), exist_ok=True)

        for source_dir in ("mri", "surf"):
            if not os.path.isdir(os.path.join(subject_path, source_dir)):
                log_queue.put(f"  Warning: {source_dir} directory not found for {subject_name}")

        pairs = expected_pairs(subject_path, output_path)
        new_conversions, already_converted = convert_files(pairs, log_queue, force)
        failures = len(pairs) - new_conversions - already_converted

        # Only log completion message if any new conversions were made
        if new_conversions > 0:
            log_queue.put(f"Processing subject: {subject_name}")
            log_queue.put(f"  Completed processing for {subject_name}: {new_conversions} new files, "
                          f"{already_converted} previously converted\n")

        # (worked_on, new_count, already_count, failure_count)
        return (new_conversions > 0, new_conversions, already_converted, failures)

    except Exception as e:
        log_queue.put(f"ERROR processing {subject_dir}: {e}")
        log_queue.put(traceback.format_exc())
        return (False, 0, 0, EXPECTED_OUTPUTS)  # Count all possible conversions as failures


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


# ---- locating recons ---------------------------------------------------


def resolve_subject(input_path, output_folder_name):
    """(fs_dir, scan, output_path) for one recon directory or farm link, or None if it is not one.

    Follows a farm symlink to the real recon so the output lands next to its freesurfer741.
    """
    real_path = os.path.realpath(input_path)
    fs_dir = os.path.dirname(real_path)
    if os.path.basename(fs_dir) != FREESURFER_DIRNAME:
        return None
    output_path = os.path.join(os.path.dirname(fs_dir), output_folder_name)
    return fs_dir, os.path.basename(real_path), output_path


def find_subjects(farm_path, output_folder_name, warn):
    """(fs_dir, scan, output_path) for every recon in the symlink farm. Creates nothing.

    Each farm entry is a symlink to <root>/<subjid>/<session>/freesurfer741/<recon>; it is resolved
    so the output folder is still a sibling of freesurfer741.
    """
    subjects = []
    for entry in sorted(os.listdir(farm_path)):
        link_path = os.path.join(farm_path, entry)
        if not os.path.isdir(link_path):
            warn(f"  WARNING: skipping {entry} (broken symlink or not a directory)")
            continue
        resolved = resolve_subject(link_path, output_folder_name)
        if resolved is None:
            warn(f"  WARNING: skipping {entry} "
                 f"({os.path.realpath(link_path)} is not inside a {FREESURFER_DIRNAME} directory)")
            continue
        subjects.append(resolved)
    return subjects


def process_specific_subject(subject_path, output_folder_name, force_reconversion, log_queue):
    """Process a single specific subject."""
    resolved = resolve_subject(subject_path, output_folder_name)
    if resolved is None:
        log_queue.put(f"ERROR: {subject_path} is not a subject directory "
                      f"within a {FREESURFER_DIRNAME} directory")
        return (False, 0, 0, EXPECTED_OUTPUTS)

    fs_dir, subject_dir, output_path = resolved
    os.makedirs(output_path, exist_ok=True)
    return process_subject((fs_dir, subject_dir, output_path, force_reconversion), log_queue)


# ---- status report -----------------------------------------------------


def report_status(records, output_folder_name, show_all=False):
    """Print what has already been converted. Changes nothing."""
    counts = Counter(r.state for r in records)

    print(f"\n=== {len(records)} scan(s), output folder {output_folder_name}/ ===")
    for state in SiteDataState:
        print(f"  {state.value:<12} {counts[state]:>5}   {STATE_ACTION[state]}")

    for state in SiteDataState:
        if not counts[state] or (state is SiteDataState.COMPLETE and not show_all):
            continue
        print(f"\n--- {state.value} ({counts[state]}) ---")
        for record in records:
            if record.state is state:
                line = f"  {record.scan}   {record.converted}/{EXPECTED_OUTPUTS} converted"
                print(f"{line}   {record.detail}" if record.detail else line)

    # Counted over every record, not just the rerunnable states: a no_source scan still has files
    # to convert, it just can never reach complete. Skipping it here would under-forecast the rerun.
    todo = [r for r in records if r.to_convert]
    files = sum(r.to_convert for r in todo)
    convertible = sum(r.converted + r.stale + r.pending for r in records)
    print(f"\nA rerun would convert {files} file(s) across {len(todo)} scan(s); "
          f"--force would redo all {convertible}.")


def write_status_csv(records, csv_path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow({"scan": r.scan, "state": r.state.value, "converted": r.converted,
                             "stale": r.stale, "pending": r.pending, "no_source": r.no_source,
                             "detail": r.detail, "recon": r.recon, "output": r.output})
    print(f"Wrote {csv_path}")


def run_status(input_path, is_specific_subject, output_folder_name, show_all, csv_path):
    """--status: report only, so no FreeSurfer, no output folders and no log file."""
    if is_specific_subject:
        resolved = resolve_subject(input_path, output_folder_name)
        if resolved is None:
            print(f"ERROR: {input_path} is not a subject directory "
                  f"within a {FREESURFER_DIRNAME} directory", file=sys.stderr)
            return 1
        subjects = [resolved]
    else:
        subjects = find_subjects(input_path, output_folder_name, warn=print)

    print(f"Input path: {input_path}")
    records = [scan_status(scan, os.path.join(fs_dir, scan), output_path)
               for fs_dir, scan, output_path in subjects]
    report_status(records, output_folder_name, show_all)

    if csv_path:
        write_status_csv(records, csv_path)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path', nargs='?', default=DEFAULT_LINK_DIR,
                        help='Flat FreeSurfer symlink farm as built by freesurfer_symlink.py, '
                             f'or a specific subject directory / farm link (default: {DEFAULT_LINK_DIR})')
    parser.add_argument('--output_name', help='Name of the output folder (sibling to freesurfer741)',
                        default='sitedata_mri')
    parser.add_argument('--cores', type=int, help='Number of parallel processes to use', default=1)
    parser.add_argument('--force', action='store_true',
                        help='Force reconversion even if output files are already up to date')
    parser.add_argument('--status', action='store_true',
                        help='Report which scans are already converted and exit; converts nothing')
    parser.add_argument('--all', action='store_true', help='With --status, also list complete scans')
    parser.add_argument('--csv', type=Path, help='With --status, write one row per scan to this file')

    args = parser.parse_args()

    if (args.csv or args.all) and not args.status:
        parser.error("--csv and --all only apply to --status")

    input_path = os.path.abspath(args.path.rstrip('/'))
    output_folder_name = args.output_name
    num_processes = args.cores or max(1, multiprocessing.cpu_count() - 1)  # Default: all cores except one
    force_reconversion = args.force

    # Determine if this is a specific subject or a symlink farm
    is_specific_subject = False
    if os.path.basename(os.path.dirname(os.path.realpath(input_path))) == FREESURFER_DIRNAME:
        is_specific_subject = True
    elif not os.path.isdir(input_path):
        print(f"ERROR: {input_path} is not a directory")
        return 1

    if args.status:
        return run_status(input_path, is_specific_subject, output_folder_name, args.all, args.csv)

    # Check if FreeSurfer is initialized
    if not check_freesurfer():
        return 1

    # Set up log directory
    if is_specific_subject:
        # For a specific subject, place logs in the session directory (grandparent of the real recon)
        base_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(input_path))),
                                    "conversion_logs")
    else:
        # For the farm, place logs beside it (not inside, so the farm stays links-only)
        base_log_dir = os.path.join(os.path.dirname(input_path), "conversion_logs")

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
    if is_specific_subject:
        log_queue.put(f"Processing specific subject: {os.path.basename(input_path)}")
        log_queue.put(f"Force reconversion: {force_reconversion}")
        log_queue.put("")

        result = process_specific_subject(input_path, output_folder_name, force_reconversion, log_queue)
        results = [result]
        subject_count = 1
    else:
        log_queue.put("Scanning for all subjects in symlink farm")
        log_queue.put(f"Using {num_processes} parallel processes")
        log_queue.put(f"Force reconversion: {force_reconversion}")
        log_queue.put("")

        all_subjects = [(fs_dir, scan, output_path, force_reconversion)
                        for fs_dir, scan, output_path in
                        find_subjects(input_path, output_folder_name, warn=log_queue.put)]
        log_queue.put(f"Found {len(all_subjects)} subjects to process")
        subject_count = len(all_subjects)

        # Process subjects in parallel
        with multiprocessing.Pool(processes=num_processes) as pool:
            process_func = partial(process_subject, log_queue=log_queue)
            results = pool.map(process_func, all_subjects)

    # Calculate statistics
    worked_on_count = sum(1 for r in results if r[0])
    new_conversions = sum(r[1] for r in results)
    already_converted = sum(r[2] for r in results)
    failure_count = sum(r[3] for r in results)

    # Print summary
    end_time = datetime.datetime.now()
    elapsed_time = end_time - start_time

    summary = [
        "",
        f"Conversion process completed at {end_time}",
        f"Total execution time: {elapsed_time}",
    ]

    if is_specific_subject:
        summary.append(f"Subject: {os.path.basename(input_path)}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
