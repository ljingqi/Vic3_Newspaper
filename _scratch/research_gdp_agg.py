# -*- coding: utf-8 -*-
"""Verify: per-state GDP proxy (building income) + culture/religion aggregate."""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
state_ids = (country or {}).get("states") or []

# GDP proxy: sum of building incomes per state
by_state, btype_map, objs = ctx.buildings_index(state_ids)
print("buildings indexed:", len(objs))

gdp_by_state = {}
for sid in state_ids:
    inc = 0.0
    for bid in by_state.get(sid, []):
        o = objs.get(bid, {})
        v = o.get("profit_after_reserves")
        if isinstance(v, (int, float)):
            inc += v
    gdp_by_state[sid] = inc
total = sum(gdp_by_state.values())
print("\nstate profit-based 'GDP' proxy (profit_after_reserves):")
for sid in sorted(state_ids, key=lambda s: -gdp_by_state[s]):
    name = ctx.state_zh(sid)
    print(f"  {name}: {gdp_by_state[sid]:.0f} ({gdp_by_state[sid]/total*100:.1f}%)")

# alt: state_building_budget.income
print("\nstate_building_budget.income:")
for sid in state_ids[:5]:
    o = ctx.state_object(sid)
    sbb = o.get("state_building_budget") or {}
    print(f"  {ctx.state_zh(sid)}: income={sbb.get('income')}")

# culture/religion aggregate per state
pops = ctx.pops_by_state(state_ids)
sid = state_ids[0]
cult = Counter()
rel = Counter()
for p in pops[sid]:
    wf = p.get("workforce") or 0
    dep = p.get("dependents") or 0
    n = wf + dep
    if p.get("culture") is not None:
        cult[p["culture"]] += n
    if p.get("religion") is not None:
        rel[p["religion"]] += n
print(f"\nstate {ctx.state_zh(sid)} culture ids:", dict(cult.most_common(3)))
print("  religion ids:", dict(rel.most_common(3)))
print("  culture zh:", {js.culture_id_to_name(k): v for k, v in cult.most_common(3)})
