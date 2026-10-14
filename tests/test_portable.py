import unittest
from pathlib import Path

from clarity.devices import endpoint_guid

MACHINE_GUID = "955162d5-3d36-485d-a83c-536abcc07e2f"


class PortableTests(unittest.TestCase):
    def test_endpoint_guid_comes_from_the_device_id(self):
        device_id = "{0.0.0.00000000}.{955162d5-3d36-485d-a83c-536abcc07e2f}"
        self.assertEqual(endpoint_guid(device_id), "{955162d5-3d36-485d-a83c-536abcc07e2f}")
        self.assertEqual(endpoint_guid(""), "")

    def test_source_does_not_bake_in_one_endpoint(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / "main.py", root / "setup.ps1", root / "README.md"]
        files.extend(root.joinpath("clarity").glob("*.py"))
        files.extend(root.joinpath("tests").glob("*.py"))
        for path in files:
            if path.name == "test_portable.py":
                continue
            text = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn(MACHINE_GUID, text, path.name)
            self.assertNotIn("adswerg", text, path.name)
