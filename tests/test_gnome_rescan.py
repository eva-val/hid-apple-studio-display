"""Regression tests for docked startup, lid-open and late backlights."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from display_config_fixtures import state_for

loader = importlib.machinery.SourceFileLoader(
    "rescan", str(Path(__file__).resolve().parents[1] / "contrib/asd-gnome-rescan"))
spec = importlib.util.spec_from_loader(loader.name, loader)
rescan = importlib.util.module_from_spec(spec)
sys.modules["rescan"] = rescan
loader.exec_module(rescan)


def config(serial=1, laptop=False):
    logical = [(0, 0, 2.0, 0, True, [("DP-1", "5120x2880@60", {})])]
    if laptop:
        logical.append((2560, 0, 2.0, 0, False, [("eDP-1", "2880x1920@120", {})]))
    return serial, logical, {"layout-mode": rescan.GLib.Variant("u", 1)}


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.proxy = Mock()
        self.proxy.get_name_owner.return_value = ":1.42"
        self.watcher = rescan.Watcher(self.proxy)
        self.read = self.patch("read_config", return_value=config())
        self.apply = self.patch("apply_config")
        self.timer = self.patch("GLib.timeout_add", return_value=99)
        self.remove = self.patch("GLib.source_remove")
        self.patch("connectors_ready", return_value=True)

    def patch(self, target, **kwargs):
        p = patch("rescan." + target, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def test_initial_scan_and_own_notification_does_not_loop(self):
        self.watcher.rescan()
        self.read.return_value = config(serial=2)
        self.watcher.monitor_changed(None, None, "MonitorsChanged", None)
        self.watcher.rescan()
        self.apply.assert_called_once()
        self.assertEqual(self.watcher.pending, 0)

    def test_lid_open_waits_for_panel_then_rescans_once(self):
        self.watcher.rescan()  # docked startup, external only
        self.read.return_value = config(serial=2, laptop=True)
        self.watcher.monitor_changed(None, None, "MonitorsChanged", None)
        with patch.object(rescan, "connectors_ready", side_effect=[False, True]):
            self.watcher.rescan()
            self.assertEqual(self.apply.call_count, 1)
            self.assertNotEqual(self.watcher.pending, 0)
            self.watcher.rescan()
        self.assertEqual(self.apply.call_count, 2)
        self.read.return_value = config(serial=3, laptop=True)
        self.watcher.rescan()
        self.assertEqual(self.apply.call_count, 2)

    def test_backlight_events_force_scan_without_layout_change(self):
        self.watcher.rescan()
        for action in ("remove", "add"):
            self.watcher.backlight_changed(action)
            self.watcher.rescan()
        self.assertEqual(self.apply.call_count, 3)
        self.timer.reset_mock()
        self.watcher.backlight_changed("change")
        self.timer.assert_not_called()
        self.watcher.rescan()
        self.assertEqual(self.apply.call_count, 3)

    def test_waits_for_mutter_and_rescans_after_owner_restart(self):
        self.proxy.get_name_owner.return_value = None
        self.watcher.rescan()
        self.read.assert_not_called()
        self.proxy.get_name_owner.return_value = ":1.43"
        self.watcher.owner_changed()
        self.watcher.rescan()
        self.watcher.owner_changed()
        self.watcher.rescan()
        self.assertEqual(self.apply.call_count, 2)

    def test_failed_apply_uses_fresh_state_on_retry(self):
        self.apply.side_effect = [rescan.GLib.Error("stale serial"), None]
        self.watcher.rescan()
        self.assertIsNone(self.watcher.handled)
        self.read.return_value = config(serial=2, laptop=True)
        self.watcher.rescan()
        self.assertEqual(self.apply.call_args.args[1][0], 2)
        self.assertIsNotNone(self.watcher.handled)

    def test_retry_budget_and_new_event_recovery(self):
        with patch.object(rescan, "connectors_ready", return_value=False):
            for _ in range(20):
                self.watcher.rescan()
        self.apply.assert_not_called()
        self.assertEqual(self.timer.call_count, 19)
        self.assertEqual(self.watcher.pending, 0)
        self.watcher.monitor_changed(None, None, "MonitorsChanged", None)
        self.assertEqual(self.watcher.attempts, 0)
        self.watcher.rescan()
        self.apply.assert_called_once()

    def test_event_burst_coalesces(self):
        self.watcher.schedule()
        self.watcher.schedule()
        self.remove.assert_called_once_with(99)

    def test_no_active_monitors_is_not_reapplied(self):
        self.read.return_value = (1, [], {})
        self.watcher.rescan()
        self.apply.assert_not_called()
        self.assertEqual(self.watcher.pending, 0)


class ConnectorTests(unittest.TestCase):
    def test_closed_lid_is_ignored_until_panel_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for connector, state in (("DP-1", "enabled"), ("eDP-1", "disabled")):
                d = root / f"card0-{connector}"
                d.mkdir()
                (d / "enabled").write_text(state + "\n")
            self.assertTrue(rescan.connectors_ready(config(), root))
            self.assertFalse(rescan.connectors_ready(config(laptop=True), root))
            (root / "card0-eDP-1/enabled").write_text("enabled\n")
            self.assertTrue(rescan.connectors_ready(config(laptop=True), root))

    def test_virtual_outputs_do_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(rescan.connectors_ready(config(), Path(tmp)))


class RoundTripTests(unittest.TestCase):
    def test_tv_underscanning_round_trip_keeps_settings_and_geometry(self):
        for enabled in (True, False, None):
            with self.subTest(underscanning=enabled):
                props = {"color-mode": 1, "rgb-range": 3}
                if enabled is not None:
                    props["is-underscanning"] = enabled
                state = state_for([("HDMI-1", 0, 0, 3840, 2160, 2., 0, True)],
                                  properties={"HDMI-1": props})
                proxy = Mock()
                proxy.call_sync.return_value.unpack.return_value = state
                current = rescan.read_config(proxy)
                rescan.apply_config(proxy, current)
                payload = proxy.call_sync.call_args.args[1].unpack()
                self.assertEqual(payload[2][0][:5], (0, 0, 2., 0, True))
                expected = {"color-mode": 1, "rgb-range": 3}
                if enabled is not None:
                    expected["underscanning"] = enabled
                self.assertEqual(payload[2][0][5][0][2], expected)
                self.assertEqual(payload[3], {"layout-mode": 1})


if __name__ == "__main__":
    unittest.main()
