"""Build small synthetic behavior packfiles for tests."""

from __future__ import annotations

import struct
from pathlib import Path

from havok_ps4 import ClassDatabase
from havok_ps4.packfile import HKX_VERSION, MAGIC, PC_LAYOUT, PS4_LAYOUT

CLASS_NAME = "hkbBehaviorGraph"
CLASSNAME_OFFSET = 5
CLASS_SECTION_OFFSET = 0x100

BASE_CLASS_XML = """\
<class name="SyntheticBase" signature="0x10203040" size="16">
  <members>
    <member name="prefix" vtype="TYPE_UINT64" vsubtype="TYPE_VOID" offset="0" arrsize="0" />
    <member name="tail" vtype="TYPE_UINT32" vsubtype="TYPE_VOID" offset="8" arrsize="0" />
  </members>
</class>
"""

BEHAVIOR_CLASS_XML = """\
<class name="hkbBehaviorGraph" parent="SyntheticBase" signature="0x12345678" size="48">
  <members>
    <member name="mode" vtype="TYPE_UINT8" vsubtype="TYPE_VOID" offset="16" arrsize="0" />
    <member name="values" vtype="TYPE_ARRAY" vsubtype="TYPE_UINT32" offset="24" arrsize="0" />
    <member name="nextId" vtype="TYPE_UINT16" vsubtype="TYPE_VOID" offset="40" arrsize="0" />
  </members>
</class>
"""


def make_class_database(root: Path) -> ClassDatabase:
    """Write hand-made class definitions and return their database."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SyntheticBase_0.xml").write_text(BASE_CLASS_XML, encoding="utf-8")
    (root / "hkbBehaviorGraph_0.xml").write_text(
        BEHAVIOR_CLASS_XML,
        encoding="utf-8",
    )
    return ClassDatabase(root)


def _write_section(
    data: bytearray,
    header_offset: int,
    name: str,
    values: tuple[int, int, int, int, int, int, int],
) -> None:
    encoded_name = name.encode("ascii")
    data[header_offset : header_offset + len(encoded_name)] = encoded_name
    struct.pack_into("<7I", data, header_offset + 0x14, *values)


def make_packfile(layout: bytes, object_data: bytes, signature: int) -> bytes:
    """Build one packfile with one synthetic hkbBehaviorGraph object."""
    class_data = struct.pack("<I", signature) + b"\x09" + CLASS_NAME.encode() + b"\x00"
    type_section_offset = CLASS_SECTION_OFFSET + len(class_data)
    data_section_offset = type_section_offset
    virtual = struct.pack("<III", 0, 0, CLASSNAME_OFFSET)
    object_end = len(object_data)
    data_end = object_end + len(virtual)
    data = bytearray(data_section_offset + data_end)

    data[:8] = MAGIC
    struct.pack_into("<I", data, 0x0C, 11)
    data[0x10:0x14] = layout
    struct.pack_into("<I", data, 0x14, 3)
    data[0x28 : 0x28 + len(HKX_VERSION)] = HKX_VERSION
    _write_section(
        data,
        0x40,
        "__classnames__",
        (CLASS_SECTION_OFFSET,) + (len(class_data),) * 6,
    )
    _write_section(
        data,
        0x80,
        "__types__",
        (type_section_offset, 0, 0, 0, 0, 0, 0),
    )
    _write_section(
        data,
        0xC0,
        "__data__",
        (
            data_section_offset,
            object_end,
            object_end,
            object_end,
            data_end,
            data_end,
            data_end,
        ),
    )
    data[CLASS_SECTION_OFFSET:type_section_offset] = class_data
    data[data_section_offset : data_section_offset + object_end] = object_data
    data[data_section_offset + object_end :] = virtual
    return bytes(data)


def synthetic_behavior_pair(database: ClassDatabase) -> tuple[bytes, bytes]:
    """Return a PC input and its manually defined PS4 result."""
    layout = database.get(CLASS_NAME)
    pc_object = bytearray(48)
    pc_object[0:8] = bytes.fromhex("8877665544332211")
    pc_object[8:12] = bytes.fromhex("ddccbbaa")
    pc_object[16] = 0xA1
    pc_object[24:40] = bytes(range(0x20, 0x30))
    struct.pack_into("<H", pc_object, 40, 0xBEEF)

    ps4_object = bytearray(48)
    ps4_object[0:8] = bytes.fromhex("8877665544332211")
    ps4_object[8:12] = bytes.fromhex("ddccbbaa")
    ps4_object[12] = 0xA1
    ps4_object[16:32] = bytes(range(0x20, 0x30))
    struct.pack_into("<H", ps4_object, 32, 0xBEEF)
    return (
        make_packfile(PC_LAYOUT, pc_object, layout.signature),
        make_packfile(PS4_LAYOUT, ps4_object, layout.signature),
    )
