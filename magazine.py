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
import copy
from concurrent.futures import ThreadPoolExecutor

import journal

import style


# 当前文风系统 (legacy/dynamic), 由 generate_magazine 从 cfg 设置。
_STYLE_SYSTEM = "legacy"


def _set_style_system(s):
    global _STYLE_SYSTEM
    _STYLE_SYSTEM = s or "legacy"


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
                    "胜负——以上一律以数据为准, 攻守双方不得互换或颠倒。只有数据给出战役细节时"
                    "才写战斗过程; 数据缺失时, 若存在进行中的战争, 只依据战争记录写态势; "
                    "否则本板块改写真切简短的旧战事回顾或和平景象, 绝不虚构战役地点、将领、"
                    "日期、兵力等数字。军队名未给出时, 可据将领姓名与家乡州合情拟名, "
                    "但不得虚构国家名或改动给定数字。"
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
                    "从跨年指纹中取一个真实发生职业转变的POP(数据给出旧职业、新职业、人数、所在州), "
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


# ---------------------------------------------------------------------------
# 文章池 (pool): 每期由 journal_save 按数据可用性抽取 3 篇。
# 文章标题不写死: default_title 仅作结构名/兜底, 实际标题由模型按
# style.resolve_magazine_title_guide 的文风指南拟题 (与文风档位联动)。
# 兜底文章走上方 ARTICLES (court/migration/war), 数据永远可用。
# ---------------------------------------------------------------------------

POOL = {
    "railway": {
        "default_title": "帝国铁道纪行",
        "theme": "铁路、蒸汽与沿线民生",
        "sections": [
            {"key": "lead", "title": "铁轨上的州", "req": (
                "报道铁路及其所在州：建筑等级、生产方法、所有权、投入产出一律以数据为准；"
                "以城市为舞台立起全篇的旅途与人物，不虚构车站名与里程。"
            )},
            {"key": "rural", "title": "乡村的货厢", "req": (
                "随铁路走访两座乡村（农场/矿场/林场/渔港）的建筑：等级、生产方法、"
                "所有权与投入产出用给定数据；写乡村货物如何经铁路外运。"
            )},
            {"key": "workers", "title": "站台上的人", "req": (
                "以铁路建筑中的中上层民众（官僚/职员/工程师/资本家等）为主角，"
                "写其工作场景与下班后的日子；职业、文化、宗教、人数、识字率等不得改动。"
            )},
            {"key": "life", "title": "车票的另一端", "req": (
                "写乡村建筑中下层民众（劳工/农民/矿工等）的生活，与开篇的铁路形成对照："
                "他们如何乘着铁路往返，以家书或邻人口述收束全篇。"
            )},
        ],
    },
    "turmoil": {
        "default_title": "在光辉以外的地方",
        "theme": "动乱州的运动、衙门与街垒",
        "sections": [
            {"key": "lead", "title": "阴影下的州", "req": (
                "报道动乱指数（按州内激进派占比估算）超过25%的州：总人口、激进派规模、"
                "阶层构成与全国对比，立起全篇的冲突氛围；口径以数据为准。"
            )},
            {"key": "movement", "title": "旗帜与人群", "req": (
                "聚焦该州支持度最高的政治运动：名称、思潮、激进档位、支持者规模与构成，"
                "写运动在街头的面貌，不虚构运动领袖姓名。"
            )},
            {"key": "institutions", "title": "衙门与法律", "req": (
                "报道相关现行法律（公民权/内部安全/教会与国家/言论）与该地机构覆盖，"
                "写政府如何回应或压制民间诉求。"
            )},
            {"key": "clash", "title": "街垒与公文", "req": (
                "写政府与群众的冲突场景：以给定运动数据与法律为据，描写街垒、公文与对峙，"
                "收束全篇，不得虚构具体伤亡数字。"
            )},
        ],
    },
    "shelf": {
        "default_title": "从货架里长出来的",
        "theme": "一件商品的产业链与家庭餐桌",
        "sections": [
            {"key": "lead", "title": "货架上的商品", "req": (
                "从贸易中心交易的大宗商品中取最活跃者（仅限我国境内有生产建筑的制成品，"
                "按市价推定，不得编造出口量），"
                "写它如何摆上货架：贸易中心等级、生产方法、所有权以数据为准。"
            )},
            {"key": "workshop", "title": "车间里的手", "req": (
                "写该商品本地生产建筑及其工人的工作场景：等级、生产方法、所有权、"
                "人数、识字率以数据为准，写从原料到成品的工序。"
            )},
            {"key": "mine", "title": "矿脉的尽头", "req": (
                "逆产业链向上游原料建筑（矿场/农场/林场，原材料分支随机）：写原料产地的"
                "工人如何把原料变成货架上的商品。"
            )},
            {"key": "customer", "title": "回家的路", "req": (
                "写目的地顾客买到商品后带回家的场景：家庭收支、识字、生活水平为据，"
                "收束全篇，不得编造具体价格以外的数字。"
            )},
        ],
    },
    "service": {
        "default_title": "为人民服务",
        "theme": "教育医疗与国家触角",
        "sections": [
            {"key": "lead", "title": "国家的触角", "req": (
                "报道教育/卫生/执法机构的投资等级与相关法律，写国家力量如何自上而下延伸"
                "到州县；机构与法律以数据为准。"
            )},
            {"key": "classroom", "title": "课堂与诊室", "req": (
                "以样本州的识字率、政府雇员与基层公职/教员，写学校与诊所的具体面貌，"
                "不虚构机构名称。"
            )},
            {"key": "grassroots", "title": "最基层的一天", "req": (
                "以随机州随机下层民众为主角，写国家服务覆盖到最基层的一日：识字、收支、"
                "接受度以数据为准，写课堂、诊室或衙门中的具体场景。"
            )},
            {"key": "lights", "title": "灯火与课本", "req": (
                "以全国识字率与激进派占比收束，展望国家与民众的关系，行文含蓄克制。"
            )},
        ],
    },
    "voting": {
        "default_title": "神圣庄严的权利",
        "theme": "选举权与门槛",
        "sections": [
            {"key": "lead", "title": "权利的法律", "req": (
                "报道权力分配法、公民权法、教会与国家法律及其效果，解释谁有权投票、"
                "谁被排除；法律名称以数据为准，效果描述可据法律条文演绎。"
            )},
            {"key": "gate", "title": "门槛与选票", "req": (
                "解读选民门槛：合格选民占政治参与人口比例、资格规则（财产/资格/显贵/"
                "普选/文化宗教排除），写门槛内外的人群。"
            )},
            {"key": "ballot", "title": "投票日", "req": (
                "以随机州随机POP为主角：程序已检定其是否拥有投票权，严格按检定结果写"
                "投票日履行权利或站在门外的场景，不得反转检定结果。"
            )},
            {"key": "future", "title": "来年的潮水", "req": (
                "以政治运动与立法动态收束，展望选举与权利的未来，不虚构立法结果。"
            )},
        ],
    },
    "price": {
        "default_title": "餐桌上的价格",
        "theme": "物价与家庭账本",
        "sections": [
            {"key": "lead", "title": "货架上的价签", "req": (
                "报道本年度物价涨落（以基准价为参照），写涨价与跌价最明显的商品；"
                "价格一律以数据为准，不得编造。"
            )},
            {"key": "household", "title": "餐桌上的账本", "req": (
                "以样本州一户下层家庭的收支、消费画像与恩格尔系数，写物价如何落在餐桌上，"
                "数据以给定为准。"
            )},
            {"key": "market", "title": "市场的涨落", "req": (
                "罗列几件商品的市价与基准价，写市场涨落背后的贸易与生产，不作价格预测。"
            )},
            {"key": "street", "title": "街市与生计", "req": (
                "以平均周薪与阶层结构收束，写百姓在物价中的生计，行文平实。"
            )},
        ],
    },
    "letters": {
        "default_title": "海外来信",
        "theme": "海外属地的家书",
        "sections": [
            {"key": "lead", "title": "海外的来信", "req": (
                "报道玩家未并入本土的海外属地：位置、城市名、主要文化、并入进度，"
                "立起一封家书的背景，不虚构地名。"
            )},
            {"key": "harbor", "title": "港口的抵达", "req": (
                "写属地港口与交易商品，信从港口寄出或抵达：港口建筑等级、生产方法、"
                "所有权与交易商品以数据为准。"
            )},
            {"key": "island", "title": "海外的日子", "req": (
                "以属地居民（多为下层）写海外生活的日常：文化、宗教、接受度、收支，"
                "写与本土不同的水土与人情。"
            )},
            {"key": "home", "title": "故乡的回信", "req": (
                "以首都本土家庭对照，写回信与乡愁：本土家庭样本数据为据，收束全篇。"
            )},
        ],
    },
}


# 接受度状态 → 军队与当地居民的关系基调 (和平年驻地板块动态使用)
ACCEPTANCE_GARRISON_TONES = {
    "full_acceptance": (
        "军民鱼水情",
        "当地社会完全接纳驻军，军民互信互助、亲如一家，可写军民同乐、互助共建的融洽场景。",
    ),
    "open_prejudice": (
        "军民隔阂",
        "当地人对驻军或外来者公开歧视，军民关系疏离克制，可写彼此保持距离、礼节性往来的场景。",
    ),
    "second_rate_citizen": (
        "二等公民待遇",
        "当地把驻军或外来者当二等公民看待，军民之间存在明显身份落差，可写隐忍与隔膜并存的日常。",
    ),
    "cultural_erasure": (
        "文化压制",
        "驻军代表的文化在当地占压倒地位，本地文化正被抹除同化，可写军队推行教化与本地人失语的场景。",
    ),
    "violent_hostility": (
        "殖民者做派",
        "当地社会与驻军暴力敌对，军队以占领者姿态行事，可写戒严、冲突与仇恨交织的场面。",
    ),
}


def _dominant_acceptance(pops):
    """样本POP → 出现次数最多的接受度状态; 无样本返回 None。"""
    cnt = {}
    for p in pops or []:
        s = p.get("acceptance_status")
        if s:
            cnt[s] = cnt.get(s, 0) + 1
    if not cnt:
        return None
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def _acceptance_zh(status):
    """接受度状态 key → 中文区间文字; 未知返回 None。"""
    if not status:
        return None
    return journal.ACCEPTANCE_NAMES.get(status, status)


def _war_article_variant(data):
    """文章一《战地与后方》按是否爆发战争切换结构:
    战争年 → 战地报道/士兵与营/后方家书/战火余烬;
    和平年 → 驻地与训练/士兵与营/后方家书/(营区与驻地民生, 仅玩家州有荒废时保留)。"""
    m = data.get("magazine") or {}
    at_war = data.get("player_at_war")
    if at_war is None:
        at_war = m.get("player_at_war")
    if at_war:
        return dict(ARTICLES[0])
    a = dict(ARTICLES[0])
    a["title"] = "军营与家园"
    local_pops = (m.get("soldiers") or []) + (m.get("civilians") or [])
    dom_acc = _dominant_acceptance(local_pops)
    tone_name, tone_req = ACCEPTANCE_GARRISON_TONES.get(
        dom_acc, ("军民日常相处", "写军队与当地居民的日常相处。"))
    secs = []
    for s in ARTICLES[0]["sections"]:
        s2 = dict(s)
        if s["key"] == "front":
            s2["key"] = "garrison"
            s2["title"] = "驻地与训练"
            s2["facts"] = "garrison"
            s2["req"] = (
                "报道我国军队的驻地生活: 数据给出军团/营的番号、兵员与驻地, 士兵POP的"
                "职业/文化/宗教/所在州/人数。写军队在驻地操演训练、整饬营务，与当地人"
                "相处。驻地军民关系基调: " + tone_name + "。" + tone_req
            )
            secs.append(s2)
        elif s["key"] == "soldier":
            s2["req"] = (
                "以我方某营的步兵POP为主角(数据给出职业/文化/宗教/所在州/人数), "
                "结合当地平民POP, 写出驻军士兵的群像、营中日常与军民相处。驻地军民关系基调: "
                + tone_name + "。" + tone_req +
                "当前我国无战事、亦无敌军资料, 请据驻军生活展开。"
            )
            secs.append(s2)
        elif s["key"] == "homefront":
            s2["req"] = (
                "写士兵家乡(数据给出州名)的家人: 用给定的后方家庭POP(职业/文化/生活水平) "
                "塑造人物, 以家书或邻居口述体呈现和平时期军属家庭的日常与牵挂。"
            )
            secs.append(s2)
        elif s["key"] == "aftermath":
            if m.get("war_states"):
                s2["title"] = "营区与驻地民生"
                s2["req"] = (
                    "报道驻军所在地的民生状况: 给定州的荒废度/污染档位、主要文化, "
                    "写驻军与当地民众共同生活的面貌与地方恢复建设。驻地军民关系基调: "
                    + tone_name + "。" + tone_req
                )
                secs.append(s2)
        else:
            secs.append(s2)
    a["sections"] = secs
    return a


NONFICTION_RULE = (
    "「非虚构文学」铁律: 给定的国家名、人名、地名、日期、数字、职业、文化、宗教必须原样使用, "
    "不得改动或替换; 人物的心理、对话、场景、信函等细节允许作家合情演绎; "
    "数据缺失的内容应简写或略去, 不得编造具体数字或国家/人名来填空。"
)

WORLD_FRAME_RULE = (
    "「平行世界规则」: 本刊报道的世界由程序提供的存档数据构成, 与任何真实历史无关。"
    "所有国家、战争、边界、统治者、人物、日期、数字一律以本提示词给出的数据为准; "
    "数据未提供的即视为不存在或未知, 不得调用真实历史事件/人物/战役(如巴拉圭战争、"
    "真实将领)或常识补写, 不得虚构国家名、战役名、将领名与具体数字。宁可写得含蓄, 也不可编造。"
)

BATTLE_TYPE_ZH = {
    "land": "陆战",
    "naval": "海战",
    "naval_invasion_landing": "登陆战",
    "raid_supply": "袭扰补给",
    "invasion": "登陆作战",
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


def _fmt_int(v):
    """整数加千分位; 非法输入返回 None。"""
    if not isinstance(v, (int, float)):
        return None
    return format(int(round(v)), ",")


def _morale_band(v):
    """士气数值 → 档位名 (提示词用自然语言, 不传裸数字)。"""
    if not isinstance(v, (int, float)):
        return None
    if v >= 0.9:
        return "高昂"
    if v >= 0.7:
        return "稳定"
    if v >= 0.4:
        return "动摇"
    if v >= 0.1:
        return "濒临崩溃"
    return "崩溃"


def _morale_change(start, end):
    """起止士气 → 自然语言, 如「由稳定跌至崩溃」「维持高昂」。"""
    s, e = _morale_band(start), _morale_band(end)
    if s is None and e is None:
        return None
    if s is None:
        return f"士气为{e}"
    if e is None:
        return f"士气自{s}起"
    if s == e:
        return f"士气维持{s}"
    if (end or 0) > (start or 0):
        return f"士气由{s}回升至{e}"
    return f"士气由{s}跌至{e}"


def _battalion_change(start, end):
    """营数起止 → 自然语言, 如「参战19营, 战后全军覆没」「保持19营完整」。"""
    if start is None:
        return None
    s = int(round(start))
    if end is None or int(round(end)) == s:
        return f"参战{s}营"
    e = int(round(end))
    if e == 0:
        return f"参战{s}营，战后全军覆没"
    if e < s:
        return f"参战{s}营，战后仅余{e}营"
    return f"参战{s}营，战后增至{e}营"


def _manpower_phrase(men, battalions):
    """兵力(人) → 自然语言; 满编比例过小时不输出离谱的精确人数。
    例: 1营1人 → 「兵力近乎空虚」; 19营3433人 → 「兵力严重不足(约3,433人)」。"""
    if men is None:
        return None
    if isinstance(battalions, (int, float)) and battalions > 0:
        frac = men / (battalions * 1000.0)
        if frac < 0.05:
            return "兵力近乎空虚"
        if frac < 0.2:
            return f"兵力严重不足（约{_fmt_int(men)}人）"
    return f"兵力约{_fmt_int(men)}人"


def _unit_manpower(mp):
    """营/舰船兵员 → 括号说明; 空编不输出人数。"""
    if mp is None:
        return ""
    if mp <= 0:
        return "（空编）"
    return f"（兵员{_fmt_int(mp)}人）"


def _fmt_battle(b):
    atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
    btype = BATTLE_TYPE_ZH.get(b.get("type"), b.get("type") or "未知")
    status = BATTLE_STATUS_ZH.get(b.get("status"), b.get("status") or "未知")
    place = b.get("place") or "地点未知"
    lines = [
        f"{btype}发生于{place}，自{_fmt_date(b.get('start_date'))}至"
        f"{_fmt_date(b.get('end_date'))}，以{status}告终。",
    ]
    for label, sd in (("攻方", atk), ("守方", dfd)):
        if not sd:
            continue
        bits = [f"{label}为{sd.get('country') or '未知'}，由{sd.get('commander') or '未知'}统帅"]
        bc = _battalion_change(sd.get("battalions_start"), sd.get("battalions_end"))
        if bc:
            bits.append(bc)
        ships = sd.get("ships_start")
        if ships is not None:
            s = int(round(ships))
            se = sd.get("ships_end")
            if se is None or int(round(se)) == s:
                bits.append(f"参战{s}艘")
            else:
                e = int(round(se))
                if e <= 0:
                    bits.append(f"参战{s}艘，战后全数沉没")
                else:
                    bits.append(f"参战{s}艘，战后仅余{e}艘")
        mp = _manpower_phrase(sd.get("manpower_start"),
                              sd.get("battalions_start") or sd.get("initial_size"))
        if mp:
            bits.append(mp)
        lines.append("，".join(bits) + "。")
    if b.get("war_participants"):
        lines.append("该役所属战争参战方包括：" + "、".join(
            str(x) for x in b["war_participants"][:8]) + "。")
    occ = b.get("occupation") or []
    if occ:
        lines.append("波及州包括：" + "、".join(
            f"{o.get('name') or o.get('state')}（约{round((o.get('fraction') or 0) * 100)}%被占）"
            for o in occ[:4]) + "。")
    return "\n".join(lines)


def _fmt_pop(p):
    """POP 样本 → 自然语言: 身份/州/人数/生活水平档位 (不输出财富)。"""
    if not p:
        return None
    t = journal.POP_TYPE_NAMES.get(p.get("type"), p.get("type") or "未知职业")
    state = p.get("state_name") or p.get("state") or "未知州"
    if p.get("culture") and p.get("religion"):
        who = f"{p['religion']}{p['culture']}的{t}"
    elif p.get("culture"):
        who = f"{p['culture']}的{t}"
    elif p.get("religion"):
        who = f"{p['religion']}信徒中的{t}"
    else:
        who = t
    bits = [f"{who}居住于{state}"]
    if p.get("workforce") is not None:
        bits.append(f"劳动力约{_fmt_int(p['workforce'])}人")
    band = journal.sol_band(p.get("sol"))
    if band:
        bits.append(f"生活水平{band}")
    acc = _acceptance_zh(p.get("acceptance_status"))
    if acc:
        bits.append(f"当地接受度为{acc}")
    return "，".join(bits) + "。"


def _facts_front(m, data):
    battles = m.get("battles") or []
    wars = m.get("_player_wars") or []
    goals = m.get("war_goals") or []
    if not battles and not wars:
        return "本年我国无战事记录。"
    by_war = {}
    for g in goals:
        by_war.setdefault(g.get("war"), []).append(g)
    lines = []
    shown_goal_wars = set()
    if battles:
        for b in battles[:3]:
            lines.append(_fmt_battle(b))
            wg = by_war.get(b.get("war")) or []
            if wg and b.get("war") not in shown_goal_wars:
                shown_goal_wars.add(b.get("war"))
                lines.append("战争目的：")
                for g in wg[:5]:
                    lines.append(f"- {g.get('nl') or '未知'}")
    if not battles and wars:
        lines.append("存档未保留我方战役细节，依战争记录报道：")
        for w in wars[:2]:
            ps = [p.get("name") for p in (w.get("participants") or []) if p.get("name")]
            status = "已结束" if w.get("ended") else "仍在进行"
            line = f"- 我国参与的战争：{'、'.join(str(x) for x in ps[:8])}，{status}"
            if w.get("start_date"):
                line += f"，自{w['start_date']}起"
            lines.append(line + "。")
            try:
                wid = int(w.get("id"))
            except (TypeError, ValueError):
                wid = None
            wg = by_war.get(wid) if wid is not None else None
            wg = wg or []
            if wg and wid not in shown_goal_wars:
                shown_goal_wars.add(wid)
                lines.append("战争目的：")
                for g in wg[:5]:
                    lines.append(f"- {g.get('nl') or '未知'}")
    return "\n".join(lines)


def _facts_soldier(m, data, peacetime=False):
    soldiers = m.get("soldiers") or []
    civilians = m.get("civilians") or []
    lines = []
    if peacetime:
        lines.append("当前我国无战事记录，亦无敌军资料。")
        local_pops = (m.get("soldiers") or []) + (m.get("civilians") or [])
        dom = _dominant_acceptance(local_pops)
        tone_name, _tone_req = ACCEPTANCE_GARRISON_TONES.get(dom, (None, None))
        if dom and tone_name:
            lines.append(f"驻地军民关系基调：{tone_name}（当地接受度为{_acceptance_zh(dom)}）。")
    formations = m.get("formations") or []
    units = m.get("units") or []
    if formations or units:
        lines.append("我方军团与营：")
        for f in formations[:3]:
            fname = (f.get("name")
                     or f"第{f.get('ordinal_number')}{'军' if f.get('type') == 'army' else '舰队'}")
            uu = [u for u in units if str(u.get("formation")) == str(f.get("id"))]
            if uu:
                unames = "、".join(
                    f"{u.get('name')}{_unit_manpower(u.get('manpower'))}"
                    for u in uu[:4])
                lines.append(f"- {fname}：{unames}" + ("等" if len(uu) > 4 else ""))
            else:
                lines.append(f"- {fname}")
    lines.append("我方士兵/军官POP（兵源样本）：")
    for p in soldiers[:3]:
        lines.append("- " + _fmt_pop(p))
    battles = m.get("battles") or []
    if not peacetime and battles:
        b = battles[0]
        atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
        player = data.get("player")
        mine = atk if atk.get("country") == player else (dfd if dfd.get("country") == player else None)
        if mine is not None:
            enemy = dfd if mine is atk else atk
            lines.append(
                f"相关战事：我方（{mine.get('country') or player or '未知'}，"
                f"将领{mine.get('commander') or '未知'}）与敌军"
                f"（{enemy.get('country') or '未知'}，将领{enemy.get('commander') or '未知'}）"
                f"在{b.get('place') or '未知地点'}交战，"
                f"战期自{_fmt_date(b.get('start_date'))}至{_fmt_date(b.get('end_date'))}。")
    elif not peacetime and not battles:
        wars = m.get("_player_wars") or []
        if wars:
            w = wars[0]
            player = data.get("player")
            pid = data.get("player_country_id")
            others = []
            for p in (w.get("participants") or []):
                nm = p.get("name")
                if not nm or nm == player:
                    continue
                if pid is not None and p.get("id") == pid:
                    continue
                others.append(nm)
            if others:
                lines.append("我方战争对象：" + "、".join(
                    dict.fromkeys(str(x) for x in others)) + "。")
    ships = m.get("ships") or []
    if (not peacetime and battles
            and battles[0].get("naval") and ships):
        cid_name = {}
        for b in battles:
            for side in ("attacker", "defender"):
                sd = b.get(side) or {}
                if sd.get("country_id") is not None and sd.get("country"):
                    cid_name[sd["country_id"]] = sd["country"]
        by_c = {}
        for s in ships:
            by_c.setdefault(s.get("country"), []).append(s)
        lines.append("双方舰船：")
        for cid2, ss in by_c.items():
            cname = cid_name.get(cid2, str(cid2))
            names = []
            for s in ss[:5]:
                if s.get("name") and s.get("type_zh"):
                    names.append(f"{s['name']}{s['type_zh']}")
                elif s.get("type_zh"):
                    names.append(f"一艘{s['type_zh']}")
            if names:
                lines.append("- " + cname + "：" + "、".join(names)
                             + ("等" if len(ss) > 5 else ""))
    lines.append("当地平民POP（" + ("驻军所在州" if peacetime else "战场/驻军所在州") + "居民）：")
    for p in civilians[:2]:
        lines.append("- " + _fmt_pop(p))
    return "\n".join(lines)


def _facts_garrison(m, data):
    """和平年「驻地与训练」: 军团/营、士兵POP与驻地平民, 不含战役。"""
    return _facts_soldier(m, data, peacetime=True)


def _facts_homefront(m):
    fam = m.get("families") or []
    soldiers = m.get("soldiers") or []
    lines = ["后方家庭POP（士兵同州的平民）："]
    if fam:
        for p in fam[:3]:
            lines.append("- " + _fmt_pop(p))
    else:
        lines.append("（暂无与士兵同州的平民样本）")
    if soldiers:
        st = list(dict.fromkeys(
            str(s.get("state_name") or s.get("state"))
            for s in soldiers[:3] if s.get("state_name") or s.get("state")))
        if st:
            lines.append("士兵所在州：" + "、".join(st) + "。")
    return "\n".join(lines)


def _facts_aftermath(m):
    ws = m.get("war_states") or []
    lines = []
    if ws:
        lines.append("受战争影响或驻军所在地的州（荒废度/污染为档位）：")
        for s in ws[:4]:
            bits = [f"{s.get('name') or '未知州'}"]
            dev = s.get("devastation")
            pol = s.get("pollution")
            if isinstance(dev, (int, float)) and dev > 0:
                bits.append(f"荒废度{journal._devastation_band(dev)}")
            if isinstance(pol, (int, float)) and pol > 0:
                bits.append(f"污染{journal._pollution_band(pol)}")
            if s.get("top_culture"):
                bits.append(f"主要文化为{s['top_culture']}")
            lines.append("- " + "，".join(bits) + "。")
    else:
        lines.append("（无荒废度>0的玩家州）")
    wars = m.get("_player_wars") or []
    if wars:
        for w in wars[:2]:
            parts = list(dict.fromkeys(
                p.get("name") for p in (w.get("participants") or []) if p.get("name")))
            bits = []
            cas = w.get("casualties_total")
            wnd = w.get("wounded_total")
            if isinstance(cas, (int, float)):
                bits.append(f"阵亡及失踪约{_fmt_int(cas * 100000)}人")
            if isinstance(wnd, (int, float)):
                bits.append(f"负伤约{_fmt_int(wnd * 100000)}人")
            if bits:
                lines.append(f"- 参战方{'、'.join(str(x) for x in parts[:6])}的战争累计"
                             + "，".join(bits) + "。")
    battles = m.get("battles") or []
    if battles:
        for b in battles[:2]:
            atk, dfd = b.get("attacker") or {}, b.get("defender") or {}
            mc = _morale_change(atk.get("morale_start"), atk.get("morale_end"))
            md = _morale_change(dfd.get("morale_start"), dfd.get("morale_end"))
            if mc or md:
                bits = []
                if mc:
                    bits.append("攻方" + mc)
                if md:
                    bits.append("守方" + md)
                lines.append(f"- {b.get('place') or '地点未知'}一役，" + "，".join(bits) + "。")
    return "\n".join(lines)


def _facts_minister(m):
    cab = m.get("cabinet") or []
    ruler = m.get("ruler") or {}
    lines = []
    if ruler and ruler.get("name"):
        lines.append(f"统治者{ruler['name']}，头衔{ruler.get('title') or '未知'}，"
                     f"意识形态{ruler.get('ideology') or '意识形态未知'}。")
    lines.append("执政利益集团（内阁大臣来源）：")
    for g in cab[:4]:
        ig_zh = journal.IG_NAMES.get(g.get("name"),
                                     journal.IG_NAMES.get(g.get("definition"),
                                                          g.get("name")))
        bits = []
        if g.get("leader_name"):
            bits.append(f"大臣{g['leader_name']}")
        else:
            bits.append("姓名未知")
        bits.append(f"来自{ig_zh}")
        if g.get("leader_ideology"):
            bits.append(f"意识形态为{g['leader_ideology']}")
        if isinstance(g.get("clout_pct"), (int, float)):
            bits.append(f"政治力量占比约{g['clout_pct']:.1f}%")
        if g.get("leader_home_region"):
            bits.append(f"家乡在{g['leader_home_region']}")
        lines.append("- " + "，".join(bits) + "。")
    return "\n".join(lines) or "暂无执政集团数据。"


def _facts_decrees(m, data):
    lines = []
    if data.get("laws_enacted"):
        lines.append("本年新施行法律：" + "、".join(
            journal.law_zh(str(x)) for x in data["laws_enacted"]))
    else:
        lines.append("本年无新施行法律。")
    if data.get("laws_repealed"):
        lines.append("本年废除法律：" + "、".join(
            journal.law_zh(str(x)) for x in data["laws_repealed"]))
    else:
        lines.append("本年无废除法律。")
    if data.get("laws_in_progress"):
        lines.append("立法进行中：" + "、".join(
            f"{journal.law_zh(str(x.get('law')))}（{x.get('phase_zh') or '进行中'}）"
            for x in data["laws_in_progress"][:4]))
    else:
        lines.append("今年无正在制定的法律。")
    ruler = m.get("ruler") or {}
    if ruler.get("activity"):
        lines.append(f"统治者活动：{ruler['activity']}")
    igs = data.get("interest_groups") or []
    if igs:
        ig_bits = []
        for g in igs[:6]:
            nm = journal.IG_NAMES.get(g.get("name"),
                                      journal.IG_NAMES.get(g.get("definition"),
                                                           g.get("name")))
            if isinstance(g.get("clout_pct"), (int, float)):
                ig_bits.append(f"{nm}占政治力量约{g['clout_pct']:.1f}%")
            else:
                ig_bits.append(nm)
        lines.append("利益集团力量格局：" + "、".join(ig_bits) + "。")
    return "\n".join(lines) or "本年无法律变化记录。"


def _facts_household(m, data):
    elites = m.get("elites") or []
    cap = data.get("capital") or "未知"
    lines = [f"首都/上层社会样本（大臣之家素材，首都 {cap}）："]
    for p in elites[:3]:
        lines.append("- " + _fmt_pop(p))
    return "\n".join(lines)


def _facts_regime(m, data):
    lines = [
        f"政体为{data.get('govt_zh') or data.get('govt') or '未知'}。",
    ]
    rp = data.get("radicals_pct")
    lp = data.get("loyalists_pct")
    if rp is not None or lp is not None:
        lines.append(f"激进派约占人口{rp}%，效忠派约占人口{lp}%。")
    movs = data.get("political_movements") or []
    if movs:
        lines.append("主要政治运动：")
        for mv in movs[:3]:
            nm = mv.get("name") or mv.get("type") or "未知运动"
            if mv.get("ideology"):
                nm = f"由{mv['ideology']}发起的{nm}"
            bits = []
            if isinstance(mv.get("support_pct"), (int, float)):
                bits.append(f"支持度约{mv['support_pct']:.1f}%")
            if mv.get("supporters"):
                bits.append(f"支持者约{mv['supporters'] / 10000:.1f}万人")
            tier = mv.get("activism") or "消极"
            if tier == "武斗":
                line = f"- {nm}引发了街头暴力冲突"
            elif tier == "抗议":
                line = f"- {nm}引发了街头抗议"
            elif tier == "不满":
                line = f"- {nm}引发部分群众不满"
            else:
                line = f"- {nm}"
            if bits:
                line += ("：" if tier == "消极" else "，") + "，".join(bits)
            lines.append(line)
    return "\n".join(lines)


def _facts_migrants(m):
    migs = m.get("migrations") or []
    if not migs:
        return "本年无玩家州迁出记录（可据人口与文化构成写平静的一年）。"
    lines = ["玩家州迁出记录（人数已按存档口径换算）："]
    for r in migs[:3]:
        origin = r.get("origin_state") or "未知州"
        target = r.get("target_name") or r.get("target_state") or "未知州"
        cul = r.get("culture_zh")
        rel = r.get("religion_zh")
        if rel and cul:
            who = f"的{rel}{cul}人"
        elif cul:
            who = f"的{cul}人"
        elif rel:
            who = f"的{rel}信徒"
        else:
            who = ""
        n = r.get("num_people")
        n_txt = f"约{_fmt_int(n)}人" if n is not None else "人数未知"
        acc = _acceptance_zh(r.get("target_acceptance_status"))
        if acc:
            acc_txt = f"，在新家园接受度为{acc}"
        else:
            acc_txt = "，在新家园接受度未知"
        lines.append(f"- 从{origin}迁入{target}{who}，共{n_txt}{acc_txt}。")
    return "\n".join(lines)


def _facts_transformed(m):
    pros = m.get("promotions") or []
    if not pros:
        return "本年无跨年可比的职业转变样本（首次生成年无上年指纹，或无人转变）。"
    lines = []
    for p in pros[:3]:
        old = journal.POP_TYPE_NAMES.get(p.get("old_type"), p.get("old_type") or "未知职业")
        new = journal.POP_TYPE_NAMES.get(p.get("new_type"), p.get("new_type") or "未知职业")
        state = p.get("state_name") or p.get("state") or "未知州"
        who = ""
        if p.get("culture_zh") and p.get("religion_zh"):
            who = f"{p['religion_zh']}{p['culture_zh']}人群中的"
        elif p.get("culture_zh"):
            who = f"{p['culture_zh']}人群中的"
        wf = p.get("workforce")
        wf_txt = f"{_fmt_int(wf)}名劳动力" if wf is not None else "部分劳动力"
        lines.append(f"- {state}的{who}{wf_txt}由{old}转为{new}。")
    return "\n".join(lines)


# 文化名「人化」修正: 游戏本地化把部分文化翻成国名/地名(如 brazilian→"巴西"),
# 在「正同化为X」等语境下补「人」字更通顺。按需扩展。
CULTURE_DEMONYM_OVERRIDES = {
    "巴西": "巴西人",
    "英格兰": "英格兰人",
    "法兰西": "法兰西人",
    "俄罗斯": "俄罗斯人",
    "荷兰": "荷兰人",
    "北德意志": "北德意志人",
}


def _culture_demonym(name):
    """文化名 → 通顺的「人」称呼; 无修正时原样返回。"""
    if not name:
        return name
    return CULTURE_DEMONYM_OVERRIDES.get(name, name)


def _facts_assimilation(m, data):
    convs = m.get("conversions") or []
    lines = []
    if convs:
        lines.append("正在改信/同化的真实POP：")
        for c in convs[:3]:
            extra = []
            if c.get("converting_to_religion"):
                extra.append(f"正改信{c['converting_to_religion']}")
            if c.get("assimilating_to_culture"):
                extra.append(
                    f"正同化为{_culture_demonym(c['assimilating_to_culture'])}")
            base = _fmt_pop(c)
            if extra:
                base = base.rstrip("。") + "，" + "、".join(extra) + "。"
            lines.append("- " + base)
    else:
        lines.append("（暂无改信/同化样本）")
    cult_laws = []
    for x in (data.get("laws") or []):
        zh = journal.law_zh(str(x))
        if any(k in zh for k in ("文化", "宗教", "国教", "公民", "言论", "奴隶", "排斥")):
            cult_laws.append(zh)
    if cult_laws:
        lines.append("相关法律变动：" + "、".join(cult_laws) + "。")
    return "\n".join(lines)


def _facts_newhome(m, data):
    lines = []
    pc = data.get("pop_cultures") or []
    if pc:
        lines.append("人口文化构成（按占比）：" + "、".join(
            f"{c.get('name')}约{c.get('pct')}%" for c in pc[:5]))
    prof = data.get("professions") or []
    if prof:
        lines.append("职业构成：" + "、".join(
            f"{journal.POP_TYPE_NAMES.get(p.get('name'), p.get('name'))}约{p.get('pct')}%"
            for p in prof[:5]))
    migs = m.get("migrations") or []
    if migs:
        lines.append(f"本期移民样本共{len(migs)}条（见移民群像板块）。")
    return "\n".join(lines)


def render_facts(article_key, section_key, data):
    m = data.get("magazine") or {}
    if article_key in POOL:
        art = m.get(article_key) or {}
        secs = art.get("sections") or {}
        return (secs.get(section_key)
                or "（本板块数据不足，请据已知事实含蓄写作或略去。）")
    m["_player_wars"] = m.get("player_wars") or data.get("player_wars") or []
    m["_player_at_war"] = m.get("player_at_war") if m.get("player_at_war") is not None else data.get("player_at_war")
    fn = {
        "front": lambda: _facts_front(m, data),
        "garrison": lambda: _facts_garrison(m, data),
        "soldier": lambda: _facts_soldier(
            m, data, peacetime=not bool(m.get("_player_at_war"))),
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
    """政体 → 杂志基调; 和平年自动剥离基调中涉及战争/战事的句子,
    避免模型在无战事时仍按战争语境写作。"""
    if _STYLE_SYSTEM == "dynamic":
        prompt = style.resolve_magazine_voice(data)
    else:
        cat = style.govt_category(data)
        prompt = style.GOVT_PROMPTS.get(cat, style.GOVT_PROMPTS["other"])
    m = data.get("magazine") or {}
    at_war = data.get("player_at_war")
    if at_war is None:
        at_war = m.get("player_at_war")
    if not at_war and ("战争" in prompt or "战事" in prompt):
        sents = []
        for sent in prompt.split("。"):
            if "战争" not in sent and "战事" not in sent:
                sents.append(sent)
                continue
            segs = [s for s in sent.split("，")
                    if "战争" not in s and "战事" not in s]
            if segs:
                sents.append("，".join(segs))
        prompt = "。".join(sents)
    return prompt


def _intro_framework(data):
    """导言用「本期数据框架」: 把杂志数据里的大势事实压缩成几行,
    让导言有据可依, 不靠 OTL 常识猜测本年大事。"""
    m = data.get("magazine") or {}
    at_war = data.get("player_at_war")
    if at_war is None:
        at_war = m.get("player_at_war")
    battles = m.get("battles") or []
    wars = m.get("player_wars") or data.get("player_wars") or []
    lines = []
    if battles:
        b = battles[0]
        atk = (b.get("attacker") or {}).get("country") or "未知"
        dfd = (b.get("defender") or {}).get("country") or "未知"
        lines.append(
            f"档案保留战役{len(battles)}场（最近一场：{b.get('place') or '未知地点'}，"
            f"{_fmt_date(b.get('start_date'))}起，{atk}对{dfd}，"
            f"{BATTLE_STATUS_ZH.get(b.get('status'), b.get('status') or '结果未知')}）。")
    ongoing = [w for w in wars if not w.get("ended")]
    if ongoing:
        names = list(dict.fromkeys(
            str(p.get("name")) for w in ongoing
            for p in (w.get("participants") or []) if p.get("name")))
        if names:
            lines.append("我国参与进行中的战争，参战方：" + "、".join(names[:8]) + "。")
    elif not battles:
        lines.append("本年度我国无战事记录。")
    if data.get("laws_enacted"):
        lines.append("本年新施行法律：" + "、".join(
            journal.law_zh(str(x)) for x in data["laws_enacted"][:4]) + "。")
    elif data.get("laws_in_progress"):
        lines.append("本年立法进行中：" + "、".join(
            journal.law_zh(str(x.get("law")))
            for x in data["laws_in_progress"][:3]) + "。")
    ruler = m.get("ruler") or {}
    if ruler.get("name") and ruler.get("activity"):
        lines.append(f"统治者{ruler['name']}的活动：{ruler['activity']}。")
    pool_keys = set((m.get("pool") or {}).get("picked") or [])
    pool_keys |= set((m.get("pool") or {}).get("fallback") or [])
    migs = m.get("migrations") or []
    if migs and "migration_change" in pool_keys:
        lines.append(f"本年度玩家州有{len(migs)}条人口迁移记录（见《迁徙与蜕变》）。")
    convs = m.get("conversions") or []
    if convs and "migration_change" in pool_keys:
        lines.append(f"档案有{len(convs)}个正在改信/同化的POP样本（见《迁徙与蜕变》）。")
    return "\n".join(lines) or "（无额外数据）"


def _intro_article_preview(data):
    """导言用三篇特稿预告: 文章默认标题 + 主题 (最终标题由模型按文风拟题)。"""
    arts = _build_article_list(data)
    marks = "①②③④⑤"
    parts = []
    for i, a in enumerate(arts, 1):
        title = a.get("default_title") or a.get("title") or a.get("key")
        theme = a.get("theme") or ""
        mark = marks[i - 1] if i <= len(marks) else f"{i}."
        parts.append(f"{mark}《{title}》" + (f"（{theme}）" if theme else ""))
    return " ".join(parts)


def _lead_digest(text, limit=260):
    """首板块全文太长时, 后续板块只回贴程序截取的摘要, 避免提示词膨胀,
    也防止模型照抄首板块篇幅把后续板块写得过长。"""
    t = re.sub(r"[#*_>`~\-]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "……"


def build_intro_messages(data):
    country = data.get("player", "未知")
    capital = data.get("capital", "未知")
    govt_zh = data.get("govt_zh") or data.get("govt") or "未知"
    year = data.get("year", "?")
    preview = _intro_article_preview(data)
    sys_msg = (
        f"你是《{country}》杂志的总编辑。本刊定位为19世纪的非虚构文学月刊, "
        "聚焦具体人物的命运, 以小人物与大人物映照时代大局。\n\n"
        f"本期关键变量(抬头必须原样保留):\n"
        f"【国名】{country}\n【都城】{capital}\n【政体】{govt_zh}\n【年份】{year}\n\n"
        f"本刊基调:\n{_voice(data)}\n\n"
        f"三篇特稿: {preview}。\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}\n"
        "请先拟定刊名(据都城/国名+政体惯例, 如《巴黎纪事月刊》), 撰写杂志导言: "
        "概括本年度大势, 预告三篇特稿, 并点明本刊的政体立场。"
        "导言正文控制在约400–600字。"
        "输出格式:\n"
        "# 《刊名》\n"
        "国名：X｜都城：Y｜政体：Z｜年份：W\n\n"
        "导言正文..."
    )
    at_war = data.get("player_at_war")
    if at_war is None:
        at_war = (data.get("magazine") or {}).get("player_at_war")
    if not at_war:
        sys_msg += (
            "\n本期我国无战事记录，各板块均按和平年代写作，不涉及任何战争或敌军。"
        )
    user_msg = (
        f"本期杂志: 【国名】{country}, 【都城】{capital}, 【政体】{govt_zh}, 【年份】{year}。"
        "\n\n本期数据框架（程序提供，一切事实以此为准，不得另行发挥或套用真实历史）：\n"
        f"{_intro_framework(data)}\n\n"
        "请据上述变量与数据框架拟定刊名并撰写导言。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _article_section(article_key, key):
    for ak, a in POOL.items():
        if ak == article_key:
            for s in a["sections"]:
                if s["key"] == key:
                    return s
    for a in ARTICLES:
        if a["key"] == article_key:
            for s in a["sections"]:
                if s["key"] == key:
                    return s
    return None


def _article_display_title(article, generated=None):
    """文章最终标题: 优先模型拟题, 其次 default_title/原 title, 最后 key。"""
    return (generated or article.get("default_title")
            or article.get("title") or article.get("key"))


def build_lead_messages(article, data, intro):
    sec = article["sections"][0]
    country = data.get("player", "未知")
    facts = render_facts(article["key"], sec["key"], data)
    title_guide = ""
    try:
        title_guide = style.resolve_magazine_title_guide(data)
    except Exception:
        pass
    sys_msg = (
        f"你是本刊特稿《{_article_display_title(article)}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"这是文章的开篇板块《{sec['title']}》, 需立起全篇的人物与场景。要求: {sec['req']}\n\n"
        f"篇幅要求：开篇板块正文控制在800–1200字，须立起人物与场景，但不宜冗长。\n\n"
        f"文章标题拟题指南（为本期特稿拟一个正式标题，与正文分开）: {title_guide}\n\n"
        "注意：本期三篇文章标题应各不相同、各具面目，避免与其他两篇雷同。\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"请先为全篇文章拟一个与本刊文风相称的标题，再写开篇板块《{sec['title']}》正文。"
        f"相关数据如下(涉及国名请用【国名】={country}):\n"
        f"{facts}\n\n输出格式：第一行直接输出文章标题（不加井号、不写『标题：』前缀，"
        f"不超过24字），空一行后输出开篇板块正文(Markdown)。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_section_messages(article, section, data, intro, lead_text,
                           article_title=None):
    country = data.get("player", "未知")
    facts = render_facts(article["key"], section["key"], data)
    title = _article_display_title(article, article_title)
    sys_msg = (
        f"你是本刊特稿《{title}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"请撰写板块《{section['title']}》。要求: {section['req']}\n\n"
        f"篇幅要求：板块正文控制在1200–1800字。\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"本文开篇板块《{article['sections'][0]['title']}》内容摘要（程序截取，全文较长）:\n"
        f"{_lead_digest(lead_text)}\n\n"
        f"请撰写后续板块《{section['title']}》, 须与开篇呼应。相关数据(国名请用【国名】={country}):\n"
        f"{facts}\n\n请直接输出板块正文(Markdown)。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# 文本规范化与组装
# ---------------------------------------------------------------------------

_MAG_HEAD_RE = re.compile(r"^#{1,6}\s+")


def _strip_markdown_tables(text):
    """把模型仍可能输出的 Markdown 表格行转成自然语言句子(逗号连接)。
    只作兜底: 事实层已全部自然语言化, 此处防御模型自行出表。"""
    lines = (text or "").split("\n")
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if (ln.startswith("|")
                and i + 1 < len(lines)
                and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1])):
            headers = [c.strip() for c in ln.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                pairs = []
                for h, v in zip(headers, cells):
                    if not h or not v or v in ("-", "—", "N/A"):
                        continue
                    pairs.append(f"{h}为{v}")
                rows.append("，".join(pairs) if pairs else "、".join(cells))
                i += 1
            if rows:
                out.append("，".join(rows) + "。")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _normalize_section(text, title):
    """板块正文规范化: 所有标题降为 ###, 表格转自然语言, 无标题时补 ### 板块名。"""
    out = []
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
        out.append(s)
    body = _strip_markdown_tables("\n".join(out)).strip()
    first = next((ln for ln in body.split("\n") if ln.strip()), "")
    if not _MAG_HEAD_RE.match(first):
        return f"### {title}\n\n{body}"
    return body


def _build_article_list(data):
    """按文章池挑选本期文章 (池数据由 journal_save 提供);
    不足 3 篇时用兜底文章补位; 旧数据无 pool 时退回原三篇文章的裁剪逻辑。"""
    m = data.get("magazine") or {}
    pool = m.get("pool") or {}
    keys = list(pool.get("picked") or []) + list(pool.get("fallback") or [])
    articles = []
    for k in keys[:3]:
        a = POOL.get(k)
        if a:
            a2 = copy.deepcopy(a)
            a2["key"] = k
            titles_map = (m.get(k) or {}).get("section_titles") or {}
            for s in a2["sections"]:
                if s["key"] in titles_map and titles_map[s["key"]]:
                    s["title"] = titles_map[s["key"]]
            articles.append(a2)
            continue
        for fa in ARTICLES:
            if fa["key"] == k:
                if k == "war_family":
                    articles.append(_war_article_variant(data))
                elif k == "migration_change" and not bool(m.get("promotions")):
                    a2 = copy.deepcopy(fa)
                    a2["sections"] = [s for s in a2["sections"]
                                      if s["key"] != "transformed"]
                    articles.append(a2)
                else:
                    articles.append(copy.deepcopy(fa))
                break
    if not pool:
        # 旧数据: 原有按数据可用性裁剪逻辑
        has_promo = bool(m.get("promotions"))
        for a in ARTICLES:
            if a["key"] == "war_family":
                a2 = _war_article_variant(data)
            elif a["key"] == "migration_change" and not has_promo:
                a2 = dict(a)
                a2["sections"] = [s for s in a["sections"] if s["key"] != "transformed"]
            else:
                a2 = a
            if a2["sections"]:
                articles.append(a2)
    if not articles:
        articles = [copy.deepcopy(a) for a in ARTICLES[:3]]
    return articles


def _assemble(intro, leads, sections, data, articles=None, titles=None):
    parts = [intro]
    for a in (articles or ARTICLES):
        title = ((titles or {}).get(a["key"])
                 or a.get("default_title") or a.get("title") or a["key"])
        parts.append(f"## {title}")
        parts.append(leads[a["key"]])
        for s in a["sections"][1:]:
            parts.append(sections[(a["key"], s["key"])])
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# 主流程 (需求2: 导言 -> 首板块(3并发) -> 后续三板块(9并发))
# ---------------------------------------------------------------------------

def generate_magazine(data, cfg, force=True):
    _set_style_system(cfg.get("style_system", "legacy"))
    # 兼容两种调用形态: player_at_war / player_wars 可能直接挂在 data 上,
    # 也可能在 build_magazine_data 返回的 data["magazine"] 里, 统一提升到 data。
    m = data.get("magazine") or {}
    if data.get("player_at_war") is None and m.get("player_at_war") is not None:
        data["player_at_war"] = m.get("player_at_war")
    if not data.get("player_wars") and m.get("player_wars"):
        data["player_wars"] = m.get("player_wars")
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

    def _parse_article_title(text, fallback):
        """首板块输出第一行 → 文章标题; 解析失败回退 default_title。"""
        lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
        if not lines:
            return fallback, text
        first = re.sub(r"^#+\s*", "", lines[0]).strip()
        cand = re.sub(r"^(?:文章标题[：:]|标题[：:])?\s*", "", first)
        cand = cand.strip("《》 \t").strip()
        if 2 <= len(cand) <= 24:
            # 去掉模型在正文开头重复写一遍标题的行
            body_lines = [ln for ln in lines[1:]
                          if re.sub(r"^#+\s*", "", ln).strip().strip("《》 ") != cand]
            return cand, "\n".join(body_lines).strip()
        return fallback, text

    def _gen_lead(article):
        try:
            msg = build_lead_messages(article, data, intro)
            text = journal.call_deepseek(msg, sec_cfg).strip()
            fallback = (article.get("default_title")
                        or article.get("title") or article["key"])
            title, body = _parse_article_title(text, fallback)
            body = _normalize_section(body or text,
                                      article["sections"][0]["title"])
            return article["key"], title, body
        except Exception as e:
            journal.log(f"首板块《{article['sections'][0]['title']}》生成失败: {e}")
            fallback = (article.get("default_title")
                        or article.get("title") or article["key"])
            return (article["key"], fallback,
                    f"### {article['sections'][0]['title']}\n\n(本板块生成失败)")

    leads = {}
    titles = {}
    with ThreadPoolExecutor(max_workers=len(articles)) as ex:
        futures = [ex.submit(_gen_lead, a) for a in articles]
        for f in futures:
            k, t, body = f.result()
            leads[k] = body
            titles[k] = t

    def _gen_section(article, section):
        try:
            sec2 = dict(sec_cfg)
            # 末篇收束板块常被模型写长, 单独提高输出预算防止截断
            if section["key"] == "newhome":
                sec2["max_tokens"] = min(cfg.get("max_tokens", 8000), 6000)
            msg = build_section_messages(article, section, data, intro,
                                         leads[article["key"]],
                                         article_title=titles.get(article["key"]))
            text = journal.call_deepseek(msg, sec2).strip()
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

    text = _assemble(intro, leads, sections, data, articles=articles,
                     titles=titles)
    header = (f"<!-- 数据来源: 维多利亚3 报纸Mod 杂志版 | 报告日期: {data.get('date', '未知')} | "
              f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
    try:
        with open(mag_path, "w", encoding="utf-8") as f:
            f.write(header + text.rstrip() + "\n")
        journal.log(f"[{year}年] 杂志已生成: {mag_path}")
    except Exception as e:
        journal.log(f"[{year}年] 写入杂志失败: {e}")
