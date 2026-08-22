import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from synthetic_packfile import make_class_database, synthetic_behavior_pair

from havok_ps4.packfile import (
    HKX_VERSION,
    MAGIC,
    PC_LAYOUT,
    PS4_LAYOUT,
    parse_sections,
)
from hkx_behavior_to_ps4 import (
    BehaviorConverter,
    ConversionError,
    convert_file,
    convert_files,
    validate_ps4_packfile,
)


class ConverterSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.class_folder = tempfile.TemporaryDirectory()
        cls.database = make_class_database(Path(cls.class_folder.name))
        cls.pc_behavior, cls.ps4_behavior = synthetic_behavior_pair(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.class_folder.cleanup()

    def test_converter_can_be_used_twice(self):
        converter = BehaviorConverter(self.pc_behavior, self.database)
        first = converter.convert()
        second = converter.convert()
        self.assertEqual(first, second)
        self.assertEqual(first, self.ps4_behavior)

    def test_large_section_padding_is_a_conversion_error(self):
        data = bytearray(0x100)
        data[:8] = MAGIC
        struct.pack_into("<I", data, 0x0C, 11)
        data[0x10:0x14] = PC_LAYOUT
        struct.pack_into("<I", data, 0x14, 3)
        data[0x28 : 0x28 + len(HKX_VERSION)] = HKX_VERSION
        struct.pack_into("<H", data, 0x3E, 0xFFFF)
        with self.assertRaisesRegex(ConversionError, "Section-header table"):
            BehaviorConverter(bytes(data), self.database)

    def test_validator_rejects_global_target_outside_data(self):
        data = bytearray(self.ps4_behavior)
        data_section = parse_sections(data, PS4_LAYOUT)[2]
        struct.pack_into(
            "<I", data, data_section.header_offset + 0x20, data_section.data3 + 12
        )
        first_global = data_section.offset + data_section.data2
        data[first_global : first_global + 12] = struct.pack(
            "<III",
            16,
            2,
            data_section.data1,
        )
        with self.assertRaisesRegex(ConversionError, "global fixup target"):
            validate_ps4_packfile(data, self.database)

    def test_validator_rejects_unknown_virtual_class(self):
        data = bytearray(self.ps4_behavior)
        data_section = parse_sections(data, PS4_LAYOUT)[2]
        first_virtual = data_section.offset + data_section.data3
        struct.pack_into("<I", data, first_virtual + 8, 0x12345678)
        with self.assertRaisesRegex(ConversionError, "Class name fixup not found"):
            validate_ps4_packfile(data, self.database)

    def test_folder_failure_does_not_commit_prior_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "inputs"
            inputs.mkdir()
            valid = inputs / "valid.hkx"
            invalid = inputs / "invalid.hkx"
            valid.write_bytes(self.pc_behavior)
            invalid.write_bytes(b"not an hkx")
            output = root / "output"
            jobs = [
                (valid, output / "valid.hkx"),
                (invalid, output / "invalid.hkx"),
            ]
            with self.assertRaises(ConversionError):
                convert_files(jobs, self.database, force=False)
            self.assertFalse((output / "valid.hkx").exists())
            self.assertFalse((output / "invalid.hkx").exists())
            self.assertEqual(list(output.iterdir()), [])

    def test_failed_replace_restores_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "inputs"
            inputs.mkdir()
            source = inputs / "behavior.hkx"
            source.write_bytes(self.pc_behavior)
            output = root / "behavior.hkx"
            output.write_bytes(b"existing output")
            real_replace = os.replace
            calls = 0

            def fail_install(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("test install failure")
                return real_replace(source, destination)

            with (
                mock.patch(
                    "havok_ps4.files.os.replace",
                    side_effect=fail_install,
                ),
                self.assertRaisesRegex(OSError, "test install failure"),
            ):
                convert_file(
                    source,
                    output,
                    self.database,
                    force=True,
                )
            self.assertEqual(output.read_bytes(), b"existing output")
            self.assertEqual(
                sorted(path.name for path in output.parent.iterdir()),
                ["behavior.hkx", "inputs"],
            )

    def test_folder_commit_failure_restores_all_prior_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "inputs"
            inputs.mkdir()
            first_input = inputs / "first.hkx"
            second_input = inputs / "second.hkx"
            first_input.write_bytes(self.pc_behavior)
            second_input.write_bytes(self.pc_behavior)
            first_output = root / "first.hkx"
            second_output = root / "second.hkx"
            first_output.write_bytes(b"old first")
            second_output.write_bytes(b"old second")
            real_replace = os.replace
            calls = 0

            def fail_second_install(source, destination):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("test batch install failure")
                return real_replace(source, destination)

            jobs = [
                (first_input, first_output),
                (second_input, second_output),
            ]
            with (
                mock.patch(
                    "havok_ps4.files.os.replace",
                    side_effect=fail_second_install,
                ),
                self.assertRaisesRegex(OSError, "test batch install failure"),
            ):
                convert_files(jobs, self.database, force=True)
            self.assertEqual(first_output.read_bytes(), b"old first")
            self.assertEqual(second_output.read_bytes(), b"old second")
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["first.hkx", "inputs", "second.hkx"],
            )


if __name__ == "__main__":
    unittest.main()
