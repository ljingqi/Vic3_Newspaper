# -*- coding: utf-8 -*-
"""Research for 3 new features:
1. hover tooltip: per-state GDP share + culture/religion pie
2. why is Formosa (Taiwan) in the inset for 大清? adjacency?
3. per-state capital hub names
"""
import json
import os
import re
import sys

sys.path.insert(0, r"D:/Journal")

# ---- 2. Formosa adjacency ----
adj = json.load(open(r"D:/Journal/state_adjacency.json", encoding="utf-8"))
print("STATE_FORMOSA neighbors:", adj.get("STATE_FORMOSA"))
# neighbors of Fujian / Zhejiang (mainland side)
for k in ("STATE_FUJIAN", "STATE_ZHEJIANG", "STATE_GUANGDONG", "STATE_TAIWAN"):
    if k in adj:
        print(f"{k} neighbors:", adj[k])
    else:
        print(f"{k}: not in adjacency (key: {k in adj})")
# search any state whose name contains TAIWAN or FORMOSA
print("\nstate keys containing FORMOSA/TAIWAN:",
      [k for k in adj if "FORMOSA" in k or "TAIWAN" in k])
# does any mainland state touch Formosa?
formosa_nb = set(adj.get("STATE_FORMOSA", []))
print("Formosa neighbors subset:", sorted(formosa_nb)[:20])

# ---- 1. per-state GDP in melt ----
with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()


def obj_end(b, i):
    depth = 0
    while i < len(b):
        c = b[i]
        if c == 123:
            depth += 1
        elif c == 125:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return i


si = data.find(b'"states":{"database":')
db = data.find(b"{", si)
end = obj_end(data, db)
pat = re.compile(rb'"(\d+)":\{')
j = db
fields = {}
sample = None
while j < end:
    m = pat.search(data, j, end - 1)
    if not m:
        break
    o = m.start() + len(m.group(0)) - 1
    e = obj_end(data, o)
    seg = data[o:min(e, o + 12000)]
    if b'"region"' in seg and b'"country"' in seg:
        for f in re.findall(rb'"([a-z_]+)":', seg):
            fields[f] = fields.get(f, 0) + 1
        if sample is None:
            sample = seg
    j = e + 1
print("\nstate fields histogram (top 40):")
for k, v in sorted(fields.items(), key=lambda kv: -kv[1])[:40]:
    print(f"  {k.decode()}: {v}")
# look for gdp-related fields
print("\ngdp-related fields:", [k.decode() for k in fields if b"gdp" in k or b"GDP" in k])
