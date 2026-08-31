# -*- coding: utf-8 -*-
"""Decisive check (QGIS Python): which player-state centroids are OFF-LAND?
Island-chain states (Ryukyu etc.) have vertex-average centroids in the sea.
Also compare representative_point (inside polygon) vs centroid."""
import json
import sys

import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union

REPO = r"D:/Journal"
fc = json.load(open(REPO + "/_scratch/state_geojson_test.json", encoding="utf-8"))
md = json.load(open(REPO + "/_scratch/map_test.json", encoding="utf-8"))

geo = {}
for f in fc["features"]:
    geo[f["properties"]["id"]] = shape(f["geometry"])

print("Player states — centroid inside polygon?")
for r in sorted(set(md.get("main") or []) | set(md.get("overseas") or [])):
    g = geo.get(r)
    if g is None:
        print(f"  {r}: 无几何")
        continue
    cent = g.centroid
    rep = g.representative_point()
    print(f"  {r}: centroid={cent.x:.0f},{cent.y:.0f} "
          f"in_poly={g.covers(cent)}  "
          f"rep_pt={rep.x:.0f},{rep.y:.0f} in_poly={g.covers(rep)}")

print("\nRyukyu geometry type/parts:", geo["STATE_RYUKYU_ISLANDS"].geom_type)
