# -*- coding: utf-8 -*-
"""Analyze map SVG structure to verify correctness (text/paths/palette)."""
import re
import sys

svg = open("_scratch/map_demo.svg", encoding="utf-8").read()
print("svg length:", len(svg))

# text elements
texts = re.findall(r"<text[^>]*>(.*?)</text>", svg)
print("text count:", len(texts))
for t in texts[:20]:
    print("  text:", t.strip()[:60])

# check title text present
print("title ok:", "疆域图" in svg)

# polygon fill colors used
fills = set(re.findall(r'fill="#([0-9a-fA-F]{6})"', svg))
print("unique fills:", len(fills))
for f in sorted(fills):
    print("  #" + f)

# check 4-color palette present
for c in ["FBB4AE", "B3CDE3", "CCEBC5", "DECBE4"]:
    print(f"palette {c}:", c in svg)
