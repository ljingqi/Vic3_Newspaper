# -*- coding: utf-8 -*-
"""Render map SVG to PNG for visual check (via matplotlib re-import)."""
import json
import os
import sys

REPO = r"D:/Journal"
sys.path.insert(0, REPO)
import htmlview

md = json.load(open(os.path.join(REPO, "_scratch", "map_test.json"),
                    encoding="utf-8"))
shapes = htmlview._map_shapes()

# Reuse render but capture to PNG instead of SVG: monkey-patch savefig target
# Simpler: call render_map_svg then convert with a tiny svg->png via matplotlib?
# We can't rasterize SVG easily; instead render a PNG directly with a parallel
# code path that mirrors render_map_svg (draw the same patches).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Polygon as MplPolygon

_CJK = ("KaiTi", "SimHei", "SimSun", "Microsoft YaHei",
        "Source Han Serif SC", "Source Han Sans CN", "Noto Sans CJK SC")
avail = {f.name for f in font_manager.fontManager.ttflist}
fam = next((f for f in _CJK if f in avail), None)
if fam:
    plt.rcParams["font.sans-serif"] = [fam]
plt.rcParams["axes.unicode_minus"] = False

_PALETTE = ["#FBB4AE", "#B3CDE3", "#CCEBC5", "#DECBE4"]
_SEA = "#dceaf2"
_LAND = "#efe6cf"
_BORDER = "#c9bb9a"
_OWN_BORDER = "#8a6d3b"

main = md.get("main") or []
overseas = md.get("overseas") or []
colors = md.get("colors") or {}
foreign = md.get("foreign_capitals") or []
rail_links = md.get("rail_links") or []
cap_rk = md.get("capital_region")
player = md.get("player") or ""
year = md.get("year")
centroids = shapes.get("centroids") or {}
all_shapes = shapes.get("shapes") or {}

view = htmlview._map_viewport(main, shapes)
vx0, vy0, vx1, vy1 = view
W, H = 1000, 640
fig = plt.figure(figsize=(W / 100, H / 100), dpi=110)
ax = fig.add_axes([0.02, 0.06, 0.90, 0.82])
ax.set_facecolor(_SEA)
ax.set_xlim(vx0, vx1)
ax.set_ylim(vy0, vy1)
ax.set_aspect("equal")
ax.axis("off")


def in_view(poly, v):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (max(xs) >= v[0] and min(xs) <= v[2]
            and max(ys) >= v[1] and min(ys) <= v[3])


own_set = set(main) | set(overseas)
for r, polys in all_shapes.items():
    if r in own_set:
        continue
    for poly in polys:
        if not in_view(poly, view):
            continue
        ax.add_patch(MplPolygon(poly, closed=True, facecolor=_LAND,
                                edgecolor=_BORDER, linewidth=0.3))
for r in main + overseas:
    c = _PALETTE[colors.get(r, 0) % len(_PALETTE)]
    for poly in all_shapes.get(r, ()):
        ax.add_patch(MplPolygon(poly, closed=True, facecolor=c,
                                edgecolor=_OWN_BORDER, linewidth=0.9))
if rail_links:
    for a, b in rail_links:
        pa, pb = centroids.get(a), centroids.get(b)
        if pa and pb:
            ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color="#3a3a3a",
                    linewidth=1.2, solid_capstyle="round", zorder=5)
for fc in foreign:
    c = centroids.get(fc.get("region"))
    if not c:
        continue
    rgb = fc.get("color") or [120, 120, 120]
    ax.plot(c[0], c[1], "o", ms=4, color=tuple(v / 255 for v in rgb),
            mec="#222", mew=0.4, zorder=6)
    ax.text(c[0] + 6, c[1] + 3, fc.get("name", ""), fontsize=7,
            color="#3a2c16", zorder=6)
if cap_rk and centroids.get(cap_rk):
    cx, cy = centroids[cap_rk]
    ax.plot(cx, cy, marker="*", ms=13, color="#d23b2e",
            mec="#7a1508", mew=0.8, zorder=7)
if overseas:
    ov = htmlview._map_viewport(overseas, shapes, pad=0.10)
    if ov:
        ox0, oy0, ox1, oy1 = ov
        iax = fig.add_axes([0.78, 0.72, 0.20, 0.24])
        iax.set_facecolor(_SEA)
        iax.set_xlim(ox0, ox1)
        iax.set_ylim(oy0, oy1)
        iax.set_aspect("equal")
        iax.axis("off")
        for r, polys in all_shapes.items():
            if r in own_set:
                continue
            for poly in polys:
                if not in_view(poly, (ox0, oy0, ox1, oy1)):
                    continue
                iax.add_patch(MplPolygon(poly, closed=True, facecolor=_LAND,
                                         edgecolor=_BORDER, linewidth=0.2))
        for r in overseas:
            c = _PALETTE[colors.get(r, 0) % len(_PALETTE)]
            for poly in all_shapes.get(r, ()):
                iax.add_patch(MplPolygon(poly, closed=True, facecolor=c,
                                         edgecolor=_OWN_BORDER, linewidth=0.6))
        iax.set_title("海外省", fontsize=8, pad=2, color="#3a2c16")

title = f"{player}疆域图" + (f" · {year}年" if year else "")
fig.suptitle(title, fontsize=16, y=0.96, color="#3a2c16")

ax.annotate("", xy=(vx0 + (vx1 - vx0) * 0.04, vy1 - (vy1 - vy0) * 0.04),
            xytext=(vx0 + (vx1 - vx0) * 0.04,
                    vy1 - (vy1 - vy0) * 0.04 - (vy1 - vy0) * 0.05),
            arrowprops=dict(arrowstyle="-|>", color="#3a2c16", lw=1.2))
ax.text(vx0 + (vx1 - vx0) * 0.035, vy1 - (vy1 - vy0) * 0.075, "北",
        fontsize=9, color="#3a2c16", ha="center")

legend_items = [
    ("#FBB4AE", "本国省份（相邻异色）"),
    ("#d23b2e", "首都"),
    ("#555555", "外国首都"),
    ("#3a3a3a", "铁路"),
]
lx = vx0 + (vx1 - vx0) * 0.03
ly0 = vy0 + (vy1 - vy0) * 0.03
step = (vy1 - vy0) * 0.035
for i, (c, label) in enumerate(legend_items):
    y = ly0 + i * step
    ax.add_patch(plt.Rectangle((lx, y), (vx1 - vx0) * 0.008,
                               step * 0.7, facecolor=c,
                               edgecolor="#8a6d3b", linewidth=0.4))
    ax.text(lx + (vx1 - vx0) * 0.012, y + step * 0.25, label,
            fontsize=7.5, color="#3a2c16", va="center")

out = os.path.join(REPO, "_scratch", "map_demo.png")
fig.savefig(out, facecolor="#fbf6e9", bbox_inches="tight")
print("PNG written:", out, os.path.getsize(out), "bytes")
