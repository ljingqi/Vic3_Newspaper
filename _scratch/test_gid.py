# -*- coding: utf-8 -*-
"""Test: matplotlib polygon gid -> SVG attribute for hover binding."""
import io
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
import re
m = re.search(r'<path[^>]*id="STATE_TEST"[^>]*>', svg)
print("gid path:", m.group(0)[:300] if m else "NOT FOUND")
