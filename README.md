# hid-apple-studio-display

Linux kernel driver for the **Apple Studio Display** (2022) and **Studio
Display XDR** (2026):

- **Brightness** as a `/sys/class/backlight` device attached to the DRM
  connector the display is on — the layout GPU drivers use for laptop panels,
  so desktops treat it as an ordinary backlight: GNOME (mutter ≥ 48) shows its
  brightness slider for the monitor, brightness keys work, and `brightnessctl`
  or `light` can drive it.
- **Orientation sensor** as an IIO inclinometer, with an experimental
  `asd-autorotate` helper that rotates the GNOME output to match.

```
$ ls /sys/class/backlight/
apple_studio_display0 -> ../../devices/pci0000:00/.../drm/card1/card1-DP-1/apple_studio_display0
$ brightnessctl -d apple_studio_display0 set 50%
```

Tested on a Studio Display XDR with Linux 7.2 and GNOME 50 (NVIDIA, DisplayPort
for video + the display's USB link to the host). Compiles against every LTS
kernel from 5.10 up (checked in CI).

## Requirements

- The display's **USB/Thunderbolt link connected to the host** — brightness is
  a USB HID control, not DDC/CI. Over Thunderbolt/USB‑C this is automatic; on a
  DisplayPort GPU you need an adapter that also passes USB data (the display's
  speakers, camera and hub come with it).
- Linux ≥ 5.10 and its headers.
- For the GNOME slider: mutter ≥ 48. Anything else that talks to
  `/sys/class/backlight` works regardless of desktop.

## Install

### Nix / NixOS

This fork provides a flake with a kernel module package, desktop helpers and a
NixOS module. Add it to your system flake's `inputs`:

```nix
apple-studio-display = {
  url = "github:eva-val/hid-apple-studio-display";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Add `apple-studio-display` to your `outputs` arguments, then include the module
in your existing `nixpkgs.lib.nixosSystem` definition:

```nix
modules = [
  apple-studio-display.nixosModules.default
  ./configuration.nix
  {
    hardware.apple-studio-display = {
      enable = true;
      # connector = "DP-1"; # optional override; auto-detected by default
      # fadeMs = 150;
      # ambientLight.enable = true; # annotate light-sensor roles only
      # autoRotate.enable = true; # experimental; GNOME only
      # autoRotate.extraArgs = [ "--axis" "z" "--invert" ];
    };
  }
];
```

For a local checkout, use `url = "path:/absolute/path/to/hid-apple-studio-display"`.
The module builds against **your `boot.kernelPackages`**, installs and loads
the driver, installs the helpers, and provides the GNOME backlight watcher
with its Python dependencies. One service starts with the graphical session,
rescans initially, and watches display configuration and backlight add/remove
events. This covers displays connected before login and opening the laptop lid
while docked; no udev rule is needed to start the service.
NixOS rebuilds the driver when the kernel changes; DKMS and `install.sh` are
unnecessary. Rebuild your system and reboot to activate the new kernel/module
combination.

`connector` defaults to auto-detection (`null`), which identifies a single Studio
Display from its EDID and skips secondary tiles and other monitors, including a
laptop's built-in panel. For two Studio Displays, configure `displayMap` as
described below. `fadeMs` defaults to `0`.
Sensor annotations are opt-in. Set `ambientLight.enable = true` to tag light
sensors with their role; this does not enable or configure iio-sensor-proxy.
`autoRotate.enable = true` enables orientation rebinding and starts the
experimental GNOME rotation service with the graphical session. To expose
orientation readings without running that service, set `orientation.enable =
true` alone. The default adds neither sensor rule; the driver itself can still
claim its matching orientation interface during normal device enumeration.

When replacing an inline NixOS derivation, remove its old
`boot.extraModulePackages`, module-loading, modprobe, udev and rescan-service
definitions in favour of the options above. Keep your kernel selection. For example, the existing kernel 7.2 setup uses
`connector = "DP-1"`; the display's unused `DP-2` tile is not the right parent
for its backlight.

To build the packages without activating them:

```sh
nix build                         # module for the flake's default kernel
nix build .#tools                 # udev rules and self-contained GNOME helpers
nix flake check                   # build packages and check NixOS integration
```

For a non-flake NixOS configuration, import `./packaging/nix/module.nix` from a checkout
and set the same `hardware.apple-studio-display` options. The driver can also
be built with `nix-build`, or with a chosen kernel package set:

```sh
nix-build --arg kernelPackages '(import <nixpkgs> {}).linuxPackages_latest'
```

The standalone build must match the target kernel exactly. Installing it with
`nix profile install` does not register a kernel module; on NixOS use the
module above or `boot.extraModulePackages`. Outputs are provided for
`x86_64-linux` and `aarch64-linux`.

### Any distribution

```sh
git clone https://github.com/michaljach/hid-apple-studio-display
cd hid-apple-studio-display
sudo ./install.sh
```

`install.sh` installs the kernel headers and DKMS with your package manager
(apt, dnf/yum, zypper, pacman, xbps, apk), registers the module with DKMS so it
is rebuilt on every kernel update, and loads it. Where DKMS does not exist
(Alpine, Gentoo, …) it builds and installs the module for the running kernel
instead. `sudo ./uninstall.sh` reverses all of it.

Without the script: `make dkms-install` (DKMS) or `make && sudo make install`
(this kernel only).

### Distribution packages

| Distribution | |
|---|---|
| Arch / Manjaro / EndeavourOS | `sudo pacman -U https://github.com/michaljach/hid-apple-studio-display/releases/download/v1.2.0/hid-apple-studio-display-dkms-1.2.0-1-any.pkg.tar.zst` (built from `packaging/arch/PKGBUILD`; AUR submission pending) |
| Debian / Ubuntu / Mint / Pop!_OS | `cp -r packaging/debian debian && dpkg-buildpackage -us -uc -b`, then `apt install ../hid-apple-studio-display-dkms_*.deb` |
| Fedora / RHEL / Rocky / Alma / openSUSE | `rpmbuild -ba packaging/rpm/hid-apple-studio-display-dkms.spec` (needs `dkms`, from EPEL on RHEL‑likes) |

All three ship the same thing: the source in `/usr/src/` plus a DKMS
registration, so the module follows kernel updates.

### Secure Boot

Out-of-tree modules must be signed when Secure Boot is on. DKMS signs its
builds with a machine-owner key; enroll it once and reboot:

```sh
sudo mokutil --import /var/lib/dkms/mok.pub     # Ubuntu: /var/lib/shim-signed/mok/MOK.der
```

## Verify

```sh
dmesg | grep apple-studio
#   apple-studio-display ...: backlight apple_studio_display0 registered on card1-DP-1 (400..60000, now 30000)
cat /sys/class/backlight/apple_studio_display0/actual_brightness
```

GNOME only looks for backlights when it applies a monitor configuration, not
when a backlight appears. It can also select the wrong backlight when a laptop
panel is not yet enabled, for example when opening the lid after docked startup.
The `asd-gnome-rescan` session service watches monitor changes and backlight
add/remove events, waits for active connectors to become enabled, and re-applies
the current configuration unchanged. It ignores its own configuration
notification and brightness-only events, so it does not continuously rescan.

NixOS enables this service automatically; `install.sh` enables it for all users.
For other package installations, install Python GObject and pyudev, then enable
it for your user:

```sh
systemctl --user enable --now asd-gnome-rescan.service
```

Running `asd-gnome-rescan` without arguments still performs a single manual
rescan; `--watch` runs the session watcher. A successful manual rescan does not
verify the lid-open event path; test closed-lid login followed by opening the
lid and adjusting both screens independently.

If `install.sh` reports that the display's USB hub is there but the display
itself is not, its USB controller has stopped responding (the kernel log shows
`error -71` for it): unplug the USB‑C/Thunderbolt cable for a few seconds, or
power-cycle the display.

## Detecting and pairing multiple displays

Run `asd-detect` (or `python3 contrib/asd-detect` from a checkout) to list USB
serials and connected Studio Display video outputs. It only reads sysfs and
does not need root. `--json` produces machine-readable output.

A Studio Display can expose two DP connectors with the same EDID serial. Those
are tiles of one physical screen; the driver attaches its backlight to tile
0,0. It ignores laptop panels and other monitor models during auto-detection.

Two physical Studio Displays have independent USB brightness interfaces, but
the USB serial is not the numeric serial in their EDIDs. This driver currently
needs a one-time pairing to associate them reliably. Connect **one physical
Studio Display at a time**, with both USB and video attached, and record the
`display_map=USB_SERIAL:EDID_SERIAL` pair printed by `asd-detect`. Repeat for the
other display. With both reconnected, configure the two pairs:

```nix
hardware.apple-studio-display = {
  enable = true;
  displayMap = {
    "FIRST-USB-SERIAL" = "12345678";
    "SECOND-USB-SERIAL" = "87654321";
  };
};
```

Or, for other distributions, use a modprobe configuration:

```conf
options hid-apple-studio-display display_map=FIRST-USB-SERIAL:12345678,SECOND-USB-SERIAL:87654321
```

Replace the example identities with the tool's output. EDID serials are eight
hexadecimal digits. Rebuild/reboot on NixOS, or reload the module after changing
modprobe settings. Mappings take precedence over `connector=`; include every
Studio Display when using them. They survive changes to GPU card and connector
numbers. A missing, zero or duplicate EDID serial cannot provide a unique match.
Ambiguous matches remain unattached to DRM rather than controlling the wrong
monitor. After the registration timeout they still get individual backlight
devices for command-line control, but GNOME cannot associate those devices.

Use `/sys/class/backlight/apple_studio_display*/` to verify that each backlight
has a different DRM connector as its parent, then test each GNOME brightness
slider independently. The numeric suffix is an allocation ID, not a persistent
display identity. Video-only reconnection while USB stays attached still needs
a module reload to redo the mapping.

## Ambient-light sensor exposure

This project exposes hardware controls and identifies which sensors belong to
which physical display. It does not adjust brightness from sensor readings or
choose an ambient-light source. Automatic brightness, lid policy and sensor
fallback belong to the desktop or another project consuming these interfaces.

Ambient-light readings come from the standard Linux `hid-sensor-hub` and
`hid-sensor-als` drivers. `asd-detect --json` groups their IIO paths under each
physical USB display alongside its backlight and orientation sensor. The
laptop's own light sensor remains independent. Every display's sensors stay
available, including rear sensors; their numeric IIO IDs are not persistent.

Optional `ambientLight.enable = true` on NixOS installs only udev role metadata:
`ASD_ALS_ROLE=single`, `front`, or `rear`. The tested 2022 display has one sensor;
models with two ALS collections on one HID interface are annotated by their
collection order. This annotation neither hides a sensor nor changes its
readings. It does not install a sensor proxy or modify GNOME packages. The
standalone udev rules provide the same annotations.

There is still a kernel units issue on the tested display: its illuminance
field declares unit `0x010000e1` with exponent `-3`, but the generic HID sensor
unit table does not recognize that unit and exposes scale `1`. The field's
millilux counts require scale `0.001` to report lux (`24000` corresponds to
`24 lux`, before any sensor calibration). Correcting that standard IIO scale
belongs in the kernel's HID sensor unit handling. This project currently does
not fix that kernel bug and does not replace it with a userspace scale override.
Consumers should not assume the affected kernel's raw count is already lux.

The former `ambientLight.preferredSerial` option and patched sensor-proxy
package have been removed. Configure source selection and automatic brightness
in the project that owns that policy instead.

## Auto-rotate (experimental)

The orientation interface is claimed by this driver (udev rebinds it from
`hid-sensor-hub`, which cannot parse its 9-bit fields) and shows up as
`/sys/bus/iio/devices/iio:deviceN` named `apple_studio_display_orientation`
with `in_incli_{x,y,z}_raw` in degrees. An upright display reads 0/0/0.

GNOME only auto-rotates a laptop's built-in panel, so `asd-autorotate` polls
each display's sensor and applies the transform to its connector through
mutter's DisplayConfig API (temporary configuration, nothing is written to
`monitors.xml`):

```sh
asd-autorotate --watch                       # print readings while you turn the display
asd-autorotate --serial USB_SERIAL --watch   # inspect one physical display
systemctl --user enable --now asd-autorotate # run it for the session
```

The helper pairs each orientation sensor with a backlight belonging to the
same physical USB device. The driver exposes that association as the
backlight's `physical_device` symlink, while its parent identifies the DRM connector.
Install the updated driver together with the helper; older drivers without
this link can still be inspected with `--watch`, but will not be auto-rotated.
For multiple displays, configure `displayMap` so each backlight has the correct
DRM parent. By default all unambiguously matched displays rotate independently;
`--serial` and `--connector` restrict that selection. `--connector` filters an
existing match and cannot assign an unrelated sensor to an output.

Discovery repeats on each poll, including when no display is connected at
startup. Unplugging, replugging and IIO device renumbering discard stale state;
each new pairing requires two consecutive matching readings. Disabled outputs
stay disabled, and the laptop panel is left alone whether its lid is open or
closed. Mirrored outputs, multiple sensors on one display, and connector names
that are ambiguous across GPUs are skipped rather than rotated together.

Rotation recalculates monitor positions to retain existing edge contacts and
top/left, bottom/right, or center alignment. This accounts for each monitor's
mode, scale, and the compositor's logical or physical layout mode. Neighbors
move when the rotated display changes size; their modes, scales, transforms,
and primary status stay intact. Conflicting grids or layouts that would overlap
are rejected with a diagnostic. Mutter verifies the proposed configuration
before it is applied temporarily; a stale configuration is read and rebuilt
once if a hotplug races the operation.

Both rotation and the brightness rescan preserve supported current color mode,
RGB range, underscanning, layout mode, and monitor leases. Rescanning keeps the
existing positions and transforms as well.

Physical identity is independent of GNOME. The backlight and orientation IIO
device expose `physical_device` links to the same USB device; the standard HID
ambient-light IIO devices already descend from that device. `asd-detect` shows
brightness, ambient light (including both sensors on dual-sensor models), and
orientation grouped under each physical display. `asd-detect --json` adds a
`displays` list with their sysfs paths; the existing `usb` and `video` lists
remain available for mapping diagnostics. Enumeration reads metadata only.
The kernel contract is documented in
[the sysfs ABI](Documentation/ABI/testing/sysfs-apple-studio-display).

**Only the landscape reading has been observed so far.** The helper assumes
the Z angle is the rotation about the screen's normal and snaps it to quarter
turns; if your readings say otherwise, pass `--axis`, `--invert` or `--offset`
(edit `ExecStart` in the unit) and please open an issue with the numbers.
Each read wakes the display's USB device, so the poll interval (default 1 s)
also determines how long it stays out of autosuspend.

## Module parameters

| Parameter | Default | |
|---|---|---|
| `connector` | *(auto)* | Override such as `DP-1` or `card0-DP-1`. Auto-detection selects the single Studio Display's first tile. Bare connector names must be unique across GPUs. |
| `display_map` | *(empty)* | Comma-separated `USB_SERIAL:EDID_SERIAL` pairs for multiple displays. Overrides `connector`; matches by identity instead of connector numbering. |
| `fade_ms` | `0` | Transition time the display applies to brightness changes, in ms. |

Set them in `/etc/modprobe.d/hid-apple-studio-display.conf`:

```
options hid-apple-studio-display connector=DP-1 fade_ms=150
```

## How it works

The display's USB device carries several HID interfaces. One is a *Monitor
Control* collection (usage page 0x80) whose feature report 1 holds the
brightness as a 32-bit value in 0.01-nit units — logical range 400–60000, i.e.
4–600 nits — followed by a 16-bit transition time in milliseconds. The driver
binds that interface, reads the field layout from the report descriptor rather
than hard-coding it, and registers a `raw` backlight device with the display's
DRM connector as parent, which is what mutter requires before it will attach a
backlight to an external monitor.

Another interface is a HID sensor hub with a single *Device Orientation*
collection: input report 1 with three 9-bit angles and no feature report. The
driver claims it and answers IIO reads with `GET_REPORT`. The ambient light
sensors are on a third sensor-hub interface, which stays with the in-tree
`hid-sensor-hub`/`hid-sensor-als` drivers; the vendor interface is passed
through to the generic HID paths untouched.

`brightness` is in the display's native units. Values below the hardware
minimum (400) are raised to it: the panel can be dimmed but not switched off
through this control. Requests wake the (autosuspended) display first.

## Known limitations

- **No change notifications.** The descriptor advertises an input report for
  brightness changes, but the interrupt endpoint behind it fails on the XDR;
  keeping it open makes usbhid reset the display every few seconds. Changes made
  by other means are only seen when the value is read.
- Brightness is linear in nits, so half of the slider is 300 nits. A
  perceptual curve would feel closer to macOS.
- The 2022 Studio Display (USB ID `05ac:1114`) uses the same report layout but
  has not been tested with this driver.
- The orientation sensor's readings for a rotated display are unconfirmed
  (see *Auto-rotate*). It is also unknown whether the display pushes a report
  when turned; the helper polls instead.
- The generic kernel HID ALS driver still exposes Apple's incorrect scale.
  See the ambient-light section; no userspace override is supplied here.
- Finding the connector walks the device tree (PCI display controller →
  `drm/cardN` → connector). Non-PCI GPUs are not handled, even with an override.
- Multiple Studio Displays require the one-time USB/EDID pairing above. Fully
  automatic pairing of two identical displays is not implemented.
- With HDR enabled in GNOME, mutter uses its own reference-white control
  instead of the backlight.

## Contributing

The driver is `hid-apple-studio-display.c`; `contrib/` holds the udev rule
and helpers; everything else is packaging. CI
compiles it against each supported LTS kernel plus current stable, runs
checkpatch, and builds the Debian package. Please keep `checkpatch.pl --strict`
clean and bump the version in `dkms.conf`, `MODULE_VERSION`, the PKGBUILD, the
spec and `debian/changelog` together (CI checks they agree).

`nix flake check` runs helper regression tests, including layout geometry and
monitor-property round trips. To verify against Mutter itself, use Python with
PyGObject and `dbus-run-session` available, then run:

```sh
python3 tests/mutter_integration.py --mutter /path/to/mutter
```

This starts a private headless compositor with two virtual outputs, temporary
settings and a separate D-Bus session. It checks that Mutter rejects the
original disconnected layout and accepts rotation, reversal and rescan in
horizontal, vertical and (where supported) physical layouts.

Contributors:

- Michal Jach — original driver and desktop integration.
- Stephanie Howanietz — multi-display detection, physical device associations,
  sensor integration, and NixOS packaging.

## License

GPL-2.0-only. See `LICENSE`.
