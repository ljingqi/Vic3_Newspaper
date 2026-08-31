#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""熔化最新存档并读取玩家/日期/列强。"""
import re
import sys

sys.path.insert(0, r"D:\Journal")
import journal_save as js

V3 = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:/Users/CHINE/Documents/Paradox Interactive/Victoria 3/save games/autosave.v3")
path, err = js.melt_with_rakaly(V3, force=True)
print("melt result:", path, err)
if err:
    sys.exit(1)
with open(path, "rb") as f:
    melted = f.read()
player = js._first_player_name(melted)
m = re.search(rb'"game_date":"([0-9.]+)"', melted[:600000])
print("player:", player, "| game_date:", m.group(1).decode() if m else None)
try:
    country, meta, tag, cid = js.find_player_country(melted)
    print("country_id:", cid, "| tag:", tag,
          "| govt:", (country or {}).get("type"),
          "| definition:", (country or {}).get("definition"))
except Exception as e:
    print("find_player_country failed:", e)
