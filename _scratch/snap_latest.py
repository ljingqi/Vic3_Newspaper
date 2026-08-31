#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取最新熔化存档的完整快照 (玩家=德川幕府 1838), 存到 _scratch 供世界时局电影用。"""
import json
import os
import sys

sys.path.insert(0, r"D:\Journal")
import journal
import journal_save as js

cfg = journal.load_config()
path = os.path.join(os.path.dirname(js.__file__) or ".", "tools", "melt.json")
with open(js.MELT_CACHE, "rb") as f:
    melted = f.read()
ctx = js.SaveContext(melted)
snap = js.extract_full_snapshot(melted, ctx=ctx, journal_dir=cfg["journal_dir"])
print("player:", snap.get("player"), "| year:", snap.get("year"),
      "| date:", snap.get("date"))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snap_latest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(snap, f, ensure_ascii=False, indent=1)
print("powers:", [(p.get("name"), p.get("definition"), p.get("war")) for p in (snap.get("powers") or [])])
print("saved:", out)
