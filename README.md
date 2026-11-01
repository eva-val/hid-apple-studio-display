# hid-apple-studio-display

Linux kernel driver for the **Apple Studio Display** (2022) and **Studio
Display XDR** (2026):

- **Brightness** as a `/sys/class/backlight` device attached to the DRM
  connector the display is on — the layout GPU drivers use for laptop panels,
  so desktops treat it as an ordinary backlight: GNOME (mutter ≥ 48) shows its
  brightness slider for the monitor, brightness keys work, GNOME's automatic
  brightness follows the display's ambient light sensor, and `brightnessctl`
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
      connector = "DP-1";
      # fadeMs = 150;
      # ambientLight.enable = true; # front sensor and iio-sensor-proxy
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

`connector` defaults to auto-detection (`null`); set it when multiple connectors
are connected, including a laptop's built-in panel. `fadeMs` defaults to `0`.
Sensor integration is opt-in. Set `ambientLight.enable = true` to select the
front light sensor and enable iio-sensor-proxy for automatic brightness.
`autoRotate.enable = true` enables orientation rebinding and starts the
experimental GNOME rotation service with the graphical session. To expose
orientation readings without running that service, set `orientation.enable =
true` alone. The default adds neither sensor rule; the driver itself can still
claim its matching orientation interface during normal device enumeration.

When replacing an inline NixOS derivation, remove its old
`boot.extraModulePackages`, module-loading, modprobe, udev and rescan-service
definitions in favour of the options above. Keep your kernel selection and any
separate desktop patches. For example, the existing kernel 7.2 setup uses
`connector = "DP-1"`; the display's unused `DP-2` tile is not the right parent
for its backlight.

To build the packages without activating them:

```sh
nix build                         # module for the flake's default kernel
nix build .#tools                 # udev rules and self-contained GNOME helpers
nix flake check                   # build packages and check NixOS integration
```

For a non-flake NixOS configuration, import `./nix/module.nix` from a checkout
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

## Automatic brightness

The display has two ambient light sensors (front and rear); the kernel's
`hid-sensor-als` exposes both as IIO devices with illuminance, colour
temperature and chromaticity. iio-sensor-proxy would take the rear one, so the
installed udev rule hides it and GNOME's *Automatic Screen Brightness* follows
the front sensor.

After installing, toggle *Settings → Power → Automatic Screen Brightness* off
and on once (or log out and in): the installer restarts iio-sensor-proxy, and
gnome-settings-daemon does not re-claim the light sensor on its own after
that.

How GNOME applies it: the brightness slider acts as a **bias** on the
automatic target (`clamp(auto + slider − 0.5)`), and the reference light level
is re-normalised whenever you move the slider. So set the slider to where you
like it *now*, and the display tracks the room from there; at 100 % it can
only ever stay at maximum.

## Auto-rotate (experimental)

The orientation interface is claimed by this driver (udev rebinds it from
`hid-sensor-hub`, which cannot parse its 9-bit fields) and shows up as
`/sys/bus/iio/devices/iio:deviceN` named `apple_studio_display_orientation`
with `in_incli_{x,y,z}_raw` in degrees. An upright display reads 0/0/0.

GNOME only auto-rotates a laptop's built-in panel, so `asd-autorotate` polls
the sensor and applies the transform to the display's connector through
mutter's DisplayConfig API (temporary configuration, nothing is written to
`monitors.xml`):

```sh
asd-autorotate --watch                       # print readings while you turn the display
systemctl --user enable --now asd-autorotate # run it for the session
```

**Only the landscape reading has been observed so far.** The helper assumes
the Z angle is the rotation about the screen's normal and snaps it to quarter
turns; if your readings say otherwise, pass `--axis`, `--invert` or `--offset`
(edit `ExecStart` in the unit) and please open an issue with the numbers.
Each read wakes the display's USB device, so the poll interval (default 1 s)
also determines how long it stays out of autosuspend.

## Module parameters

| Parameter | Default | |
|---|---|---|
| `connector` | *(auto)* | DRM connector the display is on, e.g. `DP-1`. Auto-detection picks the single connected connector; with several monitors connected you must set this. |
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
- `hid-sensor-als` reports the light sensors' milli-lux values as lux
  (1000× too high). Harmless for GNOME, which works relatively.
- Finding the connector walks the device tree (PCI display controller →
  `drm/cardN` → connector). Non-PCI GPUs are not handled; set `connector=`.
- With HDR enabled in GNOME, mutter uses its own reference-white control
  instead of the backlight.

## Contributing

The driver is `hid-apple-studio-display.c`; `contrib/` holds the udev rule
and helpers; everything else is packaging. CI
compiles it against each supported LTS kernel plus current stable, runs
checkpatch, and builds the Debian package. Please keep `checkpatch.pl --strict`
clean and bump the version in `dkms.conf`, `MODULE_VERSION`, the PKGBUILD, the
spec and `debian/changelog` together (CI checks they agree).

## License

GPL-2.0-only. See `LICENSE`.
