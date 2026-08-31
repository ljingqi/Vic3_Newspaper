# -*- coding: utf-8 -*-
import re
svg = open(r"D:/Journal/_scratch/map_v6.svg", encoding="utf-8").read()
uses = re.findall(r"<use[^>]*>", svg)
print("use count:", len(uses))
for u in uses[:5]:
    print(" ", u[:120])
print("text count:", svg.count("<text"))
print("gid STATE_ count:", svg.count('id="STATE_'))
print("title text:", "疆域图" in svg)
print("legend text:", "本国省份" in svg)
