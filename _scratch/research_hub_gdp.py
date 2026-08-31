# -*- coding: utf-8 -*-
"""Research: per-state GDP proxy + hub names + culture/religion per state."""
import json
import os
import re
import sys

sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
state_ids = (country or {}).get("states") or []
print("player cid:", cid, "states:", len(state_ids))

# 1. per-state GDP proxy: state_building_budget / income? look at a state obj
sid0 = state_ids[0]
sobj = ctx.state_object(sid0)
print("\nstate obj keys:", sorted(sobj.keys())[:60])
print("\nstate_building_budget:", json.dumps(sobj.get("state_building_budget"),
      ensure_ascii=False)[:300])
print("pop_statistics:", json.dumps(sobj.get("pop_statistics"),
      ensure_ascii=False)[:300])
print("total_wealth:", sobj.get("total_wealth"))

# 2. hub names
hubs = js._hub_names(sobj)
print("\nhub names for state", sid0, ":", hubs)

# 3. per-state culture/religion from pops
pops = ctx.pops_by_state(state_ids)
print("\npops by state:", {k: len(v) for k, v in pops.items()})
sid1 = state_ids[0]
p0 = pops.get(sid1, [])[:3]
for p in p0:
    print("  pop sample:", p.get("type"), "culture:", p.get("culture"),
          "religion:", p.get("religion"), "wf:", p.get("workforce"),
          "dep:", p.get("dependents"))
