#!/usr/bin/env python3
"""PET quantification (stage 3): pair PET with MRI, register, compute SUVR and Centiloid.

Object-oriented replacement for prepare_suvr_folder.py / registration.py / suvr.py.
Output layout and res/*.csv formats are unchanged.

    python3 run_suvr.py prepare  /path/to/ADRC --cores 8
    python3 run_suvr.py register /path/to/ADRC --cores 8
    python3 run_suvr.py quantify /path/to/ADRC --cores 4
    python3 run_suvr.py all      /path/to/ADRC --cores 8          # all three, in order

    python3 run_suvr.py quantify /path/to/ADRC --subject 900004 --subject 110005
    python3 run_suvr.py quantify /path/to/ADRC --compound amyvid --subject 110123
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from suvr_pipeline.layout import Dataset
from suvr_pipeline.quantify import DEFAULT_LUT
from suvr_pipeline.runner import StageRunner, configure_logging
from suvr_pipeline.stages import PrepareStage, QuantifyStage, RegisterStage, Status
from suvr_pipeline.tracer import TRACERS, TracerPolicy


def build_stages(args):
    stages = {
        "prepare": PrepareStage,
        "register": RegisterStage,
        "quantify": lambda: QuantifyStage(TracerPolicy.from_name(args.compound), args.lut),
    }
    names = list(stages) if args.stage == "all" else [args.stage]
    return [stages[n]() for n in names]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["prepare", "register", "quantify", "all"])
    parser.add_argument("root", type=Path, help="Directory containing one folder per subject")
    parser.add_argument("--subject", action="append", metavar="ID",
                        help="Only process this subject (repeatable)")
    parser.add_argument("--cores", type=int, default=1, help="Worker processes (default 1)")
    parser.add_argument("--compound", choices=sorted(TRACERS),
                        help="quantify: force this tracer instead of inferring it from the scan date")
    parser.add_argument("--lut", type=Path, default=DEFAULT_LUT,
                        help="quantify: ROI lookup table (default: pipeline/3_suvr/FreesurferLUTR.txt)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    if not args.root.is_dir():
        print(f"Not a directory: {args.root}", file=sys.stderr)
        return 1
    try:
        subjects = Dataset(args.root.resolve()).subjects(args.subject)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    runner = StageRunner(cores=args.cores, verbose=args.verbose)
    start = datetime.now()
    failed = 0
    for stage in build_stages(args):
        outcomes = runner.run(stage, subjects)
        failed += sum(o.status is Status.FAILED for o in outcomes)

    print(f"\nFinished in {datetime.now() - start}; {failed} failed task(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
