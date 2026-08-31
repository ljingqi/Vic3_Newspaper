# -*- coding: utf-8 -*-
"""Test: matplotlib fonttype=svg keeps Chinese as text (browser renders
with system font) instead of embedded path subsets."""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# find a CJK font
_CJK = ("KaiTi", "SimHei", "SimSun", "Microsoft YaHei")
avail = {f.name for f in font_manager.fontManager.ttflist}
fam = next((f for f in _CJK if f in avail), None)
print("font:", fam)
plt.rcParams["font.sans-serif"] = [fam] if fam else []
plt.rcParams["svg.fonttype"] = "svg"   # <-- key: text not paths
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots()
ax.text(0.5, 0.5, "石狩 仙台 大和", fontsize=12)
ax.axis("off")
buf = io.StringIO()
fig.savefig(buf, format="svg")
svg = buf.getvalue()
print("has <text tag:", "<text" in svg)
print("石狩 as text:", "石狩" in svg)
i = svg.find("<text")
print("text ctx:", svg[i:i + 200] if i >= 0 else "none")
print("has font path defs:", "<use xlink" in svg)
