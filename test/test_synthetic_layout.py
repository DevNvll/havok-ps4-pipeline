import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from synthetic_packfile import make_class_database

from havok_ps4.cli import DEFAULT_CLASS_DATABASE, make_parser
from hkx_behavior_to_ps4 import ClassDatabase, ConversionError


class SyntheticLayoutTests(unittest.TestCase):
    def test_cli_uses_bundled_class_database(self):
        args = make_parser().parse_args(["input.hkx", "output.hkx"])
        self.assertEqual(args.class_db, DEFAULT_CLASS_DATABASE)
        self.assertTrue((args.class_db / "hkbBehaviorGraph_1.xml").is_file())

        layout = ClassDatabase(args.class_db).get("hkbBehaviorGraph")
        self.assertEqual(layout.pc_size, 432)
        self.assertEqual(layout.ps4_size, 424)

    def test_base_tail_padding_is_reused_for_ps4(self):
        with tempfile.TemporaryDirectory() as folder:
            database = make_class_database(Path(folder))
            layout = database.get("hkbBehaviorGraph")
            members = {member.name: member for member in layout.members}

            self.assertEqual(layout.pc_size, 48)
            self.assertEqual(layout.ps4_size, 40)
            self.assertEqual(members["mode"].pc_offset, 16)
            self.assertEqual(members["mode"].ps4_offset, 12)
            self.assertEqual(members["values"].pc_offset, 24)
            self.assertEqual(members["values"].ps4_offset, 16)
            self.assertEqual(members["nextId"].pc_offset, 40)
            self.assertEqual(members["nextId"].ps4_offset, 32)

    def test_class_xml_rejects_entity_declarations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Unsafe_0.xml").write_text(
                """<!DOCTYPE class [<!ENTITY value "unsafe">]>
<class name="Unsafe" signature="0x1" size="0" />
""",
                encoding="utf-8",
            )
            database = ClassDatabase(root)
            with self.assertRaisesRegex(ConversionError, "DTD or entity"):
                database.get("Unsafe")


if __name__ == "__main__":
    unittest.main()
