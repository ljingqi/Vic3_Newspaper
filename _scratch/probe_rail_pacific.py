# -*- coding: utf-8 -*-
"""Find which rail state centroid is out in the Pacific (explains the
big black triangle: rail links drawn from a far-flung centroid)."""
import json
import sys

sys.path.insert(0, r"D:/Journal")
import htmlview

md = json.load(open(r"D:/Journal/_scratch/map_test.json", encoding="utf-8"))
shapes = htmlview._map_shapes()
cent = shapes.get("centroids") or {}

print("railways in map data:", md.get("railways"))
print("rail_links:", md.get("rail_links"))
print()
print("viewport:", [round(v, 1) for v in
                    htmlview._map_viewport(md.get("main") or [], shapes)])

print("\nAll player regions centroids vs viewport:")
view = htmlview._map_viewport(md.get("main") or [], shapes)
vx0, vy0, vx1, vy1 = view
for r in sorted(set(md.get("main") or []) | set(md.get("overseas") or [])):
    c = cent.get(r)
    if not c:
        continue
    in_v = (vx0 <= c[0] <= vx1 and vy0 <= c[1] <= vy1)
    flag = "" if in_v else "  <-- OUTSIDE viewport"
    print(f"  {r}: ({c[0]:.0f},{c[1]:.0f}){flag}")

print("\nRail link endpoints:")
for a, b in md.get("rail_links") or []:
    pa, pb = cent.get(a), cent.get(b)
    if pa and pb:
        dx = abs(pa[0] - pb[0])
        dy = abs(pa[1] - pb[1])
        long = "  <-- LONG" if max(dx, dy) > 150 else ""
        print(f"  {a}({pa[0]:.0f},{pa[1]:.0f}) - {b}({pb[0]:.0f},{pb[1]:.0f})"
              f" span dx={dx:.0f} dy={dy:.0f}{long}")
