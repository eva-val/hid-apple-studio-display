"""Pair physical USB displays with DRM outputs and recover after hotplug."""
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from display_config_fixtures import assert_valid_payload

loader = importlib.machinery.SourceFileLoader(
    "autorotate", str(Path(__file__).resolve().parents[1] / "contrib/asd-autorotate"))
spec = importlib.util.spec_from_loader(loader.name, loader)
rotate = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = rotate
loader.exec_module(rotate)


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("bus/iio/devices", "bus/usb/devices", "class/backlight", "class/drm"):
            (self.root / directory).mkdir(parents=True)
        self.config = Mock()
        self.transforms = {"DP-1": 0, "DP-2": 0}
        self.config.current_transform.side_effect = self.transforms.get
        self.config.set_transform.side_effect = self.transforms.__setitem__
        self.rotator = rotate.Rotator(self.config)
        silence = patch("builtins.print")
        silence.start()
        self.addCleanup(silence.stop)

    def add_display(self, serial, number, connector, angle=90):
        usb = self.root / "devices/usb" / serial
        usb.mkdir(parents=True, exist_ok=True)
        (usb / "idVendor").write_text("05ac")
        (usb / "idProduct").write_text("1114")
        (usb / "serial").write_text(serial)
        usb_link = self.root / "bus/usb/devices" / serial
        if not usb_link.is_symlink():
            usb_link.symlink_to(usb)
        sensor = usb / f"orientation-hid/iio:device{number}"
        sensor.mkdir(parents=True)
        (sensor / "name").write_text(rotate.IIO_NAME)
        for axis, value in zip("xyz", (0, 0, angle)):
            (sensor / f"in_incli_{axis}_raw").write_text(str(value))
        (self.root / "bus/iio/devices" / sensor.name).symlink_to(sensor)
        hid = usb / "brightness-hid"
        hid.mkdir(exist_ok=True)
        drm = self.root / "devices/gpu" / connector
        drm.mkdir(parents=True, exist_ok=True)
        (drm / "status").write_text("connected")
        (self.root / "class/drm" / connector).symlink_to(drm)
        backlight = drm / f"apple_studio_display{number}"
        backlight.mkdir()
        (backlight / "physical_device").symlink_to(usb)
        (self.root / "class/backlight" / backlight.name).symlink_to(backlight)
        return sensor, backlight

    def add_light(self, usb, number):
        sensor = usb / f"light-hid/HID-SENSOR-200041.{number}.auto/iio:device{number}"
        sensor.mkdir(parents=True)
        (sensor / "name").write_text("als")
        (self.root / "bus/iio/devices" / sensor.name).symlink_to(sensor)
        return sensor

    def test_physical_inventory_groups_all_functions_and_excludes_laptop_als(self):
        from asd_devices import physical_displays
        first, _ = self.add_display("A", 9, "card0-DP-1")
        second, _ = self.add_display("B", 1, "card0-DP-2")
        self.add_light(first.parents[1], 12)
        self.add_light(second.parents[1], 20)
        self.add_light(second.parents[1], 21)  # front/rear both belong to B
        self.add_light(self.root / "devices/laptop", 0)
        displays = {d["serial"]: d for d in physical_displays(self.root)}
        self.assertEqual(set(displays), {"A", "B"})
        for serial, connector, lights in (("A", "card0-DP-1", 1), ("B", "card0-DP-2", 2)):
            display = displays[serial]
            self.assertEqual(len(display["ambient_light"]), lights)
            self.assertEqual(len(display["orientation"]), 1)
            self.assertEqual(display["backlights"][0]["connector"], connector)
            self.assertTrue(all(item["usb_path"] == display["path"]
                                for key in ("ambient_light", "orientation", "backlights")
                                for item in display[key]))
        shutil.rmtree(first.parents[1])
        self.assertEqual([d["serial"] for d in physical_displays(self.root)], ["B"])

    def test_sensors_group_without_brightness_or_gnome(self):
        from asd_devices import physical_displays
        sensor, bl = self.add_display("A", 1, "card0-DP-1")
        self.add_light(sensor.parents[1], 2)
        (bl / "physical_device").unlink()
        display, = physical_displays(self.root)
        self.assertEqual(len(display["ambient_light"]), 1)
        self.assertEqual(len(display["orientation"]), 1)
        self.assertEqual(display["backlights"], [])

    def displays(self, serial=None, connector=None):
        return rotate.find_displays(rotate.find_sensors(self.root, serial), self.root, connector)

    def poll(self):
        self.rotator.poll(self.displays())

    def test_two_displays_pair_by_usb_not_enumeration_order(self):
        self.add_display("A", 9, "card0-DP-1", 90)
        self.add_display("B", 1, "card0-DP-2", 270)
        sensors = list(reversed(rotate.find_sensors(self.root)))
        pairs = rotate.find_displays(sensors, self.root)
        self.assertEqual({p.sensor.serial: p.connector for p in pairs}, {"A": "DP-1", "B": "DP-2"})
        self.rotator.poll(pairs)
        self.config.set_transform.assert_not_called()
        self.rotator.poll(pairs)
        self.assertEqual(self.transforms, {"DP-1": 1, "DP-2": 3})

    def test_no_displays_at_start_then_hotplug(self):
        self.poll()
        self.add_display("A", 4, "card0-DP-1")
        self.poll()
        self.config.set_transform.assert_not_called()
        self.poll()
        self.config.set_transform.assert_called_once_with("DP-1", 1)

    def test_unplug_replug_new_sensor_and_connector(self):
        sensor, backlight = self.add_display("A", 1, "card0-DP-1")
        self.poll()
        self.poll()
        shutil.rmtree(sensor.parents[1])
        shutil.rmtree(backlight.parent)
        self.poll()  # dangling class symlinks must be harmless
        self.assertEqual(self.rotator.pending, {})
        self.add_display("A", 7, "card0-DP-2", 180)
        self.poll()
        self.assertEqual(self.transforms["DP-2"], 0)
        self.poll()
        self.assertEqual(self.transforms["DP-2"], 2)

    def test_sensor_replacement_resets_debounce_without_empty_poll(self):
        sensor, _ = self.add_display("A", 1, "card0-DP-1")
        self.poll()
        replacement = sensor.with_name("iio:device8")
        sensor.rename(replacement)
        (self.root / "bus/iio/devices" / replacement.name).symlink_to(replacement)
        self.poll()
        self.config.set_transform.assert_not_called()
        self.poll()
        self.config.set_transform.assert_called_once_with("DP-1", 1)

    def test_missing_hid_link_never_guesses_even_for_one_display(self):
        _, bl = self.add_display("A", 1, "card0-DP-1")
        (bl / "physical_device").unlink()
        self.assertEqual(self.displays(), [])
        self.assertEqual(len(rotate.find_sensors(self.root)), 1)  # --watch still works

    def test_unrelated_or_usb_parented_backlight_is_ignored(self):
        _, bl = self.add_display("A", 1, "card0-DP-1")
        (bl / "physical_device").unlink()
        (bl / "physical_device").symlink_to(self.root / "devices/gpu")
        self.assertEqual(self.displays(), [])
        (bl / "physical_device").unlink()
        (bl / "physical_device").symlink_to(self.root / "devices/usb/A")
        bl.rename(self.root / "devices/usb/A" / bl.name)
        link = self.root / "class/backlight" / bl.name
        link.unlink()
        link.symlink_to(self.root / "devices/usb/A" / bl.name)
        self.assertEqual(self.displays(), [])

    def test_duplicate_bare_connector_across_gpus_is_unsafe(self):
        self.add_display("A", 1, "card0-DP-1")
        self.add_display("B", 2, "card1-DP-1")
        self.assertEqual(self.displays(), [])
        self.assertEqual(self.displays(connector="card0-DP-1"), [])

    def test_duplicate_sensors_on_one_display_are_unsafe(self):
        sensor, _ = self.add_display("A", 1, "card0-DP-1")
        other = sensor.with_name("iio:device2")
        shutil.copytree(sensor, other)
        (self.root / "bus/iio/devices" / other.name).symlink_to(other)
        self.assertEqual(self.displays(), [])

    def test_serial_and_connector_filter_matched_pairs(self):
        self.add_display("A", 1, "card0-DP-1")
        self.add_display("B", 2, "card0-DP-2")
        self.assertEqual([p.connector for p in self.displays(serial="B")], ["DP-2"])
        self.assertEqual([p.sensor.serial for p in self.displays(connector="DP-1")], ["A"])
        self.assertEqual(self.displays(serial="A", connector="DP-2"), [])

    def test_inactive_output_waits_and_rechecks_after_lid_or_session_change(self):
        self.add_display("A", 1, "card0-DP-1")
        self.transforms.clear()
        self.poll()
        self.poll()
        self.config.set_transform.assert_not_called()
        self.transforms["DP-1"] = 0
        self.poll()
        self.poll()
        self.assertEqual(self.transforms["DP-1"], 1)
        self.transforms["DP-1"] = 0  # compositor reset; sensor has not moved
        self.poll()
        self.assertEqual(self.transforms["DP-1"], 1)

    def test_bad_sensor_does_not_block_second_display_and_resets_debounce(self):
        sensor, _ = self.add_display("A", 1, "card0-DP-1")
        self.add_display("B", 2, "card0-DP-2", 180)
        self.poll()
        (sensor / "in_incli_z_raw").write_text("invalid")
        self.poll()
        self.assertEqual(self.transforms, {"DP-1": 0, "DP-2": 2})
        (sensor / "in_incli_z_raw").write_text("90")
        self.poll()
        self.assertEqual(self.transforms["DP-1"], 0)
        self.poll()
        self.assertEqual(self.transforms["DP-1"], 1)

    def test_transient_dbus_failure_retries(self):
        self.add_display("A", 1, "card0-DP-1")
        self.poll()
        self.config.set_transform.side_effect = rotate.GLib.Error("stale serial")
        self.poll()
        self.config.set_transform.side_effect = self.transforms.__setitem__
        self.poll()
        self.assertEqual(self.transforms["DP-1"], 1)


class DisplayConfigTests(unittest.TestCase):
    def state(self, laptop, mirrored=False):
        monitors = [(("DP-1", "APP", "Studio", "one"),
                     [("studio-mode", 5120, 2880, 60., 2., [2.], {"is-current": True})], {})]
        logical = [(0, 0, 2.0, 0, True, [("DP-1", "APP", "Studio", "one")], {})]
        if laptop:
            monitors.append((("eDP-1", "BOE", "Panel", "two"),
                             [("laptop-mode", 2880, 1920, 60., 1.5, [1.5], {"is-current": True})], {}))
            if mirrored:
                logical[0][5].append(("eDP-1", "BOE", "Panel", "two"))
            else:
                logical.append((2560, 0, 1.5, 0, False,
                                [("eDP-1", "BOE", "Panel", "two")], {}))
        return 7, monitors, logical, {}

    def config(self, state):
        config = rotate.DisplayConfig.__new__(rotate.DisplayConfig)
        config.proxy = Mock()
        config._state = Mock(return_value=state)
        return config

    def test_desktop_and_laptop_open_or_closed_reflow_without_changing_other_modes(self):
        for laptop in (False, True):
            with self.subTest(laptop=laptop):
                state = self.state(laptop)
                config = self.config(state)
                config.set_transform("DP-1", 1)
                self.assertEqual([call.args[1].unpack()[1] for call in config.proxy.call_sync.call_args_list],
                                 [0, 1])
                args = config.proxy.call_sync.call_args.args[1].unpack()
                assert_valid_payload(self, state, args)
                self.assertEqual(args[:2], (7, 1))
                self.assertEqual(args[2][0], (0, 0, 2.0, 1, True, [("DP-1", "studio-mode", {})]))
                if laptop:
                    self.assertEqual(args[2][1], (1440, 0, 1.5, 0, False,
                                                 [("eDP-1", "laptop-mode", {})]))

    def test_mirroring_cannot_rotate_laptop_with_studio(self):
        config = self.config(self.state(True, mirrored=True))
        with self.assertRaisesRegex(RuntimeError, "mirrored"):
            config.set_transform("DP-1", 1)
        config.proxy.call_sync.assert_not_called()

    def test_verification_rejection_does_not_apply(self):
        config = self.config(self.state(True))
        config.proxy.call_sync.side_effect = rotate.GLib.Error("unsupported configuration")
        with self.assertRaises(rotate.GLib.Error):
            config.set_transform("DP-1", 1)
        self.assertEqual(config.proxy.call_sync.call_count, 1)
        self.assertEqual(config.proxy.call_sync.call_args.args[1].unpack()[1], 0)

    def test_stale_serial_rebuilds_geometry_and_retries_once(self):
        old = self.state(True)
        new = list(self.state(False))  # laptop closed during verification
        new[0] = 8
        config = self.config(old)
        config._state.side_effect = [old, new, new]
        config.proxy.call_sync.side_effect = [rotate.GLib.Error("stale serial"), None, None]
        config.set_transform("DP-1", 1)
        payloads = [c.args[1].unpack() for c in config.proxy.call_sync.call_args_list]
        self.assertEqual([p[:2] for p in payloads], [(7, 0), (8, 0), (8, 1)])
        self.assertEqual(len(payloads[-1][2]), 1)

    def test_repeated_stale_serial_does_not_retry_forever(self):
        old = self.state(True)
        new = list(self.state(True))
        new[0] = 8
        config = self.config(old)
        config._state.side_effect = [old, new, new]
        config.proxy.call_sync.side_effect = rotate.GLib.Error("stale serial")
        with self.assertRaises(rotate.GLib.Error):
            config.set_transform("DP-1", 1)
        self.assertEqual(config.proxy.call_sync.call_count, 2)


if __name__ == "__main__":
    unittest.main()
