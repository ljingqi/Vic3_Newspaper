# -*- coding: utf-8 -*-
"""Prototype: render map from clean GeoJSON (plain Python + matplotlib only,
no shapely needed at render time) — the QGIS-side approach."""
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib import font_manager

REPO = r"D:/Journal"
GEO = os.path.join(REPO, "_scratch", "state_geojson_test.json")
MD = os.path.join(REPO, "_scratch", "map_test.json")

fc = json.load(open(GEO, encoding="utf-8"))
md = json.load(open(MD, encoding="utf-8"))

# feature index: id -> list of polygons (each as Nx2 array)
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

print("geo states:", len(geo))

main = md.get("main") or []
overseas = md.get("overseas") or []
colors = md.get("colors") or {}
foreign = md.get("foreign_capitals") or []
rail_links = md.get("rail_links") or []
cap_rk = md.get("capital_region")
player = md.get("player") or ""
year = md.get("year")

# centroids from GeoJSON
cent = {}
for r, polys in geo.items():
    pts = np.concatenate(polys, axis=0)
    cent[r] = [float(pts[:, 0].mean()), float(pts[:, 1].mean())]

# viewport from main regions
xs, ys = [], []
for r in main:
    for p in geo.get(r, []):
        xs.extend(p[:, 0]); ys.extend(p[:, 1])
x0, x1 = min(xs) - 15, max(xs) + 15
y0, y1 = min(ys) - 15, max(ys) + 15
data_w, data_h = x1 - x0, y1 - y0

_PALETTE = ["#FBB4AE", "#B3CDE3", "#CCEBC5", "#DECBE4"]
_SEA = "#dceaf2"
_LAND = "#efe6cf"
_BORDER = "#c9bb9a"
_OWN_BORDER = "#8a6d3b"

_CJK = ("KaiTi", "SimHei", "SimSun", "Microsoft YaHei",
        "Source Han Serif SC", "Source Han Sans CN", "Noto Sans CJK SC")
avail = {f.name for f in font_manager.fontManager.ttflist}
fam = next((f for f in _CJK if f in avail), None)
if fam:
    plt.rcParams["font.sans-serif"] = [fam]
plt.rcParams["axes.unicode_minus"] = False

target_w = 10.0
target_h = min(8.2, max(4.6, target_w * data_h / data_w * 0.92))
fig = plt.figure(figsize=(target_w, target_h), dpi=100)
ax = fig.add_axes([0.02, 0.06, 0.92, 0.80])
ax.set_xlim(x0, x1)
ax.set_ylim(y1, y0)   # 北朝上
ax.set_aspect("equal")
ax.axis("off")

own_set = set(main) | set(overseas)

def in_v(poly):
    return (max(poly[:, 0]) >= x0 and min(poly[:, 0]) <= x1
            and max(poly[:, 1]) >= y0 and min(poly[:, 1]) <= y1)

# sea
ax.add_patch(MplPolygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                        closed=True, facecolor=_SEA, edgecolor="none", zorder=0))
# foreign land
for r, polys in geo.items():
    if r in own_set:
        continue
    for p in polys:
        if not in_v(p):
            continue
        ax.add_patch(MplPolygon(p, closed=True, facecolor=_LAND,
                                edgecolor=_BORDER, linewidth=0.25))
# player states
for r in main + overseas:
    c = _PALETTE[colors.get(r, 0) % len(_PALETTE)]
    for p in geo.get(r, []):
        ax.add_patch(MplPolygon(p, closed=True, facecolor=c,
                                edgecolor=_OWN_BORDER, linewidth=0.9))
# railways
if rail_links:
    for a, b in rail_links:
        pa, pb = cent.get(a), cent.get(b)
        if pa and pb:
            ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color="#3a3a3a",
                    linewidth=1.2, solid_capstyle="round", zorder=5)
# foreign capitals
for fc0 in foreign:
    c = cent.get(fc0.get("region"))
    if not c:
        continue
    rgb = fc0.get("color") or [120, 120, 120]
    ax.plot(c[0], c[1], "o", ms=4.5, color=tuple(v / 255 for v in rgb),
            mec="#222", mew=0.5, zorder=6)
    ax.text(c[0] + 6, c[1] + 3, fc0.get("name", ""), fontsize=7.5,
            color="#2a1d0e", zorder=6)
# capital
if cap_rk and cent.get(cap_rk):
    cx, cy = cent[cap_rk]
    ax.plot(cx, cy, marker="*", ms=13, color="#d23b2e", mec="#7a1508",
            mew=0.8, zorder=7)

title = f"{player}疆域图" + (f" · {year}年" if year else "")
fig.suptitle(title, fontsize=17, y=0.965, color="#2a1d0e", fontweight="bold")

ax.annotate("", xy=(0.045, 0.90), xytext=(0.045, 0.83),
            xycoords="axes fraction", textcoords="axes fraction",
            arrowprops=dict(arrowstyle="-|>", color="#2a1d0e", lw=1.5))
ax.text(0.045, 0.78, "北", fontsize=10, color="#2a1d0e",
        ha="center", fontweight="bold", transform=ax.transAxes)

legend_items = [
    ("#FBB4AE", "本国省份（相邻异色）"),
    ("#d23b2e", "首都"),
    ("#555555", "外国首都"),
    ("#3a3a3a", "铁路"),
]
lx, ly = 0.035, 0.075
step = 0.052
for i, (c, label) in enumerate(legend_items):
    y = ly + i * step
    ax.add_patch(plt.Rectangle((lx, y), 0.014, step * 0.55,
                               facecolor=c, edgecolor="#6d5230",
                               linewidth=0.6, transform=ax.transAxes, zorder=8))
    ax.text(lx + 0.022, y + step * 0.26, label, fontsize=8.5,
            color="#2a1d0e", va="center", transform=ax.transAxes, zorder=8)

out = os.path.join(REPO, "_scratch", "map_geojson_demo.png")
fig.savefig(out, bbox_inches="tight", facecolor="#fbf6e9")
plt.close(fig)
print("PNG written:", out, os.path.getsize(out), "bytes")
