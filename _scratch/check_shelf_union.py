# -*- coding: utf-8 -*-
"""验证两处修改: 商品板块 customer 段无「到岸价」; 杂志工会法行为破折号直陈式。"""
import io
import sys
import json

sys.path.insert(0, r'D:\Journal')
import journal_save as JS

snap = json.load(io.open(r'D:\Journal\_scratch\mexico_1878_backup\data\snapshot_1878.json',
                         encoding='utf-8'))
with io.open(r'D:\Journal\tools\melt.json', 'rb') as fh:
    melted = fh.read()

data = JS.build_magazine_data(melted, snap, folder=r'D:\Journal\_scratch\tmp_shelf',
                              year=1878, pool_override=["shelf"], pool_size=1)
sec = data.get("shelf") or {}
cust = (sec.get("sections") or {}).get("customer", "")
print("=== customer 段 (前 900 字) ===")
print(cust[:900])
print("\n含「到岸价」:", "到岸价" in cust)
print("含「按到岸价」:", "按到岸价" in cust)

# 工会法行: 杂志侧 (若本期 shelf 注入过) 与报纸侧直接断言
found = [ln for ln in cust.splitlines() if "工会法" in ln]
print("\n=== 杂志 customer 段工会法行 ===")
for ln in found:
    print(ln)
if not found:
    lab = JS._labor_union_line(melted, 185, JS._load_loc_all())
    print("(本池未注入, 直接调 _labor_union_line 示例:)")
    print(lab)
