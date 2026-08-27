# -*- coding: utf-8 -*-
"""德川幕府2 杂志重生成 (2026-08-27): 按年份轮换 melt 存档后调 make_magazine,
完成后恢复当前 melt.json。用法: python _scratch/_regen_magazines.py
"""
import os
import shutil
import sys

sys.path.insert(0, r'D:\Journal')
import journal
import journal_save as JS

FOLDER = "德川幕府2"
SAVES = {
    1836: r"C:\Users\CHINE\Documents\Paradox Interactive\Victoria 3\save games\autosave_3.v3",
    1837: r"C:\Users\CHINE\Documents\Paradox Interactive\Victoria 3\save games\autosave_2.v3",
    1838: None,  # 当前 melt.json 即 1838 存档
}
BACKUP = r"D:\Journal\_scratch\_melt_backup_tokugawa.json"

cfg = journal.load_config()

# 备份当前 melt (1838)
shutil.copy(JS.MELT_CACHE, BACKUP)
print("melt.json 已备份 ->", BACKUP, flush=True)

rcs = {}
try:
    for year in (1836, 1837, 1838):
        save = SAVES[year]
        if save:
            path, err = JS.melt_with_rakaly(save, force=True)
            if err:
                print(f"[{year}] melt 失败: {err}", flush=True)
                rcs[year] = -1
                continue
            print(f"[{year}] 已熔化存档 {os.path.basename(save)}", flush=True)
        else:
            print(f"[{year}] 使用当前 melt.json (1838)", flush=True)
        with open(JS.MELT_CACHE, "rb") as f:
            melted = f.read()
        journal.log(f"[{year}] 开始重生成杂志 (melt={os.path.basename(save) if save else 'current'})")
        try:
            rc = JS.make_magazine(year=year, force=True, melted=melted,
                                  cfg=cfg, folder=FOLDER)
        except Exception as e:
            journal.log(f"[{year}] 杂志重生成失败: {e}")
            rc = -1
        rcs[year] = rc
        print(f"[{year}] make_magazine rc={rc}", flush=True)
finally:
    try:
        shutil.copy(BACKUP, JS.MELT_CACHE)
        print("melt.json 已恢复为 1838 存档", flush=True)
    except Exception as e:
        print("恢复 melt.json 失败:", e, flush=True)

print("结果:", rcs, flush=True)
sys.exit(0 if all(v == 0 for v in rcs.values()) else 1)
