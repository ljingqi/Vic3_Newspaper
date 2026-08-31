# -*- coding: utf-8 -*-
import re
svg = open("_scratch/map_demo.svg", encoding="utf-8").read()
rects = re.findall(r"<rect[^>]*>", svg)
for r in rects[:4]:
    print(repr(r[:300]))
    print()
m = re.search(r'<path[^>]*id="patch_[0-9]+"[^>]*>', svg)
print("first patch with id:", m.group(0)[:250] if m else "none")
# find the axes background path (first path usually)
paths = re.findall(r"<path[^>]*>", svg)
print("first path:", paths[0][:250] if paths else "none")
