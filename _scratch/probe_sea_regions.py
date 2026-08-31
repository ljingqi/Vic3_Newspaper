# -*- coding: utf-8 -*-
"""Verify: state_shapes.json / state_geojson.json contain SEA regions
(STATE_*_SEA etc.) that are being rendered as land (beige)."""
import json
import sys
import re

sys.path.insert(0, r"D:/Journal")

# 1. state_shapes.json (current render source)
shapes = json.load(open(r"D:/Journal/state_shapes.json", encoding="utf-8"))
keys = list(shapes["shapes"].keys())
sea_keys = [k for k in keys if re.search(r"_(SEA|OCEAN|LAKE|STRAIT)$", k)]
print("state_shapes.json states:", len(keys))
print("  sea-like keys:", len(sea_keys))
for k in sea_keys[:20]:
    print("   ", k)

# 2. default.map sea colors -> which STATE_XXX are sea-only
GAME = "F:/Game/steamapps/common/Victoria 3"
dm = open(GAME + "/game/map_data/default.map", encoding="utf-8",
          errors="replace").read()
m = re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm)
sea_colors = set(re.findall(r"x([0-9A-Fa-f]{6})", m.group(1)))
m2 = re.search(r"lakes\s*=\s*\{([^}]*)\}", dm)
lake_colors = set(re.findall(r"x([0-9A-Fa-f]{6})", m2.group(1)))
print("\ndefault.map sea colors:", len(sea_colors), "lake colors:", len(lake_colors))

# 3. state_regions: which STATE_ keys contain ONLY sea colors
sr = GAME + "/game/map_data/state_regions"
sea_only = []
for fn in __import__("os").listdir(sr):
    if not fn.endswith(".txt"):
        continue
    txt = open(sr + "/" + fn, encoding="utf-8", errors="replace").read()
    for mm in re.finditer(r"([A-Z0-9_]+)\s*=\s*\{", txt):
        name = mm.group(1)
        if not name.startswith("STATE_"):
            continue
        start = mm.end() - 1
        depth = 1
        i = start + 1
        while depth and i < len(txt):
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
            i += 1
        block = txt[start:i]
        cols = [p.upper() for p in re.findall(r"x([0-9A-Fa-f]{6})", block)]
        if cols and all(c in sea_colors or c in lake_colors for c in cols):
            sea_only.append(name)
print("sea-only STATE keys in state_regions:", len(sea_only))
for k in sea_only[:20]:
    print("   ", k)

# 4. are sea-only keys present in state_shapes.json?
in_shapes = [k for k in sea_only if k in shapes["shapes"]]
print("\nsea-only keys present in state_shapes.json:", len(in_shapes))
for k in in_shapes[:20]:
    n_pts = sum(len(p) for p in shapes["shapes"][k])
    print("   ", k, "polys:", len(shapes["shapes"][k]), "pts:", n_pts)
