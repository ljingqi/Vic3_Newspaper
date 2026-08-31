# -*- coding: utf-8 -*-
"""Check state_shapes.json centroids for rail link endpoints + viewport."""
import json
import sys

sys.path.insert(0, r"D:/Journal")
import htmlview

md = json.load(open(r"D:/Journal/_scratch/map_test.json", encoding="utf-8"))
shapes = htmlview._map_shapes()
cent = shapes.get("centroids") or {}

print("state_shapes.json centroids for rail endpoints:")
for a, b in md.get("rail_links") or []:
    pa, pb = cent.get(a), cent.get(b)
    print(f"  {a}({pa[0]:.0f},{pa[1]:.0f}) - {b}({pb[0]:.0f},{pb[1]:.0f})")

print("\nviewport:", [round(v, 1) for v in
                      htmlview._map_viewport(md.get("main") or [], shapes)])

# check all centroids used in rendering (player states + foreign + rail)
used = set(md.get("railways") or [])
for a, b in md.get("rail_links") or []:
    used.add(a); used.add(b)
print("\nall centroids used by rail rendering:")
for r in sorted(used):
    c = cent.get(r)
    print(f"  {r}: ({c[0]:.0f},{c[1]:.0f})" if c else f"  {r}: NONE")
