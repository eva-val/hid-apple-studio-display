#!/usr/bin/env python3
"""Exercise rotation against a private headless Mutter with two virtual outputs.

Run with the tools package's Python environment and --mutter /path/to/mutter.
The outer process always creates a private bus, runtime directory and settings
environment; it never connects to the user's compositor or changes its outputs.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contrib"))
from asd_display_config import apply_config, read_state, rotation_config, serialize_state
from gi.repository import Gio, GLib


def scenarios(proxy):
    initial = read_state(proxy)
    modes = {spec[0]: next(m for m in modes if m[-1].get("is-current"))
             for spec, modes, _ in initial[1]}
    first = next(conn for conn, mode in modes.items() if mode[1:3] == (5120, 2880))
    second = next(conn for conn, mode in modes.items() if mode[1:3] == (3840, 2160))
    for mode in modes.values():
        assert 2.0 in mode[5], "virtual mode must support 200% scale"

    def baseline(vertical=False, physical=False):
        current = read_state(proxy)
        serial, _, props = serialize_state(current)
        if current[3].get("supports-changing-layout-mode"):
            props["layout-mode"] = GLib.Variant("u", 2 if physical else 1)
        else:
            assert current[3].get("layout-mode", 1) == 1 and not physical
        width, height = (5120, 2880) if physical else (2560, 1440)
        rows = [(0, 0, 2., 0, True, [(first, modes[first][0], {})]),
                (0 if vertical else width, height if vertical else 0,
                 2., 0, False, [(second, modes[second][0], {})])]
        apply_config(proxy, (serial, rows, props), method=0)
        apply_config(proxy, (serial, rows, props))
        return read_state(proxy)

    state = baseline()
    serial, invalid, props = serialize_state(state)
    target = next(i for i, row in enumerate(invalid) if row[5][0][0] == first)
    row = list(invalid[target])
    row[3] = 1
    invalid[target] = tuple(row)
    try:
        apply_config(proxy, (serial, invalid, props), method=0)
    except GLib.Error as error:
        assert "not adjacent" in str(error), str(error)
        print("Mutter rejected the original 1120-pixel gap", flush=True)
    else:
        raise AssertionError("Mutter accepted the original disconnected layout")

    cases = [(False, False), (True, False)]
    if state[3].get("supports-changing-layout-mode"):
        cases.append((False, True))
    for vertical, physical in cases:
        state = baseline(vertical, physical)
        for transform in (1, 0, 3, 0):
            proposal = rotation_config(state, first, transform)
            apply_config(proxy, proposal, method=0)
            apply_config(proxy, proposal)
            state = read_state(proxy)
            row = next(row for row in state[2] if row[5][0][0] == second)
            width, height = (5120, 2880) if physical else (2560, 1440)
            if transform % 2:
                width, height = height, width
            assert row[:2] == ((0, height) if vertical else (width, 0)), row
        before = serialize_state(state)
        apply_config(proxy, before)
        after = serialize_state(read_state(proxy))
        # Compare variants to include the preserved property's type and value.
        variant = lambda c: GLib.Variant("(a(iiduba(ssa{sv}))a{sv})", c[1:]).print_(False)
        assert variant(before) == variant(after), "rescan changed configuration"
        print(f"Mutter accepted rotation/reversal/rescan: vertical={vertical}, physical={physical}", flush=True)


def inside(mutter):
    log = Path(os.environ["XDG_RUNTIME_DIR"]).parent / "mutter.log"
    with log.open("w") as output:
        process = subprocess.Popen([mutter, "--headless", "--wayland", "--no-x11",
                                    "--virtual-monitor", "5120x2880",
                                    "--virtual-monitor", "3840x2160"], stdout=output, stderr=output)
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                "org.gnome.Mutter.DisplayConfig", None)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                context = GLib.MainContext.default()
                while context.pending():
                    context.iteration(False)
                if process.poll() is not None:
                    raise RuntimeError("headless Mutter exited during startup")
                try:
                    if len(read_state(proxy)[2]) == 2:
                        break
                except GLib.Error:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("headless Mutter did not expose two monitors")
            scenarios(proxy)
        except BaseException:
            print(log.read_text(), file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutter", required=True)
    parser.add_argument("--private-bus", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.private_bus:
        inside(args.mutter)
        return
    with tempfile.TemporaryDirectory(prefix="asd-mutter-test-") as temp:
        runtime = Path(temp) / "runtime"
        runtime.mkdir(mode=0o700)
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=temp,
                   GSETTINGS_BACKEND="memory", GIO_USE_VFS="local", LIBGL_ALWAYS_SOFTWARE="1")
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(key, None)
        subprocess.run(["dbus-run-session", "--", sys.executable, __file__,
                        "--private-bus", "--mutter", args.mutter], env=env, check=True)


if __name__ == "__main__":
    main()
