#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实存档验证: 构建电影 7 槽数据, 检查:
1. 主角与各配角 pop_key 两两不同 (无同 POP 选角);
2. 提示词槽位渲染无裸数值 (生活水平裸数 / 月收入裸数);
3. 同年重建可复现 (种子确定性)。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal
import journal_save as js
import movie

cfg = journal.load_config()
V3 = sys.argv[1] if len(sys.argv) > 1 else (
    "C:/Users/CHINE/Documents/Paradox Interactive/Victoria 3/save games/卢卡_1850_04_12.v3")
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "movie_verify")

melt_path, err = js.melt_with_rakaly(V3, force=True)
if err:
    print("熔化失败:", err)
    sys.exit(1)
with open(melt_path, "rb") as fp:
    melted = fp.read()
ctx = js.SaveContext(melted)
snap = js.extract_full_snapshot(melted, ctx=ctx, journal_dir=cfg["journal_dir"])
year = snap.get("year")
player = snap.get("player")
print(f"快照: {player} {year}年, 州数={len(snap.get('states') or [])}")

os.makedirs(SCRATCH, exist_ok=True)
data = js.build_magazine_data(melted, snap, SCRATCH, year, ctx=ctx,
                              pool_override=None, pool_size=3)
m = data.get("movie") or {}
if m.get("error"):
    print("movie 数据错误:", m["error"])
    sys.exit(1)

print("剧种:", m.get("term"), "| 体裁:", [g.get("zh") for g in (m.get("genre") or [])])
prot = m.get("protagonist") or {}
ants = m.get("antagonist") or {}
sups = m.get("supporting") or []
print("主角:", {k: prot.get(k) for k in ("role", "source", "state", "sol", "literacy", "pop_id", "pop_key")})
print("反派:", {k: ants.get(k) for k in ("role", "source", "name")})
for i, c in enumerate(sups, 1):
    print(f"配角{i}:", {k: c.get(k) for k in ("role", "source", "state", "sol", "pop_id", "pop_key")})

fails = []


def check(name, cond, detail=""):
    print(("  [OK] " if cond else "  [FAIL] ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# 1. pop_key 互斥
keys = [prot.get("pop_key")] + [c.get("pop_key") for c in sups]
keys = [k for k in keys if k is not None]
check("主角与配角 pop_key 两两不同", len(keys) == len(set(keys)), f"keys={keys}")
check("配角内 pop_id 不重复",
      len([c.get("pop_id") for c in sups]) == len({c.get("pop_id") for c in sups}),
      f"pids={[c.get('pop_id') for c in sups]}")
roles = [prot.get("role")] + [c.get("role") for c in sups]
check("主角与配角职业不重复", len(roles) == len(set(roles)), f"roles={roles}")

# 2. 渲染无裸数值
render_data = {"currency": snap.get("currency") or journal.DEFAULT_CURRENCY,
               "exchange_rates": (data.get("exchange_rates")
                                  or snap.get("exchange_rates") or {})}
block = movie._slots_block(m, data=render_data)
print("---- 渲染块 ----")
print(block)
print("----------------")
bad_sol = re.findall(r"生活水平\d", block)
bad_inc = re.findall(r"月收入\d", block)
check("槽位渲染无裸生活水平数值", not bad_sol, f"found={bad_sol}")
check("槽位渲染无裸月收入数值", not bad_inc, f"found={bad_inc}")
check("槽位渲染含生活水平档名", "生活水平" in block)

# 3. 同年可复现 (重建一次对比选角)
data2 = js.build_magazine_data(melted, snap, SCRATCH, year, ctx=ctx,
                               pool_override=None, pool_size=3)
m2 = data2.get("movie") or {}
same_cast = ((prot or {}).get("pop_id") == (m2.get("protagonist") or {}).get("pop_id")
             and [(c.get("pop_id") or c.get("name")) for c in sups]
             == [(c.get("pop_id") or c.get("name")) for c in (m2.get("supporting") or [])])
check("同年重建选角可复现", same_cast)

print()
if fails:
    print("存在失败项:", fails)
    sys.exit(1)
print("真实存档验证全部通过")
