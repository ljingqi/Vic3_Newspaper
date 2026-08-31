# -*- coding: utf-8 -*-
"""Test new map data extraction: near-sea merge + hub + gdp + culture/rel."""
import json
import os
import sys

sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
state_ids = (country or {}).get("states") or []
snap = js.snapshot_from_country(country, meta)
snap["states"] = ctx.player_states(state_ids)
snap["capital_region_key"] = ctx.state_region_key((country or {}).get("capital"))
names = js.load_current_country_names(data, index=ctx.index()[0])
index, gp_ids, dp_index = ctx.index()
m = js._extract_map_data(data, snap, ctx, cid, state_ids, names=names,
                         index=index)
print("main:", len(m["main"]), "overseas:", len(m["overseas"]))
if m["overseas"]:
    print("  overseas:", m["overseas"])
print("states detail keys:", list(m["states"].keys())[:5])
for rk in list(m["states"])[:3]:
    d = m["states"][rk]
    print(f"  {d['name']}: hub={d['hub']} gdp={d['gdp']} "
          f"({d['gdp_pct']}%) cult={d['culture'][:2]} rel={d['religion'][:2]}")
out = os.path.join(r"D:/Journal/_scratch", "map_data_v2.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False, indent=1)
print("saved:", out)
