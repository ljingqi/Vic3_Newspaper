# -*- coding: utf-8 -*-
svg = open("_scratch/map_demo.svg", encoding="utf-8").read()
i = svg.find("<rect")
print("context around first rect:")
print(svg[max(0, i - 300):i + 300])
