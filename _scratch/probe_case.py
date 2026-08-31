# -*- coding: utf-8 -*-
"""Why were 3D6A6A (PHILIPPINES_SEA) and B6CECE (E.INDIAN_OCEAN) missed?"""
import re

GAME = "F:/Game/steamapps/common/Victoria 3"
dm = open(GAME + "/game/map_data/default.map", encoding="utf-8",
          errors="replace").read()
sea = set(re.findall(r"x([0-9A-Fa-f]{6})",
                     re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1)))
print("3D6A6A in sea (upper):", "3D6A6A" in sea)
print("3d6a6a in sea (lower):", "3d6a6a" in sea)
print("B6CECE in sea (upper):", "B6CECE" in sea)
print("b6cece in sea (lower):", "b6cece" in sea)
# find actual forms
for c in sea:
    if c.upper() in ("3D6A6A", "B6CECE"):
        print("  found as:", c)
