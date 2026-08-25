# -*- coding: utf-8 -*-
"""临时检查: 打印若干 pop 的完整 weekly_budget 数组, 观察槽位形态。"""
import os
import sys
import re
import json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal_save as js

MELT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "melt.json")
with open(MELT, "rb") as f:
    melted = f.read()

# 长度分布
lens = Counter()
examples = []
pop_db = melted.find(b'"pops"')
db = melted.find(b'"database"', pop_db)
ob = melted.find(b'{', db)
j = ob
while True:
    i = melted.find(b'":{', j)
    if i < 0:
        break
    ob2 = melted.find(b'{', i)
    head = melted[ob2:min(ob2 + 600, len(melted))]
    m_loc = re.search(rb'"location":(\d+)', head)
    if not m_loc:
        j = melted.find(b'}', ob2) + 1
        continue
    raw, end = js.extract_json_object(melted, ob2)
    if not raw:
        break
    try:
        p = json.loads(raw)
    except Exception:
        j = end
        continue
    if isinstance(p, dict) and "workforce" in p:
        wb = p.get("weekly_budget") or []
        lens[len(wb)] += 1
        if len(examples) < 10 and len(wb) >= 13:
            examples.append((p.get("type"), p.get("workforce"), p.get("dependents"),
                             wb))
    j = end

print("weekly_budget length distribution:", dict(lens))
for e in examples:
    print("type=%s wf=%s dep=%s" % (e[0], e[1], e[2]))
    print("  wb =", [round(x, 3) if isinstance(x, (int, float)) else x for x in e[3]])
