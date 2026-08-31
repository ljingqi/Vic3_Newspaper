#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单国验证: 用 extract_full_snapshot(cid=外国) + build_magazine_data 构建电影数据,
确认卡司来自该国 POP (家庭访谈+样本池), 非统治者/国家。"""
import os
import sys

sys.path.insert(0, r"D:\Journal")
import journal
import journal_save as js
import movie

cfg = journal.load_config()
with open(js.MELT_CACHE, "rb") as f:
    melted = f.read()
ctx = js.SaveContext(melted)

TAG = sys.argv[1] if len(sys.argv) > 1 else "GBR"
obj, cid = js._find_country_by_definition(melted, TAG)
if not obj:
    print("找不到国家:", TAG)
    sys.exit(1)
print("国家:", obj.get("definition"), "cid:", cid)
snap = js.extract_full_snapshot(melted, cid=cid, ctx=ctx)
print("player:", snap.get("player"), "| year:", snap.get("year"),
      "| capital:", snap.get("capital"), "| govt:", snap.get("govt_zh"),
      "| 州数:", len(snap.get("states") or []))
scratch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_test", TAG)
os.makedirs(scratch, exist_ok=True)
data = js.build_magazine_data(melted, snap, scratch, snap.get("year"), ctx=ctx)
m = data.get("movie") or {}
if m.get("error"):
    print("movie 数据错误:", m["error"])
    sys.exit(1)
print("剧种:", m.get("term"), "| 体裁:", [g.get("zh") for g in (m.get("genre") or [])],
      "| 结局:", (m.get("finale") or {}).get("zh"))
prot = m.get("protagonist") or {}
ants = m.get("antagonist") or {}
sups = m.get("supporting") or []
print("主角:", {k: prot.get(k) for k in ("name", "role", "source", "state", "culture",
                                         "sol", "literacy", "income", "pop_key")})
print("反派:", {k: ants.get(k) for k in ("name", "role", "source")})
for i, c in enumerate(sups, 1):
    print(f"配角{i}:", {k: c.get(k) for k in ("name", "role", "source", "state",
                                              "culture", "sol", "pop_key")})
print("主题:", [t.get("facts") for t in (m.get("themes") or [])])
print()
print(movie._slots_block(m, data={"currency": snap.get("currency")}))
