# -*- coding: utf-8 -*-
"""Test: 4x downsampled polygonize + shapely simplify -> GeoJSON size."""
import json
import os
import re
import time

import numpy as np
from PIL import Image
from osgeo import gdal, ogr
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")

t0 = time.time()
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
colors_sorted = sorted(color_to_region.keys())
cidx = {c: i + 1 for i, c in enumerate(colors_sorted)}
lut = np.zeros(1 << 24, dtype=np.int32)
for c, i in cidx.items():
    lut[int(c, 16)] = i
prov_ids = lut[rgb24]
print("4x raster", prov_ids.shape, "in %.1fs" % (time.time() - t0))

drv = gdal.GetDriverByName("MEM")
ds = drv.Create("prov", prov_ids.shape[1], prov_ids.shape[0], 1, gdal.GDT_Int32)
band = ds.GetRasterBand(1)
band.WriteArray(prov_ids.astype(np.int32))
band.SetNoDataValue(0)
vec = ogr.GetDriverByName("Memory").CreateDataSource("v")
layer = vec.CreateLayer("p", geom_type=ogr.wkbPolygon)
layer.CreateField(ogr.FieldDefn("PID", ogr.OFTInteger))
gdal.Polygonize(band, None, layer, 0, [], callback=None)
print("province polys:", layer.GetFeatureCount(), "in %.1fs" % (time.time() - t0))

state_geom = {}
feat = layer.GetNextFeature()
while feat:
    pid = feat.GetField("PID")
    geom = feat.GetGeometryRef()
    if geom is not None and pid > 0:
        r = color_to_region.get(colors_sorted[pid - 1])
        if r:
            state_geom.setdefault(r, []).append(
                shape(json.loads(geom.ExportToJson())))
    feat = layer.GetNextFeature()
print("states:", len(state_geom), "in %.1fs" % (time.time() - t0))

# simplify: tolerance 1.0 px (4x scale) - preserve shape, drop pixel noise
simplified = {}
for r, polys in state_geom.items():
    u = unary_union(polys)
    s = u.simplify(1.0, preserve_topology=True)
    simplified[r] = s

total = sum(len(s.exterior.coords) if s.geom_type == "Polygon" else sum(
    len(p.exterior.coords) for p in s.geoms) for s in simplified.values())
print("vertices after simplify(1.0):", total)
for tol in (2.0, 3.0):
    t2 = sum(len(s.simplify(tol, preserve_topology=True).exterior.coords)
             if s.geom_type == "Polygon" else sum(
                 len(p.exterior.coords)
                 for p in s.simplify(tol, preserve_topology=True).geoms)
             for s in simplified.values())
    print(f"  tol {tol}: ~{t2}")

# write GeoJSON FeatureCollection (compact)
features = []
for r, s in sorted(simplified.items()):
    if s.is_empty:
        continue
    features.append({"type": "Feature", "properties": {"id": r},
                     "geometry": mapping(s)})
fc = {"type": "FeatureCollection", "features": features}
out = os.path.join(r"D:/Journal/_scratch", "state_geojson_test.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
print("GeoJSON written:", out, "%.1f KB" % (os.path.getsize(out) / 1024))
