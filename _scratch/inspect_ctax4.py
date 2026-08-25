# -*- coding: utf-8 -*-
"""临时检查: 按税收法律+taxed_goods+税级 对比槽位 9/10/11/12 的均摊值。"""
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

# 每国: 税收法律, tax_level, taxed_goods, 劳动力总数, 槽位总额
info = {}
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
    if owner is None:
        j2 = melted.find(b'}', ob2) + 1
        continue
    raw, end = js.extract_json_object(melted, ob2)
    if not raw:
        break
    try:
        p = json.loads(raw)
    except Exception:
        j2 = end
        continue
    if isinstance(p, dict) and "workforce" in p:
        a = info.setdefault(owner, {"wf": 0, 9: 0.0, 10: 0.0, 11: 0.0, 12: 0.0})
        a["wf"] += p.get("workforce") or 0
        wb = p.get("weekly_budget") or []
        for sl in (9, 10, 11, 12):
            if sl < len(wb) and isinstance(wb[sl], (int, float)) and wb[sl]:
                a[sl] += wb[sl]
    j2 = end

# 汇总输出: 每组列出几个典型国家
rows = []
for cid, cobj in countries.items():
    laws = laws_by_cid.get(cid) or []
    tl = next((l for l in laws if l in target_laws), None)
    if not tl or cid not in info:
        continue
    tg = cobj.get("taxed_goods") or []
    lvl = cobj.get("tax_level")
    a = info[cid]
    wf = a["wf"] or 1
    rows.append((tl, str(lvl), tuple(sorted(tg))[:3], cid,
                 round(a[9] / wf * 1000, 3), round(a[10] / wf * 1000, 3),
                 round(a[11] / wf * 1000, 3), round(a[12] / wf * 1000, 3)))

# 按 (法律, 税级, taxed_goods) 分组求均值
from collections import defaultdict
grp = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
for tl, lvl, tg, cid, s9, s10, s11, s12 in rows:
    key = (tl, lvl, "taxed" if tg else "notax")
    g = grp[key]
    g[0] += 1
    g[1] += s9; g[2] += s10; g[3] += s11; g[4] += s12

print(f"{'law':42s} {'lvl':9s} {'taxed':6s} {'n':>3s} {'s9':>9s} {'s10':>9s} {'s11':>9s} {'s12':>9s}")
for key in sorted(grp):
    n, s9, s10, s11, s12 = grp[key]
    if n == 0:
        continue
    print(f"{key[0]:42s} {key[1]:9s} {key[2]:6s} {n:3d} {s9/n:9.3f} {s10/n:9.3f} {s11/n:9.3f} {s12/n:9.3f}")
