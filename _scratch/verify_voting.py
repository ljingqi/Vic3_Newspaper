# -*- coding: utf-8 -*-
"""强制插入验证: 用 magazine_pool_override=['voting'] 生成墨西哥 1878 年杂志
(一党制国家), 写入独立验证目录 output/_voting_verify, 确认投票日文章生效。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal
import journal_save as js

cfg = journal.load_config()
cfg["journal_dir"] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "_scratch", "voting_verify")
cfg["magazine_pool_override"] = ["voting"]
cfg["newspaper_enabled"] = False
cfg["magazine_enabled"] = True
cfg["parallel_generation_enabled"] = False

print("=== 强制插入投票文章验证: 墨西哥 1878 (一党制) ===", flush=True)
rc = js.make_magazine(year=1878, force=True, cfg=cfg, folder="墨西哥")
print("make_magazine rc:", rc, flush=True)

# 校验产物
mag_md = os.path.join(cfg["journal_dir"], "墨西哥", "杂志", "杂志_1878.md")
mag_json = os.path.join(cfg["journal_dir"], "墨西哥", "data", "magazine_1878.json")
if os.path.exists(mag_md):
    with open(mag_md, encoding="utf-8") as f:
        text = f.read()
    print("=== 杂志文件存在, 投票相关标题 ===", flush=True)
    for ln in text.splitlines():
        if ("投票" in ln or "选票" in ln or "选举" in ln or "一党" in ln
                or "权利的法律" in ln or "门槛" in ln or "投票日" in ln):
            print("  ", ln.strip()[:80], flush=True)
    print("=== 一党选举相关行 ===", flush=True)
    hits = [ln.strip()[:90] for ln in text.splitlines()
            if ("一党" in ln or "执政党" in ln or "参选" in ln)]
    print("\n".join("  " + h for h in hits[:12]) or "  (无)", flush=True)
else:
    print("杂志文件未生成:", mag_md, flush=True)
