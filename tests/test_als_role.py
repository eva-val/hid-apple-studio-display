"""Keep a sole ALS; classify dual sensors within their own HID interface."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'contrib/asd-als-role'


class SensorRoleTests(unittest.TestCase):
    def role(self, root, path):
        return subprocess.run(['sh', str(HELPER), '/' + str(path.relative_to(root))],
                              env={**os.environ, 'ASD_SYSFS_ROOT': str(root)},
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_single_sensor_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'devices/hid/HID-SENSOR-200041.11.auto/iio:device1'
            path.mkdir(parents=True)
            self.assertEqual(self.role(root, path), 'single')

    def test_dual_sensor_order_is_numeric_and_per_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for hid in ('first', 'second'):
                for number in (9, 10):
                    path = root / f'devices/{hid}/HID-SENSOR-200041.{number}.auto/iio:device{number}'
                    path.mkdir(parents=True)
                for number, expected in ((9, 'rear'), (10, 'front')):
                    path = root / f'devices/{hid}/HID-SENSOR-200041.{number}.auto/iio:device{number}'
                    self.assertEqual(self.role(root, path), expected)
            single = root / 'devices/third/HID-SENSOR-200041.2.auto/iio:device2'
            single.mkdir(parents=True)
            self.assertEqual(self.role(root, single), 'single')


if __name__ == '__main__':
    unittest.main()
