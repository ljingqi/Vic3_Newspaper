# -*- coding: utf-8 -*-
"""Test P1: extract map data for 大清 from melt.json (mirrors snapshot flow)."""
import json
import os
import sys

REPO = r"D:/Journal"
sys.path.insert(0, REPO)
import journal_save as js

with open(os.path.join(REPO, "tools", "melt.json"), "rb") as f:
    data = f.read()

ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
print("player:", tag, cid)
state_ids = (country or {}).get("states") or []
snap = js.snapshot_from_country(country, meta)
snap["states"] = ctx.player_states(state_ids)
snap["capital_region_key"] = ctx.state_region_key((country or {}).get("capital"))
snap["player"] = tag
names = js.load_current_country_names(data, index=ctx.index()[0])
index, gp_ids, dp_index = ctx.index()

m = js._extract_map_data(data, snap, ctx, cid, state_ids, names=names,
                         index=index)
print("map data keys:", list(m.keys()) if m else None)
if m:
    print("main:", len(m["main"]), "overseas:", len(m["overseas"]))
    if m["overseas"]:
        print("  overseas:", m["overseas"][:8])
    print("colors used:", len(set(m["colors"].values())), "of",
          len(js.MAP_PALETTE))
    print("capital_region:", m["capital_region"])
    print("foreign capitals:", len(m["foreign_capitals"]))
    for fc in m["foreign_capitals"][:8]:
        print("  ", fc["tag"], fc["name"], fc["region"], fc["color"])
    print("railways:", len(m["railways"]), "rail_links:", len(m["rail_links"]))
    out = os.path.join(REPO, "_scratch", "map_test.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    print("saved:", out)
