#!/usr/bin/env python3
"""
Download files from Dropbox links listed in a CSV file.

CSV must have columns: 'name' and 'link'
Each row will be downloaded as: <name>.zip

The output folder is created next to the CSV file.

Usage:
    python download_from_csv.py <csv_file> <folder_name>
"""

import argparse
import csv
import subprocess
import zipfile
from pathlib import Path


def download_from_csv(csv_path: str, scan_type: str = "MRI"):
    output = Path(csv_path).parent  / scan_type
    output.mkdir(parents=True, exist_ok=True)

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames or "name" not in reader.fieldnames or "link" not in reader.fieldnames:
            raise ValueError(f"CSV must have 'name' and 'link' columns. Found: {reader.fieldnames}")

        rows = list(reader)

    print(f"Found {len(rows)} rows to download.\n")

    for i, row in enumerate(rows, 1):
        name = row["name"].strip()
        link = row["link"].strip()
        out_file = output / f"{name}.zip"

        print(f"[{i}/{len(rows)}] Downloading: {name}")
        print(f"  URL : {link}")
        print(f"  -> {out_file}")

        result = subprocess.run(
            ["curl", "-L", "-o", str(out_file), link],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"  Extracting...")
            with zipfile.ZipFile(out_file, 'r') as zip_ref:
                zip_ref.extractall(out_file.with_suffix(''))
            out_file.unlink()
            print(f"  Done.\n")
        else:
            print(f"  FAILED (exit {result.returncode})")
            print(f"  {result.stderr.strip()}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Dropbox links from a CSV file as zip files."
    )
    parser.add_argument("csv_file", help="Path to the CSV file with 'name' and 'link' columns")
    # parser.add_argument("folder_name", help="Name of the output folder (created next to the CSV file)")
    parser.add_argument("--type", choices=["MRI", "PET"], required=True, help="Type of scan: MRI or PET")
    args = parser.parse_args()

    #download_from_csv(args.csv_file, args.folder_name, args.type)
    download_from_csv(args.csv_file, args.type)
