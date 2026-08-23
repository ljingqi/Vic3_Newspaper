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


# 加粗回显板块标题行 (如 **《乡里访谈》** / **头版导语：**) 的渲染兜底:
# 生成端 (journal.py/magazine.py) 已归一化, 此处处理存量 md (未重生成的年份),
# 避免「板块名出现在正文」。
_BOLD_ONLY_RE = re.compile(r"^\*\*(.+?)[:：]?\*\*[:：]?\s*$")


def _norm_title(t):
    t = (t or "").strip().strip("《》「」").strip().rstrip("：:")
    if t.endswith("导语"):
        t = t[:-2]
    return t.strip()


def md_to_html(text):
    """整篇 Markdown → HTML 片段 (不含 <html> 外壳)。"""
    lines = text.split("\n")
    out = []
    seen_headings = set()
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        m_chart = re.fullmatch(r"<!--CHART\s+([a-z_]+)\s*-->", s)
        if m_chart:
            out.append(f'<div class="chart" data-chart="'
                       f'{html.escape(m_chart.group(1))}"></div>')
            i += 1
            continue
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
            seen_headings.add(_norm_title(m.group(2)))
            i += 1
            continue
        m_bold = _BOLD_ONLY_RE.match(s)
        if m_bold and _norm_title(m_bold.group(1)) in seen_headings:
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
.chart{margin:18px 0 22px}
.chart-hint{color:#8a7a55;text-align:center;font-size:14px;padding:18px 0;border:1px dashed #c9b98f;border-radius:4px}
.chart-title{font-weight:700;color:var(--accent);margin:0 0 4px;font-size:15px}
.chart-sub{color:var(--ink-soft);font-size:12px;margin:0 0 8px}
.chart svg{display:block;margin:0 auto;max-width:100%;height:auto}
.chart svg text{font-family:inherit;fill:var(--ink-soft)}
.chart svg text.val{fill:var(--ink);font-size:10px}
.chart svg text.axis{font-size:11px}
.chart svg text.legend{font-size:12px;font-weight:700}
/* 个股年K线: TradingView 风格坐标轴/网格/悬停 */
.stock-chart{position:relative;margin:0 0 16px}
.chart svg .grid{stroke:#d8cba7;stroke-width:1}
.chart svg .grid-v{stroke:#e6dbbd;stroke-width:1}
.chart svg .axis-line{stroke:#b7a67e;stroke-width:1.2}
.chart svg .candle{cursor:crosshair}
.candle-tip{position:absolute;display:none;pointer-events:none;background:rgba(38,32,22,.94);color:#f0e6d2;font-size:12px;line-height:1.7;padding:6px 10px;border-radius:4px;z-index:5;white-space:nowrap;box-shadow:0 2px 8px rgba(30,22,8,.35)}
.candle-tip b{color:var(--gold)}
.candle-tip .up{color:var(--up-soft,#7fd4a2)}
.candle-tip .down{color:var(--down-soft,#f0a49a)}

/* 股市板块: 指数置顶 + 个股按钮切换 + 涨跌图例 (颜色随国家约定翻转) */
.stock-head{display:flex;align-items:baseline;gap:10px;margin:0 0 6px}
.stock-head .chart-title{margin:0}
.stock-legend{font-size:12px;color:var(--ink-soft);display:inline-flex;align-items:center;gap:5px;margin-left:auto}
.stock-legend i{width:11px;height:11px;border-radius:2px;display:inline-block;border:1px solid rgba(0,0,0,.18)}
.stock-chart.stock-exchange{margin:0 0 14px}
.stock-chart.stock-exchange .chart-title{margin:0 0 4px}
.chg-badge{font-size:12px;font-weight:700;margin-left:6px}
.chg-up{color:var(--up,#1e7d46)}
.chg-down{color:var(--down,#b03a2e)}
.stock-btns{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.stock-btn{font:inherit;padding:4px 12px;border:1px solid #c4b58c;background:#f3ecd8;color:var(--ink);border-radius:14px;cursor:pointer;font-size:13px;line-height:1.5}
.stock-btn:hover{border-color:var(--accent)}
.stock-btn.active{background:var(--accent);border-color:var(--accent);color:#fdf8ea;font-weight:700}
.stock-btn .chg{font-weight:700;margin-left:5px}
.stock-btn .chg.new{color:#9a8a5f}
.stock-pane .stock-chart{margin:0}

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
const CHARTS = __CHARTS__;
const kinds = ["报纸", "杂志"];
const tabsEl = document.getElementById("tabs");
const yearSelect = document.getElementById("year-select");
const stage = document.getElementById("stage");
const metaLine = document.getElementById("meta-line");
let type = null, year = null;

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function lineChartSvg(series) {
  const W = 340, H = 170, ml = 46, mr = 12, mt = 16, mb = 26;
  const pw = W - ml - mr, ph = H - mt - mb;
  let html = "";
  series.forEach(s => {
    const pts = s.points;
    if (!pts.length) return;
    const ys = pts.map(p => p.y);
    let lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    if (hi === lo) { hi += 1; lo -= 1; }
    const padY = (hi - lo) * 0.12;
    lo -= padY; hi += padY;
    const X = i => pts.length === 1 ? ml + pw / 2 : ml + pw * i / (pts.length - 1);
    const Y = v => mt + ph - (v - lo) / (hi - lo) * ph;
    let grid = "";
    for (let t = 0; t < 4; t++) {
      const v = lo + (hi - lo) * t / 3;
      const y = Y(v);
      grid += `<line x1="${ml}" y1="${y}" x2="${W - mr}" y2="${y}" stroke="#d8cba7" stroke-width="1"/>`;
      grid += `<text class="axis" x="${ml - 5}" y="${y + 4}" text-anchor="end">${s.fmt(v)}</text>`;
    }
    let line = "", dots = "", vals = "", years = "";
    pts.forEach((p, i) => {
      const x = X(i), y = Y(p.y);
      line += (i ? "L" : "M") + x + "," + y;
      dots += `<circle cx="${x}" cy="${y}" r="2.8" fill="${s.color}"/>`;
      vals += `<text class="val" x="${x}" y="${y - 7}" text-anchor="middle">${s.fmt(p.raw)}</text>`;
      years += `<text class="axis" x="${x}" y="${H - 8}" text-anchor="middle">${p.x}</text>`;
    });
    const poly = `<path d="${line}" fill="none" stroke="${s.color}" stroke-width="1.8"/>`;
    html += `<div class="mini-chart">
      <div class="chart-title">${esc(s.label)}${s.unit ? "（" + esc(s.unit) + "）" : ""}</div>
      <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img">${grid}${poly}${dots}${vals}${years}</svg>
    </div>`;
  });
  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">${html}</div>`;
}

function renderMacroChart(div, curYear) {
  const macro = (CHARTS.macro || [])
    .filter(r => r.year <= curYear).sort((a, b) => a.year - b.year);
  if (macro.length < 2) {
    div.innerHTML = '<p class="chart-hint">本馆历年数据不足（需两年以上），图表自第二年起显示。</p>';
    return;
  }
  const currency = CHARTS.currency || "";
  const num = v => Math.round(v).toLocaleString("en-US");
  const series = [
    { label: "GDP", unit: currency, color: "#7a3b2e", fmt: num,
      points: macro.map(r => ({ x: r.year, y: r.gdp, raw: r.gdp })) },
    { label: "人口", unit: "人", color: "#2f5d50", fmt: num,
      points: macro.map(r => ({ x: r.year, y: r.pop, raw: r.pop })) },
    { label: "生活水平", unit: "", color: "#8c6d1f",
      fmt: v => Number(v).toFixed(2),
      points: macro.map(r => ({ x: r.year, y: r.sol, raw: r.sol })) },
    { label: "识字率", unit: "%", color: "#4a6f8a",
      fmt: v => Number(v).toFixed(2) + "%",
      points: macro.map(r => ({ x: r.year, y: r.literacy, raw: r.literacy })) },
  ].filter(s => s.points.every(p => p.y != null));
  div.innerHTML = lineChartSvg(series);
}

function niceStep(range, target) {
  if (!(range > 0)) return 1;
  const rough = range / target;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  const n = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
  return n * mag;
}

function candleGeom(rows) {
  // 只保留左侧股价轴 (需求: K线图两侧竖轴太丑), 右留白收窄让蜡烛区更宽
  const W = 470, H = 232, ml = 54, mr = 16, mt = 22, mb = 30;
  const pw = W - ml - mr, ph = H - mt - mb;
  const years = [];
  for (let y = rows[0].year; y <= rows[rows.length - 1].year; y++) years.push(y);
  let lo = Math.min.apply(null, rows.map(r => r.low));
  let hi = Math.max.apply(null, rows.map(r => r.high));
  if (hi === lo) { hi += 1; lo -= 1; }
  const padY = (hi - lo) * 0.12;
  lo -= padY; hi += padY;
  const span = (years.length - 1) || 1;
  const X = y => ml + pw * (y - years[0]) / span;
  const Y = v => mt + ph - (v - lo) / (hi - lo) * ph;
  return { W, H, ml, mr, mt, mb, pw, ph, years, lo, hi, X, Y };
}

function candleChartSvg(rows, palette) {
  const g = candleGeom(rows);
  const { W, H, ml, mr, mt, mb, pw, years, lo, hi, X, Y } = g;
  const pal = palette || { up: "#1e7d46", down: "#b03a2e" };
  const fmt = v => Number(v).toFixed(0);
  const step = niceStep(hi - lo, 4);
  const t0 = Math.ceil(lo / step) * step;
  let grid = "", labels = "";
  for (let v = t0; v <= hi + 1e-9; v += step) {
    const y = Y(v);
    grid += `<line class="grid" x1="${ml}" y1="${y}" x2="${W - mr}" y2="${y}"/>`;
    labels += `<text class="axis" x="${ml - 8}" y="${y + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  years.forEach(y => {
    const x = X(y);
    grid += `<line class="grid-v" x1="${x}" y1="${mt}" x2="${x}" y2="${H - mb}"/>`;
    labels += `<text class="axis" x="${x}" y="${H - 10}" text-anchor="middle">${y}</text>`;
  });
  grid += `<line class="axis-line" x1="${ml}" y1="${mt}" x2="${ml}" y2="${H - mb}"/>`;
  grid += `<line class="axis-line" x1="${ml}" y1="${H - mb}" x2="${W - mr}" y2="${H - mb}"/>`;
  const band = pw / years.length;
  const cw = Math.max(4, Math.min(20, band * 0.55));
  let candles = "";
  rows.forEach(r => {
    const x = X(r.year);
    const col = r.close >= r.open ? pal.up : pal.down;
    const y1 = Y(Math.max(r.open, r.close));
    const y2 = Y(Math.min(r.open, r.close));
    const h = Math.max(2, y2 - y1);
    candles += `<g class="candle" data-year="${r.year}" data-o="${r.open}" data-h="${r.high}" data-l="${r.low}" data-c="${r.close}">`;
    candles += `<line x1="${x}" y1="${Y(r.high)}" x2="${x}" y2="${Y(r.low)}" stroke="${col}" stroke-width="1"/>`;
    candles += `<rect x="${x - cw / 2}" y="${y1}" width="${cw}" height="${h}" fill="${col}" rx="0.5"/>`;
    candles += `</g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" class="candle-svg">${grid}${labels}${candles}</svg>`;
}

function attachCandleTip(svg, rows) {
  const wrap = svg.closest(".stock-chart");
  if (!wrap) return;
  let tip = wrap.querySelector(".candle-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "candle-tip";
    wrap.appendChild(tip);
  }
  const g = candleGeom(rows);
  const band = g.pw / g.years.length;
  const cw = Math.max(4, Math.min(20, band * 0.55));
  svg.addEventListener("mousemove", ev => {
    const rect = svg.getBoundingClientRect();
    const sx = g.W / rect.width, sy = g.H / rect.height;
    const mx = (ev.clientX - rect.left) * sx;
    const my = (ev.clientY - rect.top) * sy;
    let best = null, bestD = 1e18;
    rows.forEach(r => {
      const d = Math.abs(g.X(r.year) - mx);
      if (d < bestD) { bestD = d; best = r; }
    });
    if (!best || bestD > cw / 2 + 8) { tip.style.display = "none"; return; }
    const chg = best.change_pct == null
      ? "<span class='up'>新设上市</span>"
      : `<span class="${best.change_pct >= 0 ? 'up' : 'down'}">${best.change_pct >= 0 ? "涨" : "跌"} ${Math.abs(best.change_pct).toFixed(1)}%</span>`;
    tip.innerHTML = `<b>${best.year}年</b> 开 ${best.open} · 收 ${best.close} · 高 ${best.high} · 低 ${best.low}　${chg}`;
    tip.style.display = "block";
    tip.style.left = Math.min(mx / sx + 14, wrap.clientWidth - 200) + "px";
    tip.style.top = Math.max(6, my / sy - 8) + "px";
  });
  svg.addEventListener("mouseleave", () => { tip.style.display = "none"; });
}

const PALETTES = {
  east: { up: "#b03a2e", down: "#1e7d46" },
  west: { up: "#1e7d46", down: "#b03a2e" },
};
const PALETTE_SOFT = {
  east: { up: "#f0a49a", down: "#7fd4a2" },
  west: { up: "#7fd4a2", down: "#f0a49a" },
};
let curStock = null;   // 当前选中的个股名 (跨年份保持)

function stockSub(s) {
  return [s.kind === "national" ? "国家级公司" : "地方企业",
          s.state, s.industries ? "主营" + s.industries : ""]
    .filter(Boolean).join(" · ") || s.name;
}

function stockTitle(s) {
  return s.orig && s.orig !== s.name ? `${esc(s.name)}（前身${esc(s.orig)}）` : esc(s.name);
}

function renderOneStock(s, pal) {
  return `<div class="stock-chart"><div class="chart-title">${stockTitle(s)}</div>`
       + candleChartSvg(s.rows, pal) + "</div>";
}

function renderStockChart(div, curYear) {
  // 退市年份映射: 当年被并购(target)/退市(name) 的企业当年仍可点击查看最后一根K线,
  // 次年该企业仅存于 data/raw_*.json, 不再出现在个股列表中
  const delistYear = {};
  (CHARTS.market || []).forEach(m => (m.events || []).forEach(ev => {
    if (ev.type === "merger" && ev.target) delistYear[ev.target] = m.year;
    if (ev.type === "delisting" && ev.name) delistYear[ev.name] = m.year;
  }));
  const stocks = (CHARTS.stock || [])
    .map(s => ({ ...s, rows: s.rows.filter(r => r.year <= curYear) }))
    .filter(s => s.rows.length && (s.rows[s.rows.length - 1].year === curYear
      || delistYear[s.name] === curYear));
  const exRows = (CHARTS.exchange || []).filter(r => r.year <= curYear);
  if (!stocks.length && !exRows.length) {
    div.innerHTML = '<p class="chart-hint">本期无个股行情数据，图表自交易所开市次年起显示。</p>';
    return;
  }
  const mode = CHARTS.palette === "east" ? "east" : "west";
  const pal = PALETTES[mode];
  div.style.setProperty("--up", pal.up);
  div.style.setProperty("--down", pal.down);
  div.style.setProperty("--up-soft", PALETTE_SOFT[mode].up);
  div.style.setProperty("--down-soft", PALETTE_SOFT[mode].down);

  // 板块标题 + 涨跌图例 (颜色随国家约定)
  let html = '<div class="stock-head"><span class="chart-title">股市</span>'
    + '<span class="stock-legend"><i style="background:' + pal.up + '"></i>涨'
    + '<i style="background:' + pal.down + '"></i>跌</span></div>';
  // 交易所指数置顶 (动态名: 市场中心州首府 hub 名 + 交易所指数)
  if (exRows.length) {
    const last = exRows[exRows.length - 1];
    const chg = last.change_pct;
    const hub = CHARTS.capital ? esc(CHARTS.capital) : "";
    const badge = chg == null ? ""
      : `<span class="chg-badge ${chg >= 0 ? "chg-up" : "chg-down"}">`
        + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%</span>";
    html += `<div class="stock-chart stock-exchange"><div class="chart-title">`
      + hub + "交易所指数" + badge + "</div>";
    html += candleChartSvg(exRows, pal) + "</div>";
  }
  // 个股按钮条 + 当前选中个股视图
  if (stocks.length) {
    if (curStock == null || !stocks.some(s => s.name === curStock)) {
      curStock = stocks[0].name;   // 默认选开市最早者 (stocks 已按首年排序)
    }
    html += '<div class="stock-btns">';
    stocks.forEach(s => {
      const r = s.rows[s.rows.length - 1];
      const chg = r ? r.change_pct : null;
      const badge = chg == null
        ? '<span class="chg new">新</span>'
        : `<span class="chg ${chg >= 0 ? "chg-up" : "chg-down"}">`
          + (chg >= 0 ? "+" : "-") + Math.abs(chg).toFixed(1) + "%</span>";
      html += `<button type="button" class="stock-btn${s.name === curStock ? " active" : ""}"`
        + ` data-name="${esc(s.name)}" title="${esc(stockSub(s))}">`
        + esc(s.name) + badge + "</button>";
    });
    html += "</div>";
    const cur = stocks.find(s => s.name === curStock);
    if (cur) html += '<div class="stock-pane">' + renderOneStock(cur, pal) + "</div>";
  }
  div.innerHTML = html;
  const attach = (svg, rows) => { if (svg && rows && rows.length) attachCandleTip(svg, rows); };
  attach(div.querySelector(".stock-exchange .candle-svg"), exRows);
  const cur0 = stocks.find(s => s.name === curStock);
  attach(div.querySelector(".stock-pane .candle-svg"), cur0 ? cur0.rows : null);
  div.querySelectorAll(".stock-btn").forEach(b => b.addEventListener("click", () => {
    curStock = b.dataset.name;
    const pane = div.querySelector(".stock-pane");
    const s = stocks.find(x => x.name === curStock);
    if (s && pane) {
      pane.innerHTML = renderOneStock(s, pal);
      attach(pane.querySelector(".candle-svg"), s.rows);
    }
    div.querySelectorAll(".stock-btn").forEach(x =>
      x.classList.toggle("active", x === b));
  }));
}

function renderCharts(root) {
  root.querySelectorAll(".chart").forEach(div => {
    const kind = div.dataset.chart;
    if (kind === "macro") renderMacroChart(div, year);
    else if (kind === "stock") renderStockChart(div, year);
  });
}

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
  renderCharts(stage);
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


def _parse_literacy(v):
    """识字率字段 ("9.58%" 或数值) → 浮点; 失败返回 None。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.rstrip("%").strip())
        except ValueError:
            return None
    return None


# 东亚国家名单 (与 journal_save._EAST_ASIAN_NAME_HINTS 保持同步;
# 用于股市涨跌颜色约定: 东亚红涨绿跌, 其余绿涨红跌)
_EAST_ASIAN_NAME_HINTS = ("大清", "日本", "德川", "朝鲜", "韩国", "大韩", "越南",
                          "大南", "安南", "琉球", "西藏", "蒙古", "中华", "中国")


def _is_east_asian(name):
    """玩家国名是否东亚国家 (子串命中任一即算)。"""
    if not name:
        return False
    return any(h in name for h in _EAST_ASIAN_NAME_HINTS)


def _collect_chart_data(base_dir):
    """读取会话 data/raw_*.json, 汇总图表历史:
    macro: 逐年 GDP/人口/生活水平/识字率;
    stock: 各标的逐年开收高低 (按 enterprise_id 分组, 兼容旧格式按 name;
           同名标的合并为一只, 兼容并购/退市后同名重新上市的历史数据);
    exchange: 交易所指数逐年开收高低 (自开市年连续);
    market: 逐年大盘概况 (涨跌家数/均值/领涨领跌/市场事件)。
    附带 player/capital (交易所指数命名用: 市场中心州首府 hub 名) 与
    palette ("east" 红涨绿跌 / "west" 绿涨红跌, 由玩家国名判定)。
    返回 {"macro": [...], "stock": [...], "exchange": [...], "market": [...],
          "currency": "...", "player": "...", "capital": "...", "palette": "..."}。
    结果同时落盘为 data/history.json (供程序直接读取)。"""
    data_dir = os.path.join(base_dir, "data")
    macro = []
    stock = {}
    exchange = []
    market = []
    currency = ""
    player = ""
    capital = ""
    if not os.path.isdir(data_dir):
        return {"macro": macro, "stock": [], "exchange": exchange,
                "market": market, "currency": currency, "player": player,
                "capital": capital,
                "palette": "east" if _is_east_asian(
                    player or os.path.basename(base_dir)) else "west"}
    for fn in sorted(os.listdir(data_dir)):
        m = re.fullmatch(r"raw_(\d{4})\.json", fn)
        if not m:
            continue
        try:
            with open(os.path.join(data_dir, fn), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue
        year = int(m.group(1))
        currency = currency or (raw.get("currency") or "")
        if raw.get("player"):
            player = raw["player"]       # 取最新年国名
        if raw.get("capital"):
            capital = raw["capital"]     # 取最新年首都 hub 名
        lit = _parse_literacy(raw.get("literacy"))
        macro.append({
            "year": year,
            "gdp": raw.get("gdp"),
            "pop": raw.get("pop"),
            "sol": raw.get("sol"),
            "literacy": lit,
        })
        sm = raw.get("stock_market") or {}
        market.append({
            "year": year,
            "advancers": sm.get("advancers"),
            "decliners": sm.get("decliners"),
            "avg_change": sm.get("avg_change"),
            "top_gainer": sm.get("top_gainer"),
            "top_loser": sm.get("top_loser"),
            "first_year": sm.get("first_year"),
            "events": sm.get("events") or [],
        })
        ex = sm.get("exchange_index") or {}
        if isinstance(ex, dict) and ex.get("close") is not None \
                and all(ex.get(k) is not None for k in ("open", "high", "low")):
            exchange.append({
                "year": year,
                "open": ex["open"], "high": ex["high"],
                "low": ex["low"], "close": ex["close"],
                "change_pct": ex.get("change_pct"),
            })
        for c in sm.get("companies") or []:
            name = c.get("name")
            if not name:
                continue
            key = c.get("enterprise_id") or name
            rec = stock.setdefault(key, {
                "id": key, "name": name, "orig": None,
                "kind": c.get("kind"),
                "state": c.get("state"), "industries": c.get("industries"),
                "rows": [],
            })
            rec["name"] = name   # 企业改名后图表沿用最新名
            # 企业改名后标注前身名
            nh = c.get("name_history") or []
            if nh and nh[0].get("name") != name and not rec.get("orig"):
                rec["orig"] = nh[0].get("name")
            if rec.get("kind") is None:
                rec["kind"] = c.get("kind")
            if rec.get("state") is None:
                rec["state"] = c.get("state")
            if rec.get("industries") is None:
                rec["industries"] = c.get("industries")
            if all(c.get(k) is not None
                   for k in ("open", "high", "low", "close")):
                rec["rows"].append({
                    "year": year,
                    "open": c["open"], "high": c["high"],
                    "low": c["low"], "close": c["close"],
                    "change_pct": c.get("change_pct"),
                    "band": c.get("band"), "note": c.get("note"),
                })
    macro.sort(key=lambda r: r["year"])
    market.sort(key=lambda r: r["year"])
    exchange.sort(key=lambda r: r["year"])
    for rec in stock.values():
        rec["rows"].sort(key=lambda r: r["year"])
    # 同名标的合并为一只 (兼容历史数据), 同名同年以较后企业为准 (确定性)
    merged = {}
    for rec in sorted(stock.values(),
                      key=lambda r: (r["rows"][0]["year"] if r["rows"] else 9999,
                                     r["id"])):
        nm = rec["name"]
        base = merged.get(nm)
        if base is None:
            merged[nm] = rec
            continue
        by_year = {r["year"]: r for r in base["rows"]}
        for r in rec["rows"]:
            by_year[r["year"]] = r
        base["rows"] = [by_year[y] for y in sorted(by_year)]
        for k in ("kind", "state", "industries", "orig"):
            if base.get(k) is None:
                base[k] = rec.get(k)
    stocks_out = list(merged.values())
    stocks_out.sort(key=lambda r: (r["rows"][0]["year"] if r["rows"] else 9999,
                                   r["name"]))
    return {"macro": macro, "stock": stocks_out, "exchange": exchange,
            "market": market, "currency": currency, "player": player,
            "capital": capital,
            "palette": "east" if _is_east_asian(
                player or os.path.basename(base_dir)) else "west"}


def _write_history_json(base_dir, charts):
    """把汇总图表历史落盘为 data/history.json, 供程序直接读取 (需求4)。"""
    import datetime
    data_dir = os.path.join(base_dir, "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        return None
    out = dict(charts)
    out["stocks"] = out.pop("stock", [])   # 对外 API 用 stocks, 内部 JS 沿用 stock
    out["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    path = os.path.join(data_dir, "history.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return None
    return path


def rebuild_session(journal_dir, folder):
    """为单个会话文件夹生成/更新 index.html 与 data/history.json; 无任何 md 时返回 None。"""
    base = os.path.join(journal_dir, folder)
    entries = _collect_entries(base)
    if not entries:
        return None
    charts = _collect_chart_data(base)
    _write_history_json(base, charts)
    title = f"{folder} · 报纸/杂志阅读页"
    out = (TEMPLATE
           .replace("__TITLE__", html.escape(title))
           .replace("__FOLDER__", html.escape(folder))
           .replace("__ARTICLES__", json.dumps(entries, ensure_ascii=False))
           .replace("__CHARTS__", json.dumps(charts, ensure_ascii=False)))
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
