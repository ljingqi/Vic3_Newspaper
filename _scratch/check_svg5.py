# -*- coding: utf-8 -*-
import io
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig = plt.figure(figsize=(6, 4))
ax = fig.add_axes([0.02, 0.06, 0.9, 0.8])
ax.set_facecolor("#dceaf2")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis("off")
# draw a polygon to force background render
from matplotlib.patches import Rectangle
ax.add_patch(Rectangle((1, 1), 3, 3, facecolor="#efe6cf"))
buf = io.StringIO()
fig.savefig(buf, format="svg", bbox_inches="tight", facecolor="#fbf6e9")
svg = buf.getvalue()
fills = set(re.findall(r'fill:\s*#([0-9a-fA-F]{6})', svg))
print("fills:", fills)
print("dceaf2:", "dceaf2" in svg)
i = svg.find("<svg")
j = svg.find("</svg>")
print("len:", j - i)
