# -*- coding: utf-8 -*-
idx = open(r"D:/Journal/_scratch/sess_map_test/index.html", encoding="utf-8").read()
print('class="map-figure" present:', 'class="map-figure"' in idx)
print("svg count:", idx.count("<svg"))
print("map-figure count:", idx.count("map-figure"))
print("leftover data-chart=map:", idx.count('data-chart="map"'))
