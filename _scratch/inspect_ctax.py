# -*- coding: utf-8 -*-
"""临时检查脚本: 验证存档中 weekly_budget 第10槽(消费税)的真实取值, 以及
墨西哥的税收法律, 判断「未开征消费税却出现消费税支出」是数据口径问题还是
槽位解读错误。"""
import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal_save as js

MELT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "melt.json")

with open(MELT, "rb") as f:
    melted = f.read()

print("melt bytes:", len(melted))

# 1. 玩家国家与法律
country, meta, tag, cid = js.find_player_country(melted)
print("player:", tag, "cid:", cid, "name:", country.get("name") if country else None)

laws = js.query_laws(melted, cid) or []
print("laws count:", len(laws))
for l in laws:
    print("  law:", l)

# 2. 直接跑完整快照, 检查家庭采访的收支 (含消费税)
print("extracting full snapshot...")
snap = js.extract_full_snapshot(melted)
fi = snap.get("family_interview") or {}
print("family_interview keys:", sorted(fi.keys()))
br = fi.get("budget_rates") or {}
print("budget_rates:", br)
print("workplace_pms_zh:", fi.get("workplace_pms_zh"))
print("region:", fi.get("region_name"), "| hub:", fi.get("hub_name"))

# 3. 抽样 pop 的 weekly_budget
ctx = js.SaveContext(melted)
state_ids = sorted(s.get("id") for s in (snap.get("states") or []) if s.get("id") is not None)
print("player state ids:", state_ids)
pops = ctx.player_pops(state_ids)  # 全部玩家州
print("total player pops:", len(pops))

n10 = 0
n_nonzero = 0
tot10 = 0.0
samples = []
for pid, p in list(pops.items()):
    wb = p.get("weekly_budget") or []
    if len(wb) > 10 and isinstance(wb[10], (int, float)):
        n10 += 1
        if wb[10] != 0:
            n_nonzero += 1
            tot10 += wb[10]
            if len(samples) < 8:
                samples.append((pid, p.get("type"), p.get("culture"),
                                p.get("workforce"), p.get("dependents"),
                                round(float(wb[10]), 4), wb))
print(f"pops with wb[10] readable: {n10}; nonzero: {n_nonzero}; total: {tot10:.2f}")
for s in samples:
    print("  sample:", s[:6])

# 3. 收入/支出各槽位均值(按有值的pop)
from collections import Counter
slot_stats = Counter()
slot_sum = {}
for pid, p in pops.items():
    wb = p.get("weekly_budget") or []
    for i, v in enumerate(wb):
        if isinstance(v, (int, float)) and v:
            slot_stats[i] += 1
            slot_sum[i] = slot_sum.get(i, 0.0) + float(v)
print("slot usage stats (idx: count, sum):")
for i in sorted(slot_stats):
    print(f"  slot {i}: count={slot_stats[i]}, sum={slot_sum[i]:.2f}")
