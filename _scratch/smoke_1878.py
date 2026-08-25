# -*- coding: utf-8 -*-
"""1878 冒烟重跑: 用修复后的代码 + 最新熔化的 1878 存档, 重新生成墨西哥
报纸与杂志 (全新提取, 不使用旧快照缓存), 覆盖 output/墨西哥 下 1878 产物。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal
import journal_save as js

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = journal.load_config()
cfg["magazine_pool_override"] = None
cfg["parallel_generation_enabled"] = False

with open(os.path.join(REPO, "tools", "melt.json"), "rb") as f:
    melted = f.read()
ctx = js.SaveContext(melted)

print("=== 1878 报纸重生成 ===", flush=True)
rc1 = js.make_newspaper(year=1878, force=True, melted=melted, ctx=ctx,
                        folder="墨西哥")
print("newspaper rc:", rc1, flush=True)
print("=== 1878 杂志重生成 ===", flush=True)
rc2 = js.make_magazine(year=1878, force=True, melted=melted, ctx=ctx,
                       cfg=cfg, folder="墨西哥")
print("magazine rc:", rc2, flush=True)

# ---- 断言 ----
fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  | " + detail if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


out = os.path.join(REPO, "output", "墨西哥")
paper = os.path.join(out, "报纸", "报纸_1878.md")
mag = os.path.join(out, "杂志", "杂志_1878.md")

if os.path.exists(paper):
    t = open(paper, encoding="utf-8").read()
    check("报纸: 无消费税", "消费税" not in t)
    check("报纸: 无都城若缺失常设句", "都城若缺失" not in t)
    check("报纸: 无否定态生产方式(无冷藏等)", not re.search(r"无冷藏|无飞艇|无灯街道|无效果", t))
    check("报纸: 人头税出现", "人头税" in t)
else:
    check("报纸文件存在", False, paper)

if os.path.exists(mag):
    t = open(mag, encoding="utf-8").read()
    check("杂志: 刊名固定《墨西哥城思潮》", "《墨西哥城思潮》" in t)
    check("杂志: 无刊名派生指导句", "刊名由首都或国名派生" not in t)
    check("杂志: 无消费税", "消费税" not in t)
    check("杂志: 无否定态生产方式", not re.search(r"无冷藏|无飞艇|无灯街道|无效果", t))
    check("杂志: 无无新州", "无新州" not in t)
    # 极权现代文风: 系统性仿古 (整段骈文) 已消除; 允许零星成语式四字 (现代报章也常用)
    archaic = re.findall(r"岁在\w+|嗟乎|谨识|孟春|伟哉|呜呼|之盛况", t)
    check("杂志: 极权现代文风(无系统性仿古)", len(archaic) <= 2, f"archaic={archaic[:5]}")
    # 标题一致性: 导言预告中的《X》应出现在正文标题中 (预告区=首个"## "之前;
    # 排除刊名与导言正文提到的法律名)
    preview_region = t.split("\n## ")[0]
    preview_names = re.findall(r"《([^《》]{2,24})》", preview_region)
    body_titles = [ln.strip().lstrip("# ").strip() for ln in t.splitlines()
                   if re.match(r"^## \S", ln)]
    body_names = [re.sub(r"^《|》$", "", x) for x in body_titles]

    def _is_law_name(n):
        return any(k in n for k in ("法", "案", "条例", "细则", "律"))

    preview_articles = [n for n in preview_names
                        if n != "墨西哥城思潮" and not _is_law_name(n)]
    mismatch = [n for n in preview_articles
                if n not in body_names and not any(
                    n in b or b in n for b in body_names)]
    check("杂志: 导言预告与正文标题一致", not mismatch, f"mismatch={mismatch}")
else:
    check("杂志文件存在", False, mag)

if os.path.exists(paper):
    pt_ = open(paper, encoding="utf-8").read()
    archaic_p = re.findall(r"岁在\w+|嗟乎|谨识|孟春|伟哉|呜呼|之盛况", pt_)
    check("报纸: 极权现代文风(无系统性仿古)", len(archaic_p) <= 2,
          f"archaic={archaic_p[:5]}")
    check("报纸: 报名现代体例", "日报" in pt_[:400] or "建设报" in pt_[:400])

print()
print("FAILED:", len(fails), fails if fails else "(none)", flush=True)
sys.exit(1 if fails else 0)
