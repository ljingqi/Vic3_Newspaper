# -*- coding: utf-8 -*-
"""Full-chain test: htmlview render with new GeoJSON + journal_save extract."""
import json
import os
import sys

REPO = r"D:/Journal"
sys.path.insert(0, REPO)
import htmlview

# 1. shapes load (new format)
shapes = htmlview._map_shapes()
print("shapes loaded:", bool(shapes))
if shapes:
    print("  states:", len(shapes["shapes"]), "points:", len(shapes["points"]))
    print("  width x height:", shapes["width"], "x", shapes["height"])

# 2. render with existing map test data
md = json.load(open(os.path.join(REPO, "_scratch", "map_test.json"),
                    encoding="utf-8"))
svg = htmlview.render_map_svg(md, shapes)
print("SVG render:", "OK" if svg else "FAILED", "%.1f KB" % (len(svg) / 1024) if svg else "")
if svg:
    open(os.path.join(REPO, "_scratch", "map_v3.svg"), "w",
         encoding="utf-8").write(svg)

png = htmlview.render_map_svg(md, shapes, fmt="png")
if png:
    open(os.path.join(REPO, "_scratch", "map_v3.png"), "wb").write(png)
    from PIL import Image
    im = Image.open(os.path.join(REPO, "_scratch", "map_v3.png"))
    print("PNG:", im.size, len(png), "bytes")

# 3. journal_save extraction path (needs melt)
import journal_save as js
with open(os.path.join(REPO, "tools", "melt.json"), "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
state_ids = (country or {}).get("states") or []
snap = js.snapshot_from_country(country, meta)
snap["states"] = ctx.player_states(state_ids)
snap["capital_region_key"] = ctx.state_region_key((country or {}).get("capital"))
names = js.load_current_country_names(data, index=ctx.index()[0])
index, gp_ids, dp_index = ctx.index()
m = js._extract_map_data(data, snap, ctx, cid, state_ids, names=names, index=index)
if m:
    print("\nextract OK: main", len(m["main"]), "overseas", len(m["overseas"]),
          "foreign", len(m["foreign_capitals"]),
          "rail_links", len(m["rail_links"]))
else:
    print("\nextract FAILED")
