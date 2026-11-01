"""Compile the driver's real lookup code against a small DRM/device shim."""
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIM = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define ASD_MAX_DISPLAYS 16
struct mutex { int unused; };
static void mutex_lock(struct mutex *m) { (void)m; }
static void mutex_unlock(struct mutex *m) { (void)m; }
struct drm_device { struct { struct mutex mutex; } mode_config; };
struct drm_property_blob { void *data; size_t length; };
struct drm_connector {
    const char *name;
    struct drm_device *dev;
    struct drm_property_blob *edid_blob_ptr;
    int status, has_tile, tile_h_loc, tile_v_loc;
};
struct device_type { const char *name; };
struct device { struct device_type *type; const char *name; void *data; };
struct hid_device { char uniq[128]; };
static const int connector_status_connected = 1;
static void *dev_get_drvdata(struct device *d) { return d->data; }
static const char *dev_name(struct device *d) { return d->name; }
static struct device *get_device(struct device *d) { return d; }
static char *display_map[16];
static unsigned int display_map_count;
static char *connector;
static int kstrtou32(const char *s, unsigned int base, u32 *result) {
    char *end;
    unsigned long value;
    errno = 0;
    value = strtoul(s, &end, base);
    if (errno || end == s || *end || value > UINT32_MAX) return -EINVAL;
    *result = value;
    return 0;
}
'''
WRAPPER = r'''
int matches(const unsigned char *edid, size_t len, unsigned int serial,
            int connected, int tile_x, int tile_y, const char *override,
            const char *full_name) {
    struct asd_connector_search search = {
        .name = override, .match_serial = serial != 0, .serial = serial,
    };
    struct drm_device gpu = {0};
    struct drm_property_blob blob = { (void *)edid, len };
    struct drm_connector conn = {
        .name = "DP-1", .dev = &gpu, .edid_blob_ptr = edid ? &blob : NULL,
        .status = connected, .has_tile = 1,
        .tile_h_loc = tile_x, .tile_v_loc = tile_y,
    };
    struct device_type type = { "drm_connector" };
    struct device dev = { &type, full_name, &conn };
    asd_match_connector(&dev, &search);
    return search.n_connected;
}
int identity(const char *usb, const char *first, const char *second,
             const char *override, unsigned int *serial) {
    struct asd_connector_search search = {0};
    struct hid_device hid = {0};
    int result;
    strcpy(hid.uniq, usb);
    display_map_count = (first != NULL) + (second != NULL);
    display_map[0] = (char *)first;
    display_map[1] = (char *)second;
    connector = (char *)override;
    result = asd_lookup_identity(&hid, &search);
    *serial = search.serial;
    if (result) return result;
    return search.match_serial ? 1 : (search.name ? 2 : 0);
}
'''


def edid(serial=0x8D617832, name=b"StudioDisplay", vendor=b"\x06\x10"):
    data = bytearray(128)
    data[8:10] = vendor
    data[12:16] = serial.to_bytes(4, "little")
    data[108:113] = b"\0\0\0\xfc\0"
    data[113:126] = name.ljust(13, b" ")[:13]
    return bytes(data)


class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source = (ROOT / "hid-apple-studio-display.c").read_text()
        lookup = source[source.index("struct asd_connector_search {"):
                        source.index("static int asd_match_card")]
        path = Path(cls.tmp.name)
        (path / "lookup.c").write_text(SHIM + lookup + WRAPPER)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-shared", "-fPIC",
                        "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare",
                        str(path / "lookup.c"), "-o", str(path / "lookup.so")], check=True)
        cls.lib = ctypes.CDLL(str(path / "lookup.so"))
        cls.lib.matches.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_char_p, ctypes.c_char_p]
        cls.lib.identity.argtypes = [ctypes.c_char_p] * 4 + [ctypes.POINTER(ctypes.c_uint)]

    def match(self, data=None, serial=0, connected=1, x=0, y=0,
              override=None, full_name=b"card0-DP-1"):
        if data is None:
            data = edid()
        return self.lib.matches(data, len(data), serial, connected, x, y, override, full_name)

    def test_laptop_and_other_apple_models_are_excluded(self):
        self.assertEqual(self.match(), 1)
        self.assertEqual(self.match(edid(vendor=b"\x0e\x77")), 0)
        self.assertEqual(self.match(edid(name=b"Pro Display")), 0)
        self.assertEqual(self.match(edid(name=b"Studio Displa")), 1)

    def test_secondary_tiles_are_excluded_even_with_matching_serial(self):
        for serial in (0, 0x8D617832):
            self.assertEqual(self.match(serial=serial, x=1), 0)
            self.assertEqual(self.match(serial=serial, y=1), 0)
            self.assertEqual(self.match(serial=serial), 1)

    def test_two_displays_are_selected_by_identity_not_order(self):
        first, second = edid(0x12345678), edid(0x87654321)
        for displays in ((first, second), (second, first)):
            results = [self.match(data, serial=0x87654321) for data in displays]
            self.assertEqual(sum(results), 1)
            self.assertEqual(displays[results.index(1)], second)
        self.assertEqual(self.match(first, serial=0x87654321), 0)
        # Without a mapping, the search counts both, so its caller rejects it.
        self.assertEqual(sum(self.match(data) for data in (first, second)), 2)

    def test_missing_truncated_or_disconnected_edid(self):
        for size in (0, 16, 54, 113, 127):
            self.assertEqual(self.match(edid()[:size]), 0)
        self.assertEqual(self.match(connected=0), 0)

    def test_bare_connector_ambiguity_and_card_qualified_override(self):
        names = (b"card0-DP-1", b"card1-DP-1")
        self.assertEqual(sum(self.match(override=b"DP-1", full_name=n) for n in names), 2)
        self.assertEqual(sum(self.match(override=b"card1-DP-1", full_name=n) for n in names), 1)

    def test_identity_map_and_no_fallback(self):
        serial = ctypes.c_uint()
        identity = lambda usb, a=None, b=None, override=None: self.lib.identity(
            usb, a, b, override, ctypes.byref(serial))
        self.assertEqual(identity(b"first"), 0)
        self.assertEqual(identity(b"first", override=b"DP-1"), 2)
        self.assertEqual(identity(b"second", b"first:12345678", b"second:87654321", b"DP-1"), 1)
        self.assertEqual(serial.value, 0x87654321)
        self.assertLess(identity(b"missing", b"first:12345678", override=b"DP-1"), 0)
        for value in (b"first", b":12345678", b"first:", b"first:xyz", b"first:0",
                      b"first:100000000"):
            self.assertLess(identity(b"first", value), 0)
        self.assertLess(identity(b"first", b"first:12345678", b"first:87654321"), 0)
        self.assertLess(identity(b"first", b"first:12345678", b"second:12345678"), 0)
        self.assertLess(identity(b"first", b"second:12345678", b"first:12345678"), 0)


if __name__ == "__main__":
    unittest.main()
