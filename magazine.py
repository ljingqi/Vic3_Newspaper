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
                    "胜负——以上一律以数据为准, 攻守双方按数据所述。只有数据给出战役细节时"
                    "才写战斗过程; 数据缺失时, 若存在进行中的战争, 依据战争记录写态势; "
                    "否则本板块改写真切简短的旧战事回顾或和平景象。军队名未给出时, "
                    "可据将领姓名与家乡州合情拟名, 国家名与给定数字以数据为准。"
                ),
                "facts": "front",
            },
            {
                "key": "soldier",
                "title": "士兵与营",
                "req": (
                    "以我方某营的步兵为主角(数据给出其职业/文化/宗教/所在州/人数), "
                    "敌军同逻辑取一个营, 再加上当地平民, 写出战场三方处境对照。"
                    "营的番号与军队名可演绎, 人物的所在州、职业、人数等给定事实以数据为准。"
                ),
                "facts": "soldier",
            },
            {
                "key": "homefront",
                "title": "后方家书",
                "req": (
                    "写士兵家乡(数据给出州名)的家人: 用给定的后方家庭样本(职业/文化/生活水平) "
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
                    "围绕其政见与施政方向展开。姓名缺失时用职务与集团代称。"
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
                    "写大臣家族的生活: 用给定首都或家乡州的上层人群(贵族/资本家/官僚) "
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
                    "以数据中的具体人群为原型塑造移民离乡与抵达的故事。"
                ),
                "facts": "migrants",
            },
            {
                "key": "transformed",
                "title": "蜕变者",
                "req": (
                    "从档案记录中取一个真实发生职业转变的人群(数据给出旧职业、新职业、人数、所在州), "
                    "写其个人与家庭层面的转变故事。"
                ),
                "facts": "transformed",
            },
            {
                "key": "assimilation",
                "title": "同化与改信",
                "req": (
                    "报道正在改信(给定目标宗教)或同化(给定目标文化)的真实人群, "
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

# 罪案类型清单 (与 journal_save.CRIME_TYPE_ZH 同步的提示词版本, 2026-08-19)
CRIME_TYPE_LIST_REQ = (
    "凶杀/纵火/故意伤害/勒索/抢劫/盗窃/绑架/恐怖主义（含刺杀要员、炸弹袭击、"
    "冲击政府机构、政治绑架、街头骚乱等细分）/伪造货币/走私/官仓贪腐/饥年盗粮/"
    "海盗劫掠/私刑/异端审判/逃兵军纪案/坟场盗掘/骗婚/伪造文书"
)
# 物证/在场证明与暴力尺度规则 (方案A/B 共用)
CRIME_EVIDENCE_REQ = (
    "资料给出的「物证与在场证明」（常购商品/物价动向/案发现场实物/勘验手段/"
    "案发时节等）按原文照写或化入叙述，物证与人物以资料为限。"
    "非暴力案（盗窃/勒索/欺诈/走私/贪腐等）按资料的非暴力性质写；"
    "绑架/政治绑架案受害者获救或放归、安然无恙。"
)

POOL = {
    "railway": {
        "default_title": "帝国铁道纪行",
        "theme": "铁路、蒸汽与沿线民生",
        "sections": [
            {"key": "lead", "title": "铁轨上的州", "req": (
                "报道铁路及其所在州：生产方法、所有权、投入产出一律以数据为准；"
                "以城市为舞台立起全篇的旅途与人物，车站名与里程以资料为准。"
                "按州情速写给出的路网/铁路档位措辞描写旅途与沿线民生。"
            )},
            {"key": "rural", "title": "乡村的货厢", "req": (
                "随铁路走访两座乡村（农场/矿场/林场/渔港）的建筑：生产方法、"
                "所有权与投入产出用给定数据；写乡村货物如何经铁路外运。"
            )},
            {"key": "workers", "title": "站台上的人", "req": (
                "以铁路建筑中的中上层民众（官僚/职员/工程师/资本家等）为主角，"
                "写其工作场景与下班后的日子；职业、文化、宗教、人数、识字率等以数据为准。"
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
                "报道激进派占比超过25%的动乱州：总人口、激进派规模、"
                "阶层构成与全国对比，立起全篇的冲突氛围；一切以资料为准。"
            )},
            {"key": "movement", "title": "旗帜与人群", "req": (
                "聚焦该州支持度最高的政治运动：名称、思潮、激进程度、支持者规模与构成，"
                "写运动在街头的面貌，运动领袖姓名以资料为准。"
            )},
            {"key": "institutions", "title": "衙门与法律", "req": (
                "报道相关现行法律（公民权/内部安全/教会与国家/言论）与该地机构覆盖，"
                "写政府如何回应或压制民间诉求。"
            )},
            {"key": "clash", "title": "街垒与公文", "req": (
                "写政府与群众的冲突场景：以给定运动数据与法律为据，描写街垒、公文与对峙，"
                "收束全篇。"
            )},
        ],
    },
    "shelf": {
        "default_title": "从货架里长出来的",
        "theme": "一件商品的产业链与家庭餐桌",
        "sections": [
            {"key": "lead", "title": "货架上的商品", "req": (
                "从贸易中心交易的大宗商品中取最活跃者（仅限我国境内有生产建筑的制成品，"
                "出口量以数据为准），"
                "写它如何摆上货架：贸易中心的生产方法、所有权以数据为准。"
            )},
            {"key": "workshop", "title": "车间里的手", "req": (
                "写该商品本地生产建筑及其工人的工作场景：生产方法、所有权、"
                "人数、识字率以数据为准，写从原料到成品的工序。"
            )},
            {"key": "mine", "title": "矿脉的尽头", "req": (
                "逆产业链向上游原料建筑（矿场/农场/林场，原材料分支随机）：写原料产地的"
                "工人如何把原料变成货架上的商品。"
            )},
            {"key": "customer", "title": "回家的路", "req": (
                "写目的地顾客买到商品后带回家的场景：家庭收支、识字、生活水平为据，"
                "收束全篇，数字一律以给定数据为准。"
            )},
        ],
    },
    "service": {
        "default_title": "为人民服务",
        "theme": "教育医疗与国家触角",
        "sections": [
            {"key": "lead", "title": "国家的触角", "req": (
                "报道教育/卫生/执法等机构的投入档位（自然语言）与相关法律，写国家力量如何自上而下延伸"
                "到州县；机构与法律以数据为准。"
                "按州情速写给出的行政覆盖档位措辞描写国家触角所及。"
            )},
            {"key": "classroom", "title": "课堂与诊室", "req": (
                "以样本州的识字率、政府雇员与基层公职/教员，写学校与诊所的具体面貌，"
                "机构名称以资料为准。"
            )},
            {"key": "grassroots", "title": "最基层的一天", "req": (
                "以样本州的下层民众为主角，写国家服务覆盖到最基层的一日：识字、收支、"
                "接受度以数据为准，写课堂、诊室或衙门中的具体场景。"
                "若资料给出「投资结果」行，须把该人群分红/投资收入与该企业本年行情"
                "对应写作其投资得失，行情数字一律以资料给出者为限。"
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
                "以样本州某一人群为主角：资料已明确其投票资格，严格按资料写"
                "投票日履行权利或站在门外的场景。"
                "若资料给出「投资结果」行，须把该人群分红/投资收入与该企业本年行情"
                "对应写作其投资得失，行情数字一律以资料给出者为限。"
            )},
            {"key": "future", "title": "来年的潮水", "req": (
                "以政治运动与立法动态收束，展望选举与权利的未来，立法结果以资料为准。"
            )},
        ],
    },
    "price": {
        "default_title": "餐桌上的价格",
        "theme": "物价与家庭账本",
        "sections": [
            {"key": "lead", "title": "货架上的价签", "req": (
                "报道本年度物价涨落：写涨价与跌价最明显的商品及其市价"
                "（或市价最高/最低者，按资料给出为准）；"
                "价格一律以数据为准，涨落用「较上年」表述，不另设价位参照。"
            )},
            {"key": "household", "title": "餐桌上的账本", "req": (
                "以样本州一户下层家庭的收支、消费画像与恩格尔系数，写物价如何落在餐桌上，"
                "数据以给定为准。"
                "若资料给出「投资结果」行，须把该人群分红/投资收入与该企业本年行情"
                "对应写作其投资得失，行情数字一律以资料给出者为限。"
            )},
            {"key": "market", "title": "市场的涨落", "req": (
                "罗列几件商品的市价（及资料给出的较上年涨落），写市场涨落背后的贸易与生产。"
            )},
            {"key": "street", "title": "街市与生计", "req": (
                "以平均月薪与阶层结构收束，写百姓在物价中的生计，行文平实。"
            )},
        ],
    },
    "letters": {
        "default_title": "海外来信",
        "theme": "海外属地的家书",
        "sections": [
            {"key": "lead", "title": "海外的来信", "req": (
                "报道我国未并入本土的海外属地：位置、城市名、主要文化、并入进度，"
                "立起一封家书的背景，地名以资料为准。"
            )},
            {"key": "harbor", "title": "港口的抵达", "req": (
                "写属地港口与交易商品，信从港口寄出或抵达：港口建筑的生产方法、"
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
    "crime": {
        "default_title": "罪案与法网",
        "theme": "一桩案件的社会与法",
        "sections": [
            {"key": "case", "title": "案件卷宗", "req": (
                "报道本年度发生的一桩案件：案件类型为资料给定的"
                + CRIME_TYPE_LIST_REQ + "之一；案发地为受害者工作建筑所在"
                "城邑、村落等聚落（案发现场以资料为准）；"
                "受害者、犯罪嫌疑人、证人三角色与动机一律以资料为准，三人姓名已给定、"
                "全篇直接使用。案件经过可按资料合情演绎，身份、地点、职业与数字"
                "以给定资料为准。" + CRIME_EVIDENCE_REQ +
                "绑架案可写胁迫、囚禁、赎金与解救。"
                "三角色的结局以资料为准，资料未写明死亡的人物皆安好；"
                "案件的破案与悬案结局以资料为准，正文按此收束。"
            )},
            {"key": "victim", "title": "受害者与证人", "req": (
                "从资料中的【受害者】与【证人】两位的视角写案发前后他们在同一聚落的"
                "生活与现场见闻，与开篇《案件卷宗》呼应；职业、文化、宗教、生活水平、"
                "接受度、物证与在场证明等以资料为准。案件类型与案发经过与开篇一致"
                "（" + CRIME_EVIDENCE_REQ + "结局以资料为准）。"
            )},
            {"key": "perpetrator", "title": "嫌疑人与动机", "req": (
                "从资料中的【犯罪嫌疑人】（被控加害人）一人的视角写其处境与动机如何从资料中"
                "生长出来：经济落差/文化隔阂/政治怨愤以资料给定的动机为准；恐怖主义"
                "案件写其参与的抗议政治运动背景与细分类型（刺杀要员/炸弹袭击/"
                "冲击政府机构/政治绑架/街头骚乱按资料为准），运动领袖姓名与具体"
                "行动细节以资料为准。" + CRIME_EVIDENCE_REQ +
                "本板块只叙述案发前后的处境与心路，庭审与判决由《法网与衙门》板块叙述。"
            )},
            {"key": "justice", "title": "法网与衙门", "req": (
                "三角色身份与全篇一致（资料原样），报道现行警察机构法律与国内安全法律、"
                "执法与内务两机构投入的自然语言档位，以及资料给定的现行刑法框架"
                "（刑罚取向），写案件进入法网后的后续——侦办、缉凶、庭审或悬案收束；"
                + CRIME_EVIDENCE_REQ + "受害者以资料结局为准；"
                "破案结果与判决以资料原文为准照写"
                "（含刑种、刑期与金额），资料未给出判决时以侦办过程收束。"
                "资料若有「嫌疑人使计」与「第一目击者」信息，按资料写明诡计得逞/"
                "被识破及第一目击者结局。"
            )},
            {"key": "impact", "title": "判决之后", "req": (
                "报道案件了结后的社会余波：以资料给定的判决、诡计（如有）、机构与"
                "动乱数据为限，写街巷舆论、受害与加害两方家庭的境遇、执法与立法风气、"
                "以及对未来运动或社会情绪的影响。判决以资料原文为唯一依据"
                "（刑种、刑期与金额照写）；诡计按资料写其得逞或被识破，第一目击者"
                "结局（已死亡/死里逃生）以资料为准；正文中的事件、人名与数字均出自"
                "资料。" + CRIME_EVIDENCE_REQ
            )},
        ],
    },
}

# 疫情特稿 (疫情活跃年作为第 4 篇文章加入; 素材 key 与
# journal_save._pool_epidemic_data 对应, 主题: 人们如何对抗看不见的敌人)
POOL["disease"] = {
    "default_title": "疫海浮生",
    "theme": "一场瘟疫如何改变人与城",
    "sections": [
        {"key": "outbreak", "title": "疫起之地", "req": (
            "报道疫情的来势：疾病名与俗称、首发州、持续年数与疫期进程（分波袭来/"
            "一波未平），传播途径与该时代应对此病的通行手段——以上一律以资料为准照写；"
            "蔓延情形以资料给出的各州染病人数、死亡人数与感染率为限，"
            "写疫病如何被察觉、官府与医者如何开始应对。"
        )},
        {"key": "healers", "title": "医者与众生", "req": (
            "报道人们如何对抗看不见的敌人：以资料给出的本国卫生法律、卫生机构投入、"
            "相关科技与疫区人物样本（职业/文化/宗教/生活水平/收支）为限，"
            "写医者与护理者的诊治、民间偏方与传闻的流行、"
            "部分民众配合隔离防疫、部分民众照常营生的众生相；"
            "人物姓名未给出时用身份与职业代称。"
        )},
        {"key": "households", "title": "门户与街巷", "req": (
            "写疫区门户与街巷的面貌：以资料给出的最重疫区染病人数、死亡人数、"
            "感染率与本年度新传至的州为限，写隔离、封市、施粥、丧葬与邻里互助；"
            "人物样本（职业/文化/宗教/生活水平）以资料为准，写家庭如何过疫期。"
        )},
        {"key": "aftermath", "title": "疫尽或未", "req": (
            "以资料给出的全国累计染病与死亡人数、最重疫区、疫情进程写代价与反思："
            "死者数字照资料写，遗属处境、官府善后与防疫得失以资料为限展开；"
            "疫情仍在流行时写其未息之势与来年展望，疫情入尾时写善后与教训。"
        )},
    ],
}


# ---------------------------------------------------------------------------
# 社会与法专版 (crime 抽中后 15% 触发): 1 大案 + 2 小案 整期替换
# 大案 5 板块 (案件卷宗/受害人与现场/嫌疑人与动机/法网与衙门/判决之后);
# 小案各 3 板块 (案件简报/街头反响/法网收束)。素材 key 与 journal_save 对应。
# ---------------------------------------------------------------------------
POOL["crime_big"] = {
    "default_title": "社会与法专版·头版大案",
    "theme": "一桩大案的社会与法",
    "sections": [
        {"key": "case", "title": "案件卷宗", "req": (
            "报道本期社会与法专版的头版大案：案件类型为资料给定的连环杀人/连环毒杀/"
            "可疑盗尸/双重生活/分尸弃尸之一；案发地、案发现场、多名受害者、"
            "犯罪嫌疑人、证人与动机一律以资料为准，姓名与身份已给定、全篇直接使用。"
            "连环案按资料写多名受害者的先后遇害；盗尸案写尸体失踪与解剖房疑云；"
            "双重生活案写嫌疑人的公开身份与秘密生活；献祭动机按资料作为「民俗/迷信"
            "之说」叙述，克制处理。" + CRIME_EVIDENCE_REQ +
            "案件发生在本刊的平行世界中，与现实人物、地名无关。案件的破案与悬案"
            "结局以资料为准，正文按此收束。"
        )},
        {"key": "victim", "title": "受害人与现场", "req": (
            "从资料中的【受害者】（含其余受害者）与【证人】的视角写案发前后他们在"
            "同一聚落的生活与现场见闻；职业、文化、宗教、生活水平、接受度以资料为准。"
            "案发现场与作案经过与开篇一致；物证与在场证明以资料为准照写；"
            "多名受害者按资料逐个交代结局"
            "（资料未写明死亡的人物皆安好）。"
        )},
        {"key": "perpetrator", "title": "嫌疑人与动机", "req": (
            "从资料中的【犯罪嫌疑人】（被控加害人）一人的视角写其处境与动机如何从"
            "资料中生长出来：骗保/私奔/丑闻/神秘学献祭/卖尸牟利/遗产债务以资料给定"
            "的动机为准；双重生活案写其公开身份与秘密生活（别名、重婚、第二处住所"
            "以资料为准）。本板块只叙述案发前后的处境与心路，庭审与判决由"
            "《法网与衙门》板块叙述。"
        )},
        {"key": "justice", "title": "法网与衙门", "req": (
            "三角色身份与全篇一致（资料原样），报道现行警察机构法律与国内安全法律、"
            "执法与内务两机构投入的自然语言档位，以及资料给定的现行刑法框架，写案件"
            "进入法网后的后续——侦办、缉凶、庭审或悬案收束；破案结果与判决以资料原文"
            "为准照写（含刑种、刑期与金额）。" + CRIME_EVIDENCE_REQ +
            "资料若有「嫌疑人使计」与「第一目击者」"
            "信息，按资料写明诡计得逞/被识破及第一目击者结局。"
        )},
        {"key": "impact", "title": "判决之后", "req": (
            "报道大案了结后的社会余波：以资料给定的判决、诡计（如有）、机构与动乱"
            "数据为限，写街巷舆论、受害与加害两方家庭的境遇、执法与立法风气，以及对"
            "未来运动或社会情绪的影响。判决以资料原文为唯一依据（刑种、刑期与金额照写）；"
            "诡计按资料写其得逞或被识破；" + CRIME_EVIDENCE_REQ +
            "事件、人名与数字以资料给出者为限。"
        )},
    ],
}

POOL["crime_small_a"] = {
    "default_title": "社会与法专版·案情简报（甲）",
    "theme": "一桩小案的始末",
    "sections": [
        {"key": "brief", "title": "案件简报", "req": (
            "报道本期社会与法专版的一桩小案：案件类型为资料给定的"
            + CRIME_TYPE_LIST_REQ + "之一；案发地与案发现场以资料为准；"
            "受害者、犯罪嫌疑人、证人三角色与动机一律以资料为准，姓名已给定、全篇"
            "直接使用。" + CRIME_EVIDENCE_REQ +
            "案件的破案与悬案结局以资料为准，正文按此收束。"
        )},
        {"key": "street", "title": "街头反响", "req": (
            "写这桩小案在案发地街巷的即时反响：以资料给出的案发州动乱度、识字率、"
            "失业率、政治运动、物价与舆论方向为限，写邻里的议论、受害与加害两方家庭的"
            "情形；事件、人名与数字以资料给出者为限。结局与判决以资料为准。"
        )},
        {"key": "close", "title": "法网收束", "req": (
            "写这桩小案进入法网后的收束：现行警察机构法律与国内安全法律、执法与"
            "内务机构投入档位以资料为准；破案结果与判决照抄资料原文（含刑种、刑期与"
            "金额），悬案时以资料为准收束。" + CRIME_EVIDENCE_REQ +
            "资料若有「嫌疑人使计」信息，按资料写明"
            "诡计得逞/被识破。"
        )},
    ],
}

POOL["crime_small_b"] = {
    "default_title": "社会与法专版·案情简报（乙）",
    "theme": "另一桩小案的始末",
    "sections": [
        {"key": "brief", "title": "案件简报", "req": (
            "报道本期社会与法专版的另一桩小案：案件类型为资料给定的"
            + CRIME_TYPE_LIST_REQ + "之一；案发地与案发现场"
            "以资料为准；受害者、犯罪嫌疑人、证人三角色与动机一律以资料为准，姓名"
            "已给定、全篇直接使用。" + CRIME_EVIDENCE_REQ +
            "案件的破案与悬案结局以资料为准，正文按此收束。"
        )},
        {"key": "street", "title": "街头反响", "req": (
            "写这桩小案在案发地街巷的即时反响：以资料给出的案发州动乱度、识字率、"
            "失业率、政治运动、物价与舆论方向为限，写邻里的议论、受害与加害两方家庭的"
            "情形；事件、人名与数字以资料给出者为限。结局与判决以资料为准。"
        )},
        {"key": "close", "title": "法网收束", "req": (
            "写这桩小案进入法网后的收束：现行警察机构法律与国内安全法律、执法与"
            "内务机构投入档位以资料为准；破案结果与判决照抄资料原文（含刑种、刑期与"
            "金额），悬案时以资料为准收束。" + CRIME_EVIDENCE_REQ +
            "资料若有「嫌疑人使计」信息，按资料写明"
            "诡计得逞/被识破。"
        )},
    ],
}

# 极刑行刑方式: 判词保持「判处死刑」, 行刑方式由正文按当地惯例演绎
for _key, _sec in (("crime", "justice"), ("crime_big", "justice"),
                   ("crime_small_a", "close"), ("crime_small_b", "close")):
    for _s in POOL[_key]["sections"]:
        if _s["key"] == _sec:
            _s["req"] += ("极刑案件（判处死刑）的行刑方式可按当地惯例合情演绎"
                          "（如绞刑、斩首），判决原文仍为「判处死刑」。")


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


def _dominant_acceptance(pops, weight_key=None):
    """样本POP → 出现次数最多(可加权)的接受度状态; 无样本返回 None。"""
    try:
        from journal_save import dominant_acceptance_status
    except Exception:
        dominant_acceptance_status = None
    if dominant_acceptance_status is not None:
        return dominant_acceptance_status(pops, weight_key=weight_key)
    cnt = {}
    for p in pops or []:
        s = p.get("acceptance_status")
        if s:
            w = 1
            if weight_key is not None:
                v = p.get(weight_key)
                if isinstance(v, (int, float)) and v > 0:
                    w = v
            cnt[s] = cnt.get(s, 0) + w
    if not cnt:
        return None
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def _garrison_tone(m):
    """驻地军民关系基调: 优先数据层算好的 garrison_tone_status
    (逐驻军州按游戏文件 add_homeland 本土文化的接受度加权众数后取最差档);
    旧缓存数据回退为平民加权众数。"""
    st = (m or {}).get("garrison_tone_status")
    if st:
        return st
    return _dominant_acceptance((m or {}).get("civilians"),
                                weight_key="workforce")


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
        a = dict(ARTICLES[0])
        battles = m.get("battles") or []
        wars = m.get("player_wars")
        if wars is None:
            wars = data.get("player_wars") or []
        if battles:
            front_req = ARTICLES[0]["sections"][0]["req"]
        elif wars:
            front_req = (
                "本刊资料未保留我方战役细节，本板块依战争记录写战局态势："
                "依据给定的参战方、起止时间与战争目的写态势，"
                "战役地点、将领、日期、兵力等数字以数据为准。"
            )
        else:
            front_req = (
                "本年数据无战事记录，本板块写和平景象下的国内风貌："
                "以给定的州、人口与民生数据为据，收束于安宁的日常。"
            )
        secs = [dict(s) for s in ARTICLES[0]["sections"]]
        for s in secs:
            if s["key"] == "front":
                s["req"] = front_req
        a["sections"] = secs
        return a
    a = dict(ARTICLES[0])
    a["title"] = "军营与家园"
    dom_acc = _garrison_tone(m)
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
                "报道我国军队的驻地生活: 数据给出军团/营的番号、兵员与驻地, 士兵群体的"
                "职业/文化/宗教/所在州/人数。写军队在驻地操演训练、整饬营务，与当地人"
                "相处。驻地军民关系基调: " + tone_name + "。" + tone_req
            )
            secs.append(s2)
        elif s["key"] == "soldier":
            s2["req"] = (
                "以我方某营的步兵为主角(数据给出其职业/文化/宗教/所在州/人数), "
                "结合当地平民, 写出驻军士兵的群像、营中日常与军民相处。驻地军民关系基调: "
                + tone_name + "。" + tone_req +
                "当前我国无战事、亦无敌军资料, 请据驻军生活展开。"
            )
            secs.append(s2)
        elif s["key"] == "homefront":
            s2["req"] = (
                "写士兵家乡(数据给出州名)的家人: 用给定的后方家庭样本(职业/文化/生活水平) "
                "塑造人物, 以家书或邻居口述体呈现和平时期军属家庭的日常与牵挂。"
            )
            secs.append(s2)
        elif s["key"] == "aftermath":
            if m.get("war_states"):
                s2["title"] = "营区与驻地民生"
                s2["req"] = (
                    "报道驻军所在地的民生状况: 给定州的荒废度/污染程度、主要文化, "
                    "写驻军与当地民众共同生活的面貌与地方恢复建设。驻地军民关系基调: "
                    + tone_name + "。" + tone_req
                )
                secs.append(s2)
        else:
            secs.append(s2)
    a["sections"] = secs
    return a


NONFICTION_RULE = (
    "「非虚构文学」铁律: 给定的国家名、人名、地名、日期、数字、职业、文化、宗教按原样使用; "
    "人物的心理、对话、场景、信函等细节允许作家合情演绎; "
    "数据缺失的内容简写或略去; "
    "凡数据给出姓名的人物直接使用该姓名, 未给出姓名的直接描写对象用身份/职业代称。"
)

WORLD_FRAME_RULE = (
    "「平行世界规则」: 本刊报道的世界完全由本刊资料构成, 与任何真实历史无关。"
    "所有国家、战争、边界、统治者、人物、日期、数字一律以本提示词给出的数据为准; "
    "数据未提供的即视为不存在或未知。行文含蓄, 以给定资料为限。"
    "度量衡一律使用公制单位（吨、千克、千米、米、升、度、平方米）。"
)

_CRIME_KEYS = ("crime", "crime_big", "crime_small_a", "crime_small_b")

CRIME_TERM_RULE = (
    "「罪案称谓」: 全篇提及被控加害人时一律称「犯罪嫌疑人」(必要时可简称"
    "「嫌疑人」), 不使用「凶手」等假定有罪的称谓; 人物对白、引文与街巷传闻"
    "同样遵守; 资料中【犯罪嫌疑人】一栏的姓名与身份原样使用。"
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


# 动员选项: 补给类只保留已启用中的最高档 (基础 < 额外 < 奢侈)。
MOBILIZATION_SUPPLIES_TIER = (
    "mobilization_option_basic_supplies",
    "mobilization_option_extra_supplies",
    "mobilization_option_luxurious_supplies",
)
MOBILIZATION_OPTION_ZH = {
    "mobilization_option_basic_supplies": "基础补给",
    "mobilization_option_extra_supplies": "额外补给",
    "mobilization_option_luxurious_supplies": "奢侈补给",
    "mobilization_option_chocolate": "巧克力",
    "mobilization_option_tobacco": "烟草",
    "mobilization_option_liquor": "烈酒",
    "mobilization_option_opium": "鸦片",
    "mobilization_option_narcotics_supplies": "麻醉品供给",
    "mobilization_option_forced_march": "强行军",
    "mobilization_option_truck_transport": "卡车运输",
    "mobilization_option_rail_transport": "铁路运输",
    "mobilization_option_machinegunners": "机枪手",
    "mobilization_option_chemical_weapons": "化学武器",
    "mobilization_option_flamethrowers": "火焰喷射器",
    "mobilization_option_motorized_recon": "摩托化侦察",
    "mobilization_option_balloon_recon": "气球侦察",
    "mobilization_option_aerial_recon": "空中侦察",
    "mobilization_option_first_aid": "急救",
    "mobilization_option_field_hospitals": "战地医院",
}


def _mobilization_options_zh(keys):
    """动员选项 key 列表 → 中文名; 补给类只保留最高档, 未知 key 原样保留。"""
    keys = list(keys or [])
    best = None
    for k in MOBILIZATION_SUPPLIES_TIER:
        if k in keys:
            best = k
    kept = []
    for k in keys:
        if k in MOBILIZATION_SUPPLIES_TIER:
            if k == best:
                kept.append(k)
        else:
            kept.append(k)
    return [MOBILIZATION_OPTION_ZH.get(k, k) for k in kept]


def _formation_status_bits(f):
    """军团 → 动员状态/动员选项自然语言片段 (空列表表示无信息)。"""
    bits = []
    flags = set(f.get("flags") or [])
    if "is_mobilized" in flags:
        bits.append("已动员")
    else:
        bits.append("未动员")
    if "has_raised_conscripts" in flags:
        bits.append("已征召后备兵")
    opts = _mobilization_options_zh(f.get("active_mobilization_options"))
    if opts:
        bits.append("动员选项：" + "、".join(opts))
    return bits


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
        lines.append("本刊资料未保留我方战役细节，依战争记录报道：")
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
        dom = _garrison_tone(m)
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
                line = f"- {fname}：{unames}" + ("等" if len(uu) > 4 else "")
            else:
                line = f"- {fname}"
            sbits = _formation_status_bits(f)
            if sbits:
                line += "（" + "；".join(sbits) + "）"
            lines.append(line)
    lines.append("我方士兵与军官（兵源样本）：")
    if soldiers:
        for p in soldiers[:3]:
            lines.append("- " + _fmt_pop(p))
    else:
        lines.append("（无足量士兵样本，请据军团与营的番号含蓄写作。）")
    ck = next((s.get("culture_key") for s in soldiers if s.get("culture_key")), None)
    blk = _mag_person_names(data, "war_family", [("士兵（主角）", ck)],
                            soldier=True)
    if blk:
        lines.append(blk)
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
    lines.append("当地平民（" + ("驻军所在州" if peacetime else "战场/驻军所在州") + "居民）：")
    if civilians:
        for p in civilians[:2]:
            lines.append("- " + _fmt_pop(p))
    else:
        lines.append("（无足量平民样本，请据驻地数据含蓄写作。）")
    _fl = _mag_flavor_block(m, [s.get("state") for s in soldiers[:3]]
                            + [c.get("state") for c in civilians[:2]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_garrison(m, data):
    """和平年「驻地与训练」: 军团/营、士兵POP与驻地平民, 不含战役。"""
    return _facts_soldier(m, data, peacetime=True)


def _mag_person_names(data, article_key, roles, soldier=False, genders=None,
                      fixed_last=None):
    """生成「人物名单（姓名已给定）」提示块。
    roles: [(角色名, culture_key|None)]; 种子按 (年|国名|文章|角色) 播种,
    同一角色在同年各板块间姓名一致, 保证跨板块连续性。
    soldier=True: 士兵文章, 军人/军官角色强制男名池, 其余角色不应用法律概率
    (维持合并池现行为); 否则女性概率按现行女权法律 (data["women_law"]) 调整。
    genders: {角色: "male"/"female"} 显式强制性别 (如 长子/幼女 等自带性别的角色)。
    fixed_last: 所有角色共用同一固定姓 (如大臣之家子女随受访大臣姓)。"""
    try:
        from journal_save import person_names_block, women_law_female_pct
    except Exception:
        return ""
    seed = f"{data.get('year')}|{data.get('player')}|magazine|{article_key}"
    female_pct = None
    genders = dict(genders or {})
    if soldier:
        for role, _ck in roles:
            if "士兵" in role or "军官" in role:
                genders.setdefault(role, "male")
    else:
        female_pct = women_law_female_pct(data.get("women_law"))
    return person_names_block(seed, roles, female_pct=female_pct, genders=genders,
                              fixed_last=fixed_last)


def _facts_homefront(m, data):
    fam = m.get("families") or []
    soldiers = m.get("soldiers") or []
    lines = ["后方家庭（士兵同州的平民）："]
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
    ck = next((p.get("culture_key") for p in fam if p.get("culture_key")), None)
    blk = _mag_person_names(data, "war_family", [("军属（留守家人）", ck)],
                            soldier=True)
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [p.get("state") for p in fam[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_aftermath(m, data):
    ws = m.get("war_states") or []
    lines = []
    if ws:
        lines.append("受战争影响或驻军所在地的州（荒废度/污染程度）：")
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
        lines.append("（本年度无已记录战事的州份）")
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
                    bits.append(f"攻方（{atk.get('country') or '未知'}）" + mc)
                if md:
                    bits.append(f"守方（{dfd.get('country') or '未知'}）" + md)
                lines.append(f"- {b.get('place') or '地点未知'}一役，" + "，".join(bits) + "。")
    civ = m.get("civilians") or []
    ck = next((c.get("culture_key") for c in civ if c.get("culture_key")), None)
    blk = _mag_person_names(data, "war_family", [("战区平民代表", ck)],
                            soldier=True)
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [s.get("id") for s in ws[:4]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_minister(m):
    cab = m.get("cabinet") or []
    ruler = m.get("ruler") or {}
    lines = []
    if ruler and ruler.get("name"):
        line = (f"统治者{ruler['name']}，头衔{ruler.get('title') or '未知'}，"
                f"意识形态{ruler.get('ideology') or '意识形态未知'}")
        if ruler.get("company"):
            line += f"，兼任{ruler['company']}总裁"
        lines.append(line + "。")
    lines.append("执政利益集团（内阁大臣来源）：")
    for g in cab[:4]:
        ig_nm = journal.ig_zh(g.get("name"), g.get("definition"))
        bits = []
        if g.get("leader_name"):
            bits.append(f"大臣{g['leader_name']}")
        else:
            bits.append("姓名未知")
        bits.append(f"来自{ig_nm}")
        if g.get("leader_ideology"):
            bits.append(f"意识形态为{g['leader_ideology']}")
        if isinstance(g.get("clout_pct"), (int, float)) and g["clout_pct"] >= 0.05:
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
            nm = journal.ig_zh(g.get("name"), g.get("definition"))
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
    # 大臣之家的子女与受访大臣同姓: 取大臣访谈中首位有姓名的大臣
    # (与「大臣访谈」板块同源, 即执政利益集团按政治力量排序的首个领袖)。
    surname, minister_ck = None, None
    try:
        from journal_save import surname_from_name
        for g in (m.get("cabinet") or []):
            nm = g.get("leader_name")
            if not nm:
                continue
            minister_ck = g.get("leader_culture_key")
            surname = surname_from_name(nm, minister_ck,
                                        raw_last=g.get("leader_last_name"))
            break
    except Exception:
        surname, minister_ck = None, None
    ck = (minister_ck
          or next((p.get("culture_key") for p in elites
                   if p.get("culture_key")), None))
    blk = _mag_person_names(data, "court_household",
                            [("府中长子", ck), ("府中次子", ck), ("府中幼女", ck)],
                            genders={"府中长子": "male", "府中次子": "male",
                                     "府中幼女": "female"},
                            fixed_last=surname)
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [p.get("state") for p in elites[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_regime(m, data):
    lines = [
        f"政体为{data.get('govt_zh') or data.get('govt') or '未知'}。",
    ]
    rp = data.get("radicals_pct")
    lp = data.get("loyalists_pct")
    pol_bits = []
    if rp is not None and rp:
        pol_bits.append(f"激进派约占人口{rp}%")
    if lp is not None and lp:
        pol_bits.append(f"效忠派约占人口{lp}%")
    if pol_bits:
        lines.append("、".join(pol_bits) + "。")
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


def _facts_migrants(m, data):
    migs = m.get("migrations") or []
    if not migs:
        return "本年无本国州份迁出记录（可据人口与文化构成写平静的一年）。"
    lines = ["本国各州迁出记录（人数为档案记录）："]
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
    ck = next((r.get("culture_key") for r in migs if r.get("culture_key")), None)
    blk = _mag_person_names(data, "migration_change", [("移民代表", ck)])
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [r.get("target_state") for r in migs[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_transformed(m, data):
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
    ck = next((p.get("culture_key") for p in pros if p.get("culture_key")), None)
    blk = _mag_person_names(data, "migration_change", [("职业转变者代表", ck)])
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [p.get("state") for p in pros[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
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
        lines.append("正在改信/同化的真实人群：")
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
    ck = next((c.get("culture_key") for c in convs if c.get("culture_key")), None)
    blk = _mag_person_names(data, "migration_change", [("改信者代表", ck)])
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [c.get("state") for c in convs[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _facts_newhome(m, data):
    lines = []
    pc = data.get("pop_cultures") or []
    if pc:
        lines.append("人口文化构成：" + "、".join(
            f"{c.get('name')}约{c.get('pct')}%" for c in pc[:5]))
    prof = data.get("professions") or []
    if prof:
        lines.append("职业构成：" + "、".join(
            f"{journal.POP_TYPE_NAMES.get(p.get('name'), p.get('name'))}约{p.get('pct')}%"
            for p in prof[:5]))
    migs = m.get("migrations") or []
    if migs:
        lines.append(f"本期移民样本共{len(migs)}条（见移民群像板块）。")
    ck = next((r.get("culture_key") for r in migs if r.get("culture_key")), None)
    blk = _mag_person_names(data, "migration_change", [("移民代表", ck)])
    if blk:
        lines.append(blk)
    _fl = _mag_flavor_block(m, [r.get("target_state") for r in migs[:3]], data)
    if _fl:
        lines.append("【州情速写】")
        lines.extend(_fl)
    return "\n".join(lines)


def _mag_flavor_block(m, sids, data=None):
    """按州 id 列表取州情速写行 (去重, 只取首个有数据的州)。
    data 提供时按文风档位现代化 (低档保留文言, 高档换现代白话)。"""
    out = []
    seen = set()
    for sid in sids or []:
        f = (m.get("state_flavors") or {}).get(sid)
        if not f:
            continue
        for ln in f.get("lines") or []:
            if ln not in seen:
                seen.add(ln)
                out.append(ln)
        if out:
            break
    if out and data is not None:
        out = journal._state_flavor_lines_for_tier(out, data)
    return out


STATE_FLAVOR_RULE = (
    "州情速写（路网/行政覆盖/识字/民情/人群构成）为资料给定的事实，"
    "必须自然化入正文，与速写保持一致；州情指标以速写给出者为限。"
)

def _currency_rule(data, article_key=None):
    """货币书写规则 (正向, 只列与本文相关的币种)。

    主币 = 我国币种 (data["currency"]); 文章数据可携带 units 列表
    (如货架文出口目的地的币种, 由 journal_save._pool_shelf_data 提供)。
    只输出相关币种的主辅币比例, 不再罗列他国币制, 也不用负向措辞。
    """
    base = data.get("currency") or journal.DEFAULT_CURRENCY
    units = [base]
    extra = ((data.get("magazine") or {}).get(article_key) or {}).get("units") or []
    for u in extra:
        if u and u != base and u not in units:
            units.append(u)
    segs = [f"{u}按「{journal.currency_system_text(u)}」书写" for u in units]
    return ("货币金额一律按资料给出的币种书写：" + "；".join(segs)
            + "。金额以资料给出者为限。")


def _article_has_flavor(data, article_key):
    m = data.get("magazine") or {}
    art = m.get(article_key) or {}
    sf = art.get("state_flavor") or {}
    if any(sf.get(k) for k in sf):
        return True
    if article_key not in POOL and (m.get("state_flavors")):
        return True
    return False


def render_facts(article_key, section_key, data):
    m = data.get("magazine") or {}
    if article_key in POOL:
        art = m.get(article_key) or {}
        secs = art.get("sections") or {}
        base = (secs.get(section_key)
                or "（本板块数据不足，请据已知事实含蓄写作或略去。）")
        fl = ((art.get("state_flavor") or {}).get(section_key)) or []
        if fl:
            # 州情速写按文风档位现代化 (低档保留文言, 高档换现代白话), 与报纸同口径
            fl = journal._state_flavor_lines_for_tier(fl, data)
            base = base.rstrip("\n") + "\n\n【州情速写】\n" + "\n".join(fl)
        return base
    m["_player_wars"] = m.get("player_wars") or data.get("player_wars") or []
    m["_player_at_war"] = m.get("player_at_war") if m.get("player_at_war") is not None else data.get("player_at_war")
    fn = {
        "front": lambda: _facts_front(m, data),
        "garrison": lambda: _facts_garrison(m, data),
        "soldier": lambda: _facts_soldier(
            m, data, peacetime=not bool(m.get("_player_at_war"))),
        "homefront": lambda: _facts_homefront(m, data),
        "aftermath": lambda: _facts_aftermath(m, data),
        "minister": lambda: _facts_minister(m),
        "decrees": lambda: _facts_decrees(m, data),
        "household": lambda: _facts_household(m, data),
        "regime": lambda: _facts_regime(m, data),
        "migrants": lambda: _facts_migrants(m, data),
        "transformed": lambda: _facts_transformed(m, data),
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
        if style.dop_law(data) in style.TOTALITARIAN_DOPS:
            prompt = style._TOTALITARIAN_MAG_VOICE
        else:
            prompt = style._strip_name_guide(
                style.GOVT_PROMPTS.get(cat, style.GOVT_PROMPTS["other"]))
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
        lines.append(f"本年度本国各州有{len(migs)}条人口迁移记录（见《迁徙与蜕变》）。")
    convs = m.get("conversions") or []
    if convs and "migration_change" in pool_keys:
        lines.append(f"档案有{len(convs)}个正在改信/同化的人群样本（见《迁徙与蜕变》）。")
    return "\n".join(lines) or "（无额外数据）"


def _intro_article_preview(data):
    """导言用三篇特稿预告: 文章标题 (预生成/默认) + 主题。
    标题由 _generate_article_titles 预生成后统一下发, 导言与正文同名,
    不再出现导言写默认题 (如《为人民服务》) 而正文另拟题的不同名。"""
    arts = _build_article_list(data)
    pre = (((data.get("magazine") or {}).get("pool") or {})
           .get("article_titles") or {})
    marks = "①②③④⑤"
    parts = []
    for i, a in enumerate(arts, 1):
        title = (pre.get(a["key"]) or a.get("default_title")
                 or a.get("title") or a.get("key"))
        theme = a.get("theme") or ""
        mark = marks[i - 1] if i <= len(marks) else f"{i}."
        parts.append(f"{mark}《{title}》" + (f"（{theme}）" if theme else ""))
    return " ".join(parts)


def _generate_article_titles(data, cfg):
    """一期文章标题预生成 (一次 LLM 调用, 按文章顺序每行一个):
    供导言预告与各板块统一使用, 保证同一篇文章全刊同名。"""
    articles = _build_article_list(data)
    guide = style.resolve_magazine_title_guide(data)
    voice = _voice(data)
    themes = "\n".join(
        f"{i + 1}. " + (a.get("theme") or a.get("default_title") or a["key"])
        for i, a in enumerate(articles))
    sys_msg = (
        f"你是《{data.get('player', '未知')}》杂志的特稿编辑。本刊基调:\n{voice}\n\n"
        f"{guide}\n"
        "为本期特稿各拟一个正式标题：每个标题不超过24字，与主题一一对应；"
        "输出时每行一个，标题文字紧贴行首。"
    )
    user_msg = f"本期{len(articles)}篇特稿主题:\n{themes}"
    msgs = [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]
    text = journal.call_deepseek(msgs, cfg).strip()
    cands = [re.sub(r"^[①②③④⑤\d]+[.、)]?\s*", "", ln).strip("《》 \t")
             for ln in text.splitlines() if ln.strip()]
    out = {}
    for i, a in enumerate(articles):
        fallback = a.get("default_title") or a.get("title") or a["key"]
        cand = cands[i] if i < len(cands) else ""
        out[a["key"]] = cand if 2 <= len(cand) <= 24 else fallback
    return out


def _lead_digest(text, limit=260, tail=180):
    """首板块全文太长时, 后续板块只回贴程序截取的前缀+结尾摘要, 避免提示词膨胀,
    也防止模型照抄首板块篇幅把后续板块写得过长; 结尾段保留案件收束等关键信息。
    A1: 由"纯前缀截断"改为"前缀+结尾", 避免首板块的案件结局被整个截掉。"""
    t = re.sub(r"[#*_>`~\-]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit + tail:
        return t
    head = t[:limit].rstrip("，。；：、 ")
    tail_t = t[-tail:].lstrip("，。；：、 ")
    if len(head) + len(tail_t) + 3 >= len(t):
        return t
    return head + "……" + tail_t


# ---------------------------------------------------------------------------
# B1: 罪案事实卡 (纯程序生成: 从案件资料确定性拼装, 供后续板块对齐)
# 案件类型/案发地/案发现场/三角色/结局/判决全部直接取自资料,
# 不再经 LLM 抽取, 保证后续板块与资料数据一致。
# ---------------------------------------------------------------------------

# 案发地后缀元注释: 「哈尔帕（受害者工作建筑所在的村落）」→「哈尔帕」
_CRIME_PLACE_META_RE = re.compile(r"（[^）]*工作建筑[^）]*）")


def _crime_card_roles(case_facts):
    """从 case 段落「全篇X角色身份固定」块解析角色行 (只取块内首现, 不碰
    物证/补充资料段, 也不碰大案的【受害者甲/乙/丙】)。返回 [(键, 姓名)]。"""
    in_block = False
    roles = []
    seen = set()
    for ln in (case_facts or "").split("\n"):
        s = ln.strip()
        if "身份固定" in s and "全篇" in s:
            in_block = True
            continue
        if in_block:
            if s.startswith("- 【"):
                m = re.match(r"- 【(受害者|犯罪嫌疑人|证人|真凶)】([^，,]+)", s)
                if m:
                    k, nm = m.group(1), m.group(2).strip()
                    if k not in seen and nm:
                        roles.append((k, nm))
                        seen.add(k)
                    continue
            # 角色块结束: 非角色行 (如「动机：」「大案多名受害者：」等)
            if roles:
                break
    return roles


def _crime_card_motive(case_facts):
    """从 case 段落的「动机：」行提炼案发经过简述 (去「动机（X）：」前缀)。"""
    bits = []
    for ln in (case_facts or "").split("\n"):
        s = ln.strip()
        if not s.startswith("动机："):
            continue
        body = s[len("动机："):].strip()
        for part in body.split("；"):
            p = re.sub(r"^动机（[^）]+）：", "", part.strip())
            p = re.sub(r"^动机[：:]", "", p).strip()
            if p and p not in bits:
                bits.append(p)
    return "；".join(bits)


def _crime_card_outcome_text(oc):
    """outcome → 结局行文本 (含蒙冤/错判与真凶下落)。"""
    tier = oc.get("solve_tier")
    tier_zh = {"convicted": "破案定罪", "acquitted": "无罪开释",
               "unsolved": "悬案收束"}.get(tier, "结果未知")
    misc = oc.get("miscarriage")
    culprit = oc.get("culprit_name")
    if misc == "framed":
        tier_zh = "无罪开释（蒙冤被诬）"
        if culprit:
            tier_zh += f"，真凶{culprit}仍在逃"
    elif misc == "wrongful":
        tier_zh = "错判昭雪"
        if culprit:
            tier_zh += f"，真凶{culprit}落网、原判撤销"
    return f"{tier_zh}；受害者是否死亡以资料为准。"


def _build_crime_card(data, key="crime"):
    """程序生成案件事实卡 (最多5行): 从 crime.sections['case'] 与 outcome
    确定性拼装, 不依赖 LLM, 与资料数据保持一致。"""
    m = (data.get("magazine") or {})
    crime = m.get(key) or {}
    secs = crime.get("sections") or {}
    case_facts = secs.get("case") or ""
    oc = crime.get("outcome") or {}
    lines = []
    # 1. 案件类型 / 案发地 / 案发现场
    mt = re.search(r"一桩(.+?)案", case_facts)
    place = re.search(r"案发地：([^；;。]+)", case_facts)
    scene = re.search(r"案发现场为([^。；;]+)", case_facts)
    head = "案件类型：" + (mt.group(1) + "案" if mt else "待定")
    if place:
        head += "；案发地：" + _CRIME_PLACE_META_RE.sub("", place.group(1).strip())
    if scene:
        head += "；案发现场：" + scene.group(1).strip()
    lines.append(head)
    # 2. 三角色 (含【真凶】时四角色)
    roles = _crime_card_roles(case_facts)
    if roles:
        lines.append("三角色：" + "；".join(f"{k}={v}" for k, v in roles))
    # 3. 案发经过: 动机简述
    motive = _crime_card_motive(case_facts)
    lines.append("案发经过：" + (motive if motive
                                 else "以资料给出的案件类型与案发现场为准。"))
    # 4. 结局
    lines.append("结局：" + _crime_card_outcome_text(oc))
    # 5. 判决
    sent = oc.get("sentence") or "未定"
    if oc.get("miscarriage") == "wrongful":
        sent += "（后查真凶另有其人，原判撤销、冤情昭雪）"
    lines.append("判决：" + sent)
    return "\n".join(lines[:5])


def build_intro_messages(data):
    country = data.get("player", "未知")
    capital = data.get("capital", "未知")
    govt_zh = data.get("govt_zh") or data.get("govt") or "未知"
    year = data.get("year", "?")
    preview = _intro_article_preview(data)
    n_arts = len(_build_article_list(data))
    count_txt = ("四篇特稿" if n_arts == 4
                 else ("三篇特稿" if n_arts == 3 else f"{n_arts}篇特稿"))
    pool = (data.get("magazine") or {}).get("pool") or {}
    special_note = ""
    if pool.get("special"):
        extra = ""
        if "disease" in (pool.get("picked") or []):
            extra = "另有《疫海浮生》疫情特稿一篇，与罪案报道并行。"
        special_note = ("\n\n本期为《社会与法》专版：头版大案 + 两则案情简报。"
                        "导言须点明专版定位，预告大案与两则简报，"
                        "并说明本版三篇文章同为罪案报道。" + extra)
    # 正式国名: 国名+政体 合并 (大清+专制帝国→大清帝国; 军政府→墨西哥共和国);
    # 政体字段随之从抬头移除
    full = journal.full_country_name(country, govt_zh, data.get("govt_law"))
    mag_name = style.derive_magazine_name(data)
    sys_msg = (
        f"你是《{country}》杂志的总编辑。本刊定位为19世纪的非虚构文学月刊, "
        "聚焦具体人物的命运, 以小人物与大人物映照时代大局。\n\n"
        f"本期关键变量(抬头中的国名必须原样保留正式国名):\n"
        f"【刊名】《{mag_name}》(经编辑部审定, 导言抬头一律使用该刊名)\n"
        f"【国名】{country}（合并政体后的正式国名：{full}）\n"
        f"【都城】{capital}\n【政体】{govt_zh}\n【年份】{year}\n\n"
        f"本刊基调:\n{_voice(data)}\n\n"
        f"{count_txt}: {preview}。{special_note}\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}\n"
        "撰写杂志导言: 概括本年度大势, 预告"
        f"{count_txt}, 并点明本刊的政体立场。"
        "导言正文控制在约400–600字。"
        "输出格式:\n"
        f"# 《{mag_name}》\n"
        f"国名：{full}｜都城：Y｜年份：W\n\n"
        "导言正文..."
    )
    at_war = data.get("player_at_war")
    if at_war is None:
        at_war = (data.get("magazine") or {}).get("player_at_war")
    if not at_war:
        sys_msg += (
            "\n本期我国无战事记录，各板块均按和平年代写作。"
        )
    user_msg = (
        f"本期杂志: 【刊名】《{mag_name}》, 【国名】{country}（正式国名 {full}）, "
        f"【都城】{capital}, 【政体】{govt_zh}, 【年份】{year}。"
        f"\n抬头中的国名按正式国名「{full}」一字不改写入, "
        f"刊名按「{mag_name}」原样写入。"
        "\n\n本期数据框架（以下资料为唯一事实依据）：\n"
        f"{_intro_framework(data)}\n\n"
        "请据此撰写导言。"
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
    facts = render_facts(article["key"], sec["key"], data)
    title = _article_display_title(article)
    sys_msg = (
        f"你是本刊特稿《{title}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"这是文章的开篇板块《{sec['title']}》, 需立起全篇的人物与场景。要求: {sec['req']}\n\n"
        f"篇幅要求：开篇板块正文控制在800–1200字，立起人物与场景。\n\n"
        f"本篇文章标题已定为《{title}》，正文按该标题撰写。\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    if _article_has_flavor(data, article["key"]):
        sys_msg += f"\n{STATE_FLAVOR_RULE}"
    if article["key"] in _CRIME_KEYS:
        sys_msg += f"\n{CRIME_TERM_RULE}"
    sys_msg += f"\n{_currency_rule(data, article['key'])}"
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"请撰写开篇板块《{sec['title']}》正文。相关数据如下:\n"
        f"{facts}\n\n输出格式：第一行输出文章标题《{title}》，空一行后输出开篇板块正文，"
        "正文使用 Markdown 格式。"
        "开篇正文分为 2~4 个自然段（每段聚焦一个场景或时序），"
        "段与段之间以空行分隔（Markdown 段落）。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_section_messages(article, section, data, intro, lead_text,
                           article_title=None, crime_card=None):
    facts = render_facts(article["key"], section["key"], data)
    title = _article_display_title(article, article_title)
    sys_msg = (
        f"你是本刊特稿《{title}》的主笔。本刊基调:\n{_voice(data)}\n\n"
        f"请撰写板块《{section['title']}》。要求: {section['req']}\n\n"
        f"篇幅要求：板块正文控制在1200–1800字。\n\n"
        f"{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    if _article_has_flavor(data, article["key"]):
        sys_msg += f"\n{STATE_FLAVOR_RULE}"
    if article["key"] in _CRIME_KEYS:
        sys_msg += f"\n{CRIME_TERM_RULE}"
    sys_msg += f"\n{_currency_rule(data, article['key'])}"
    lead_head = (f"本文开篇板块《{article['sections'][0]['title']}》内容摘要"
                 f"（以下为摘要，全文较长）:\n")
    if article["key"] in ("crime", "crime_big") and crime_card:
        digest = _lead_digest(lead_text, limit=600)
        user_msg = (
            f"本期杂志导言:\n{intro}\n\n"
            f"{lead_head}{digest}\n\n"
            f"【案件事实卡】（案件事实档案，后续板块必须以此为准，"
            f"与板块数据冲突时以案件事实卡与资料数据为准）：\n{crime_card}\n\n"
            f"请撰写后续板块《{section['title']}》, 须与开篇呼应。相关数据:\n"
            f"{facts}\n\n请直接输出板块正文，正文使用 Markdown 格式。"
        )
        return [{"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg}]
    user_msg = (
        f"本期杂志导言:\n{intro}\n\n"
        f"{lead_head}"
        f"{_lead_digest(lead_text)}\n\n"
        f"请撰写后续板块《{section['title']}》, 须与开篇呼应。相关数据:\n"
        f"{facts}\n\n请直接输出板块正文，正文使用 Markdown 格式。"
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
    """板块正文规范化: 所有标题降为 ###, 表格转自然语言, 无标题时补 ### 板块名。
    加粗回显标题行 (**案件卷宗** / **案件卷宗：**) 归一化为 ### 标题, 已有时删除。"""
    _bold = re.compile(r"^\*\*(.+?)[:：]?\*\*[:：]?\s*$")
    out = []
    saw_title = False
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            if title in s:
                saw_title = True
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
            out.append(s)
            continue
        m = _bold.match(s)
        if m:
            name = m.group(1).strip().strip("《》「」").strip().rstrip("：:")
            if name == title:
                if saw_title:
                    continue
                saw_title = True
                out.append(f"### {title}")
                continue
        out.append(s)
    body = _strip_markdown_tables("\n".join(out)).strip()
    # 模型偶尔重复写板块标题并以 --- 分隔 (如 ### 案件卷宗\n\n---\n### 案件卷宗),
    # 折叠为单个标题, 避免正文出现空板块头。
    body = re.sub(
        rf"^### {re.escape(title)}\s*\n\s*---\s*\n\s*### {re.escape(title)}\s*\n?",
        f"### {title}\n\n", body, count=1)
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
    # 疫情活跃年: 疫情特稿作为第 4 篇文章 (journal_save 按 epidemic 状态加入
    # picked), 其余年份仍 3 篇
    limit = 4 if "disease" in keys else 3
    articles = []
    for k in keys[:limit]:
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
    try:
        os.makedirs(os.path.join(base_dir, "杂志"), exist_ok=True)
    except Exception:
        pass
    mag_path = os.path.join(base_dir, "杂志", f"杂志_{year}.md")
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
    # 文章标题预生成 (一次调用): 导言预告与全部板块统一使用同一标题,
    # 避免导言写默认题(如《为人民服务》)而正文另拟题的刊内不同名。
    try:
        title_cfg = dict(cfg)
        title_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 600)
        pre_titles = _generate_article_titles(data, title_cfg)
        for a in articles:
            pt = pre_titles.get(a["key"])
            if pt:
                a["default_title"] = pt
        ((data.setdefault("magazine", {})).setdefault("pool", {})
         )["article_titles"] = pre_titles
    except Exception as e:
        journal.log(f"[{year}年] 文章标题预生成失败, 使用默认标题: {e}")
    n_lead = len(articles)
    n_rest = sum(len(a["sections"]) - 1 for a in articles)
    journal.log(f"[{year}年] 开始生成杂志: 标题预生成 + 导言 + {n_lead}首板块 + {n_rest}板块 "
                f"(共{2 + n_lead + n_rest}次调用)...")
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
            # 标题一致性安全网: 预生成标题已由程序给定, 模型偏离时强制回收,
            # 保证导言预告/首板块/后续板块全刊同名。
            fixed = article.get("default_title") or article.get("title")
            if fixed and title != fixed:
                title = fixed
            if article["key"] in _CRIME_KEYS:
                # 罪案称谓安全网: 提示词已要求, 此处兜底硬性词汇要求
                title = title.replace("凶手", "嫌疑人")
                body = (body or "").replace("凶手", "嫌疑人")
            body = _normalize_section(body or text,
                                      article["sections"][0]["title"])
            # 开篇板块: 模型常以单换行代替分段 (Markdown 下仍是一段),
            # 统一转为空行分隔的段落。
            body = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", body)
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

    # B1: 罪案事实卡 (纯程序生成, 供后续板块对齐)
    # (普通罪案与大案均生成; 小案靠首板块摘要对齐, 不生成事实卡)
    crime_cards = {}
    crime_article = next((a for a in articles
                          if a["key"] in ("crime", "crime_big")), None)
    if crime_article:
        ck = crime_article["key"]
        try:
            card = _build_crime_card(data, key=ck)
            if card:
                crime_cards[ck] = card
                journal.log(f"[{year}年] 罪案事实卡已生成 ({len(card)} 字)")
        except Exception as e:
            journal.log(f"[{year}年] 罪案事实卡生成失败: {e}")

    def _gen_section(article, section):
        try:
            sec2 = dict(sec_cfg)
            # 末篇收束板块常被模型写长, 单独提高输出预算防止截断
            if section["key"] == "newhome":
                sec2["max_tokens"] = min(cfg.get("max_tokens", 8000), 6000)
            card = (crime_cards.get(article["key"])
                    if article["key"] in ("crime", "crime_big") else None)
            msg = build_section_messages(article, section, data, intro,
                                         leads[article["key"]],
                                         article_title=titles.get(article["key"]),
                                         crime_card=card)
            text = journal.call_deepseek(msg, sec2).strip()
            if article["key"] in _CRIME_KEYS:
                text = text.replace("凶手", "嫌疑人")
            body = _normalize_section(text, section["title"])
            return article["key"], section["key"], body
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
        try:
            import htmlview
            page = htmlview.rebuild_session(cfg["journal_dir"], folder)
            if page:
                journal.log(f"[{year}年] 阅读页已更新: {page}")
        except Exception as e:
            journal.log(f"[{year}年] 更新阅读页失败: {e}")
    except Exception as e:
        journal.log(f"[{year}年] 写入杂志失败: {e}")
