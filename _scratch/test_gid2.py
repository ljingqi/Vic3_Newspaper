# -*- coding: utf-8 -*-
import io
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

fig, ax = plt.subplots()
p = Polygon([(0, 0), (1, 0), (1, 1)], closed=True, facecolor="red")
p.set_gid("STATE_TEST")
ax.add_patch(p)
ax.set_xlim(-1, 2)
ax.set_ylim(-1, 2)
ax.axis("off")
buf = io.StringIO()
fig.savefig(buf, format="svg")
svg = buf.getvalue()
# search for STATE_TEST anywhere
i = svg.find("STATE_TEST")
print("idx:", i)
if i >= 0:
    print(repr(svg[max(0, i - 200):i + 100]))
