"""Convert Fallout 4 PC behavior objects and fixups to the PS4 layout."""

from __future__ import annotations

import bisect
import dataclasses

from .errors import ConversionError
from .layout import ClassDatabase, ClassLayout, Platform, align
from .packfile import (
    PC_LAYOUT,
    PS4_LAYOUT,
    SENTINEL,
    active_records,
    pack_records,
    parse_classnames,
    parse_sections,
    put_u32,
    table_padding,
    table_records,
)
from .validator import validate_ps4_packfile


@dataclasses.dataclass(frozen=True, slots=True)
class AddressSegment:
    old_start: int
    old_end: int
    new_start: int

    def map(self, value: int) -> int:
        return self.new_start + value - self.old_start


class OffsetMap:
    """Map old offsets through checked, non-overlapping address segments."""

    def __init__(
        self,
        segments: list[AddressSegment],
        points: dict[int, int],
    ) -> None:
        ordered = sorted(segments, key=lambda segment: segment.old_start)
        previous_end = 0
        for segment in ordered:
            if segment.old_start < previous_end:
                raise ConversionError("Address-map segments overlap")
            if segment.old_end <= segment.old_start:
                raise ConversionError("An address-map segment is empty")
            previous_end = segment.old_end
        self._segments = tuple(ordered)
        self._starts = tuple(segment.old_start for segment in ordered)
        self._points = dict(points)

    def map(self, old_offset: int) -> int:
        if old_offset == SENTINEL:
            return old_offset
        point = self._points.get(old_offset)
        if point is not None:
            return point
        index = bisect.bisect_right(self._starts, old_offset) - 1
        if index >= 0:
            segment = self._segments[index]
            if old_offset < segment.old_end:
                return segment.map(old_offset)
        raise ConversionError(f"Cannot map data offset 0x{old_offset:x}")


@dataclasses.dataclass(frozen=True, slots=True)
class ObjectConversion:
    old_start: int
    new_start: int
    old_storage_size: int
    new_storage_size: int


@dataclasses.dataclass(frozen=True, slots=True)
class ConversionPlan:
    object_data: bytes
    offset_map: OffsetMap
    objects: tuple[ObjectConversion, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ConversionReport:
    object_count: int
    resized_object_count: int


@dataclasses.dataclass(frozen=True, slots=True)
class FixupBytes:
    local: bytes
    global_fixups: bytes
    virtual: bytes
    exports: bytes
    imports: bytes


class BehaviorConverter:
    """Convert one immutable PC behavior packfile."""

    def __init__(self, data: bytes, database: ClassDatabase) -> None:
        self.data = data
        self.database = database
        self.sections = parse_sections(data, PC_LAYOUT)
        self.class_section = self.sections[0]
        self.data_section = self.sections[2]
        self.classnames = parse_classnames(data, self.class_section)
        self.virtual_fixups = active_records(
            table_records(
                data,
                self.data_section,
                self.data_section.data3,
                self.data_section.data4,
                12,
            )
        )
        if not self._is_behavior():
            raise ConversionError("The HKX file is not a behavior graph")

    def _is_behavior(self) -> bool:
        for _, class_section, class_offset in self.virtual_fixups:
            if class_section != 0:
                continue
            classname = self.classnames.get(class_offset)
            if classname is not None and classname.name == "hkbBehaviorGraph":
                return True
        return False

    def _copy_members(
        self,
        source: bytes,
        destination: bytearray,
        layout: ClassLayout,
        old_base: int,
        new_base: int,
        segments: list[AddressSegment],
    ) -> None:
        for member in layout.members:
            pc_size = self.database.type_size(
                member.vtype,
                member.vsubtype,
                member.target,
                Platform.PC,
            )
            ps4_size = self.database.type_size(
                member.vtype,
                member.vsubtype,
                member.target,
                Platform.PS4,
            )
            for index in range(member.count):
                old_offset = member.pc_offset + index * pc_size
                new_offset = member.ps4_offset + index * ps4_size
                old_end = old_offset + pc_size
                new_end = new_offset + ps4_size
                if old_end > len(source) or new_end > len(destination):
                    raise ConversionError(
                        f"Member {layout.name}.{member.name} is outside its object"
                    )
                absolute_old = old_base + old_offset
                absolute_new = new_base + new_offset
                if member.vtype == "TYPE_STRUCT":
                    nested = self.database.get(member.target)
                    nested_destination = bytearray(ps4_size)
                    self._copy_members(
                        source[old_offset:old_end],
                        nested_destination,
                        nested,
                        absolute_old,
                        absolute_new,
                        segments,
                    )
                    destination[new_offset:new_end] = nested_destination
                    continue
                if pc_size != ps4_size:
                    raise ConversionError(
                        f"Unsupported member size change: {layout.name}.{member.name}"
                    )
                destination[new_offset:new_end] = source[old_offset:old_end]
                if pc_size:
                    segments.append(
                        AddressSegment(
                            absolute_old, absolute_old + pc_size, absolute_new
                        )
                    )

    def _transform_object(
        self,
        source: bytes,
        layout: ClassLayout,
        old_start: int,
        new_start: int,
        new_storage: int,
        segments: list[AddressSegment],
    ) -> bytes:
        destination = bytearray(new_storage)
        self._copy_members(
            source,
            destination,
            layout,
            old_start,
            new_start,
            segments,
        )
        return bytes(destination)

    def _build_plan(self) -> ConversionPlan:
        section = self.data_section
        raw = self.data[section.offset : section.offset + section.data1]
        virtual = sorted(self.virtual_fixups, key=lambda record: record[0])
        output = bytearray()
        old_cursor = 0
        segments: list[AddressSegment] = []
        object_points: dict[int, int] = {}
        objects: list[ObjectConversion] = []

        for old_start, class_section, class_offset in virtual:
            if class_section != 0:
                raise ConversionError("An object uses an unsupported class section")
            classname = self.classnames.get(class_offset)
            if classname is None:
                raise ConversionError(f"Class name fixup not found: {class_offset}")
            layout = self.database.get(classname.name)
            if layout.signature != classname.signature:
                raise ConversionError(
                    f"Class signature does not match for {classname.name}: "
                    f"file 0x{classname.signature:08x}, "
                    f"data 0x{layout.signature:08x}"
                )
            old_storage = align(layout.pc_size, 16)
            new_storage = align(layout.ps4_size, 16)
            if old_start < old_cursor:
                raise ConversionError(f"Object ranges overlap at {classname.name}")
            if old_start + old_storage > len(raw):
                raise ConversionError(f"Object is outside data: {classname.name}")

            if old_cursor < old_start:
                new_unchanged_start = len(output)
                output.extend(raw[old_cursor:old_start])
                segments.append(
                    AddressSegment(old_cursor, old_start, new_unchanged_start)
                )

            new_start = len(output)
            if old_start in object_points:
                raise ConversionError(f"Duplicate object offset: 0x{old_start:x}")
            object_points[old_start] = new_start
            object_source = raw[old_start : old_start + old_storage]
            output.extend(
                self._transform_object(
                    object_source,
                    layout,
                    old_start,
                    new_start,
                    new_storage,
                    segments,
                )
            )
            objects.append(
                ObjectConversion(
                    old_start,
                    new_start,
                    old_storage,
                    new_storage,
                )
            )
            old_cursor = old_start + old_storage

        if old_cursor < len(raw):
            tail_start = len(output)
            output.extend(raw[old_cursor:])
            segments.append(AddressSegment(old_cursor, len(raw), tail_start))
        if len(output) % 16:
            raise ConversionError("The converted object data is not 16-byte aligned")
        return ConversionPlan(
            bytes(output),
            OffsetMap(segments, object_points),
            tuple(objects),
        )

    def _map_fixup_table(
        self,
        start_mark: int,
        end_mark: int,
        width: int,
    ) -> tuple[tuple[tuple[int, ...], ...], bytes]:
        records = table_records(
            self.data,
            self.data_section,
            start_mark,
            end_mark,
            width,
        )
        padding = table_padding(
            self.data,
            self.data_section,
            start_mark,
            end_mark,
            width,
            len(records),
        )
        return records, padding

    def _mapped_fixups(self, plan: ConversionPlan) -> FixupBytes:
        section = self.data_section
        local_records, local_padding = self._map_fixup_table(
            section.data1, section.data2, 8
        )
        global_records, global_padding = self._map_fixup_table(
            section.data2, section.data3, 12
        )
        virtual_records, virtual_padding = self._map_fixup_table(
            section.data3, section.data4, 12
        )

        mapped_local = tuple(
            record
            if record[0] == SENTINEL
            else (plan.offset_map.map(record[0]), plan.offset_map.map(record[1]))
            for record in local_records
        )
        mapped_global = tuple(
            record
            if record[0] == SENTINEL
            else (
                plan.offset_map.map(record[0]),
                record[1],
                plan.offset_map.map(record[2]) if record[1] == 2 else record[2],
            )
            for record in global_records
        )
        mapped_virtual = tuple(
            record
            if record[0] == SENTINEL
            else (plan.offset_map.map(record[0]), record[1], record[2])
            for record in virtual_records
        )

        absolute = section.offset
        exports = self.data[absolute + section.data4 : absolute + section.data5]
        imports = self.data[absolute + section.data5 : absolute + section.end]
        if exports or imports:
            raise ConversionError("Behavior exports or imports are not supported")
        return FixupBytes(
            pack_records(mapped_local, 8) + local_padding,
            pack_records(mapped_global, 12) + global_padding,
            pack_records(mapped_virtual, 12) + virtual_padding,
            exports,
            imports,
        )

    def convert_with_report(self) -> tuple[bytes, ConversionReport]:
        plan = self._build_plan()
        fixups = self._mapped_fixups(plan)
        section = self.data_section
        new_data = b"".join(
            (
                plan.object_data,
                fixups.local,
                fixups.global_fixups,
                fixups.virtual,
                fixups.exports,
                fixups.imports,
            )
        )
        old_data_end = section.offset + section.end
        output = bytearray(self.data[: section.offset])
        output.extend(new_data)
        output.extend(self.data[old_data_end:])

        data1 = len(plan.object_data)
        data2 = data1 + len(fixups.local)
        data3 = data2 + len(fixups.global_fixups)
        data4 = data3 + len(fixups.virtual)
        data5 = data4 + len(fixups.exports)
        end = data5 + len(fixups.imports)
        for index, value in enumerate((data1, data2, data3, data4, data5, end)):
            put_u32(output, section.header_offset + 0x18 + index * 4, value)
        output[0x10:0x14] = PS4_LAYOUT

        validation = validate_ps4_packfile(output, self.database)
        if validation.object_count != len(plan.objects):
            raise ConversionError(
                "The output object count does not match the conversion plan"
            )
        report = ConversionReport(
            object_count=len(plan.objects),
            resized_object_count=sum(
                item.old_storage_size != item.new_storage_size for item in plan.objects
            ),
        )
        return bytes(output), report

    def convert(self) -> bytes:
        converted, _ = self.convert_with_report()
        return converted
