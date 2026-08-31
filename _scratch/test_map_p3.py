# -*- coding: utf-8 -*-
"""Test P3: render map SVG from previously extracted map data."""
import json
import os
import sys

REPO = r"D:/Journal"
sys.path.insert(0, REPO)
import htmlview

md = json.load(open(os.path.join(REPO, "_scratch", "map_test.json"),
                    encoding="utf-8"))
shapes = htmlview._map_shapes()
print("shapes loaded:", bool(shapes), "states:", len(shapes.get("shapes", {})))

svg = htmlview.render_map_svg(md, shapes)
if svg:
    out = os.path.join(REPO, "_scratch", "map_demo.svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print("SVG written:", out, "%.1f KB" % (len(svg) / 1024))
    print("has title:", "疆域图" in svg, "| has legend:", "本国省份" in svg,
          "| has rail:", "铁路" in svg)
else:
    print("render failed")
