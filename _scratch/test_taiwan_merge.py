# -*- coding: utf-8 -*-
"""Verify near-sea merge with 大清-like data: Formosa should join main."""
import json
import os
import sys

sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)

# 大清 1853 raw data has states incl. FORMOSA — check region keys exist
raw = json.load(open(r"D:/Journal/output/大清/data/raw_1853.json",
                     encoding="utf-8"))
print("大清 states count:", len(raw["states"]))
# map state ids to regions via ctx
id2rk = {}
for sid in [s["id"] for s in raw["states"]]:
    rk = ctx.state_region_key(sid)
    if rk:
        id2rk[sid] = rk
rk_names = {v: k for k, v in id2rk.items()}
print("regions:", sorted(rk_names)[:8], "...")
print("FORMOSA in raw states:", "STATE_FORMOSA" in rk_names.values())
print("BEIJING:", "STATE_BEIJING" in rk_names.values())

# simulate: use 大清 state ids with this melt's ctx (regions only, pop lookup
# will be off but connectivity/points logic is what we test)
qids = [s["id"] for s in raw["states"]]
snap = {"capital_region_key": "STATE_BEIJING", "year": 1853,
        "player": "大清"}
names = js.load_current_country_names(data, index=ctx.index()[0])
index, gp_ids, dp_index = ctx.index()

# 只测连通+近海合并 (pops 会因存档不同对不上, 但 main/overseas 只靠几何)
m = js._extract_map_data(data, snap, ctx, 17, qids, names=names, index=index)
if m:
    print("\nmain:", len(m["main"]), "overseas:", len(m["overseas"]))
    if m["overseas"]:
        print("  overseas:", m["overseas"])
    print("FORMOSA in main:", "STATE_FORMOSA" in m["main"])
else:
    print("extract failed")
