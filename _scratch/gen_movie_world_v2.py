#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界时局电影 v2: 用最新熔化存档 (德川幕府 1838), 从受承认列强中随机抽 5 国,
每个国家走标准管线 (extract_full_snapshot(cid=该国) + build_magazine_data),
卡司一律来自该国真实 POP (家庭访谈 + 街坊/邻里/乡绅/同乡样本池, pop_key 互斥),
与玩家国电影同一机制, 不读取统治者, 不把国家当角色。

用法:
  python gen_movie_world_v2.py --dry          # 只构建数据并打印卡司, 不调 LLM
  python gen_movie_world_v2.py [--seed N]     # 正式生成 5 部剧本
输出: output/<会话>/电影剧本/<年>世界时局/电影剧本_<年>_<国名>.md
"""
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal
import journal_save as js
import movie

DRY = "--dry" in sys.argv
SEED = None
if "--seed" in sys.argv:
    SEED = int(sys.argv[sys.argv.index("--seed") + 1])

cfg = journal.load_config()
with open(js.MELT_CACHE, "rb") as f:
    melted = f.read()
ctx = js.SaveContext(melted)

SNAP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "snap_latest.json")
with open(SNAP_JSON, encoding="utf-8") as f:
    snap = json.load(f)
YEAR = snap.get("year") or 1838
player = snap.get("player")
powers = [p for p in (snap.get("powers") or []) if isinstance(p, dict)]
cands = [p for p in powers
         if p.get("definition") and not (p.get("is_player")
                                         or p.get("name") == player)]
rnd = random.Random(SEED) if SEED is not None else random
order = cands[:]
rnd.shuffle(order)
print(f"候选列强: {[p.get('name') for p in cands]}")
print(f"随机顺序: {[p.get('name') for p in order]}")

folder = journal.determine_folder(player, cfg["journal_dir"])
OUT_DIR = os.path.join(cfg["journal_dir"], folder, "电影剧本",
                       f"{YEAR}世界时局")
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_test")


def _build_country(p):
    name, tag = p.get("name"), p.get("definition")
    obj, cid = js._find_country_by_definition(melted, tag)
    if not obj:
        print(f"[skip] {name}: 找不到国家对象")
        return None
    print(f"== {name} (cid={cid}) 提取快照 + 杂志数据 ...")
    snapC = js.extract_full_snapshot(melted, cid=cid, ctx=ctx)
    scratch_dir = os.path.join(SCRATCH, tag)
    os.makedirs(scratch_dir, exist_ok=True)
    dataC = js.build_magazine_data(melted, snapC, scratch_dir,
                                   snapC.get("year") or YEAR, ctx=ctx)
    m = dataC.get("movie") or {}
    if m.get("error"):
        print(f"[skip] {name}: movie 数据错误 {m['error']}")
        return None
    keys = [(m.get("protagonist") or {}).get("pop_key")]
    keys += [c.get("pop_key") for c in (m.get("supporting") or [])]
    keys = [k for k in keys if k is not None]
    if len(keys) != len(set(keys)):
        print(f"[skip] {name}: 卡司 pop_key 重复 {keys}")
        return None
    return (p, snapC, m)


built = []
for p in order:
    r = _build_country(p)
    if r:
        built.append(r)
        prot = (r[2].get("protagonist") or {})
        print(f"  主角: {prot.get('name')}（{prot.get('role')}）"
              f" 来源={prot.get('source')} pop_key={prot.get('pop_key')}")
        for i, c in enumerate((r[2].get("supporting") or [])[:2], 1):
            print(f"  配角{i}: {c.get('name')}（{c.get('role')}）"
                  f" 来源={c.get('source')} pop_key={c.get('pop_key')}")
        print(f"  反派: {(r[2].get('antagonist') or {}).get('name')}"
              f"（{(r[2].get('antagonist') or {}).get('role')}）")
    if len(built) >= 5:
        break

if len(built) < 5:
    print(f"只有 {len(built)} 国数据可用, 不足 5 部")
    sys.exit(1)

if DRY:
    for p, snapC, m in built:
        print("\n----", p.get("name"), "----")
        print(movie._slots_block(m, data={"currency": snapC.get("currency")}))
    print("\nDRY 模式结束, 未调用 LLM")
    sys.exit(0)

os.makedirs(OUT_DIR, exist_ok=True)
for p, snapC, m in built:
    name = p.get("name")
    try:
        data = {"player": name, "year": YEAR,
                "capital": snapC.get("capital") or name,
                "currency": snapC.get("currency"),
                "output_dir": folder,
                "date": snapC.get("date") or f"{YEAR}.1.1"}
        title = movie._generate_title(m, data, cfg)
        m["title"] = title
        acts = movie._generate_full(m, data, cfg, title)
        m["acts"] = acts
        movie._check_names(m, acts)
        text = movie._assemble(m, data, title, acts)
        header = (f"<!-- 数据来源: 维多利亚3 报纸Mod 电影剧本(世界时局) | "
                  f"报告日期: {data.get('date')} | 生成时间: "
                  f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
        path = os.path.join(OUT_DIR, f"电影剧本_{YEAR}_{name}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + text.rstrip() + "\n")
        print(f"[OK] 已生成: {path}  《{title}》")
    except Exception as e:
        print(f"[FAIL] {name} 生成失败: {e}")
print("完成")
