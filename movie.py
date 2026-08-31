#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""维多利亚3 年度杂志附带的电影剧本生成 (movie.py)
=====================================================
每次杂志生成时, 按固定 7 槽叙事骨架生成一部剧本。骨架参考
Hollywood-Animal-Calculator (https://callon84.github.io/Hollywood-Animal-Calculator/)
的 Genre/Setting/Protagonist/Antagonist/Supporting/Theme&Event/Finale 结构,
类型体系采用其 11 种体裁 + 双体裁配比机制 (V3 化中文名, 见 journal_save.MOVIE_GENRES)。

分工:
- 槽位全部由 journal_save._movie_data 确定性选值 (种子=年份, 同年可复现),
  人物/地点/事件/数字全部来自真实存档;
- 本模块只负责把槽位值扩写成剧本散文: 片名 1 次 + 分幕 3 次调用 (full 模式),
  或 片名 1 次 + 全剧 1 次 (compact 模式);
- 输出独立文件 电影剧本_<年份>.md, 阅读页 (htmlview) 增加「电影剧本」页签。

电影技术判定 (B2 决策): 存档已研发 film 发明或年份达 1895 → 称「电影剧本」,
否则称「新剧」(7 槽骨架与生成流程不变, 仅称谓与格式微调)。
"""

import datetime
import os
import re

import journal


# ---------------------------------------------------------------------------
# 提示词规则 (全部正向表述, 无禁令词)
# ---------------------------------------------------------------------------

WORLD_FRAME_RULE = (
    "本刊的世界完全由本刊资料构成，与真实历史无关；所有国家、战争、人物、日期、"
    "数字一律以本提示词给出的数据为准；度量衡一律使用公制单位（吨、千克、千米、米、升、度、平方米）。"
)

SCREENPLAY_RULE = (
    "本剧为虚构作品，取材于本刊所记时事。给定人名、地名、日期、数字按原样使用；"
    "人物心理、对白、场景细节允许合情演绎；资料未给出姓名的人物以身份与职业代称；"
    "资料未给出的情节要素简写或略去。"
)


def _currency_rule(data):
    base = data.get("currency") or journal.DEFAULT_CURRENCY
    return (f"货币金额一律按资料给出的币种书写：{base}按「{journal.currency_system_text(base)}」"
            "书写。金额以资料给出者为限。")


# 分幕结构: 每幕只发相关槽位资料 (分板块思路, 让每幕聚焦自己的数据)
# 槽位映射: 序幕与第一幕=人物登场; 第二幕=主题事件推进; 第三幕与尾声=结局收束
ACTS = (
    ("序幕与第一幕",
     "立起人物与情境：以背景、主角、配角、反派展开开场与第一次冲突，交代时代与处境。",
     ("setting", "protagonist", "supporting", "antagonist")),
    ("第二幕",
     "事件展开与冲突升级：以主题/事件为核心推进情节，人物在事件中抉择与行动。",
     ("themes", "protagonist", "antagonist")),
    ("第三幕与尾声",
     "收束与结局：按编辑部给定的结局写作，为全剧落笔收束，交代人物去向。",
     ("finale", "protagonist")),
)


# ---------------------------------------------------------------------------
# 槽位文本渲染
# ---------------------------------------------------------------------------

def _genre_text(movie):
    gs = movie.get("genre") or []
    if not gs:
        return "未知"
    return " + ".join(
        f"{g.get('zh') or g.get('id')}（{g.get('percent')}%）" for g in gs)


def _char_fact(card, data=None):
    """角色卡 → 一行事实 (数值一律转自然语言: 生活水平/识字率用档名,
    月收支按币种主辅币格式化, 与杂志样本同口径)。"""
    if not card or not isinstance(card, dict):
        return "（未知）"
    name = card.get("name")
    role = card.get("role") or "未知身份"
    bits = []
    if card.get("culture"):
        bits.append(f"{card['culture']}人")
    if card.get("religion"):
        bits.append(card["religion"])
    if card.get("state"):
        bits.append(f"居于{card['state']}")
    if card.get("place"):
        bits.append(card["place"])
    if isinstance(card.get("sol"), (int, float)):
        band = journal.sol_band(card["sol"])
        bits.append(f"生活水平{band}" if band else f"生活水平{card['sol']}")
    if isinstance(card.get("literacy"), (int, float)):
        band = journal.literacy_band(card["literacy"])
        bits.append(f"识字率{band}")
    if card.get("family"):
        bits.append(f"家庭：{card['family']}")
    if (isinstance(card.get("income"), (int, float))
            and isinstance(card.get("expense"), (int, float))):
        unit = (data or {}).get("currency") or journal.DEFAULT_CURRENCY
        rate = journal._fx_rate(data, unit) if data else None
        bits.append("月收入约" + journal.format_money(
            journal._monthly(card["income"]), unit, rate)
            + "、月支出约" + journal.format_money(
                journal._monthly(card["expense"]), unit, rate))
    body = "，".join(bits)
    if name:
        return f"{name}（{role}）" + (f"，{body}" if body else "")
    return f"（{role}）" + (f"，{body}" if body else "")


def _setting_text(st):
    st = st or {}
    base = f"{st.get('capital') or '未知都城'}" + (
        f"，{st['state']}" if st.get("state") else "")
    if st.get("era"):
        base += f"；{st['era']}"
    return base


def _slots_block(movie, keys=None, data=None):
    """按槽位渲染资料块; keys 为 None 时渲染全部槽位。
    data 提供币种/汇率, 供角色卡金额按主辅币格式化。"""
    lines = []
    all_keys = ("setting", "protagonist", "antagonist", "supporting",
                "themes", "finale", "genre", "term")
    keys = all_keys if keys is None else keys
    if "term" in keys:
        lines.append("【剧种】" + str(movie.get("term") or "新剧"))
    if "genre" in keys:
        lines.append("【体裁】" + _genre_text(movie))
    if "setting" in keys:
        lines.append("【背景】" + _setting_text(movie.get("setting")))
    if "protagonist" in keys:
        lines.append("【主角】" + _char_fact(movie.get("protagonist"), data))
    if "antagonist" in keys:
        lines.append("【反派】" + _char_fact(movie.get("antagonist"), data))
    if "supporting" in keys:
        sup = movie.get("supporting") or []
        lines.append("【配角】" + ("；".join(_char_fact(c, data) for c in sup)
                                  if sup else "（暂无）"))
    if "themes" in keys:
        th = movie.get("themes") or []
        lines.append("【主题/事件】" + ("；".join(
            str(t.get("facts") or "") for t in th) if th else "（暂无）"))
    if "finale" in keys:
        fn = movie.get("finale") or {}
        lines.append("【结局】" + f"{fn.get('zh') or '未知'}（{fn.get('desc') or ''}）")
    return "\n".join(lines)


def _cast_names(movie):
    """人物名单块 (姓名已给定, 全文直接使用)。"""
    lines = ["人物名单（姓名已给定，全文直接使用）："]
    p = movie.get("protagonist") or {}
    a = movie.get("antagonist") or {}
    for label, c in (("主角", p), ("反派", a)):
        if c.get("name"):
            lines.append(f"- {label}：{c['name']}")
        else:
            lines.append(f"- {label}：{c.get('role') or '未知身份'}（姓名未给出，以身份代称）")
    for i, c in enumerate((movie.get("supporting") or [])[:3], 1):
        if c.get("name"):
            lines.append(f"- 配角{i}：{c['name']}")
        else:
            lines.append(f"- 配角{i}：{c.get('role') or '未知身份'}（姓名未给出，以身份代称）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 消息构建
# ---------------------------------------------------------------------------

def build_title_messages(movie, data):
    sys_msg = (
        "你是本刊特约的编剧。本刊的世界完全由本刊资料构成，与真实历史无关。\n\n"
        + SCREENPLAY_RULE + "\n" + WORLD_FRAME_RULE
        + "\n为本期剧本拟定一个正式片名：不超过12字，与给定要素一一对应。"
          "输出时只输出片名一行，紧贴行首。"
    )
    user_msg = _slots_block(movie, data=data)
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_act_messages(act_name, act_req, slot_keys, movie, data, title,
                       prev=None):
    sys_msg = (
        "你是本刊特约的编剧。本刊的世界完全由本刊资料构成，与真实历史无关。\n\n"
        + SCREENPLAY_RULE + "\n" + WORLD_FRAME_RULE + "\n" + _currency_rule(data)
    )
    user_msg = (
        f"本期剧本片名已定为《{title}》。\n\n"
        f"这是本剧的「{act_name}」部分。要求：{act_req}\n\n"
        f"篇幅要求：本部分正文800–1200字，分为2~4个自然段，段与段之间以空行分隔（Markdown段落）。\n\n"
        "正文使用Markdown格式，只输出本部分正文。\n\n"
        "相关数据如下（以资料给出者为限）：\n"
        + _slots_block(movie, slot_keys, data=data) + "\n\n" + _cast_names(movie)
        + (f"\n\n前文梗概：{prev}" if prev else "")
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_full_messages(movie, data, title):
    """compact 模式: 一次生成全剧。"""
    sys_msg = (
        "你是本刊特约的编剧。本刊的世界完全由本刊资料构成，与真实历史无关。\n\n"
        + SCREENPLAY_RULE + "\n" + WORLD_FRAME_RULE + "\n" + _currency_rule(data)
    )
    user_msg = (
        f"本期剧本片名已定为《{title}》。请按给定要素写全剧正文：\n\n"
        f"篇幅要求：全剧正文1500–2500字，按「序幕与第一幕／第二幕／第三幕与尾声」"
        "三部分展开，每部分2~3个自然段，段与段之间以空行分隔（Markdown段落），"
        "各部分之间以Markdown二级标题分隔。\n\n"
        "正文使用Markdown格式。\n\n"
        "相关数据如下（以资料给出者为限）：\n"
        + _slots_block(movie, data=data) + "\n\n" + _cast_names(movie)
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def _normalize_act(text):
    """清洗模型输出: 去掉开头的标题行, 单换行统一为空行分隔的段落。"""
    lines = [ln.rstrip() for ln in (text or "").split("\n")]
    while lines and re.match(r"^#{1,4}\s*", lines[0]):
        lines.pop(0)
    body = "\n".join(lines).strip()
    body = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", body)
    return body


def _generate_title(movie, data, cfg):
    try:
        msg = build_title_messages(movie, data)
        text = journal.call_deepseek(msg, cfg).strip()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return "未名之作"
        cand = re.sub(r"^[#\s]*", "", lines[0])
        cand = re.sub(r"^(?:片名[：:]|标题[：:])?\s*", "", cand).strip("《》 \t")
        if 2 <= len(cand) <= 12:
            return cand
    except Exception as e:
        journal.log(f"片名预生成失败: {e}")
    return "未名之作"


def _generate_full(movie, data, cfg, title):
    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 4000)
    acts = {}
    prev = None
    for act_name, act_req, slot_keys in ACTS:
        msg = build_act_messages(act_name, act_req, slot_keys, movie, data,
                                 title, prev=prev)
        text = journal.call_deepseek(msg, sec_cfg).strip()
        body = _normalize_act(text)
        acts[act_name] = body
        prev = body[-300:]
    return acts


def _generate_compact(movie, data, cfg, title):
    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 6000)
    msg = build_full_messages(movie, data, title)
    text = journal.call_deepseek(msg, sec_cfg).strip()
    return {"序幕与第一幕／第二幕／第三幕与尾声": _normalize_act(text)}


def _char_line(prefix, card):
    """登场人物表一行。"""
    if not card or not isinstance(card, dict):
        return f"- {prefix}（资料未给出人物）"
    name = card.get("name")
    role = card.get("role") or "未知身份"
    bits = []
    if card.get("culture"):
        bits.append(f"{card['culture']}族")
    if card.get("religion"):
        bits.append(card["religion"])
    if card.get("state"):
        bits.append(f"居于{card['state']}")
    if isinstance(card.get("sol"), (int, float)):
        band = journal.sol_band(card["sol"])
        bits.append(f"生活水平{band}" if band else f"生活水平{card['sol']}")
    if card.get("desc"):
        return f"- {prefix} {name or role}：{card['desc']}"
    head = f"{prefix} {name}" if name else f"{prefix}（{role}）"
    return "- " + head + ("，" + "，".join(bits) if bits else "")


def _assemble(movie, data, title, acts):
    st = movie.get("setting") or {}
    parts = [f"# 《{title}》",
             (f"国名：{data.get('player', '未知')}｜都城：{st.get('capital') or data.get('capital', '未知')}"
              f"｜年份：{data.get('year', '?')}"),
             (f"剧种：{movie.get('term') or '新剧'}｜体裁：{_genre_text(movie)}"
              f"｜结局：{(movie.get('finale') or {}).get('zh') or '未知'}"),
             "## 登场人物",
             _char_line("主角", movie.get("protagonist")),
             _char_line("反派", movie.get("antagonist"))]
    for i, c in enumerate((movie.get("supporting") or [])[:3], 1):
        parts.append(_char_line(f"配角{i}", c))
    if st.get("flavor"):
        parts.append("## 场景")
        parts.extend(list(st["flavor"]))
    for act_name, body in acts.items():
        parts.append(f"## {act_name}")
        parts.append(body)
    parts.append("—— 剧终 ——")
    return "\n\n".join(parts)


def _check_names(movie, acts):
    """人名校验 (软): 给定姓名 (全名或其「名」部分) 应在正文出现; 缺失仅记日志。"""
    given = {}
    for c in ([movie.get("protagonist"), movie.get("antagonist")]
              + list((movie.get("supporting") or [])[:3])):
        if c and isinstance(c, dict) and c.get("name"):
            name = c["name"]
            given[name] = name.split("·")[-1] if "·" in name else name
    if not given:
        return
    text = "\n".join(str(v) for v in (acts or {}).values())
    missing = [n for n, given_part in given.items()
               if n not in text and given_part not in text]
    if missing:
        journal.log(f"[movie] 人名校验(软): 以下给定姓名未在正文出现: {missing}")


def generate_movie(data, cfg, force=True):
    m = data.get("magazine") or {}
    movie = m.get("movie") or data.get("movie") or {}
    year = data.get("year")
    if not movie or movie.get("error"):
        journal.log(f"[{year}年] 电影剧本数据缺失, 已跳过")
        return
    folder = data.get("output_dir") or journal.SESSION.get("folder") or ""
    base_dir = os.path.join(cfg["journal_dir"], folder)
    movie_dir = os.path.join(base_dir, "电影剧本")
    try:
        os.makedirs(movie_dir, exist_ok=True)
    except Exception:
        pass
    path = os.path.join(movie_dir, f"电影剧本_{year}.md")
    if os.path.exists(path) and not force:
        journal.log(f"[{year}年] 电影剧本已存在, 跳过 (加 --force 重新生成): {path}")
        return
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key or "sk-" not in key or "这里" in key or "填写" in key:
        journal.log(f"[{year}年] 未配置 DeepSeek API Key, 已跳过电影剧本生成。")
        return
    try:
        title_cfg = dict(cfg)
        title_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 400)
        title = _generate_title(movie, data, title_cfg)
        movie["title"] = title
        if cfg.get("movie_script_mode", "full") == "compact":
            acts = _generate_compact(movie, data, cfg, title)
        else:
            acts = _generate_full(movie, data, cfg, title)
        movie["acts"] = acts
        _check_names(movie, acts)
        text = _assemble(movie, data, title, acts)
        header = (f"<!-- 数据来源: 维多利亚3 报纸Mod 电影剧本 | 报告日期: {data.get('date', '未知')} | "
                  f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + text.rstrip() + "\n")
        journal.log(f"[{year}年] 电影剧本已生成: {path}")
        try:
            import htmlview
            page = htmlview.rebuild_session(cfg["journal_dir"], folder)
            if page:
                journal.log(f"[{year}年] 阅读页已更新: {page}")
        except Exception as e:
            journal.log(f"[{year}年] 更新阅读页失败: {e}")
    except Exception as e:
        journal.log(f"[{year}年] 电影剧本生成失败: {e}")
