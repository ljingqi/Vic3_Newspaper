# -*- coding: utf-8 -*-
"""P3 integration test: inject map SVG into a session and rebuild index.html."""
import json
import os
import shutil
import sys

REPO = r"D:/Journal"
sys.path.insert(0, REPO)
import htmlview

# Build a temp session: copy one newspaper md + raw json, add map placeholder
tmp = os.path.join(REPO, "_scratch", "sess_map_test")
if os.path.exists(tmp):
    shutil.rmtree(tmp)
os.makedirs(os.path.join(tmp, "报纸"))
os.makedirs(os.path.join(tmp, "data"))

# use 德川幕府 (Kyoto save) 1838 md if exists, else craft one
src_md = os.path.join(REPO, "output", "德川幕府3", "报纸")
candidates = []
if os.path.isdir(src_md):
    candidates = [f for f in os.listdir(src_md) if f.endswith(".md")]
src_md_path = os.path.join(src_md, candidates[0]) if candidates else None

if src_md_path and os.path.exists(src_md_path):
    text = open(src_md_path, encoding="utf-8").read()
else:
    text = "# 《测试报》\n\n国名：测试｜都城：京都｜年份：1838\n\n## 本报评论\n\n评论内容。\n"
# ensure map placeholder present at end of comment section (before next section)
marker = "<!--CHART macro-->"
if marker in text:
    text = text.replace(marker, marker + "\n\n<!--CHART map-->", 1)
else:
    text += "\n\n<!--CHART map-->\n"
open(os.path.join(tmp, "报纸", "报纸_1838.md"), "w", encoding="utf-8").write(text)

# raw json with map field
raw = json.load(open(os.path.join(REPO, "_scratch", "map_test.json"),
                     encoding="utf-8"))
raw["year"] = 1838
raw["player"] = "德川幕府"
raw_payload = {"year": 1838, "player": "德川幕府", "map": raw,
               "gdp": 1000, "pop": 1000, "sol": 10, "literacy": "50%"}
open(os.path.join(tmp, "data", "raw_1838.json"), "w", encoding="utf-8").write(
    json.dumps(raw_payload, ensure_ascii=False))

page = htmlview.rebuild_session(os.path.dirname(tmp), "sess_map_test")
print("rebuild ->", page)
# diagnostics if failed
if not page:
    ents = htmlview._collect_entries(tmp)
    print("entries now:", len(ents))
    for e in ents:
        print("  type", e["type"], "year", e["year"],
              "has map div:", 'data-chart="map"' in e["html"])
idx = open(os.path.join(tmp, "index.html"), encoding="utf-8").read()
print("index.html size:", len(idx))
print("map-figure present:", 'class="map-figure"' in idx)
print("svg present:", "<svg" in idx)
print("caption present:", "本报疆域图" in idx)
print("hint present (should be False):", "本期无疆域图数据" in idx)
i = idx.find('class="map-figure"')
print("context:", idx[i:i + 120] if i >= 0 else "N/A")
