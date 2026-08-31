# -*- coding: utf-8 -*-
"""Debug: why didn't Formosa merge? Check point distances."""
import sys
sys.path.insert(0, r"D:/Journal")
import journal_save as js

shapes = js._state_shapes()
points = shapes.get("points") or {}
print("FORMOSA point:", points.get("STATE_FORMOSA"))
print("BEIJING point:", points.get("STATE_BEIJING"))
print("FUJIAN point:", points.get("STATE_FUJIAN"))
print("ZHEJIANG point:", points.get("STATE_ZHEJIANG"))

# distance from Formosa to mainland states
import math
fp = points.get("STATE_FORMOSA")
if fp:
    for r, p in sorted(points.items()):
        if r.startswith("STATE_F") or "FUJIAN" in r or "ZHEJIANG" in r \
                or "GUANGDONG" in r or "JIANGXI" in r or "SHAOZHOU" in r:
            d = math.hypot(fp[0] - p[0], fp[1] - p[1])
            print(f"  {r}: dist={d:.0f}px")

# threshold
thr = (shapes.get("width") or 2048) * 0.009
print("\nnear threshold:", thr, "px (width:", shapes.get("width"), ")")
print("points count:", len(points))
