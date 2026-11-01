"""Read physical Studio Display topology; no desktop policy or sensor sampling.

The physical USB device is the identity. Sensor ancestry and backlight
physical_device links associate standard class devices with that identity.
Only metadata is read: enumerating displays does not sample or wake sensors.
"""
from pathlib import Path
import re

ORIENTATION_NAME = "apple_studio_display_orientation"


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def usb_identity(device):
    device = device.resolve(strict=True)
    for parent in (device, *device.parents):
        if read(parent / "idVendor") == "05ac" and read(parent / "idProduct") in {"1114", "1116"}:
            return parent, read(parent / "serial")
    return None


def iio_devices(sysfs=Path("/sys")):
    devices = []
    for path in sorted((sysfs / "bus/iio/devices").glob("iio:device*")):
        name = read(path / "name")
        kind = {"als": "ambient-light", ORIENTATION_NAME: "orientation"}.get(name)
        if kind is None:
            continue
        try:
            identity = usb_identity(path)
            if identity:
                usb, serial = identity
                devices.append({"device": path.name, "path": str(path.resolve(strict=True)),
                                "usb_path": str(usb), "serial": serial, "kind": kind})
        except OSError:
            continue
    return devices


def backlight_devices(sysfs=Path("/sys")):
    devices = []
    for path in sorted((sysfs / "class/backlight").glob("apple_studio_display*")):
        try:
            identity = usb_identity(path / "physical_device")
            if not identity:
                continue  # Older drivers cannot provide a trustworthy association.
            usb, serial = identity
            target = path.resolve(strict=True)
            parent = target.parent
            connector = None
            if re.fullmatch(r"card[0-9]+-.+", parent.name):
                if (sysfs / "class/drm" / parent.name).resolve(strict=True) == parent:
                    connector = parent.name
            devices.append({"device": path.name, "path": str(target),
                            "usb_path": str(usb), "serial": serial, "connector": connector})
        except OSError:
            continue
    return devices


def physical_displays(sysfs=Path("/sys")):
    displays = {}
    for path in sorted((sysfs / "bus/usb/devices").glob("*")):
        if read(path / "idVendor") != "05ac" or read(path / "idProduct") not in {"1114", "1116"}:
            continue
        try:
            usb = str(path.resolve(strict=True))
        except OSError:
            continue
        displays[usb] = {"device": path.name, "path": usb,
                         "serial": read(path / "serial"), "product": read(path / "product"),
                         "ambient_light": [], "orientation": [], "backlights": []}
    for sensor in iio_devices(sysfs):
        if sensor["usb_path"] in displays:
            key = "ambient_light" if sensor["kind"] == "ambient-light" else "orientation"
            displays[sensor["usb_path"]][key].append(sensor)
    for backlight in backlight_devices(sysfs):
        if backlight["usb_path"] in displays:
            displays[backlight["usb_path"]]["backlights"].append(backlight)
    return list(displays.values())
