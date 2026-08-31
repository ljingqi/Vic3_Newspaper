# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, r"D:/Journal")
import htmlview
import json

tmp = r"D:/Journal/_scratch/sess_map_test"
page = htmlview.rebuild_session(os.path.dirname(tmp), "sess_map_test")
idx = open(page, encoding="utf-8").read()
i = idx.find("data-map-year")
print("ctx:", repr(idx[max(0, i - 60):i + 180]))
# In ARTICLES json the script tag is JSON-escaped (\\\") — check raw form
j = idx.find('data-map-year')
print("\nraw script open tag present:", idx.count('script type=\\"application/json\\"'))
print("contains 石狩:", "石狩" in idx)
