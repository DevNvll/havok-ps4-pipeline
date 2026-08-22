import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from synthetic_packfile import make_class_database, synthetic_behavior_pair

from hkx_behavior_to_ps4 import ConversionError, convert_file


class BehaviorConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.class_folder = tempfile.TemporaryDirectory()
        cls.database = make_class_database(Path(cls.class_folder.name))
        cls.pc_behavior, cls.ps4_behavior = synthetic_behavior_pair(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.class_folder.cleanup()

    def test_synthetic_behavior_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.hkx"
            output = root / "output.hkx"
            source.write_bytes(self.pc_behavior)
            objects, resized = convert_file(
                source,
                output,
                self.database,
                force=False,
            )
            self.assertEqual(objects, 1)
            self.assertEqual(resized, 0)
            self.assertEqual(output.read_bytes(), self.ps4_behavior)

    def test_ps4_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.hkx"
            source.write_bytes(self.ps4_behavior)
            with self.assertRaises(ConversionError):
                convert_file(
                    source,
                    root / "output.hkx",
                    self.database,
                    force=False,
                )


if __name__ == "__main__":
    unittest.main()
