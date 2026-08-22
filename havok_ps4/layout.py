"""Calculate PC and PS4 class layouts from compatible class XML data."""

from __future__ import annotations

import dataclasses
import enum
import re
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path

from .errors import ConversionError

MAX_CLASS_XML_BYTES = 1_000_000
FORBIDDEN_XML_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def parse_class_xml(path: Path) -> ET.Element:
    """Read the limited class XML format without DTD or entity declarations."""
    raw = path.read_bytes()
    if len(raw) > MAX_CLASS_XML_BYTES:
        raise ConversionError(f"Class data is too large: {path}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionError(f"Class data is not UTF-8: {path}") from exc
    if FORBIDDEN_XML_DECLARATION.search(text):
        raise ConversionError(
            f"Class data contains a DTD or entity declaration: {path}"
        )
    try:
        # The size and declaration checks above block XML entity attacks.
        root = ET.fromstring(text)  # nosec B314
    except ET.ParseError as exc:
        raise ConversionError(f"Class data is invalid: {path}") from exc
    if root.tag not in {"class", "struct"}:
        raise ConversionError(f"Class data has an invalid root element: {path}")
    return root


def align(value: int, boundary: int) -> int:
    if boundary <= 1:
        return value
    return (value + boundary - 1) // boundary * boundary


class Platform(enum.Enum):
    PC = "pc"
    PS4 = "ps4"


@dataclasses.dataclass(frozen=True, slots=True)
class ScalarLayout:
    size: int
    alignment: int


@dataclasses.dataclass(frozen=True, slots=True)
class Member:
    name: str
    pc_offset: int
    ps4_offset: int
    vtype: str
    vsubtype: str
    target: str
    count: int


@dataclasses.dataclass(frozen=True, slots=True)
class ClassLayout:
    name: str
    signature: int
    members: tuple[Member, ...]
    alignment: int
    pc_data_size: int
    ps4_data_size: int
    pc_size: int
    ps4_size: int


SCALAR_LAYOUTS: dict[str, ScalarLayout] = {
    "TYPE_NONE": ScalarLayout(0, 1),
    "TYPE_VOID": ScalarLayout(0, 1),
    "TYPE_BOOL": ScalarLayout(1, 1),
    "TYPE_CHAR": ScalarLayout(1, 1),
    "TYPE_INT8": ScalarLayout(1, 1),
    "TYPE_UINT8": ScalarLayout(1, 1),
    "TYPE_HALF": ScalarLayout(2, 2),
    "TYPE_INT16": ScalarLayout(2, 2),
    "TYPE_UINT16": ScalarLayout(2, 2),
    "TYPE_INT32": ScalarLayout(4, 4),
    "TYPE_UINT32": ScalarLayout(4, 4),
    "TYPE_REAL": ScalarLayout(4, 4),
    "TYPE_INT64": ScalarLayout(8, 8),
    "TYPE_UINT64": ScalarLayout(8, 8),
    "TYPE_ULONG": ScalarLayout(8, 8),
    "TYPE_CSTRING": ScalarLayout(8, 8),
    "TYPE_STRINGPTR": ScalarLayout(8, 8),
    "TYPE_POINTER": ScalarLayout(8, 8),
    "TYPE_FUNCTIONPOINTER": ScalarLayout(8, 8),
    "TYPE_VARIANT": ScalarLayout(16, 8),
    "TYPE_ARRAY": ScalarLayout(16, 8),
    "TYPE_SIMPLEARRAY": ScalarLayout(16, 8),
    "TYPE_RELARRAY": ScalarLayout(4, 2),
    "TYPE_VECTOR4": ScalarLayout(16, 16),
    "TYPE_QUATERNION": ScalarLayout(16, 16),
    "TYPE_ROTATION": ScalarLayout(48, 16),
    "TYPE_QSTRANSFORM": ScalarLayout(48, 16),
    "TYPE_MATRIX3": ScalarLayout(48, 16),
    "TYPE_TRANSFORM": ScalarLayout(64, 16),
    "TYPE_MATRIX4": ScalarLayout(64, 16),
}


class ClassDatabase:
    """Load Fallout 4 Havok class descriptions when needed."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._path_cache: dict[str, Path] = {}
        self._layout_cache: dict[str, ClassLayout] = {}
        self._loading: set[str] = set()
        if not root.is_dir():
            raise ConversionError(f"Class data folder not found: {root}")

    def _find_path(self, name: str) -> Path:
        cached = self._path_cache.get(name)
        if cached is not None:
            return cached
        prefix = f"{name}_"
        for candidate in sorted(self.root.iterdir()):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() != ".xml" or not candidate.name.startswith(
                prefix
            ):
                continue
            xml_root = parse_class_xml(candidate)
            if xml_root.attrib.get("name") == name:
                self._path_cache[name] = candidate
                return candidate
        raise ConversionError(f"Class data is missing for {name}")

    def get(self, name: str) -> ClassLayout:
        cached = self._layout_cache.get(name)
        if cached is not None:
            return cached
        if name in self._loading:
            raise ConversionError(f"Class parent loop found at {name}")
        self._loading.add(name)
        try:
            layout = self._load(name)
            self._layout_cache[name] = layout
            return layout
        finally:
            self._loading.remove(name)

    def _load(self, name: str) -> ClassLayout:
        path = self._find_path(name)
        try:
            xml_root = parse_class_xml(path)
            signature = int(xml_root.attrib.get("signature", "0"), 16)
        except ValueError as exc:
            raise ConversionError(f"Class data is invalid: {path}") from exc
        parent_name = xml_root.attrib.get("parent", "")
        parent = self.get(parent_name) if parent_name else None

        base_size = 8 if name == "hkBaseObject" else 0
        base_alignment = 8 if name == "hkBaseObject" else 1
        inherited = parent.members if parent else ()
        pc_cursor = parent.pc_size if parent else base_size
        ps4_cursor = parent.ps4_data_size if parent else base_size
        max_alignment = parent.alignment if parent else base_alignment
        direct: list[Member] = []

        members_node = xml_root.find("members")
        nodes = members_node.findall("member") if members_node is not None else ()
        for node in nodes:
            vtype = node.attrib.get("vtype", "TYPE_NONE")
            vsubtype = node.attrib.get("vsubtype", "TYPE_NONE")
            target = node.attrib.get("ctype", "")
            try:
                count = max(1, int(node.attrib.get("arrsize", "0")))
                pc_offset = int(node.attrib.get("offset", "0"))
            except ValueError as exc:
                raise ConversionError(f"Class member data is invalid: {path}") from exc
            member_alignment = self.type_alignment(vtype, vsubtype, target)
            pc_element_size = self.type_size(vtype, vsubtype, target, Platform.PC)
            ps4_element_size = self.type_size(vtype, vsubtype, target, Platform.PS4)
            expected_pc = align(pc_cursor, member_alignment)
            if pc_offset < expected_pc:
                member_name = node.attrib.get("name", "")
                raise ConversionError(
                    f"Class member overlaps prior data: {name}.{member_name}"
                )
            explicit_gap = pc_offset - expected_pc
            ps4_offset = align(ps4_cursor, member_alignment) + explicit_gap
            direct.append(
                Member(
                    name=node.attrib.get("name", ""),
                    pc_offset=pc_offset,
                    ps4_offset=ps4_offset,
                    vtype=vtype,
                    vsubtype=vsubtype,
                    target=target,
                    count=count,
                )
            )
            pc_cursor = pc_offset + pc_element_size * count
            ps4_cursor = ps4_offset + ps4_element_size * count
            max_alignment = max(max_alignment, member_alignment)

        if not direct and parent:
            pc_data_size = parent.pc_data_size
            ps4_data_size = parent.ps4_data_size
        else:
            pc_data_size = pc_cursor
            ps4_data_size = ps4_cursor
        pc_size = align(pc_data_size, max_alignment)
        ps4_size = align(ps4_data_size, max_alignment)
        declared_size = xml_root.attrib.get("size")
        if declared_size is not None:
            try:
                parsed_size = int(declared_size)
            except ValueError as exc:
                raise ConversionError(f"Class size is invalid: {path}") from exc
            if parsed_size != pc_size:
                raise ConversionError(
                    f"Calculated PC class size does not match XML for {name}: "
                    f"{pc_size} != {declared_size}"
                )
        return ClassLayout(
            name=name,
            signature=signature,
            members=inherited + tuple(direct),
            alignment=max_alignment,
            pc_data_size=pc_data_size,
            ps4_data_size=ps4_data_size,
            pc_size=pc_size,
            ps4_size=ps4_size,
        )

    def type_size(
        self,
        vtype: str,
        vsubtype: str,
        target: str,
        platform: Platform,
    ) -> int:
        if vtype in ("TYPE_ENUM", "TYPE_FLAGS"):
            return self._scalar(vsubtype, "enum storage").size
        if vtype == "TYPE_STRUCT":
            layout = self.get(target)
            return layout.ps4_size if platform is Platform.PS4 else layout.pc_size
        return self._scalar(vtype, "Havok member").size

    def type_alignment(self, vtype: str, vsubtype: str, target: str) -> int:
        if vtype in ("TYPE_ENUM", "TYPE_FLAGS"):
            return self._scalar(vsubtype, "enum storage").alignment
        if vtype == "TYPE_STRUCT":
            return self.get(target).alignment
        return self._scalar(vtype, "Havok member").alignment

    @staticmethod
    def _scalar(vtype: str, label: str) -> ScalarLayout:
        try:
            return SCALAR_LAYOUTS[vtype]
        except KeyError as exc:
            raise ConversionError(f"Unsupported {label} type: {vtype}") from exc
