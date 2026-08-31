# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, r"D:/Journal")

# 1. raw md 文件是否有问题
md_path = r"D:/Journal/_scratch/sess_map_test/报纸/报纸_1838.md"
print("=== md 文件 ===")
print(repr(open(md_path, encoding="utf-8").read()[:200]))

# 2. raw json
raw_path = r"D:/Journal/_scratch/sess_map_test/data/raw_1838.json"
raw = open(raw_path, encoding="utf-8").read()
print("\n=== raw json head ===")
print(repr(raw[:200]))

# 3. index.html 编码检查
idx_path = r"D:/Journal/_scratch/sess_map_test/index.html"
data = open(idx_path, "rb").read()
print("\n=== index.html bytes ===")
print("size:", len(data))
print("head bytes:", data[:50])
# check charset meta
print("charset utf-8 in html:", b'charset="utf-8"' in data or b"charset=utf-8" in data)
# sample: find 本报疆域图
i = data.find("疆域图".encode("utf-8"))
print("疆域图 utf8 bytes found at:", i)
# check if text is double-encoded (mojibake)
sample = data[:2000]
print("sample repr:", repr(sample[:200]))
