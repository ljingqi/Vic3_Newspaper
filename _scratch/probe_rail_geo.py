# -*- coding: utf-8 -*-
"""Check rail link endpoints in the GeoJSON render — is a centroid in the
Pacific (island-chain state like Ryukyu) causing the big triangle?"""
import json
import sys

import numpy as np

REPO = r"D:/Journal"
GEO = REPO + "/_scratch/state_geojson_test.json"
MD = REPO + "/_scratch/map_test.json"

fc = json.load(open(GEO, encoding="utf-8"))
md = json.load(open(MD, encoding="utf-8"))

geo = {}
for f in fc["features"]:
    g = f["geometry"]
    r = f["properties"]["id"]
    polys = []
    if g["type"] == "Polygon":
        polys.append(np.array(g["coordinates"][0]))
    elif g["type"] == "MultiPolygon":
        for poly in g["coordinates"]:
            polys.append(np.array(poly[0]))
    geo[r] = polys

cent = {}
for r, polys in geo.items():
    pts = np.concatenate(polys, axis=0)
    cent[r] = [float(pts[:, 0].mean()), float(pts[:, 1].mean())]

print("rail links (GeoJSON centroids):")
for a, b in md.get("rail_links") or []:
    pa, pb = cent.get(a), cent.get(b)
    if pa and pb:
        print(f"  {a}({pa[0]:.0f},{pa[1]:.0f}) - {b}({pb[0]:.0f},{pb[1]:.0f})"
              f" span dx={abs(pa[0]-pb[0]):.0f} dy={abs(pa[1]-pb[1]):.0f}")

# Compare: centroid vs representative point (inside polygon) for each player
# state, to see if any centroid is off-land (in the sea).
print("\nPlayer state centroid vs in-polygon representative point:")
for r in sorted(set(md.get("main") or []) | set(md.get("overseas") or [])):
    polys = geo.get(r)
    if not polys:
        continue
    pts = np.concatenate(polys, axis=0)
    c = [pts[:, 0].mean(), pts[:, 1].mean()]
    print(f"  {r}: centroid=({c[0]:.0f},{c[1]:.0f})  polys={len(polys)}")
