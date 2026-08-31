# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:/Journal")
import htmlview
import json

md = json.load(open(r"D:/Journal/_scratch/map_data_v2.json", encoding="utf-8"))
shapes = htmlview._map_shapes()
svg = htmlview.render_map_svg(md, shapes)
print("SVG text-mode Chinese:", "<text" in svg and "石狩" in svg)
print("gid STATE_ count:", svg.count('id="STATE_'))
print("legend 本国省份:", "本国省份" in svg)
print("title 疆域图:", "疆域图" in svg)
open(r"D:/Journal/_scratch/map_v7.svg", "w", encoding="utf-8").write(svg)
png = htmlview.render_map_svg(md, shapes, fmt="png")
open(r"D:/Journal/_scratch/map_v7.png", "wb").write(png)
print("final PNG:", len(png), "bytes")
