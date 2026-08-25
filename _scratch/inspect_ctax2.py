# -*- coding: utf-8 -*-
"""临时检查: 按国家税收法律对比 weekly_budget 槽位 9/10/11/12 总量。"""
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

# 扫描全部州, 按属主聚合各槽位总量与有值 pop 数
by_owner = {}
sob, so_end = js._states_db_bounds(melted)
pat = re.compile(rb'"(\d+)":\{')
j = sob
n = 0
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
            owner = o["country"]
            pops = o.get("pops") or {}
            if isinstance(pops, dict):
                acc = by_owner.setdefault(owner, {9: 0.0, 10: 0.0, 11: 0.0, 12: 0.0,
                                                  "c9": 0, "c10": 0, "c11": 0, "c12": 0})
                for pid, p in pops.items():
                    if not isinstance(p, dict):
                        continue
                    wb = p.get("weekly_budget") or []
                    for sl in (9, 10, 11, 12):
                        if sl < len(wb) and isinstance(wb[sl], (int, float)) and wb[sl]:
                            acc[sl] += wb[sl]
                            acc["c%d" % sl] += 1
        n += 1
    j = nxt
print("states scanned:", n)

# 汇总每种税收法律
summary = {}
for owner, acc in by_owner.items():
    laws = laws_by_cid.get(owner) or []
    tl = next((l for l in laws if l in target_laws), None) or "no_tax_law"
    s = summary.setdefault(tl, {"n": 0, 9: 0.0, 10: 0.0, 11: 0.0, 12: 0.0,
                                "c9": 0, "c10": 0, "c11": 0, "c12": 0})
    s["n"] += 1
    for k in (9, 10, 11, 12):
        s[k] += acc[k]
        s["c%d" % k] += acc["c%d" % k]

for tl, s in sorted(summary.items(), key=lambda kv: -kv[1][10]):
    print(f"{tl}: countries={s['n']} slot9={s[9]:.0f}({s['c9']}) slot10={s[10]:.0f}({s['c10']}) "
          f"slot11={s[11]:.0f}({s['c11']}) slot12={s[12]:.0f}({s['c12']})")
