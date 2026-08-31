# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, r"D:/Journal")
import htmlview

base = r"D:/Journal/_scratch/sess_map_test"
print("base exists:", os.path.exists(base))
print("base listing:", os.listdir(base))
print("报纸 listing:", os.listdir(os.path.join(base, "报纸")))
e = htmlview._collect_entries(base)
print("entries:", len(e))
print("FILE_RE:", htmlview.FILE_RE.pattern)
