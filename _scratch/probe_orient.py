# -*- coding: utf-8 -*-
"""Probe: determine map orientation from known state centroids.
State_shapes.json coordinates: check whether x=lattitude, y=longitude (rotated)."""
import json
import sys

sys.path.insert(0, r"D:/Journal")
import htmlview

shapes = htmlview._map_shapes()
cent = shapes["centroids"]
w, h = shapes["width"], shapes["height"]
print("map size:", w, "x", h)

# Known geography: (real_lon_E, real_lat_N)
known = {
    "STATE_KYOTO": (135.5, 35.0),       # 京都
    "STATE_HOKKAIDO": (141.0, 43.0),    # 北海道 (北)
    "STATE_BEIJING": (116.4, 39.9),     # 北京
    "STATE_MOSCOW": (37.6, 55.7),       # 莫斯科 (北+西)
    "STATE_LONDON": (-0.1, 51.5),       # 伦敦 (西)
    "STATE_PARIS": (2.35, 48.9),        # 巴黎
    "STATE_NEW_YORK": (-74.0, 40.7),    # 纽约 (西)
    "STATE_SINGAPORE": (103.8, 1.35),   # 新加坡 (南)
}
print("\nstate      cx     cy     real_lon real_lat")
for rk, (lon, lat) in known.items():
    c = cent.get(rk)
    if c:
        print(f"{rk:16s} {c[0]:7.1f} {c[1]:7.1f}  {lon:7.1f}  {lat:6.1f}")
    else:
        print(f"{rk:16s}  (无质心)")
