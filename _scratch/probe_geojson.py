# -*- coding: utf-8 -*-
"""Prototype: proper polygonization with shapely from provinces.png.

QGIS-style approach:
1. Read provinces.png -> per-province color raster
2. For each state region: mask -> shapely polygonize (shapely.ops.polygonize
   on contour edges, or rasterio.features.shapes - but rasterio missing;
   use shapely.vectorized / marching squares via matplotlib + shapely.buffer(0))
3. Result: topologically clean polygons (no overlaps between states)

Key question: are current matplotlib-contour polygons overlapping?
Diagnose first, then build clean GeoJSON.
"""
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")

t0 = time.time()
color_to_region = {}
region_colors = {}
sr = os.path.join(BASE, "state_regions")
for fn in os.listdir(sr):
    if not fn.endswith(".txt"):
        continue
    txt = open(os.path.join(sr, fn), encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"([A-Z0-9_]+)\s*=\s*\{", txt):
        name = m.group(1)
        if not name.startswith("STATE_"):
            continue
        start = m.end() - 1
        depth = 1
        i = start + 1
        while depth and i < len(txt):
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
            i += 1
        block = txt[start:i]
        for p in re.findall(r"x([0-9A-Fa-f]{6})", block):
            hexc = p.upper()
            color_to_region[hexc] = name
            region_colors.setdefault(name, []).append(hexc)
print("regions:", len(region_colors), "in %.1fs" % (time.time() - t0))

SCALE = 4
im = Image.open(os.path.join(BASE, "provinces.png")).convert("RGB")
im2 = im.resize((im.width // SCALE, im.height // SCALE), Image.NEAREST)
arr = np.asarray(im2, dtype=np.uint32)
rgb24 = (arr[..., 0] << 16) | (arr[..., 1] << 8) | arr[..., 2]
regions_sorted = sorted(set(color_to_region.values()))
region_idx = {r: i for i, r in enumerate(regions_sorted)}
lut = np.full(1 << 24, -1, dtype=np.int16)
for h, r in color_to_region.items():
    lut[int(h, 16)] = region_idx[r]
rid = lut[rgb24]
print("rid ready in %.1fs" % (time.time() - t0))

# ---- Diagnose overlap of existing contour approach ----
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# check two adjacent states in Japan: KANTO (关东) & TOKAI (东海)
for name in ("STATE_KANTO", "STATE_TOKAI", "STATE_KYUSHU"):
    ti = region_idx[name]
    mask = (rid == ti)
    cs = plt.contour(mask.astype(np.uint8), levels=[0.5], colors="k")
    polys = []
    for seg in cs.allsegs[0]:
        if len(seg) < 4:
            continue
        pts = np.round(seg).astype(int)
        if (pts[0] == pts[-1]).all():
            pts = pts[:-1]
        polys.append(pts)
    print(name, "contour polys:", len(polys),
          "pts:", [len(p) for p in polys])
    plt.close("all")

# ---- shapely polygonize: use contour rings -> shapely polygons, then
# compute overlaps between KANTO and TOKAI
import shapely
from shapely.geometry import Polygon as SPolygon
from shapely.ops import unary_union

def rings_to_shapely(polys):
    """matplotlib contour rings -> shapely polygons (buffer(0) to fix)."""
    out = []
    for pts in polys:
        if len(pts) < 4:
            continue
        poly = SPolygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_valid and not poly.is_empty:
            out.append(poly)
    return out

kanto = rings_to_shapely([np.round(s).astype(int) for s in
                          plt_rings(rid, region_idx["STATE_KANTO"])])
tokai = rings_to_shapely([np.round(s).astype(int) for s in
                          plt_rings(rid, region_idx["STATE_TOKAI"])])
print("\nKANTO shapely:", [p.area for p in kanto],
      "TOKAI shapely:", [p.area for p in tokai])
if kanto and tokai:
    inter = kanto[0].intersection(tokai[0])
    print("KANTO∩TOKAI intersection area:", inter.area,
          "(KANTO area:", kanto[0].area, ")")
    print("overlap ratio:", inter.area / kanto[0].area if kanto[0].area else 0)
