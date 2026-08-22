"""Read and write the supported Havok 2014.1 packfile fields."""

from __future__ import annotations

import dataclasses
import struct
from collections.abc import Sequence
from itertools import pairwise

from .errors import ConversionError

MAGIC = b"\x57\xe0\xe0\x57\x10\xc0\xc0\x10"
PC_LAYOUT = b"\x08\x01\x00\x01"
PS4_LAYOUT = b"\x08\x01\x01\x01"
HKX_VERSION = b"hk_2014.1.0-r1\x00"
PACKFILE_VERSION = 11
SECTION_COUNT = 3
SECTION_NAMES = ("__classnames__", "__types__", "__data__")
HEADER_SIZE = 0x40
SECTION_SIZE_V11 = 0x40
SENTINEL = 0xFFFFFFFF


@dataclasses.dataclass(frozen=True, slots=True)
class Section:
    name: str
    header_offset: int
    offset: int
    data1: int
    data2: int
    data3: int
    data4: int
    data5: int
    end: int

    @property
    def marks(self) -> tuple[int, int, int, int, int, int]:
        return self.data1, self.data2, self.data3, self.data4, self.data5, self.end


@dataclasses.dataclass(frozen=True, slots=True)
class Classname:
    name: str
    signature: int


def require_range(data: bytes | bytearray, start: int, size: int, label: str) -> None:
    if start < 0 or size < 0 or start > len(data) - size:
        raise ConversionError(f"{label} is outside the HKX file")


def u16(data: bytes | bytearray, offset: int, label: str) -> int:
    require_range(data, offset, 2, label)
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int, label: str) -> int:
    require_range(data, offset, 4, label)
    return struct.unpack_from("<I", data, offset)[0]


def put_u32(data: bytearray, offset: int, value: int) -> None:
    require_range(data, offset, 4, "Output section header")
    struct.pack_into("<I", data, offset, value)


def validate_header(
    data: bytes | bytearray,
    expected_layout: bytes | None = None,
) -> None:
    require_range(data, 0, HEADER_SIZE, "HKX header")
    if bytes(data[:8]) != MAGIC:
        raise ConversionError("The input file is not an HKX packfile")
    version = u32(data, 0x0C, "Packfile version")
    if version != PACKFILE_VERSION:
        raise ConversionError(f"Unsupported HKX file version: {version}")
    layout = bytes(data[0x10:0x14])
    if expected_layout is not None and layout != expected_layout:
        if layout == PS4_LAYOUT and expected_layout == PC_LAYOUT:
            raise ConversionError("The input file already uses the PS4 layout")
        raise ConversionError(f"Unsupported HKX layout: {layout.hex()}")
    if expected_layout is None and layout not in (PC_LAYOUT, PS4_LAYOUT):
        raise ConversionError(f"Unsupported HKX layout: {layout.hex()}")
    section_count = u32(data, 0x14, "Section count")
    if section_count != SECTION_COUNT:
        raise ConversionError(f"Unsupported HKX section count: {section_count}")
    if bytes(data[0x28 : 0x28 + len(HKX_VERSION)]) != HKX_VERSION:
        raise ConversionError("The input file is not Havok 2014.1")


def parse_sections(
    data: bytes | bytearray,
    expected_layout: bytes | None = None,
) -> tuple[Section, Section, Section]:
    validate_header(data, expected_layout)
    padding = u16(data, 0x3E, "Section-header padding")
    table_start = HEADER_SIZE + padding
    table_size = SECTION_COUNT * SECTION_SIZE_V11
    require_range(data, table_start, table_size, "Section-header table")

    sections: list[Section] = []
    for index in range(SECTION_COUNT):
        position = table_start + index * SECTION_SIZE_V11
        raw_name = bytes(data[position : position + 16]).split(b"\x00", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ConversionError("A section name is not valid ASCII") from exc
        values = struct.unpack_from("<7I", data, position + 0x14)
        section = Section(name, position, *values)
        if tuple(sorted(section.marks)) != section.marks:
            raise ConversionError(
                f"The {name or 'unnamed'} section offsets are not ordered"
            )
        if section.offset < table_start + table_size:
            raise ConversionError(
                f"The {name or 'unnamed'} section overlaps the header"
            )
        require_range(
            data, section.offset, section.end, f"The {name or 'unnamed'} section"
        )
        sections.append(section)

    names = tuple(section.name for section in sections)
    if names != SECTION_NAMES:
        raise ConversionError("The HKX section list is not supported")
    for current, following in pairwise(sections):
        if current.offset + current.end > following.offset:
            raise ConversionError(
                f"The {current.name} section overlaps {following.name}"
            )
    return sections[0], sections[1], sections[2]


def parse_classnames(
    data: bytes | bytearray,
    section: Section,
) -> dict[int, Classname]:
    require_range(data, section.offset, section.data1, "Class-name data")
    result: dict[int, Classname] = {}
    position = section.offset
    end = section.offset + section.data1
    while position + 5 <= end:
        signature = u32(data, position, "Class signature")
        if data[position + 4] != 0x09:
            break
        string_start = position + 5
        string_end = data.find(b"\x00", string_start, end)
        if string_end < 0:
            raise ConversionError("A class name is not terminated")
        try:
            name = bytes(data[string_start:string_end]).decode("ascii")
        except UnicodeDecodeError as exc:
            raise ConversionError("A class name is not valid ASCII") from exc
        offset = string_start - section.offset
        if offset in result:
            raise ConversionError(f"Duplicate class-name offset: 0x{offset:x}")
        result[offset] = Classname(name, signature)
        position = string_end + 1
    if not result:
        raise ConversionError("The class-name section is empty")
    return result


def parse_records(
    data: bytes | bytearray,
    start: int,
    end: int,
    width: int,
) -> tuple[tuple[int, ...], ...]:
    if width not in (8, 12):
        raise ValueError(f"Unsupported fixup record width: {width}")
    if end < start:
        raise ConversionError("A fixup table has a negative size")
    require_range(data, start, end - start, "Fixup table")
    remainder = (end - start) % width
    record_end = end - remainder
    if remainder and any(value != 0xFF for value in data[record_end:end]):
        raise ConversionError("A fixup table has invalid padding")
    format_text = "<II" if width == 8 else "<III"
    records: list[tuple[int, ...]] = []
    found_sentinel = False
    for position in range(start, record_end, width):
        record = struct.unpack_from(format_text, data, position)
        if record[0] == SENTINEL:
            if any(value != SENTINEL for value in record):
                raise ConversionError("A fixup sentinel record is invalid")
            found_sentinel = True
        elif found_sentinel:
            raise ConversionError("A fixup record follows table padding")
        records.append(record)
    return tuple(records)


def pack_records(records: Sequence[tuple[int, ...]], width: int) -> bytes:
    if width not in (8, 12):
        raise ValueError(f"Unsupported fixup record width: {width}")
    format_text = "<II" if width == 8 else "<III"
    try:
        return b"".join(struct.pack(format_text, *record) for record in records)
    except struct.error as exc:
        raise ConversionError("A fixup record has an invalid shape") from exc


def active_records(records: Sequence[tuple[int, ...]]) -> tuple[tuple[int, ...], ...]:
    return tuple(record for record in records if record[0] != SENTINEL)


def table_records(
    data: bytes | bytearray,
    section: Section,
    start_mark: int,
    end_mark: int,
    width: int,
) -> tuple[tuple[int, ...], ...]:
    return parse_records(
        data,
        section.offset + start_mark,
        section.offset + end_mark,
        width,
    )


def table_padding(
    data: bytes | bytearray,
    section: Section,
    start_mark: int,
    end_mark: int,
    width: int,
    record_count: int,
) -> bytes:
    start = section.offset + start_mark + record_count * width
    end = section.offset + end_mark
    require_range(data, start, end - start, "Fixup padding")
    return bytes(data[start:end])
