# -*- coding: utf-8 -*-
"""Prototype: QGIS-style polygonization via GDAL Polygonize.

Pipeline:
1. provinces.png -> per-province id raster (in-memory GDAL dataset)
2. gdal.Polygonize -> province polygons (topologically clean, no overlap)
3. map province color -> STATE_XXX via state_regions
4. dissolve provinces into state polygons (unary_union per state)
5. output GeoJSON per state

This runs in QGIS's Python (has osgeo + shapely + geopandas).
"""
import json
import os
import re
import sys
import time
import tempfile

import numpy as np
from PIL import Image
from osgeo import gdal, ogr
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")

t0 = time.time()
# 1. province color -> STATE_XXX
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
print("province colors:", len(color_to_region))

# 2. load provinces.png -> province id raster
im = Image.open(os.path.join(BASE, "provinces.png")).convert("RGB")
arr = np.asarray(im, dtype=np.uint32)
rgb24 = (arr[..., 0] << 16) | (arr[..., 1] << 8) | arr[..., 2]
# province id = order in map_editor_status completed block (matches
# journal_save._load_province_id_by_color). For polygonize we just need
# unique values; use color index directly (0..N).
colors_sorted = sorted(color_to_region.keys())
cidx = {c: i + 1 for i, c in enumerate(colors_sorted)}  # 0 = no data (sea)
lut = np.zeros(1 << 24, dtype=np.int32)
for c, i in cidx.items():
    lut[int(c, 16)] = i
prov_ids = lut[rgb24]
print("raster ready", prov_ids.shape, "in %.1fs" % (time.time() - t0))

# 3. in-memory GDAL raster -> polygonize
drv = gdal.GetDriverByName("MEM")
ds = drv.Create("prov", prov_ids.shape[1], prov_ids.shape[0], 1, gdal.GDT_Int32)
band = ds.GetRasterBand(1)
band.WriteArray(prov_ids.astype(np.int32))
band.SetNoDataValue(0)

mem_drv = ogr.GetDriverByName("Memory")
vec = mem_drv.CreateDataSource("prov_vec")
layer = vec.CreateLayer("prov", geom_type=ogr.wkbPolygon)
fld = ogr.FieldDefn("PID", ogr.OFTInteger)
layer.CreateField(fld)
gdal.Polygonize(band, None, layer, 0, [], callback=None)
print("province polys:", layer.GetFeatureCount(), "in %.1fs" % (time.time() - t0))

# 4. dissolve into states
state_geom = {}   # STATE_XXX -> list of shapely polygons
feat = layer.GetNextFeature()
n = 0
while feat:
    pid = feat.GetField("PID")
    geom = feat.GetGeometryRef()
    if geom is not None and pid > 0:
        c = colors_sorted[pid - 1]
        r = color_to_region.get(c)
        if r:
            state_geom.setdefault(r, []).append(shape(json.loads(geom.ExportToJson())))
    feat = layer.GetNextFeature()
    n += 1
print("states found:", len(state_geom), "in %.1fs" % (time.time() - t0))

# 5. union per state, keep only largest-ish; report sizes
total_pts = 0
big = 0
for r, polys in state_geom.items():
    u = unary_union(polys)
    npts = len(u.exterior.coords) if u.geom_type == "Polygon" else sum(
        len(p.exterior.coords) for p in u.geoms)
    total_pts += npts
    if npts > 200:
        big += 1
print("total vertices after union:", total_pts, "states >200pts:", big)

# 6. sample: KANTO/TOKAI overlap check (should be 0 or tiny)
k = unary_union(state_geom.get("STATE_KANTO", []))
t = unary_union(state_geom.get("STATE_TOKAI", []))
if not k.is_empty and not t.is_empty:
    inter = k.intersection(t).area
    print(f"KANTO∩TOKAI overlap: {inter:.0f} (KANTO {k.area:.0f}, "
          f"TOKAI {t.area:.0f})")

# 7. write a small GeoJSON sample for inspection
sample = {"STATE_KANTO": mapping(k), "STATE_TOKAI": mapping(t),
          "STATE_KYUSHU": mapping(unary_union(state_geom.get("STATE_KYUSHU", [])))}
out = os.path.join(r"D:/Journal/_scratch", "state_geojson_sample.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(sample, f, ensure_ascii=False)
print("sample written:", out, os.path.getsize(out), "bytes")
