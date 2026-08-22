"""Convert Fallout 4 PC behavior packfiles to the PS4 Havok layout."""

from havok_ps4 import (
    BehaviorConverter,
    ClassDatabase,
    ConversionError,
    ConversionReport,
    ValidationReport,
    convert_file,
    convert_files,
    file_jobs,
    validate_ps4_packfile,
)
from havok_ps4.cli import main, make_parser

__all__ = [
    "BehaviorConverter",
    "ClassDatabase",
    "ConversionError",
    "ConversionReport",
    "ValidationReport",
    "convert_file",
    "convert_files",
    "file_jobs",
    "main",
    "make_parser",
    "validate_ps4_packfile",
]


if __name__ == "__main__":
    raise SystemExit(main())
