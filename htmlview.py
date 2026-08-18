#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读页生成器 (htmlview.py)
=============================
把 <项目目录>/output/<国名>/ 下的报纸/杂志 Markdown 汇总成一个自包含的
index.html 阅读页:
  - 同一页面内可切换「报纸 / 杂志」两种版式(两套 CSS 主题);
  - 同一页面内可按年份切换当期文章;
  - 全部样式与脚本内嵌, 不依赖任何外部资源, 离线双击即可阅读。

用法:
  python htmlview.py rebuild                迁移存量 md 并按会话生成阅读页
  python htmlview.py rebuild 古巴           只处理指定会话文件夹(可多个)

目录约定 (写入/迁移后):
  output/<国名>/报纸/报纸_<年份>.md   + 由本模块生成 index.html
  output/<国名>/杂志/杂志_<年份>.md
  output/<国名>/data/               原始数据, 保持不动
"""

import html
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KINDS = ("报纸", "杂志")
FILE_RE = re.compile(r"^(报纸|杂志)_(\d{4})\.md$")


def _journal_dir():
    """读取 config.json 的 journal_dir, 缺省用仓库内 output。"""
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        d = (cfg.get("journal_dir") or "").strip()
        if d:
            return os.path.normpath(d)
    except Exception:
        pass
    return os.path.join(SCRIPT_DIR, "output")


# ---------------------------------------------------------------------------
# Markdown → HTML (覆盖现有输出实际用到的语法子集)
# ---------------------------------------------------------------------------

_META_DATE_RE = re.compile(r"报告日期\s*[:：]\s*([^|\n]+)")
_META_GEN_RE = re.compile(r"生成时间\s*[:：]\s*([^\n]+)")


def _article_meta(text):
    """从文件头注释里提取报告日期/生成时间, 拼成页面底部元信息。"""
    parts = []
    m = _META_DATE_RE.search(text)
    if m:
        parts.append("报告日期：" + m.group(1).strip())
    m = _META_GEN_RE.search(text)
    if m:
        parts.append("生成时间：" + m.group(1).strip())
    return "｜".join(parts)


def _inline(text):
    """行内语法: 先转义 HTML, 再处理粗体/斜体/行内代码。"""
    t = html.escape(text)
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return t


def _is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|")


def _render_table(rows):
    parsed = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(parsed) < 2:
        return ""
    sep = parsed[1]
    if all(re.fullmatch(r"\s*:?-{1,}:?\s*", c) for c in sep):
        header, body = parsed[0], parsed[2:]
    else:
        header, body = parsed[0], parsed[1:]
    ncol = max(len(header), max((len(r) for r in body), default=0))

    def row_html(cells, tag):
        cells = list(cells) + [""] * (ncol - len(cells))
        return "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"

    out = ["<table>"]
    out.append("<thead>" + row_html(header, "th") + "</thead>")
    out.append("<tbody>" + "".join(row_html(r, "td") for r in body) + "</tbody>")
    out.append("</table>")
    return "\n".join(out)


def _is_ul(ln):
    return bool(re.match(r"^\s*[-*]\s+", ln))


def _is_ol(ln):
    return bool(re.match(r"^\s*\d+[.)]\s+", ln))


def md_to_html(text):
    """整篇 Markdown → HTML 片段 (不含 <html> 外壳)。"""
    lines = text.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("<!--"):
            i += 1
            continue
        if re.fullmatch(r"-{3,}", s):
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            level = len(m.group(1))
            cls = ' class="masthead"' if level == 1 else ""
            out.append(f"<h{level}{cls}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if _is_table_row(ln):
            rows = []
            while i < n and _is_table_row(lines[i]):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue
        if _is_ul(ln):
            items = []
            while i < n and _is_ul(lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]).strip())
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        if _is_ol(ln):
            items = []
            while i < n and _is_ol(lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).strip())
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ol>")
            continue
        if s.startswith(">"):
            quotes = []
            while i < n and lines[i].strip().startswith(">"):
                quotes.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            body = _inline(" ".join(q.strip() for q in quotes))
            out.append(f"<blockquote>{body}</blockquote>")
            continue
        # 普通段落: 收集连续非空行, 直至遇到其它块级语法
        para = []
        while i < n:
            s2 = lines[i].strip()
            if (not s2 or s2.startswith("<!--")
                    or s2.startswith("#") or re.fullmatch(r"-{3,}", s2)
                    or _is_table_row(s2) or _is_ul(s2) or _is_ol(s2)
                    or s2.startswith(">")):
                break
            para.append(s2)
            i += 1
        if not para:
            # 空段落(如单独一行的 "###")会阻塞外层循环, 直接跳过该行
            i += 1
            continue
        text_p = " ".join(para)
        chk = text_p.strip().strip("*")
        if re.match(r"^国名\s*[:：].*｜.*[:：].*", chk):
            out.append(f'<p class="masthead-meta">{_inline(text_p)}</p>')
        else:
            out.append(f"<p>{_inline(text_p)}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 会话阅读页 (index.html)
# ---------------------------------------------------------------------------

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --paper:#fbf6e9; --paper-edge:#d9cba8; --ink:#2a2118; --ink-soft:#5a4b32;
  --rule:#b7a67e; --accent:#8a3b22; --bar:#262016; --bar-ink:#f0e6d2; --gold:#c8a24a;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{min-height:100%}
body{font-family:"Songti SC","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif;background:#e9e0cb;color:var(--ink)}
#toolbar{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;padding:10px 18px;background:var(--bar);color:var(--bar-ink);box-shadow:0 2px 10px rgba(30,22,8,.35)}
#toolbar .session{font-weight:700;letter-spacing:2px;font-size:17px}
#tabs{display:flex;gap:6px}
#tabs button,#toolbar button.nav-btn{font:inherit;padding:5px 16px;border:1px solid #8f7d55;background:#3a3121;color:var(--bar-ink);border-radius:5px;cursor:pointer}
#tabs button.active{background:var(--gold);border-color:var(--gold);color:#211a0c;font-weight:700}
#toolbar select{font:inherit;padding:5px 8px;border-radius:5px;background:#f6efdd;color:var(--ink)}
.years{margin-left:auto;display:flex;gap:6px;align-items:center}
#stage{max-width:880px;margin:28px auto 8px;padding:0 14px}
.paper{background:var(--paper);border:1px solid var(--paper-edge);box-shadow:0 6px 22px rgba(60,45,20,.18);padding:38px 46px 46px;border-radius:2px}
#meta-line{max-width:880px;margin:10px auto 60px;padding:0 14px;text-align:center;color:#6f6247;font-size:13px}
.empty{color:#8a7a55;text-align:center;padding:60px 0}
p{line-height:2.05;text-align:justify;margin:0 0 14px;font-size:17px}
strong{font-weight:700}
em{font-style:italic}
hr{border:none;border-top:1px solid var(--rule);margin:24px 0}
table{border-collapse:collapse;margin:16px auto 18px;font-size:15px;max-width:100%}
th,td{border:1px solid #b9a883;padding:7px 12px;text-align:center}
th{background:#efe6cd;font-weight:700}
ul,ol{margin:0 0 14px;padding-left:2em;line-height:2}
li{margin-bottom:4px}
blockquote{margin:0 0 14px;padding:10px 18px;border-left:4px solid var(--gold);background:#f3ecd8;color:var(--ink-soft)}
code{background:#efe7d3;border-radius:3px;padding:1px 5px;font-family:Consolas,monospace;font-size:.9em}

/* 报纸版式 */
.view-newspaper .masthead{font-family:"STKaiti","KaiTi","SimSun",serif;text-align:center;font-size:42px;letter-spacing:8px;font-weight:700;border-top:3px double #3a2c16;border-bottom:3px double #3a2c16;padding:16px 0 12px;margin:0 0 12px}
.view-newspaper .masthead-meta{text-align:center;font-size:15px;color:var(--ink-soft);letter-spacing:1px;margin-bottom:16px}
.view-newspaper h2{font-family:"STKaiti","KaiTi",serif;text-align:center;font-size:24px;font-weight:700;color:var(--accent);margin:30px 0 12px;letter-spacing:3px}
.view-newspaper h3{font-size:18px;color:var(--ink);margin:20px 0 8px}
.view-newspaper p{text-indent:2em}
.view-newspaper p.masthead-meta{text-indent:0}

/* 杂志版式 */
.view-magazine .masthead{font-family:"STXingkai","KaiTi","SimSun",serif;text-align:center;font-size:36px;letter-spacing:6px;color:#1f3a5f;margin:0 0 6px;font-weight:700}
.view-magazine .masthead-meta{text-align:center;color:#6a7c92;font-size:14px;margin-bottom:20px;letter-spacing:1px}
.view-magazine h2{font-size:25px;color:#1f3a5f;margin:32px 0 12px;padding-left:12px;border-left:5px solid var(--gold)}
.view-magazine h3{font-size:18px;color:#33506e;margin:22px 0 8px}
.view-magazine p{line-height:2.1}

@media (max-width:640px){
  .paper{padding:22px 16px}
  .view-newspaper .masthead{font-size:27px;letter-spacing:3px}
  .view-magazine .masthead{font-size:26px;letter-spacing:2px}
  .years{margin-left:0;width:100%}
}
@media print{
  #toolbar{display:none}
  body{background:#fff}
  .paper{box-shadow:none;border:none;padding:0}
  #stage{max-width:none;margin:0}
  #meta-line{margin:0 0 20px}
}
</style>
</head>
<body>
<div id="toolbar">
  <span class="session">__FOLDER__</span>
  <div id="tabs"></div>
  <div class="years">
    <select id="year-select"></select>
    <button class="nav-btn" data-dir="prev" type="button">‹ 上一年</button>
    <button class="nav-btn" data-dir="next" type="button">下一年 ›</button>
  </div>
</div>
<div id="stage"></div>
<div id="meta-line"></div>
<script>
const ARTICLES = __ARTICLES__;
const kinds = ["报纸", "杂志"];
const tabsEl = document.getElementById("tabs");
const yearSelect = document.getElementById("year-select");
const stage = document.getElementById("stage");
const metaLine = document.getElementById("meta-line");
let type = null, year = null;

function yearsOf(k) {
  return ARTICLES.filter(a => a.type === k).map(a => a.year).sort((x, y) => x - y);
}
function has(k) { return ARTICLES.some(a => a.type === k); }

function buildTabs() {
  tabsEl.innerHTML = "";
  kinds.forEach(k => {
    if (!has(k)) return;
    const b = document.createElement("button");
    b.className = "tab-btn" + (k === type ? " active" : "");
    b.textContent = k;
    b.addEventListener("click", () => selectType(k));
    tabsEl.appendChild(b);
  });
}

function selectType(k) {
  type = k;
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", b.textContent === k));
  const years = yearsOf(k);
  yearSelect.innerHTML = years.map(y => `<option value="${y}">${y} 年</option>`).join("");
  if (years.includes(year)) {
    yearSelect.value = year;
  } else {
    year = years.length ? years[years.length - 1] : null;
    if (yearSelect.options.length) yearSelect.value = year;
  }
  render();
}

function render() {
  const art = ARTICLES.find(a => a.type === type && a.year === year);
  if (!art) {
    stage.innerHTML = '<p class="empty">本期暂无内容</p>';
    metaLine.textContent = "";
    return;
  }
  const theme = type === "报纸" ? "newspaper" : "magazine";
  stage.innerHTML = `<article class="paper view-${theme}">${art.html}</article>`;
  metaLine.textContent = art.meta || "";
}

document.querySelectorAll(".nav-btn").forEach(b => b.addEventListener("click", () => {
  if (type == null) return;
  const years = yearsOf(type);
  const i = years.indexOf(year);
  const n = b.dataset.dir === "prev" ? i - 1 : i + 1;
  if (n >= 0 && n < years.length) {
    year = years[n];
    yearSelect.value = year;
    render();
  }
}));

yearSelect.addEventListener("change", () => {
  year = parseInt(yearSelect.value, 10);
  render();
});

const firstKind = kinds.find(k => has(k));
if (firstKind) {
  buildTabs();
  selectType(firstKind);
}
</script>
</body>
</html>
"""


def _collect_entries(base_dir):
    """扫描会话文件夹下的 报纸/杂志 子目录, 汇总所有 (类型, 年份, 渲染HTML)。"""
    entries = []
    for kind in KINDS:
        sub = os.path.join(base_dir, kind)
        if not os.path.isdir(sub):
            continue
        for fn in sorted(os.listdir(sub)):
            m = FILE_RE.match(fn)
            if not m:
                continue
            path = os.path.join(sub, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            entries.append({
                "type": kind,
                "year": int(m.group(2)),
                "html": md_to_html(text),
                "meta": _article_meta(text),
            })
    entries.sort(key=lambda e: (e["type"], e["year"]))
    return entries


def rebuild_session(journal_dir, folder):
    """为单个会话文件夹生成/更新 index.html; 无任何 md 时返回 None。"""
    base = os.path.join(journal_dir, folder)
    entries = _collect_entries(base)
    if not entries:
        return None
    title = f"{folder} · 报纸/杂志阅读页"
    out = (TEMPLATE
           .replace("__TITLE__", html.escape(title))
           .replace("__FOLDER__", html.escape(folder))
           .replace("__ARTICLES__", json.dumps(entries, ensure_ascii=False)))
    path = os.path.join(base, "index.html")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, path)   # 原子替换, 并行生成报纸/杂志时不会读到半截文件
    return path


def migrate_folder(journal_dir, folder):
    """把散落在会话根目录的 报纸_*.md / 杂志_*.md 移入 报纸/ 杂志/ 子目录。
    返回移动的文件数。"""
    base = os.path.join(journal_dir, folder)
    if not os.path.isdir(base):
        return 0
    moved = 0
    for kind in KINDS:
        sub = os.path.join(base, kind)
        targets = [fn for fn in os.listdir(base)
                   if (m := FILE_RE.match(fn)) and m.group(1) == kind]
        if not targets:
            continue
        try:
            os.makedirs(sub, exist_ok=True)
        except OSError:
            continue
        for fn in targets:
            src = os.path.join(base, fn)
            if os.path.isfile(src):
                shutil.move(src, os.path.join(sub, fn))
                moved += 1
    return moved


def cmd_rebuild(args):
    journal_dir = _journal_dir()
    if not os.path.isdir(journal_dir):
        print(f"输出目录不存在: {journal_dir}")
        return 1
    if args:
        targets = list(args)
    else:
        targets = sorted(os.listdir(journal_dir))
    total_moved = total_pages = 0
    for name in targets:
        base = os.path.join(journal_dir, name)
        if not os.path.isdir(base):
            continue
        if name == "Archive" and not args:
            continue
        moved = migrate_folder(journal_dir, name)
        path = rebuild_session(journal_dir, name)
        if moved:
            print(f"[{name}] 迁移 {moved} 个文件")
        if path:
            print(f"[{name}] 阅读页已生成: {path}")
            total_pages += 1
        total_moved += moved
    print(f"完成: 迁移 {total_moved} 个文件, 生成 {total_pages} 个阅读页")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rebuild"
    if cmd != "rebuild":
        print("用法: python htmlview.py rebuild [国家名 ...]")
        return 1
    return cmd_rebuild(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
