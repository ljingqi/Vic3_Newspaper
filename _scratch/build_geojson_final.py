# -*- coding: utf-8 -*-
"""Build final-format state GeoJSON with inland representative points.
Run in QGIS Python (needs shapely/osgeo). Output: state_geojson.json
{features: [{id, polys: [[[x,y],...]], point: [x,y]}], width, height}

point = shapely representative_point (always inside polygon) for rail
links / capital markers — never lands in the sea like centroid does.
"""
import json
import os
import re
import time

import numpy as np
from PIL import Image
from osgeo import gdal, ogr
from shapely.geometry import shape
from shapely.ops import unary_union

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")
OUT = r"D:/Journal/state_geojson.json"

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
print("raster", prov_ids.shape, "in %.1fs" % (time.time() - t0))

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

# simplify + representative point + extract polygons as plain lists
features = []
for r, polys in sorted(state_geom.items()):
    u = unary_union(polys)
    s = u.simplify(1.0, preserve_topology=True)
    if s.is_empty:
        continue
    rep = s.representative_point()
    polys_out = []
    if s.geom_type == "Polygon":
        polys_out.append([list(pt) for pt in s.exterior.coords])
    elif s.geom_type == "MultiPolygon":
        for p in s.geoms:
            polys_out.append([list(pt) for pt in p.exterior.coords])
    features.append({"id": r, "polys": polys_out,
                     "point": [round(rep.x, 1), round(rep.y, 1)]})

data = {"width": prov_ids.shape[1], "height": prov_ids.shape[0],
        "features": features}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
print("written:", OUT, "%.1f KB" % (os.path.getsize(OUT) / 1024),
      "states:", len(features), "in %.1fs" % (time.time() - t0))

# spot-check: Ryukyu inland point
for f in features:
    if f["id"] in ("STATE_RYUKYU_ISLANDS", "STATE_KANTO", "STATE_KANSAI"):
        print(" ", f["id"], "inland point:", f["point"])
