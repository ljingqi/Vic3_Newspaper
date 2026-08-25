# -*- coding: utf-8 -*-
"""负向提示词自查: 扫描 journal.py/journal_save.py/magazine.py/style.py 中
提示词字符串常量 (req/rule/msg/masthead/voice/guide 等) 附近的否定词。"""
import re
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEG = re.compile(r"不要|请勿|禁止|避免|切勿|不得|严禁|不可|不再|别写|勿要|勿")

FILES = ["journal.py", "journal_save.py", "magazine.py", "style.py"]
finds = 0
for fn in FILES:
    src = open(os.path.join(BASE, fn), encoding="utf-8").read()
    for i, line in enumerate(src.splitlines(), 1):
        if not NEG.search(line):
            continue
        # 只看「提示词特征」行: 含 请/要求/规则/铁律/一律/须/以…为限/你是/本刊/本报/刊名/选举/疫情/投票/都城 等
        if re.search(r"请|要求|规则|铁律|一律|须|以.{0,6}为限|你是|本刊|本报|本馆|刊名|都城|投票|选举|疫情|生产方式|提示|规定|报道|撰写|写作", line):
            print(f"{fn}:{i}: {line.strip()[:110]}")
            finds += 1
print("negative-ish prompt lines:", finds)
