# -*- coding: utf-8 -*-
"""Verify pop culture/religion field types for the detail extraction."""
import sys
sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()
ctx = js.SaveContext(data)
country, meta, tag, cid = js.find_player_country(data)
state_ids = (country or {}).get("states") or []
pops = ctx.pops_by_state(state_ids)
sid = state_ids[0]
for p in pops[sid][:6]:
    print("culture:", repr(p.get("culture")), type(p.get("culture")).__name__,
          "| religion:", repr(p.get("religion")), type(p.get("religion")).__name__)
# test _religion_zh
print("\n_religion_zh('mahayana'):", js._religion_zh("mahayana"))
print("culture_id_to_key(116):", js.culture_id_to_key(116))
