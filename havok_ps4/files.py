"""Convert files and commit outputs without partial file writes."""

from __future__ import annotations

import dataclasses
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .converter import BehaviorConverter, ConversionReport
from .errors import ConversionError
from .layout import ClassDatabase


@dataclasses.dataclass(frozen=True, slots=True)
class JobResult:
    source: Path
    destination: Path
    report: ConversionReport


@dataclasses.dataclass(frozen=True, slots=True)
class StagedOutput:
    source: Path
    destination: Path
    temporary: Path
    report: ConversionReport


@dataclasses.dataclass(slots=True)
class CommitState:
    staged: StagedOutput
    backup: Path | None = None
    installed: bool = False


def file_jobs(
    source: Path,
    destination: Path,
    recursive: bool,
) -> list[tuple[Path, Path]]:
    if source.is_file():
        if destination.is_dir():
            return [(source, destination / source.name)]
        return [(source, destination)]
    if not source.is_dir():
        raise ConversionError(f"Input path not found: {source}")
    pattern = "**/*.hkx" if recursive else "*.hkx"
    jobs = [
        (item, destination / item.relative_to(source))
        for item in sorted(source.glob(pattern))
    ]
    if not jobs:
        raise ConversionError(f"No HKX files found in: {source}")
    return jobs


def _temporary_path(destination: Path, label: str) -> tuple[int, Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=f".{label}",
        dir=destination.parent,
    )
    return descriptor, Path(raw_path)


def _stage_bytes(destination: Path, data: bytes) -> Path:
    descriptor, temporary = _temporary_path(destination, "tmp")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _backup_destination(destination: Path) -> Path:
    descriptor, backup = _temporary_path(destination, "backup")
    os.close(descriptor)
    try:
        os.replace(destination, backup)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _clean_staged(staged: Sequence[StagedOutput]) -> None:
    for item in staged:
        item.temporary.unlink(missing_ok=True)


def _rollback(states: Sequence[CommitState]) -> list[str]:
    failures: list[str] = []
    for state in reversed(states):
        try:
            if state.installed:
                if state.backup is None:
                    state.staged.destination.unlink(missing_ok=True)
                else:
                    os.replace(state.backup, state.staged.destination)
            elif state.backup is not None:
                os.replace(state.backup, state.staged.destination)
        except OSError as exc:
            failures.append(f"{state.staged.destination}: {exc}")
    return failures


def _commit(staged: Sequence[StagedOutput], force: bool) -> None:
    states: list[CommitState] = []
    try:
        for item in staged:
            state = CommitState(item)
            states.append(state)
            if item.destination.exists():
                if not force:
                    raise ConversionError(
                        f"Output file exists: {item.destination}. "
                        "Use --force to replace it"
                    )
                state.backup = _backup_destination(item.destination)
            os.replace(item.temporary, item.destination)
            state.installed = True
    except BaseException as exc:
        rollback_failures = _rollback(states)
        _clean_staged(staged)
        if rollback_failures:
            details = "; ".join(rollback_failures)
            raise ConversionError(
                f"Output commit failed and rollback was incomplete: {details}"
            ) from exc
        raise
    for state in states:
        if state.backup is not None:
            state.backup.unlink(missing_ok=True)


def _check_jobs(jobs: Sequence[tuple[Path, Path]], force: bool) -> None:
    if not jobs:
        raise ConversionError("No conversion jobs were provided")
    destinations: set[Path] = set()
    for source, destination in jobs:
        if not source.is_file():
            raise ConversionError(f"Input file not found: {source}")
        key = destination.resolve()
        if key in destinations:
            raise ConversionError(f"Duplicate output path: {destination}")
        destinations.add(key)
        if destination.exists() and not force:
            raise ConversionError(
                f"Output file exists: {destination}. Use --force to replace it"
            )


def convert_files(
    jobs: Sequence[tuple[Path, Path]],
    database: ClassDatabase,
    force: bool,
) -> list[JobResult]:
    """Convert all jobs before an atomic commit for each destination."""
    _check_jobs(jobs, force)
    staged: list[StagedOutput] = []
    try:
        for source, destination in jobs:
            converted, report = BehaviorConverter(
                source.read_bytes(),
                database,
            ).convert_with_report()
            temporary = _stage_bytes(destination, converted)
            staged.append(StagedOutput(source, destination, temporary, report))
        _commit(staged, force)
    except BaseException:
        _clean_staged(staged)
        raise
    return [JobResult(item.source, item.destination, item.report) for item in staged]


def convert_file(
    source: Path,
    destination: Path,
    database: ClassDatabase,
    force: bool,
) -> tuple[int, int]:
    result = convert_files([(source, destination)], database, force)[0]
    return result.report.object_count, result.report.resized_object_count
