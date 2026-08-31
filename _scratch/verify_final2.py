# -*- coding: utf-8 -*-
idx = open(r"D:/Journal/_scratch/sess_map_test/index.html", encoding="utf-8").read()
# find all occurrences of map-figure in the ARTICLES data portion
import re
for m in re.finditer(r'map-figure', idx):
    s = max(0, m.start() - 60)
    print(repr(idx[s:m.end() + 40]))
    print()
