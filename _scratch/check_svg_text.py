# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:/Journal")
import htmlview
import json

md = json.load(open(r"D:/Journal/_scratch/map_data_v2.json", encoding="utf-8"))
shapes = htmlview._map_shapes()
svg = htmlview.render_map_svg(md, shapes)

# 1. check Chinese text in SVG: matplotlib default fonttype? text as paths?
print("SVG len:", len(svg))
print("石狩 in svg:", "石狩" in svg)
# matplotlib converts text to paths by default (fonttype=3) — check
print("has <text tag:", "<text" in svg)
print("has <use xlink:", "xlink:href" in svg or "use " in svg)
# find the hub label context
i = svg.find("石狩")
if i >= 0:
    print("ctx:", repr(svg[max(0, i - 200):i + 100]))
