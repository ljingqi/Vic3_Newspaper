# -*- coding: utf-8 -*-
"""Find sea-named states NOT marked as water (missed by default.map colors).
These get rendered beige. Check why their colors are not in sea_starts."""
import json
import os
import re

GAME = "F:/Game/steamapps/common/Victoria 3"
BASE = os.path.join(GAME, "game", "map_data")

dm = open(os.path.join(BASE, "default.map"), encoding="utf-8",
          errors="replace").read()
sea_colors = set(re.findall(r"x([0-9A-Fa-f]{6})",
                            re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1)))
lake_colors = set(re.findall(r"x([0-9A-Fa-f]{6})",
                             re.search(r"lakes\s*=\s*\{([^}]*)\}", dm).group(1)))
water = sea_colors | lake_colors

geo = json.load(open(r"D:/Journal/state_geojson.json", encoding="utf-8"))
kept_ids = {f["id"] for f in geo["features"]}

# region colors from state_regions
sr = os.path.join(BASE, "state_regions")
region_cols = {}
for fn in os.listdir(sr):
    if not fn.endswith(".txt"):
        continue
    txt = open(os.path.join(sr, fn), encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"([A-Z0-9_]+)\s*=\s*\{", txt):
        name = m.group(1)
        if not name.startswith("STATE_"):
            continue
        start = m.end() - 1
        depth = 1
        i = start + 1
        while depth and i < len(txt):
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
            i += 1
        block = txt[start:i]
        region_cols[name] = [p.upper() for p in re.findall(r"x([0-9A-Fa-f]{6})", block)]

print("sea/lake named states that are KEPT (rendered as land):")
hits = 0
for name in sorted(region_cols):
    if not re.search(r"(SEA|OCEAN|STRAIT|GULF|BAY|COAST|CHANNEL|RISE|SOUTHERN)", name):
        continue
    if name in kept_ids:
        cols = region_cols[name]
        all_water = cols and all(c in water for c in cols)
        if not all_water:
            hits += 1
            non_water = [c for c in cols if c not in water]
            print(f"  {name}: {len(cols)}色, 非海色 {len(non_water)}个: "
                  f"{non_water[:8]}")
print("total kept sea-named with non-water colors:", hits)
