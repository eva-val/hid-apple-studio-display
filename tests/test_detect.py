"""Exercise inventory against sysfs fixtures, without opening HID devices."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

loader = importlib.machinery.SourceFileLoader(
    "detect", str(Path(__file__).resolve().parents[1] / "contrib/asd-detect"))
spec = importlib.util.spec_from_loader(loader.name, loader)
detect = importlib.util.module_from_spec(spec)
loader.exec_module(detect)


class InventoryTests(unittest.TestCase):
    def test_tiled_display_laptop_and_two_displays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def usb(path, serial, product="1114"):
                p = root / "bus/usb/devices" / path
                p.mkdir(parents=True)
                for name, text in (("idVendor", "05ac"), ("idProduct", product),
                                   ("serial", serial), ("product", "Studio Display")):
                    (p / name).write_text(text + "\n")

            def video(name, serial, vendor=b"\x06\x10", enabled="enabled"):
                p = root / "class/drm" / name
                p.mkdir(parents=True)
                data = bytearray(128)
                data[8:10] = vendor
                data[12:16] = serial.to_bytes(4, "little")
                data[108:126] = b"\0\0\0\xfc\0StudioDisplay"
                (p / "edid").write_bytes(data)
                (p / "status").write_text("connected\n")
                (p / "enabled").write_text(enabled + "\n")

            usb("5-1.4", "first")
            usb("5-1", "hub", "101d")
            video("card0-eDP-1", 0, vendor=b"\x0e\x77")
            video("card0-DP-1", 0x8D617832)
            video("card0-DP-2", 0x8D617832, enabled="disabled")
            devices = detect.inventory(root)
            self.assertEqual(len(devices["usb"]), 1)
            self.assertEqual(len(devices["video"]), 2)
            self.assertEqual(detect.single_pair(devices), "first:8d617832")
            self.assertFalse(devices["video"][1]["enabled"])
            usb("6-1.4", "second")
            video("card0-DP-3", 0x12345678)
            self.assertIsNone(detect.single_pair(detect.inventory(root)))

    def test_missing_or_zero_identity_cannot_generate_a_pair(self):
        for serial, edid in (("", "12345678"), ("usb", "00000000")):
            self.assertIsNone(detect.single_pair({
                "usb": [{"serial": serial}], "video": [{"serial": edid}]}))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect.inventory(Path(tmp)), {"usb": [], "video": []})


if __name__ == "__main__":
    unittest.main()
