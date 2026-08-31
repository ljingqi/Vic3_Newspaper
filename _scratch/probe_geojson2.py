# -*- coding: utf-8 -*-
"""Diagnose: do matplotlib-contour state polygons overlap? Then test
shapely-based clean polygonization (QGIS approach)."""
import os
import re
import time

import numpy as np
from PIL import Image

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")

color_to_region = {}
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
            color_to_region[p.upper()] = name

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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import shapely
from shapely.geometry import Polygon as SPolygon

print("shapely", shapely.__version__)


def contour_rings(region_key):
    mask = (rid == region_idx[region_key])
    cs = plt.contour(mask.astype(np.uint8), levels=[0.5], colors="k")
    rings = []
    for seg in cs.allsegs[0]:
        if len(seg) < 4:
            continue
        pts = np.round(seg).astype(int)
        if (pts[0] == pts[-1]).all():
            pts = pts[:-1]
        rings.append(pts)
    plt.close("all")
    return rings


def to_shapely(rings):
    out = []
    for pts in rings:
        p = SPolygon(pts)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_valid and not p.is_empty and p.area > 4:
            out.append(p)
    return out


# 1. overlap diagnosis on adjacent states
for a, b in (("STATE_KANTO", "STATE_TOKAI"),
             ("STATE_KYUSHU", "STATE_CHUGOKU")):
    pa = to_shapely(contour_rings(a))
    pb = to_shapely(contour_rings(b))
    if not pa or not pb:
        print(a, b, "-> no polygons")
        continue
    sa = pa[0].area
    inter = pa[0].intersection(pb[0]).area
    print(f"{a}∩{b}: overlap {inter:.0f} / area {sa:.0f} = {inter/sa*100:.2f}%")

# 2. count states with multiple disjoint polygons (islands etc)
multi = 0
for r in regions_sorted:
    if len(to_shapely(contour_rings(r))) > 1:
        multi += 1
print("states with >1 polygon (island chains):", multi, "/", len(regions_sorted))
