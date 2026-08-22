"""Command-line interface for behavior conversion."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .errors import ConversionError
from .files import convert_files, file_jobs
from .layout import ClassDatabase


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Fallout 4 PC behavior HKX files to the PS4 layout."
    )
    parser.add_argument("input", type=Path, help="Input HKX file or folder")
    parser.add_argument("output", type=Path, help="Output HKX file or folder")
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="Read subfolders"
    )
    parser.add_argument("--force", action="store_true", help="Replace output files")
    parser.add_argument(
        "--class-db",
        type=Path,
        required=True,
        help="Folder that contains your local Havok class XML files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        database = ClassDatabase(args.class_db)
        jobs = file_jobs(args.input.resolve(), args.output.resolve(), args.recursive)
        results = convert_files(jobs, database, args.force)
        for result in results:
            print(
                f"OK   {result.source} -> {result.destination} "
                f"({result.report.object_count} objects, "
                f"{result.report.resized_object_count} resized)"
            )
        print(f"Done: {len(results)} behavior file(s) converted")
        return 0
    except (ConversionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
