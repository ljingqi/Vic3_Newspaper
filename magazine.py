#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""维多利亚3 年度杂志生成 (magazine.py)
=======================================
与报纸 (journal.py) 平行: 同用存档快照与 DeepSeek, 但聚焦具体 POP 的民生访谈,
按政体决定整本杂志的基调。生成流程:
  杂志导言(1次) -> 三篇文章首板块(3次并发) -> 每篇后续三板块(9次并发) -> 组装。
非虚构文学风格: 给定事实(国名/人名/地名/日期/数字)不得改动, 细节允许作家演绎。

数据由 journal_save.build_magazine_data 提供 (真实存档: 战役/移民/升职/改信/士兵POP)。
"""

import datetime
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import journal


# ---------------------------------------------------------------------------
# 政体 -> 杂志基调 (需求3: 每个政体拥有自己的提示词)
# ---------------------------------------------------------------------------

GOVT_PROMPTS = {
    "council_republic": (
        "本刊为委员会制共和国的机关刊物，编辑立场站在工农与雇员一边。"
        "叙事重心放在劳动、集体、工厂与公社生活上；把职业转变视为阶级队伍的成长，"
        "把移民视为劳动者在世界范围内的流动，把战争中的士兵视为穿军装的工人。"
        "对旧贵族、教会与私人资本保持审视，鼓励读者以主人翁姿态看待国事。"
        "刊名宜带集体色彩，如《公社月刊》《工人之友》《人民纪事》。"
    ),
    "parliamentary_republic": (
        "本刊为议会制共和国的公共舆论平台，编辑立场尊重议会程序、政党竞争与公民权利。"
        "叙事重心放在法律辩论、内阁更迭与民意上；把职业转变视为个人奋斗与社会流动，"
        "把移民视为公民社会的新闻孔，把战争视为需要议会与舆论监督的国家行为。"
        "刊名宜带公民与公共色彩，如《共和国月刊》《公民纪事》《议会评论》。"
    ),
    "presidential_republic": (
        "本刊为总统制共和国的独立刊物，编辑立场崇尚宪法、联邦与个人自由。"
        "叙事重心放在行政权、边疆开发、市场与进步上；把职业转变写成拓荒者式的向上攀登，"
        "把移民写成新大陆的开拓者，把战争写成保卫共和国制度的斗争。"
        "刊名宜带自由与进步色彩，如《自由月刊》《合众国杂志》《进步纪事》。"
    ),
    "social_monarchy": (
        "本刊为社会君主立宪制下的改良刊物，编辑立场主张君民调和、改革与秩序并重。"
        "叙事重心放在王室象征、社会福利与渐进立法上；把职业转变写成国家扶持下的体面上升，"
        "把移民写成归化帝国的臣民，把战争写成君主统帅下的国家荣誉。"
        "刊名宜带王室与国家色彩，如《王室纪事月刊》《帝国社会评论》《御览杂志》。"
    ),
    "monarchy": (
        "本刊为君主制（帝国/王国）的宫廷与国民刊物，编辑立场忠于君主、尊崇传统与等级。"
        "叙事重心放在宫廷、贵族、帝国疆域与天命秩序上；把职业转变写成君恩与勤奋的回报，"
        "把移民写成受教化归化的新臣民，把战争写成君王御驾亲征的武功。"
        "刊名宜带宫廷与帝国色彩，如《宫廷月刊》《帝国纪事》《王冠杂志》。"
    ),
    "theocracy": (
        "本刊为神权制国家的宗教刊物，编辑立场以教义为准绳，关切信徒灵魂与俗世生活。"
        "叙事重心放在信仰、礼拜、教团与圣战上；把职业转变写成神明对勤劳者的眷顾，"
        "把移民写成来到真信之地的朝圣者，把改信写成归信的喜讯，把战争写成护教之战。"
        "刊名宜带神圣色彩，如《圣教月刊》《神谕纪事》《信众之友》。"
    ),
    "chiefdom": (
        "本刊为酋邦（部族联盟）的传统刊物，编辑立场尊重长老、土地、血缘与社群。"
        "叙事重心放在部落议事、丰收、征战与祖灵记忆上；把职业转变写成部族内部分工的演化，"
        "把移民写成邻邦来投的客民，把同化写成部族吸纳新血的传统。"
        "刊名宜带土地与部族色彩，如《酋邦纪事》《部落月刊》《篝火纪事》。"
    ),
    "other": (
        "本刊为该国当前政体下的时政与民生刊物，编辑立场中立克制，"
        "叙事重心放在具体人物的命运与时代大势的交汇处。"
        "刊名由首都或国名派生，如《XX月刊》《XX纪事》《XX杂志》。"
    ),
}


def _govt_category(data):
    """政体原始键 → 8 类基调 (与 mod GOVT type 分类一致)。"""
    key = str(data.get("govt_key") or data.get("govt") or "").lower()
    if any(k in key for k in ("council", "commune", "soviet")):
        return "council_republic"
    if "parliament" in key:
        return "parliamentary_republic"
    if any(k in key for k in ("president", "republic", "democracy", "technate",
                              "phalanstere")):
        return "presidential_republic"
    if any(k in key for k in ("theocra", "papal", "caliph", "imam", "priest",
                              "patriarch")):
        return "theocracy"
    if any(k in key for k in ("chief", "tribe", "clan", "khan", "horde",
                              "sultan", "emir")):
        return "chiefdom"
    if any(k in key for k in ("social", "welfare", "liberal")) and any(
            k in key for k in ("monarch", "empire", "kingdom")):
        return "social_monarchy"
    if any(k in key for k in ("monarch", "empire", "kingdom", "duchy",
                              "principality", "regency", "shah", "bakufu",
                              "shogun", "crown")):
        return "monarchy"
    return "other"


# ---------------------------------------------------------------------------
# 文章定义: 三篇文章 × 四板块 (需求2)
# ---------------------------------------------------------------------------

ARTICLES = [
    {
        "key": "war_family",
        "title": "战地与后方",
        "lead": "front",
        "sections": [
            {
                "key": "front",
                "title": "战地报道",
                "req": (
                    "报道真实战役: 发生地(州)、起止日期、攻守双方国家与将领、双方营数与兵力、"
                    "胜负。数据缺失时退而报道仍在进行或刚结束的战争。军队名未给出时, "
                    "可据将领姓名与家乡州合情拟名, 但不得虚构国家名或改动给定数字。"
                ),
                "facts": "front",
            },
            {
                "key": "soldier",
                "title": "士兵与营",
                "req": (
                    "以我方某营的步兵POP为主角(数据给出职业/文化/宗教/所在州/人数), "
                    "敌军同逻辑取一个营, 再加上当地平民POP, 写出战场三方处境对照。"
                    "营的番号与军队名可演绎, 但POP所在州、职业、人数等给定事实不得改动。"
                ),
                "facts": "soldier",
            },
            {
                "key": "homefront",
                "title": "后方家书",
                "req": (
                    "写士兵家乡(数据给出州名)的家人: 用给定的后方家庭POP(职业/文化/生活水平) "
                    "塑造人物, 以家书或邻居口述体呈现战争对后方家庭的影响。"
                ),
                "facts": "homefront",
            },
            {
                "key": "aftermath",
                "title": "战火余烬",
                "req": (
                    "报道战区平民处境: 给定州/地区的荒废度、污染、占领状态与伤亡规模, "
                    "写战争过后的民生、废墟与重建。"
                ),
                "facts": "aftermath",
            },
        ],
    },
    {
        "key": "court_household",
        "title": "庙堂与门庭",
        "lead": "minister",
        "sections": [
            {
                "key": "minister",
                "title": "大臣访谈",
                "req": (
                    "采访一位真实执政利益集团领袖(数据给出姓名/意识形态/集团/政治力量占比), "
                    "围绕其政见与施政方向展开。姓名缺失时用职务与集团代称, 不得虚构姓名。"
                ),
                "facts": "minister",
            },
            {
                "key": "decrees",
                "title": "政令与朝局",
                "req": (
                    "报道本年法律变化(数据给出新施行/废除的法律)、统治者活动、执政集团格局, "
                    "体现庙堂决策如何落到民生。"
                ),
                "facts": "decrees",
            },
            {
                "key": "household",
                "title": "大臣之家",
                "req": (
                    "写大臣家族的生活: 用给定首都或家乡州的上层POP(贵族/资本家/官僚) "
                    "塑造其家庭、府邸与门庭日常, 反映大人物身后的家庭世界。"
                ),
                "facts": "household",
            },
            {
                "key": "regime",
                "title": "体制与展望",
                "req": (
                    "按当前政体基调评价朝局: 政府合法性、主要政治运动、激进派/效忠派比例, "
                    "并展望来年大势。"
                ),
                "facts": "regime",
            },
        ],
    },
    {
        "key": "migration_change",
        "title": "迁徙与蜕变",
        "lead": "migrants",
        "sections": [
            {
                "key": "migrants",
                "title": "移民群像",
                "req": (
                    "报道真实迁移记录: 从哪个州到哪个州、人数、文化、宗教(数据给出)。"
                    "以具体POP为人物原型塑造移民离乡与抵达的故事。"
                ),
                "facts": "migrants",
            },
            {
                "key": "transformed",
                "title": "蜕变者",
                "req": (
                    "从跨年指纹中取一个真实发生职业转变的POP(数据给出旧职业→新职业、人数、所在州), "
                    "写其个人与家庭层面的转变故事。"
                ),
                "facts": "transformed",
            },
            {
                "key": "assimilation",
                "title": "同化与改信",
                "req": (
                    "报道正在改信(给定目标宗教)或同化(给定目标文化)的真实POP, "
                    "结合文化/宗教相关法律, 写信仰与身份在时代洪流中的变迁。"
                ),
                "facts": "assimilation",
            },
            {
                "key": "newhome",
                "title": "新家园与旧乡愁",
                "req": (
                    "写移民落地后的社会融合: 文化构成变化、接纳程度、旧乡愁与新家园对照, "
                    "为全文收束。"
                ),
                "facts": "newhome",
            },
        ],
    },
]

SECTION_FACTS = {s["key"]: s["facts"] for a in ARTICLES for s in a["sections"]}


NONFICTION_RULE = (
    "「非虚构文学」铁律: 给定的国家名、人名、地名、日期、数字、职业、文化、宗教必须原样使用, "
    "不得改动或替换; 人物的心理、对话、场景、信函等细节允许作家合情演绎; "
    "数据缺失的内容应简写或略去, 不得编造具体数字或国家/人名来填空。"
)

BATTLE_TYPE_ZH = {
    "land": "陆战",
    "naval": "海战",
    "naval_invasion_landing": "登陆战",
}

BATTLE_STATUS_ZH = {
    "attacker_victory": "攻方获胜",
    "defender_victory": "守方获胜",
}


# ---------------------------------------------------------------------------
# 事实渲染: 每个板块只看自己的数据 (与报纸同思路, 避免长提示词漏数据)
# ---------------------------------------------------------------------------

def _fmt_date(d):
    return str(d) if d else "未知"


def _fmt_num(v):
    if v is None:
        return "未知"
    if isinstance(v, float):
        return str(round(v, 3))
    return str(v)


def _fmt_battle(b):
    atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
    btype = BATTLE_TYPE_ZH.get(b.get("type"), b.get("type") or "未知")
    status = BATTLE_STATUS_ZH.get(b.get("status"), b.get("status") or "未知")
    lines = [
        f"- 战役: {b.get('place') or '地点未知'} | 类型: {btype} | "
        f"起: {_fmt_date(b.get('start_date'))} | 止: {_fmt_date(b.get('end_date'))} | "
        f"结果: {status}",
        f"- 攻方: {atk.get('country') or '未知'} | 将领: {atk.get('commander') or '未知'} | "
        f"营数: {atk.get('battalions_start')}→{atk.get('battalions_end')} | "
        f"兵力: {atk.get('manpower_start')}",
        f"- 守方: {dfd.get('country') or '未知'} | 将领: {dfd.get('commander') or '未知'} | "
        f"营数: {dfd.get('battalions_start')}→{dfd.get('battalions_end')} | "
        f"兵力: {dfd.get('manpower_start')}",
    ]
    if b.get("war_participants"):
        lines.append(f"- 相关战争参战方: {'、'.join(str(x) for x in b['war_participants'][:8])}")
    occ = b.get("occupation") or []
    if occ:
        lines.append("- 占领/波及州: " + "、".join(
            f"{o.get('name') or o.get('state')}({round((o.get('fraction') or 0) * 100)}%)"
            for o in occ[:4]))
    return "\n".join(lines)


def _fmt_pop(p):
    if not p:
        return None
    parts = [
        f"职业: {journal.POP_TYPE_NAMES.get(p.get('type'), p.get('type') or '未知')}",
        f"所在州: {p.get('state_name') or p.get('state') or '未知'}",
    ]
    if p.get("culture"):
        parts.append(f"文化: {p['culture']}")
    if p.get("religion"):
        parts.append(f"宗教: {p['religion']}")
    if p.get("workforce") is not None:
        parts.append(f"劳动力(人): {p['workforce']}")
    if p.get("sol") is not None:
        parts.append(f"生活水平: {p['sol']}")
    if p.get("wealth") is not None:
        parts.append(f"财富: {p['wealth']}")
    return " | ".join(parts)


def _facts_front(m):
    battles = m.get("battles") or []
    if not battles:
        return "本年无战役记录(可能战事较少或存档未保留)。"
    goals = m.get("war_goals") or []
    by_war = {}
    for g in goals:
        by_war.setdefault(g.get("war"), []).append(g)
    lines = []
    for b in battles[:3]:
        lines.append(_fmt_battle(b))
        wg = by_war.get(b.get("war")) or []
        if wg:
            lines.append("战争目的:")
            for g in wg[:5]:
                who = g.get("holder_zh") or "未知方"
                lines.append(f"- {who}（{g.get('demand_type_zh') or '目的'}）：{g.get('nl')}")
    return "\n".join(lines)


def _facts_soldier(m, data):
    soldiers = m.get("soldiers") or []
    civilians = m.get("civilians") or []
    lines = []
    formations = m.get("formations") or []
    units = m.get("units") or []
    if formations or units:
        lines.append("我方军团与营:")
        by_fm = {}
        for u in units:
            by_fm.setdefault(u.get("formation_name") or "未命名军团", []).append(u)
        for f in formations[:3]:
            fname = f.get("name") or f"第{f.get('ordinal_number')}{'军' if f.get('type') == 'army' else '舰队'}"
            uu = [u for u in units if str(u.get("formation")) == str(f.get("id"))]
            if uu:
                unames = "、".join(f"{u.get('name')}(兵员{u.get('manpower')})" for u in uu[:4])
                lines.append(f"- {fname}: {unames}" + ("等" if len(uu) > 4 else ""))
            else:
                lines.append(f"- {fname}")
    lines.append("我方士兵/军官POP(兵源样本):")
    for p in soldiers[:3]:
        lines.append("- " + _fmt_pop(p))
    battles = m.get("battles") or []
    if battles:
        b = battles[0]
        atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
        player = data.get("player")
        mine = atk if atk.get("country") == player else (dfd if dfd.get("country") == player else None)
        if mine is None:
            # 存档只保留到列强战役, 本场可能不直接含我方: 如实标注攻守双方
            lines.append(
                f"相关战事(存档仅保留列强战役, 我方未直接参战此役): 攻方 "
                f"{(atk or {}).get('country') or '未知'} (将领 {(atk or {}).get('commander') or '未知'}) | "
                f"守方 {(dfd or {}).get('country') or '未知'} (将领 {(dfd or {}).get('commander') or '未知'}) | "
                f"战场: {b.get('place') or '未知'} | "
                f"战期: {_fmt_date(b.get('start_date'))}~{_fmt_date(b.get('end_date'))}")
        else:
            enemy = dfd if mine is atk else atk
            lines.append(
                f"我方军队: {(mine or {}).get('country') or player or '未知'} "
                f"(将领 {(mine or {}).get('commander') or '未知'}, "
                f"家乡 {(mine or {}).get('commander_home') or '未知'}) | "
                f"敌军: {(enemy or {}).get('country') or '未知'} "
                f"(将领 {(enemy or {}).get('commander') or '未知'}) | "
                f"战场: {b.get('place') or '未知'} | "
                f"战期: {_fmt_date(b.get('start_date'))}~{_fmt_date(b.get('end_date'))}")
    ships = m.get("ships") or []
    if battles and battles[0].get("type") in ("naval", "naval_invasion_landing") and ships:
        cid_name = {}
        for b in battles:
            for side in ("attacker", "defender"):
                sd = b.get(side) or {}
                if sd.get("country_id") is not None and sd.get("country"):
                    cid_name[sd["country_id"]] = sd["country"]
        by_c = {}
        for s in ships:
            by_c.setdefault(s.get("country"), []).append(s)
        lines.append("双方舰船:")
        for cid2, ss in by_c.items():
            cname = cid_name.get(cid2, str(cid2))
            names = []
            for s in ss[:5]:
                if s.get("name") and s.get("type_zh"):
                    names.append(f"{s['name']}{s['type_zh']}")
                elif s.get("type_zh"):
                    names.append(f"一艘{s['type_zh']}")
            if names:
                lines.append(f"- {cname}: " + "、".join(names)
                             + ("等" if len(ss) > 5 else ""))
    lines.append("当地平民POP(战场州居民):")
    for p in civilians[:2]:
        lines.append("- " + _fmt_pop(p))
    return "\n".join(lines)


def _facts_homefront(m):
    fam = m.get("families") or []
    soldiers = m.get("soldiers") or []
    lines = ["后方家庭POP(士兵同州的平民):"]
    if fam:
        for p in fam[:3]:
            lines.append("- " + _fmt_pop(p))
    else:
        lines.append("(暂无与士兵同州的平民样本)")
    if soldiers:
        lines.append("士兵所在州: " + "、".join(
            str(s.get("state_name") or s.get("state")) for s in soldiers[:3]))
    return "\n".join(lines)


def _facts_aftermath(m):
    ws = m.get("war_states") or []
    lines = []
    if ws:
        lines.append("受战争影响的州(荒废度/污染):")
        for s in ws[:4]:
            lines.append(
                f"- {s.get('name')}: 荒废度 {s.get('devastation') or 0} | "
                f"污染 {s.get('pollution') or 0} | 主要文化 {s.get('top_culture') or '未知'}")
    else:
        lines.append("(无荒废度>0的玩家州)")
    wars = m.get("_last_year_wars") or []
    if wars:
        for w in wars[:2]:
            parts = list(dict.fromkeys(p.get("name") for p in (w.get("participants") or [])))
            lines.append(
                f"- 战争死伤(存档单位): 死亡 {w.get('casualties_total') or '未知'} | "
                f"负伤 {w.get('wounded_total') or '未知'} | "
                f"参战: {'、'.join(str(x) for x in parts[:6])}")
    battles = m.get("battles") or []
    if battles:
        for b in battles[:2]:
            atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
            morale = []
            for label, sd in (("攻方", atk), ("守方", dfd)):
                if sd.get("morale_start") is not None or sd.get("morale_end") is not None:
                    morale.append(
                        f"{label}士气 {_fmt_num(sd.get('morale_start'))}→{_fmt_num(sd.get('morale_end'))}")
            if morale:
                lines.append(
                    f"- 战役士气变化({b.get('place') or '地点未知'}): {' | '.join(morale)}")
    return "\n".join(lines)


def _facts_minister(m):
    cab = m.get("cabinet") or []
    ruler = m.get("ruler") or {}
    lines = []
    if ruler and ruler.get("name"):
        lines.append(f"统治者: {ruler.get('name')} ({ruler.get('title') or '未知'}, "
                     f"{ruler.get('ideology') or '意识形态未知'})")
    lines.append("执政利益集团(内阁大臣来源):")
    for g in cab[:4]:
        ig_zh = journal.IG_NAMES.get(g.get("name"),
                                     journal.IG_NAMES.get(g.get("definition"),
                                                          g.get("name")))
        lines.append(
            f"- {g.get('leader_name') or '姓名未知'} | 集团: {ig_zh} | "
            f"意识形态: {g.get('leader_ideology') or '未知'} | "
            f"政治力量占比: {g.get('clout_pct')}% | "
            f"家乡: {g.get('leader_home_region') or '未知'}")
    return "\n".join(lines) or "暂无执政集团数据。"


def _facts_decrees(m, data):
    lines = []
    if data.get("laws_enacted"):
        lines.append("本年新施行法律: " + "、".join(str(x) for x in data["laws_enacted"]))
    if data.get("laws_repealed"):
        lines.append("本年废除法律: " + "、".join(str(x) for x in data["laws_repealed"]))
    if data.get("laws_in_progress"):
        lines.append("立法进行中: " + "、".join(
            f"{x.get('law')}({x.get('phase_zh') or '进行中'})"
            for x in data["laws_in_progress"][:4]))
    ruler = m.get("ruler") or {}
    if ruler.get("activity"):
        lines.append(f"统治者活动: {ruler['activity']}")
    igs = data.get("interest_groups") or []
    if igs:
        lines.append("利益集团力量格局: " + "、".join(
            f"{g.get('name')}({g.get('clout_pct')}%)" for g in igs[:6]))
    return "\n".join(lines) or "本年无法律变化记录。"


def _facts_household(m, data):
    elites = m.get("elites") or []
    cap = data.get("capital") or "未知"
    lines = [f"首都/上层社会样本(大臣之家素材, 首都 {cap}):"]
    for p in elites[:3]:
        lines.append("- " + _fmt_pop(p))
    return "\n".join(lines)


def _facts_regime(m, data):
    lines = [
        f"政体: {data.get('govt_zh') or data.get('govt') or '未知'}",
        f"激进派占比: {data.get('radicals_pct')}% | 效忠派占比: {data.get('loyalists_pct')}%",
    ]
    movs = data.get("political_movements") or []
    if movs:
        lines.append("主要政治运动:")
        for mv in movs[:3]:
            lines.append(
                f"- {mv.get('name')} | 意识形态: {mv.get('ideology')} | "
                f"支持人数: {mv.get('supporters')} | 活跃度: {mv.get('activism')}")
    return "\n".join(lines)


def _facts_migrants(m):
    migs = m.get("migrations") or []
    if not migs:
        return "本年无玩家州迁出记录(可据人口与文化构成写平静的一年)。"
    lines = []
    for r in migs[:3]:
        pops = r.get("pop_list") or []
        lines.append(
            f"- 迁出: {r.get('origin_state') or '未知'} → 迁入: {r.get('target_name') or r.get('target_state') or '未知'} | "
            f"文化: {r.get('culture_zh') or '未知'} | 宗教: {r.get('religion_zh') or '未知'} | "
            f"迁出量(存档内部单位, 数值小=少量/涓流, 勿当作人数): {r.get('num')} | "
            f"涉及POP数: {len(pops)}")
    return "\n".join(lines)


def _facts_transformed(m):
    pros = m.get("promotions") or []
    if not pros:
        return "本年无跨年可比的职业转变样本(首次生成年无上年指纹, 或无人转变)。"
    lines = []
    for p in pros[:3]:
        lines.append(
            f"- {p.get('old_type')} → {p.get('new_type')} | 所在州: {p.get('state_name') or p.get('state')} | "
            f"劳动力(人): {p.get('workforce')} | 文化: {p.get('culture_zh') or p.get('culture') or '未知'} | "
            f"宗教: {p.get('religion_zh') or p.get('religion') or '未知'}")
    return "\n".join(lines)


def _facts_assimilation(m, data):
    convs = m.get("conversions") or []
    lines = []
    if convs:
        lines.append("正在改信/同化的真实POP:")
        for c in convs[:3]:
            extra = []
            if c.get("converting_to_religion"):
                extra.append(f"改信→{c['converting_to_religion']}")
            if c.get("assimilating_to_culture"):
                extra.append(f"同化→{c['assimilating_to_culture']}")
            lines.append("- " + _fmt_pop(c) + (" | " + "、".join(extra) if extra else ""))
    else:
        lines.append("(暂无改信/同化样本)")
    cult_laws = [str(x) for x in (data.get("laws") or []) if any(
        k in str(x) for k in ("文化", "宗教", "国教", "公民", "言论", "奴隶", "排斥"))]
    if cult_laws:
        lines.append("相关法律变动: " + "、".join(cult_laws))
    return "\n".join(lines)


def _facts_newhome(m, data):
    lines = []
    pc = data.get("pop_cultures") or []
    if pc:
        lines.append("人口文化构成(按占比): " + "、".join(
            f"{c.get('name')}({c.get('pct')}%)" for c in pc[:5]))
    prof = data.get("professions") or []
    if prof:
        lines.append("职业构成: " + "、".join(
            f"{journal.POP_TYPE_NAMES.get(p.get('name'), p.get('name'))}({p.get('pct')}%)"
            for p in prof[:5]))
    migs = m.get("migrations") or []
    if migs:
        lines.append("本期移民样本 " + str(len(migs)) + " 条(见移民群像板块)。")
    return "\n".join(lines)


def render_facts(article_key, section_key, data):
    m = data.get("magazine") or {}
    m["_last_year_wars"] = data.get("last_year_wars") or data.get("prev_year_wars") or []
    fn = {
        "front": lambda: _facts_front(m),
        "soldier": lambda: _facts_soldier(m, data),
        "homefront": lambda: _facts_homefront(m),
        "aftermath": lambda: _facts_aftermath(m),
        "minister": lambda: _facts_minister(m),
        "decrees": lambda: _facts_decrees(m, data),
        "household": lambda: _facts_household(m, data),
        "regime": lambda: _facts_regime(m, data),
        "migrants": lambda: _facts_migrants(m),
        "transformed": lambda: _facts_transformed(m),
        "assimilation": lambda: _facts_assimilation(m, data),
        "newhome": lambda: _facts_newhome(m, data),
    }[section_key]
    return fn()


# ---------------------------------------------------------------------------
# 提示词构建
# ---------------------------------------------------------------------------

def _voice(data):
    cat = _govt_category(data)
    return GOVT_PROMPTS.get(cat, GOVT_PROMPTS["other"])


def build_intro_messages(data):
    country = data.get("player", "未知")
    capital = data.get("capital", "未知")
    govt_zh = data.get("govt_zh") or data.get("govt") or "未知"
    year = data.get("year", "?")
    sys_msg = (
        f"你是《{country}》杂志的总编辑。本刊定位为19世纪的非虚构文学月刊, "
        "聚焦具体人物的命运, 以小人物与大人物映照时代大局。\n\n"
        f"本期关键变量(抬头必须原样保留):\n"
        f"【国名】{country}\n【都城】{capital}\n【政体】{govt_zh}\n【年份】{year}\n\n"
        f"本刊基调:\n{_voice(data)}\n\n"
        f"三篇特稿: ①《战地与后方》(前线士兵与后方家庭) ②《庙堂与门庭》(内阁大臣与他的家庭) "
        "③《迁徙与蜕变》(移民、升职者与改信者)。\n\n"
        f"{NONFICTION_RULE}\n"
        "请先拟定刊名(据都城/国名+政体惯例, 如《巴黎纪事月刊》), 撰写杂志导言: "
        "概括本年度大势, 预告三篇特稿, 并点明本刊的政体立场。"
        "输出格式:\n"
        "# 《刊名》\n"
        "国名：X｜都城：Y｜政体：Z｜年份：W\n\n"
        "导言正文..."
    )
    user_msg = (
        f"本期杂志: 【国名】{country}, 【都城】{capital}, 【政体】{govt_zh}, 【年份】{year}。"
        "请据上述变量拟定刊名并撰写导言。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _article_section(article_key, key):
    for a in ARTICLES:
        if a["key"] == article_key:
            for s in a["sections"]:
                if s["key"] == key:
                    return s
    return None


def build_lead_messages(article, data, intro):
    sec = article["sections"][0]
    country = data.get("player", "未知")
    facts = render_facts(article["key"], sec["key"], data)
    sys_msg = (
        f"你是本刊特稿《{article['title']}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"这是文章的开篇板块《{sec['title']}》, 需立起全篇的人物与场景。要求: {sec['req']}\n\n"
        f"{NONFICTION_RULE}"
    )
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"请撰写开篇板块《{sec['title']}》正文。相关数据如下(涉及国名请用【国名】={country}):\n"
        f"{facts}\n\n请直接输出板块正文(Markdown)。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_section_messages(article, section, data, intro, lead_text):
    country = data.get("player", "未知")
    facts = render_facts(article["key"], section["key"], data)
    sys_msg = (
        f"你是本刊特稿《{article['title']}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"请撰写板块《{section['title']}》。要求: {section['req']}\n\n"
        f"{NONFICTION_RULE}"
    )
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"本文开篇板块《{article['sections'][0]['title']}》已写成:\n{lead_text}\n\n"
        f"请撰写后续板块《{section['title']}》, 须与开篇呼应。相关数据(国名请用【国名】={country}):\n"
        f"{facts}\n\n请直接输出板块正文(Markdown)。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# 文本规范化与组装
# ---------------------------------------------------------------------------

_MAG_HEAD_RE = re.compile(r"^#{1,6}\s+")


def _normalize_section(text, title):
    """板块正文规范化: 所有标题降为 ###, 无标题时补 ### 板块名。"""
    out = []
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
        out.append(s)
    body = "\n".join(out).strip()
    first = next((ln for ln in body.split("\n") if ln.strip()), "")
    if not _MAG_HEAD_RE.match(first):
        return f"### {title}\n\n{body}"
    return body


def _build_article_list(data):
    """按数据可用性裁剪文章板块: 无真实升职/降职样本时跳过《蜕变者》。"""
    m = data.get("magazine") or {}
    has_promo = bool(m.get("promotions"))
    articles = []
    for a in ARTICLES:
        if a["key"] == "migration_change" and not has_promo:
            a2 = dict(a)
            a2["sections"] = [s for s in a["sections"] if s["key"] != "transformed"]
            if a2["sections"]:
                articles.append(a2)
        else:
            articles.append(a)
    return articles


def _assemble(intro, leads, sections, data, articles=None):
    parts = [intro]
    for a in (articles or ARTICLES):
        parts.append(f"## {a['title']}")
        parts.append(leads[a["key"]])
        for s in a["sections"][1:]:
            parts.append(sections[(a["key"], s["key"])])
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# 主流程 (需求2: 导言 -> 首板块(3并发) -> 后续三板块(9并发))
# ---------------------------------------------------------------------------

def generate_magazine(data, cfg, force=True):
    year = data.get("year")
    folder = data.get("output_dir") or journal.SESSION.get("folder") or ""
    base_dir = os.path.join(cfg["journal_dir"], folder)
    raw_dir = os.path.join(base_dir, "data")
    try:
        os.makedirs(raw_dir, exist_ok=True)
    except Exception:
        pass
    mag_path = os.path.join(base_dir, f"杂志_{year}.md")
    if os.path.exists(mag_path) and not force:
        journal.log(f"[{year}年] 杂志已存在, 跳过 (加 --force 或用 magazine 命令重新生成): {mag_path}")
        return
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key or "sk-" not in key or "这里" in key or "填写" in key:
        journal.log(f"[{year}年] 未配置 DeepSeek API Key, 已跳过杂志生成。")
        return

    try:
        with open(os.path.join(raw_dir, f"magazine_{year}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"year": year, "player": data.get("player"),
                       "magazine": data.get("magazine")},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        journal.log(f"[{year}年] 保存杂志数据失败: {e}")

    articles = _build_article_list(data)
    n_lead = len(articles)
    n_rest = sum(len(a["sections"]) - 1 for a in articles)
    journal.log(f"[{year}年] 开始生成杂志: 导言 + {n_lead}首板块 + {n_rest}板块 "
                f"(共{1 + n_lead + n_rest}次调用)...")
    intro_cfg = dict(cfg)
    intro_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 1500)
    intro = journal.call_deepseek(build_intro_messages(data), intro_cfg).strip()
    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 4000)

    def _gen_lead(article):
        try:
            msg = build_lead_messages(article, data, intro)
            text = journal.call_deepseek(msg, sec_cfg).strip()
            return article["key"], _normalize_section(text, article["sections"][0]["title"])
        except Exception as e:
            journal.log(f"首板块《{article['sections'][0]['title']}》生成失败: {e}")
            return article["key"], f"### {article['sections'][0]['title']}\n\n(本板块生成失败)"

    leads = {}
    with ThreadPoolExecutor(max_workers=len(articles)) as ex:
        futures = [ex.submit(_gen_lead, a) for a in articles]
        for f in futures:
            k, t = f.result()
            leads[k] = t

    def _gen_section(article, section):
        try:
            msg = build_section_messages(article, section, data, intro,
                                         leads[article["key"]])
            text = journal.call_deepseek(msg, sec_cfg).strip()
            return (article["key"], section["key"],
                    _normalize_section(text, section["title"]))
        except Exception as e:
            journal.log(f"板块《{section['title']}》生成失败: {e}")
            return (article["key"], section["key"],
                    f"### {section['title']}\n\n(本板块生成失败)")

    sections = {}
    jobs = [(a, s) for a in articles for s in a["sections"][1:]]
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = [ex.submit(_gen_section, a, s) for a, s in jobs]
        for f in futures:
            ak, sk, t = f.result()
            sections[(ak, sk)] = t

    text = _assemble(intro, leads, sections, data, articles=articles)
    header = (f"<!-- 数据来源: 维多利亚3 报纸Mod 杂志版 | 报告日期: {data.get('date', '未知')} | "
              f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
    try:
        with open(mag_path, "w", encoding="utf-8") as f:
            f.write(header + text.rstrip() + "\n")
        journal.log(f"[{year}年] 杂志已生成: {mag_path}")
    except Exception as e:
        journal.log(f"[{year}年] 写入杂志失败: {e}")
