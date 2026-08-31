# -*- coding: utf-8 -*-
"""Minimal test: does ax.set_facecolor survive into SVG?"""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig = plt.figure(figsize=(6, 4))
ax = fig.add_axes([0.02, 0.06, 0.9, 0.8])
ax.set_facecolor("#dceaf2")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis("off")
buf = io.StringIO()
fig.savefig(buf, format="svg", bbox_inches="tight", facecolor="#fbf6e9")
svg = buf.getvalue()
print("dceaf2 in svg:", "dceaf2" in svg)
i = svg.find("dceaf2")
print(svg[max(0, i - 200):i + 100] if i >= 0 else "NOT FOUND")
