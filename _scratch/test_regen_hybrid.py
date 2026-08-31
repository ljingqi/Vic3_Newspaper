# -*- coding: utf-8 -*-
"""P5a regression: rebuild a real-like session in _scratch (writable).
Use 德川幕府2's real newspaper md + real raw json (no map field -> hint
path) AND inject map data to test the full render path."""
import json
import os
import shutil
import sys

sys.path.insert(0, r"D:/Journal")
import htmlview

tmp = r"D:/Journal/_scratch/sess_regen_test"
if os.path.exists(tmp):
    shutil.rmtree(tmp)
os.makedirs(os.path.join(tmp, "报纸"))
os.makedirs(os.path.join(tmp, "data"))

# copy a real newspaper md from 德川幕府2 (1836) and inject map placeholder
src = r"D:/Journal/output/德川幕府2/报纸"
mds = sorted(f for f in os.listdir(src) if f.endswith(".md"))
print("source mds:", mds[:5])
text = open(os.path.join(src, mds[0]), encoding="utf-8").read()
marker = "<!--CHART macro-->"
if marker in text:
    text = text.replace(marker, marker + "\n\n<!--CHART map-->", 1)
else:
    text += "\n\n<!--CHART map-->\n"
year = mds[0].split("_")[1].split(".")[0]
open(os.path.join(tmp, "报纸", f"报纸_{year}.md"), "w",
     encoding="utf-8").write(text)

# real raw json (has no map field -> hint path)
raw_src = r"D:/Journal/output/德川幕府2/data"
raws = sorted(f for f in os.listdir(raw_src) if f.startswith("raw_"))
print("source raws:", raws[:3])
shutil.copy(os.path.join(raw_src, raws[0]),
            os.path.join(tmp, "data", f"raw_{year}.json"))

# second year WITH map data injected (full render path)
md2 = json.load(open(r"D:/Journal/_scratch/map_data_v2.json", encoding="utf-8"))
raw2 = {"year": int(year) + 1, "player": "德川幕府", "map": md2,
        "gdp": 1000, "pop": 1000, "sol": 10, "literacy": "50%"}
open(os.path.join(tmp, "data", f"raw_{int(year)+1}.json"), "w",
     encoding="utf-8").write(json.dumps(raw2, ensure_ascii=False))

# a second newspaper md for year+1
text2 = text.replace(f"{year}年", f"{int(year)+1}年")
open(os.path.join(tmp, "报纸", f"报纸_{int(year)+1}.md"), "w",
     encoding="utf-8").write(text2)

page = htmlview.rebuild_session(r"D:/Journal/_scratch", "sess_regen_test")
print("\nrebuild ->", page)
idx = open(page, encoding="utf-8").read()
print("index size:", len(idx))
print("map-figure count:", idx.count("map-figure"))
print("hint present (year without map):", "本期无疆域图数据" in idx)
print("full svg present:", idx.count("<svg") >= 2)
print("script blocks:", idx.count("<script"), "/", idx.count("</script>"))
print("MAPS payload:", "const MAPS =" in idx)
