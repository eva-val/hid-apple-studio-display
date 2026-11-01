"""Protect real monitor geometry and settings when transforming Mutter state."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contrib"))
import asd_display_config as config
from display_config_fixtures import assert_valid_payload, state_for


class GeometryTests(unittest.TestCase):
    def rotate(self, state, connector="DP-1", transform=1):
        snapshot = copy.deepcopy(state)
        result = config.rotation_config(state, connector, transform)
        proxy = Mock()
        config.apply_config(proxy, result)
        payload = proxy.call_sync.call_args.args[1].unpack()
        assert_valid_payload(self, state, payload)
        self.assertEqual(state, snapshot, "input state was mutated")
        return payload

    def test_right_neighbor_moves_from_2560_to_1440(self):
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                           ("HDMI-1", 2560, 0, 3840, 2160, 2., 0, False)])
        self.assertEqual(self.rotate(state)[2][1][:2], (1440, 0))
        state[2][0] = (0, 0, 2., 1, True, state[2][0][5], {})
        state[2][1] = (1440, 0, 2., 0, False, state[2][1][5], {})
        self.assertEqual(self.rotate(state, transform=0)[2][1][:2], (2560, 0))

    def test_neighbors_on_each_side_and_primary_on_either_display(self):
        for primary in (True, False):
            for x, y in ((2560, 0), (0, 1440), (-1920, 0), (0, -1080)):
                left, top = min(x, 0), min(y, 0)
                state = state_for([("DP-1", -left, -top, 5120, 2880, 2., 0, primary),
                                   ("HDMI-1", x-left, y-top, 3840, 2160, 2., 0, not primary)])
                with self.subTest(primary=primary, position=(x, y)):
                    self.rotate(state)

    def test_three_monitor_chain_and_l_shape(self):
        for x, y in ((4480, 0), (2560, 1080)):
            with self.subTest(last=(x, y)):
                state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                                   ("HDMI-1", 2560, 0, 3840, 2160, 2., 0, False),
                                   ("eDP-1", x, y, 2880, 1920, 1.5, 0, False)])
                rows = self.rotate(state)[2]
                self.assertEqual(rows[2][0], x - 1120)
                self.assertEqual(rows[2][1], y)

    def test_bottom_center_and_staggered_alignment(self):
        for y, expected in ((360, 1480), (180, 740), (100, 100)):
            with self.subTest(y=y):
                state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                                   ("HDMI-1", 2560, y, 3840, 2160, 2., 0, False)])
                self.assertEqual(self.rotate(state)[2][1][:2], (1440, expected))

    def test_physical_layout_ignores_scale_for_positions(self):
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                           ("HDMI-1", 5120, 0, 3840, 2160, 2., 0, False)], layout_mode=2)
        payload = self.rotate(state)
        self.assertEqual(payload[2][1][0], 2880)
        self.assertEqual(payload[3]["layout-mode"], 2)

    def test_single_display_and_half_turn_do_not_rearrange(self):
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True)])
        for transform in range(8):
            self.assertEqual(self.rotate(state, transform=transform)[2][0][:2], (0, 0))
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                           ("HDMI-1", 2560, 0, 3840, 2160, 2., 0, False)])
        self.assertEqual(self.rotate(state, transform=2)[2][1][:2], (2560, 0))

    def test_conflicting_grid_is_rejected_before_apply(self):
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                           ("DP-2", 2560, 0, 5120, 2880, 2., 0, False),
                           ("DP-3", 0, 1440, 5120, 2880, 2., 0, False),
                           ("DP-4", 2560, 1440, 5120, 2880, 2., 0, False)])
        with self.assertRaisesRegex(RuntimeError, "conflicts|overlaps"):
            config.rotation_config(state, "DP-1", 1)

    def test_existing_gap_overlap_and_corner_only_contact_are_rejected(self):
        for x, y in ((3000, 0), (2000, 0), (2560, 1440)):
            state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                               ("HDMI-1", x, y, 3840, 2160, 2., 0, False)])
            with self.subTest(position=(x, y)), self.assertRaises(RuntimeError):
                config.rotation_config(state, "DP-1", 1)

    def test_rounding_matches_mutter_not_python_bankers_rounding(self):
        mode = ("mode", 2001, 1001)
        self.assertEqual(config.monitor_size(mode, 2., 0, 1), (1001, 501))
        self.assertEqual(config.monitor_size(mode, 2., 1, 1), (501, 1001))


class PropertyTests(unittest.TestCase):
    def state(self, underscanning=True):
        props = {"color-mode": 1, "rgb-range": 3, "is-underscanning": underscanning,
                 "is-builtin": False, "supported-color-modes": [0, 1], "display-name": "TV"}
        return state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True),
                          ("HDMI-1", 2560, 0, 3840, 2160, 2., 0, False)],
                         properties={"DP-1": props, "HDMI-1": props})

    def test_rotation_and_rescan_preserve_all_active_monitor_properties(self):
        for under in (True, False):
            state = self.state(under)
            for result in (config.serialize_state(state), config.rotation_config(state, "DP-1", 1)):
                for row in result[1]:
                    props = row[5][0][2]
                    self.assertEqual({k: v.unpack() for k, v in props.items()},
                                     {"color-mode": 1, "rgb-range": 3, "underscanning": under})
                    self.assertEqual({k: v.get_type_string() for k, v in props.items()},
                                     {"color-mode": "u", "rgb-range": "u", "underscanning": "b"})
                self.assertEqual(result[2]["layout-mode"].unpack(), 1)

    def test_unsupported_properties_are_not_invented(self):
        state = state_for([("DP-1", 0, 0, 5120, 2880, 2., 0, True)])
        state[3].clear()
        result = config.serialize_state(state)
        self.assertEqual(result[1][0][5][0][2], {})
        self.assertEqual(result[2], {})

    def test_nonchangeable_layout_mode_is_not_sent(self):
        state = self.state()
        state[3]["supports-changing-layout-mode"] = False
        self.assertNotIn("layout-mode", config.serialize_state(state)[2])

    def test_leased_and_disabled_monitors_remain_outside_active_layout(self):
        state = self.state()
        leased = ("DP-3", "vendor", "headset", "lease-serial")
        state[1].append((leased, [], {"is-for-lease": True}))
        state[1].append((("eDP-1", "vendor", "panel", "laptop"), [], {}))
        result = config.rotation_config(state, "DP-1", 1)
        self.assertEqual(result[2]["monitors-for-lease"].unpack(), [leased])
        self.assertEqual([m[0] for r in result[1] for m in r[5]], ["DP-1", "HDMI-1"])

    def test_missing_active_mode_is_rejected(self):
        state = self.state()
        state[1][0][1][0][-1]["is-current"] = False
        with self.assertRaisesRegex(RuntimeError, "current mode"):
            config.serialize_state(state)


if __name__ == "__main__":
    unittest.main()
