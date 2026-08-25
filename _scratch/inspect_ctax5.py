# -*- coding: utf-8 -*-
"""临时检查: 打印不同税收法律国家的典型 pop 全槽位, 校准槽位含义。"""
import os
import sys
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal_save as js

MELT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "melt.json")
with open(MELT, "rb") as f:
    melted = f.read()

laws_by_cid = js._pool_all_laws(melted)
target_laws = ["law_consumption_based_taxation", "law_per_capita_based_taxation",
               "law_income_based_taxation", "law_land_based_taxation",
               "law_proportional_taxation", "law_graduated_taxation"]
countries, _ = js._pool_country_objects(melted)

# 找 各法律 下的代表国家: proportional / consumption / land / per-capita
picks = {}
for cid, cobj in countries.items():
    laws = laws_by_cid.get(cid) or []
    tl = next((l for l in laws if l in target_laws), None)
    if tl and tl not in picks:
        picks[tl] = cid
print("picked:", picks)

state_owner = {}
sob, so_end = js._states_db_bounds(melted)
pat = re.compile(rb'"(\d+)":\{')
j = sob
while j < so_end:
    m2 = pat.search(melted, j, so_end - 1)
    if not m2:
        break
    ob3 = m2.start() + len(m2.group(0)) - 1
    raw2, nxt = js.extract_json_object(melted, ob3)
    if raw2:
        try:
            o = json.loads(raw2)
        except Exception:
            o = None
        if isinstance(o, dict) and o.get("region") and o.get("country"):
            state_owner[int(m2.group(1))] = o["country"]
    j = nxt

# 收集每个目标国家的一个有工资的 pop
shown = {}
pop_db = melted.find(b'"pops"')
db = melted.find(b'"database"', pop_db)
ob = melted.find(b'{', db)
j2 = ob
while True:
    i = melted.find(b'":{', j2)
    if i < 0:
        break
    ob2 = melted.find(b'{', i)
    head = melted[ob2:min(ob2 + 600, len(melted))]
    m_loc = re.search(rb'"location":(\d+)', head)
    if not m_loc:
        j2 = melted.find(b'}', ob2) + 1
        continue
    owner = state_owner.get(int(m_loc.group(1)))
    raw, end = js.extract_json_object(melted, ob2)
    if not raw:
        break
    try:
        p = json.loads(raw)
    except Exception:
        j2 = end
        continue
    if isinstance(p, dict) and "workforce" in p and (p.get("workforce") or 0) > 100:
        if owner in picks.values() and owner not in shown and any(
                isinstance(x, (int, float)) and x > 0 for x in (p.get("weekly_budget") or [])[:7]):
            shown[owner] = p
    j2 = end

idx = js._build_indexes(melted)
names = js.build_country_id_names(melted, idx[0] if isinstance(idx, tuple) else idx)
for cid, p in shown.items():
    cobj = countries.get(cid) or {}
    laws = laws_by_cid.get(cid) or []
    tl = next((l for l in laws if l in target_laws), None)
    tg = cobj.get("taxed_goods") or []
    print(f"--- {names.get(cid)} (cid={cid}) law={tl} tax_level={cobj.get('tax_level')} taxed_goods={tg[:6]}")
    wb = p.get("weekly_budget") or []
    print("  wb =", [round(x, 3) if isinstance(x, (int, float)) else x for x in wb])
    print("  workforce:", p.get("workforce"), "dependents:", p.get("dependents"),
          "type:", p.get("type"))
