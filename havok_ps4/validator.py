"""Validate a converted PS4 behavior packfile without converter state."""

from __future__ import annotations

import dataclasses

from .errors import ConversionError
from .layout import ClassDatabase, align
from .packfile import (
    PS4_LAYOUT,
    active_records,
    parse_classnames,
    parse_sections,
    table_records,
)


@dataclasses.dataclass(frozen=True, slots=True)
class ValidationReport:
    object_count: int
    behavior_graph_count: int


def _check_unique_sources(
    records: tuple[tuple[int, ...], ...],
    table_name: str,
) -> None:
    sources = [record[0] for record in records]
    if len(sources) != len(set(sources)):
        raise ConversionError(f"The {table_name} fixup table has duplicate sources")


def validate_ps4_packfile(
    data: bytes | bytearray,
    database: ClassDatabase,
) -> ValidationReport:
    """Validate the supported PS4 packfile structure and behavior objects."""
    sections = parse_sections(data, PS4_LAYOUT)
    class_section, _, data_section = sections
    classnames = parse_classnames(data, class_section)

    local = active_records(
        table_records(data, data_section, data_section.data1, data_section.data2, 8)
    )
    global_fixups = active_records(
        table_records(data, data_section, data_section.data2, data_section.data3, 12)
    )
    virtual = active_records(
        table_records(data, data_section, data_section.data3, data_section.data4, 12)
    )
    if (
        data_section.data4 != data_section.data5
        or data_section.data5 != data_section.end
    ):
        raise ConversionError("Behavior exports or imports are not supported")

    _check_unique_sources(local, "local")
    _check_unique_sources(global_fixups, "global")
    _check_unique_sources(virtual, "virtual")
    all_pointer_sources = [record[0] for record in local]
    all_pointer_sources.extend(record[0] for record in global_fixups)
    if len(all_pointer_sources) != len(set(all_pointer_sources)):
        raise ConversionError("A pointer source has more than one fixup")

    object_data_size = data_section.data1
    for source, target in local:
        if source >= object_data_size or target >= object_data_size:
            raise ConversionError("A local fixup is outside the object data")

    for source, target_section, target in global_fixups:
        if source >= object_data_size:
            raise ConversionError("A global fixup source is outside the object data")
        if target_section >= len(sections):
            raise ConversionError("A global fixup uses an invalid target section")
        if target >= sections[target_section].data1:
            raise ConversionError("A global fixup target is outside its section data")

    if not virtual:
        raise ConversionError("The output object table is empty")
    object_starts = [record[0] for record in virtual]
    if object_starts != sorted(object_starts):
        raise ConversionError("The virtual fixup table is not ordered by object offset")

    behavior_graph_count = 0
    previous_end = 0
    for source, target_section, class_offset in virtual:
        if source >= object_data_size:
            raise ConversionError("A virtual fixup source is outside the object data")
        if target_section != 0:
            raise ConversionError("A virtual fixup uses an unsupported class section")
        classname = classnames.get(class_offset)
        if classname is None:
            raise ConversionError(f"Class name fixup not found: {class_offset}")
        layout = database.get(classname.name)
        if layout.signature != classname.signature:
            raise ConversionError(
                f"Class signature does not match for {classname.name}: "
                f"file 0x{classname.signature:08x}, data 0x{layout.signature:08x}"
            )
        object_end = source + align(layout.ps4_size, 16)
        if source < previous_end:
            raise ConversionError(f"Object ranges overlap at {classname.name}")
        if object_end > object_data_size:
            raise ConversionError(f"Object is outside data: {classname.name}")
        previous_end = object_end
        if classname.name == "hkbBehaviorGraph":
            behavior_graph_count += 1

    if behavior_graph_count == 0:
        raise ConversionError("The HKX file is not a behavior graph")
    return ValidationReport(len(virtual), behavior_graph_count)
