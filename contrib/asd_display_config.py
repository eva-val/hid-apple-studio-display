"""Serialize Mutter state without losing settings, and reflow rotated layouts."""
from collections import deque
import math
import struct

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

# GetCurrentState names, ApplyMonitorsConfig names, and D-Bus types.
MONITOR_PROPERTIES = (
    ("color-mode", "color-mode", "u"),
    ("rgb-range", "rgb-range", "u"),
    ("is-underscanning", "underscanning", "b"),
)


def read_state(proxy):
    return proxy.call_sync("GetCurrentState", None, Gio.DBusCallFlags.NONE, 5000, None).unpack()


def serialize_state(state):
    serial, monitors, logical, props = state
    current = {}
    leases = []
    for spec, modes, mon_props in monitors:
        mode = next((m[0] for m in modes if m[-1].get("is-current")), None)
        kept = {target: GLib.Variant(kind, mon_props[source])
                for source, target, kind in MONITOR_PROPERTIES if source in mon_props}
        current[spec[0]] = (mode, kept)
        if mon_props.get("is-for-lease"):
            leases.append(tuple(spec))

    new_logical = []
    for x, y, scale, transform, primary, mons, _ in logical:
        if not mons or any(m[0] not in current or current[m[0]][0] is None for m in mons):
            raise RuntimeError("active monitor has no current mode yet")
        new_logical.append((x, y, scale, transform, primary,
                            [(m[0], *current[m[0]]) for m in mons]))

    config_props = {}
    if props.get("supports-changing-layout-mode") and "layout-mode" in props:
        config_props["layout-mode"] = GLib.Variant("u", props["layout-mode"])
    if leases:
        config_props["monitors-for-lease"] = GLib.Variant("a(ssss)", leases)
    return serial, new_logical, config_props


def read_config(proxy):
    return serialize_state(read_state(proxy))


def apply_config(proxy, config, method=1):
    serial, logical, props = config
    proxy.call_sync(
        "ApplyMonitorsConfig",
        GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, method, logical, props)),
        Gio.DBusCallFlags.NONE, 5000, None)


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def monitor_size(mode, scale, transform, layout_mode):
    width, height = mode[1:3]
    if width <= 0 or height <= 0 or not math.isfinite(scale) or scale <= 0:
        raise RuntimeError("invalid monitor size or scale")
    if transform not in range(8) or layout_mode not in (1, 2):
        raise RuntimeError("unsupported transform or layout mode")
    if transform % 2:
        width, height = height, width
    if layout_mode == 1:
        # Mutter derives dimensions using float arithmetic and roundf, which
        # rounds half away from zero (Python round instead uses ties-to-even).
        width = math.floor(f32(f32(width) / f32(scale)) + 0.5)
        height = math.floor(f32(f32(height) / f32(scale)) + 0.5)
    if width <= 0 or height <= 0:
        raise RuntimeError("empty logical monitor")
    return width, height


def rectangles(state):
    _, monitors, logical, props = state
    modes = {spec[0]: next((m for m in modes if m[-1].get("is-current")), None)
             for spec, modes, _ in monitors}
    result = []
    for x, y, scale, transform, _, mons, _ in logical:
        if not mons or any(modes.get(m[0]) is None for m in mons):
            raise RuntimeError("active monitor has no current mode yet")
        sizes = {monitor_size(modes[m[0]], scale, transform, props.get("layout-mode", 1))
                 for m in mons}
        if len(sizes) != 1:
            raise RuntimeError("mirrored monitors have inconsistent dimensions")
        result.append((x, y, *sizes.pop()))
    return result


def adjacent(a, b):
    x, y, w, h = a
    bx, by, bw, bh = b
    return (((x + w == bx or bx + bw == x) and max(y, by) < min(y + h, by + bh))
            or ((y + h == by or by + bh == y) and max(x, bx) < min(x + w, bx + bw)))


def validate_layout(rects):
    if not rects:
        raise RuntimeError("empty monitor layout")
    if min(r[0] for r in rects) != 0 or min(r[1] for r in rects) != 0:
        raise RuntimeError("monitor layout must start at the origin")
    for i, (x, y, w, h) in enumerate(rects):
        for bx, by, bw, bh in rects[i + 1:]:
            if max(x, bx) < min(x + w, bx + bw) and max(y, by) < min(y + h, by + bh):
                raise RuntimeError("rotated monitor layout overlaps")
    reached = {0}
    pending = [0]
    while pending:
        i = pending.pop()
        for j in range(len(rects)):
            if j not in reached and adjacent(rects[i], rects[j]):
                reached.add(j)
                pending.append(j)
    if len(reached) != len(rects):
        raise RuntimeError("rotated monitor layout is disconnected")


def aligned_offset(offset, old_a, old_b, new_a, new_b):
    if offset == 0:  # Keep a shared top/left edge.
        return 0
    if offset == old_a - old_b:  # Shared bottom/right edge.
        return new_a - new_b
    if 2 * offset == old_a - old_b:  # Shared center.
        return (new_a - new_b) // 2
    # Preserve a deliberate stagger where possible, with at least one pixel
    # of common edge left after either display shrinks.
    return max(1 - new_b, min(offset, new_a - 1))


def reflow(old, sizes, anchor):
    """Keep existing edge contacts and alignment; reject conflicting layouts.

    A graph of relative position constraints propagates shifts through chains
    and branches. Cycles must agree, and all rectangles must still be disjoint.
    No arbitrary fallback rearranges a user's grid into a horizontal row.
    """
    validate_layout(old)
    edges = [[] for _ in old]
    for i, (x, y, w, h) in enumerate(old):
        nw, nh = sizes[i]
        for j in range(i + 1, len(old)):
            if not adjacent(old[i], old[j]):
                continue
            bx, by, bw, bh = old[j]
            nbw, nbh = sizes[j]
            if x + w == bx or bx + bw == x:
                dx = nw if x + w == bx else -nbw
                dy = aligned_offset(by - y, h, bh, nh, nbh)
            else:
                dx = aligned_offset(bx - x, w, bw, nw, nbw)
                dy = nh if y + h == by else -nbh
            edges[i].append((j, dx, dy))
            edges[j].append((i, -dx, -dy))
    positions = {anchor: old[anchor][:2]}
    pending = deque([anchor])
    while pending:
        i = pending.popleft()
        x, y = positions[i]
        for j, dx, dy in edges[i]:
            proposed = (x + dx, y + dy)
            if j in positions:
                if positions[j] != proposed:
                    raise RuntimeError("rotation conflicts with existing monitor edge alignments")
            else:
                positions[j] = proposed
                pending.append(j)
    left = min(x for x, _ in positions.values())
    top = min(y for _, y in positions.values())
    result = [(positions[i][0] - left, positions[i][1] - top, *sizes[i])
              for i in range(len(old))]
    validate_layout(result)
    return result


def rotation_config(state, connector, transform):
    serial, rows, props = serialize_state(state)
    indices = [i for i, row in enumerate(rows) if connector in (m[0] for m in row[5])]
    if len(indices) != 1:
        raise RuntimeError(f"connector {connector} is not uniquely active")
    target = indices[0]
    if len(rows[target][5]) != 1:
        raise RuntimeError("cannot independently rotate a mirrored display")
    primary = [i for i, row in enumerate(rows) if row[4]]
    if len(primary) != 1:
        raise RuntimeError("monitor layout must have exactly one primary")
    old = rectangles(state)
    new_logical = list(state[2])
    changed = list(new_logical[target])
    changed[3] = transform
    new_logical[target] = tuple(changed)
    resized = rectangles((state[0], state[1], new_logical, state[3]))
    layout = reflow(old, [r[2:] for r in resized], primary[0])
    result = [(layout[i][0], layout[i][1], scale, transform if i == target else old_transform,
               is_primary, mons)
              for i, (_, _, scale, old_transform, is_primary, mons) in enumerate(rows)]
    return serial, result, props
