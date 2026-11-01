"""Complete Mutter wire fixtures and independent outgoing-layout assertions."""
import math


def state_for(entries, layout_mode=1, properties=None):
    """Entries: connector, x, y, pixel width/height, scale, transform, primary."""
    monitors, logical = [], []
    for connector, x, y, width, height, scale, transform, primary in entries:
        spec = (connector, "vendor", "model", f"serial-{connector}")
        modes = [(f"{connector}-mode", width, height, 60.0, scale, [scale], {"is-current": True})]
        monitors.append((spec, modes, (properties or {}).get(connector, {})))
        logical.append((x, y, scale, transform, primary, [spec], {}))
    return (7, monitors, logical,
            {"layout-mode": layout_mode, "supports-changing-layout-mode": True})


def assert_valid_payload(test, state, payload):
    """Check rectangles independently of the implementation's reflow/validator."""
    serial, method, logical, props = payload
    test.assertEqual(serial, state[0])
    test.assertIn(method, (0, 1))
    test.assertEqual(sum(row[4] for row in logical), 1)
    modes = {spec[0]: {m[0]: m for m in modes} for spec, modes, _ in state[1]}
    boxes = []
    for x, y, scale, transform, _, mons in logical:
        sizes = []
        for connector, mode_id, _ in mons:
            mode = modes[connector][mode_id]
            w, h = mode[1:3]
            if transform in (1, 3, 5, 7):
                w, h = h, w
            if props.get("layout-mode", 1) == 1:
                w, h = math.floor(w / scale + .5), math.floor(h / scale + .5)
            sizes.append((w, h))
        test.assertTrue(all(size == sizes[0] for size in sizes))
        w, h = sizes[0]
        boxes.append((x, y, x + w, y + h))
    test.assertEqual(min(b[0] for b in boxes), 0)
    test.assertEqual(min(b[1] for b in boxes), 0)
    edges = {i: set() for i in range(len(boxes))}
    for i, (left, top, right, bottom) in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            l, t, r, b = boxes[j]
            x_overlap = min(right, r) - max(left, l)
            y_overlap = min(bottom, b) - max(top, t)
            test.assertFalse(x_overlap > 0 and y_overlap > 0, "overlapping monitors")
            if (x_overlap == 0 and y_overlap > 0) or (y_overlap == 0 and x_overlap > 0):
                edges[i].add(j)
                edges[j].add(i)
    reached, queue = set(), [0]
    while queue:
        i = queue.pop()
        if i not in reached:
            reached.add(i)
            queue.extend(edges[i] - reached)
    test.assertEqual(len(reached), len(boxes), "disconnected monitors")
