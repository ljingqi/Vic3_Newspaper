# -*- coding: utf-8 -*-
"""Build state_geojson.json v2: mark sea-only regions (skip at render).
Sea regions = STATE keys whose provinces are all default.map sea/lake colors.
Run in QGIS Python."""
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

# default.map sea/lake colors (统一大写, 与 state_regions 解析一致)
dm = open(os.path.join(BASE, "default.map"), encoding="utf-8",
          errors="replace").read()
sea_colors = {c.upper() for c in re.findall(
    r"x([0-9A-Fa-f]{6})", re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1))}
lake_colors = {c.upper() for c in re.findall(
    r"x([0-9A-Fa-f]{6})", re.search(r"lakes\s*=\s*\{([^}]*)\}", dm).group(1))}
water_colors = sea_colors | lake_colors

color_to_region = {}
region_water = {}   # STATE_XXX -> True if all provinces are water
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
        cols = [p.upper() for p in re.findall(r"x([0-9A-Fa-f]{6})", block)]
        for c in cols:
            color_to_region[c] = name
        region_water[name] = bool(cols) and all(c in water_colors for c in cols)
print("regions:", len(region_water), "water-only:",
      sum(1 for v in region_water.values() if v), "in %.1fs" % (time.time() - t0))

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

drv = gdal.GetDriverByName("MEM")
ds = drv.Create("prov", prov_ids.shape[1], prov_ids.shape[0], 1, gdal.GDT_Int32)
band = ds.GetRasterBand(1)
band.WriteArray(prov_ids.astype(np.int32))
band.SetNoDataValue(0)
vec = ogr.GetDriverByName("Memory").CreateDataSource("v")
layer = vec.CreateLayer("p", geom_type=ogr.wkbPolygon)
layer.CreateField(ogr.FieldDefn("PID", ogr.OFTInteger))
gdal.Polygonize(band, None, layer, 0, [], callback=None)

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

features = []
for r, polys in sorted(state_geom.items()):
    if region_water.get(r):
        continue   # 跳过纯海域州, 海洋由底层海色矩形呈现
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
      "land states:", len(features), "in %.1fs" % (time.time() - t0))
