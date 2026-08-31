# -*- coding: utf-8 -*-
"""Verify: is the 'big black triangle' the railway centroid links?"""
import json
import sys

sys.path.insert(0, r"D:/Journal")
import htmlview

md = json.load(open(r"D:/Journal/_scratch/map_test.json", encoding="utf-8"))
shapes = htmlview._map_shapes()
cent = shapes.get("centroids") or {}

print("rail_links:")
for a, b in md.get("rail_links") or []:
    pa, pb = cent.get(a), cent.get(b)
    if pa and pb:
        print(f"  {a}({pa[0]:.0f},{pa[1]:.0f}) <-> {b}({pb[0]:.0f},{pb[1]:.0f})")

# check the viewport
view = htmlview._map_viewport(md.get("main") or [], shapes)
print("\nviewport:", [round(v, 1) for v in view] if view else None)

# the 'triangle' near center-right: are any rail links crossing the viewport
# diagonally with long spans?
print("\nmain regions with centroids:")
for r in md.get("main") or []:
    c = cent.get(r)
    if c:
        print(f"  {r}: ({c[0]:.0f},{c[1]:.0f})")
