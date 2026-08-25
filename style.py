#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文风提示词系统 (style.py)
================================
报纸 (journal.py) 与杂志 (magazine.py) 的「文风提示词」统一出口，含两套系统：

旧系统 (legacy)
  NEWSPAPER_STYLES : 4 种报纸风格 (大公报/人民日报/新华网/泰晤士报)
  GOVT_PROMPTS     : 8 类政体的杂志基调
  FREE_SPEECH_FLAVOR: 言论自由法律对应的新闻自由文案
  由 config.json 的 newspaper_style=1~4 选择，行为与旧版完全一致。

新系统 (dynamic)
  基于 Victoria 3 社会科技树 (以 Rationalism 为分水岭, 时代加权) + 政体/
  Distribution of Power 投票权修正，动态解析出 1~5 档报纸风格与杂志基调：
    档位越低越保守 (邸报/官报体)，档位越高越现代 (现代大报/先锋思潮刊物)。
  原则: Rationalism 政治分支 (民主→平权→人权/社会主义→政治动员…) 解锁越多，
        文风越现代; 政体与投票权法律做加减档与封顶修正。
  例: 普选制的君主立宪国可上「先锋」档; 地产投票的神权制封顶第 3 档。

config.json:
  "style_system": "legacy" | "dynamic"   (缺省 legacy)
  "newspaper_style": 1~4                 (仅 legacy 生效)
"""

from currency import currency_unit

DEFAULT_STYLE = 1

# ---------------------------------------------------------------------------
# 旧系统: 四种报纸风格 (自 journal.py 原样迁移)
# ---------------------------------------------------------------------------

NEWSPAPER_STYLES = {
    1: {
        "name": "大公报（20世纪初）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，如《罗马公报》《巴黎回声报》"
            "《江户政闻录》，可再结合【政体】微调（如《巴黎共和公报》），"
            "并随其变迁而调整，以体现时代推移。"
            "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
            "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
            "报名须与国名或都城相关。"
            "示例：都城罗马可作《罗马公报》，都城巴黎可作《巴黎回声报》，"
            "都城京都可作《京都新闻》；若首都或政体数据缺失，则退而用国名拟定，"
            "如《法兰西新闻》《日本新闻》。"
        ),
        "voice": (
            "你是一位生活于19世纪至20世纪上半叶的报纸总编辑，文风「半文半白」："
            "以白话为主体、晓畅明白，又保留文言的凝练庄重（梁启超、鲁迅及民国初年"
            "《申报》《大公报》笔法）。使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部消息，我国国民生产总值为……」（填入给定GDP数值）"
            "引出经济总量，如「据户部消息，我国国民生产总值为四千六百余万{CURRENCY}」；"
            "人口、生活水平、识字率等其余指标同样以旧式公文笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为20世纪初报刊告白体：商品告白、工艺铺面招贴、学堂晓谕、书画社启事皆可，"
            "措辞半文半白、文雅得体，可带「本店」「特此告白」「惠顾」等语汇，篇幅短小有趣。"
        ),
        "number_format": "chinese",
        "number_guide": (
            "大数一律用汉字数字（如「四千六百零七万七千二百六十七」），"
            "百分比等现代度量可用阿拉伯数字（如 69.45%）。"
        ),
        "section_titles": {
            "headline": "头版",
            "war": "战事专电",
            "diplo": "外交风云",
            "econ": "经济要闻",
            "politics": "政界动态",
            "society": "民族宗教与社会",
            "epidemic": "疫情专电",
            "family": "民生访谈",
            "peer": "邻里富户",
            "unemployed": "失业民生",
            "comment": "本报评论",
            "ads": "广告与启示",
        },
    },
    2: {
        "name": "人民日报（20世纪）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格可采用《XX日报》《XX早报》"
            "《XX晨报》等体例，如都城巴黎可作《巴黎日报》、都城京都可作《京都早报》；"
            "可再结合【政体】微调（如《巴黎共和日报》），并随其变迁而调整，以体现时代推移。"
            "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
            "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
            "报名须与国名或都城相关。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西日报》《日本日报》。"
        ),
        "voice": (
            "你是一位生活于20世纪的权威大报总编辑，供职于以人民立场为根本、"
            "服务社会主义建设与人民生活的报纸。你的文风端正庄重、朴实有力："
            "善用「人民」「群众」「建设」「发展」「团结」等语汇，消息客观、社论有高度，"
            "措辞审慎；有喜报喜、有忧报忧，以建设与发展为主线。"
            "使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，如「国家统计局最新数据显示，我国GDP为四千六百零七万{CURRENCY}」；"
            "人口、生活水平、识字率等其余指标以官方书面语展开。"
        ),
        "ads_guide": (
            "广告栏须为20世纪党报广告体：国营厂矿产品广告、展览会通知、招生启事、征订启事等，"
            "措辞正式简明，突出为人民生活服务与建设成果（如「为人民生活服务」「欢迎选购」）。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如 46,077,267 {CURRENCY}、21,862,816 人、69.45%）。"
        ),
        "section_titles": {
            "headline": "今日要闻",
            "war": "军事报道",
            "diplo": "国际要闻",
            "econ": "经济建设",
            "politics": "时政要闻",
            "society": "民族与宗教",
            "epidemic": "疫情报道",
            "family": "人民生活",
            "peer": "先富观察",
            "unemployed": "就业民生",
            "comment": "社论",
            "ads": "广告启事",
        },
    },
    3: {
        "name": "新华网（新华社风格）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格可采用《XX新华报》"
            "《XX新华电讯》等体例，如都城巴黎可作《巴黎新华报》、都城京都可作"
            "《京都新华电讯》；可再结合【政体】微调（如《巴黎共和新华报》），"
            "并随其变迁而调整，以体现时代推移。"
            "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
            "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
            "报名须与国名或都城相关。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西新华报》《日本新华电讯》。"
        ),
        "voice": (
            "你是一位供职于国家通讯社的资深记者与编辑，写作新华社通稿体："
            "消息开门见山，首段即时间、地点、事件三要素；事实准确、行文凝练、"
            "措辞规范，标题朴实有力；报道以事实说话，"
            "注重权威与可信。使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本社」指代本通讯社。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，其余数据以新华社通稿体如实报道。"
        ),
        "ads_guide": (
            "广告栏须为现代新闻媒体分类广告/公告体：产品服务信息、展会通知、公益公告等，"
            "信息要素齐全（名称、地点、方式），标题简明，措辞平实。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如 46,077,267 {CURRENCY}、21,862,816 人、69.45%）。"
        ),
        "section_titles": {
            "headline": "要闻",
            "war": "军事新闻",
            "diplo": "国际新闻",
            "econ": "经济新闻",
            "politics": "时政新闻",
            "society": "社会新闻",
            "epidemic": "疫情新闻",
            "family": "民生一线",
            "peer": "富户见闻",
            "unemployed": "就业观察",
            "comment": "新华时评",
            "ads": "分类广告",
        },
    },
    4: {
        "name": "泰晤士报（中文）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格可采用《XX泰晤士报》"
            "《XX泰晤士纪事》等体例，如都城罗马可作《罗马泰晤士报》、都城巴黎可作"
            "《巴黎泰晤士报》；可再结合【政体】微调（如《巴黎共和泰晤士报》），"
            "并随其变迁而调整，以体现时代推移。"
            "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
            "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
            "报名须与国名或都城相关。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西泰晤士报》《日本泰晤士报》。"
        ),
        "voice": (
            "你是一位供职于英伦百年大报的中文版总编辑（风格仿《泰晤士报》）。"
            "你的文风庄重冷静、含蓄克制，以绅士笔调叙述世事：句子结构完整、措辞考究，"
            "善用「据悉」「据可靠消息」「观乎」「有识之士」等书面语；报道重事实、重细节，"
            "评论持重、客观，偶带英式含蓄的讽喻，标题典雅。"
            "使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部消息，我国国民生产总值为……」（填入给定GDP数值）"
            "引出经济总量，如「据户部消息，我国国民生产总值为四千六百余万{CURRENCY}」；"
            "再以庄重含蓄的笔调展开人口、生活水平、识字率等其余指标。"
        ),
        "ads_guide": (
            "广告栏须为英式大报典雅广告体：绅士用品、出版社新书、私人学校、俱乐部启事等，"
            "措辞庄重含蓄、讲究体面，可带「谨此奉告」「敬请惠顾」等英式译风用语，篇幅短小。"
        ),
        "number_format": "chinese",
        "number_guide": (
            "大数一律用汉字数字（如「四千六百零七万七千二百六十七」），"
            "百分比等现代度量可用阿拉伯数字（如 69.45%）。"
        ),
        "section_titles": {
            "headline": "头版要闻",
            "war": "战地报道",
            "diplo": "国际时讯",
            "econ": "财经报道",
            "politics": "政坛纪事",
            "society": "社会万象",
            "epidemic": "疫情专讯",
            "family": "民间专访",
            "peer": "富室专访",
            "unemployed": "失业调查",
            "comment": "社评",
            "ads": "启事与广告",
        },
    },
}

# ---------------------------------------------------------------------------
# 旧系统: 政体 -> 杂志基调 (自 magazine.py 原样迁移)
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

# ---------------------------------------------------------------------------
# 旧系统: 言论自由法律 -> 新闻自由风味文案 (自 journal.py 原样迁移)
# ---------------------------------------------------------------------------

FREE_SPEECH_FLAVOR = {
    "law_outlawed_dissent": "批评政府被视为叛国而属非法，报纸只可刊发拥护现行体制的内容。",
    "law_censorship": "新闻出版受主动审查，报纸稿件须经审查机关许可方可刊发，报道须自行把关。",
    "law_right_of_assembly": "报纸无须事前送审，可较为自由地报道与评论，惟言论自由尚无明文法律保护，报道宜有分寸。",
    "law_protected_speech": "言论自由已载入法律并受明文保护，报纸可依法自由报道与批评，唯须不逾诽谤、泄密等法律界限。",
    "law_free_speech": "报纸享有完全的言论与出版自由，可自由报道、评论国政，无须事前送审。",
}

# ---------------------------------------------------------------------------
# 新系统: 科技目录 (Victoria 3 1.13.10, common/technology/technologies/30_society.txt)
# ---------------------------------------------------------------------------

# Rationalism 政治分支 (树中位于 Rationalism 以下的政治现代化主线) 的权重。
# 时代加权: era I = 1, era II = 2, era III = 3, era IV = 4, era V = 5。
# organized_sports 为民族主义侧支(大众体育/休闲), 权重按 1 计。
RATIONALISM_BRANCH = {
    "rationalism": 1,          # era_1 分水岭本身
    "democracy": 1,            # era_1
    "mass_communication": 1,   # era_1
    "egalitarianism": 2,       # era_2
    "nationalism": 2,          # era_2
    "labor_movement": 2,       # era_2
    "organized_sports": 1,     # era_2 (侧支)
    "human_rights": 3,         # era_3
    "feminism": 3,             # era_3
    "anarchism": 3,            # era_3
    "socialism": 3,            # era_3
    "corporatism": 3,          # era_3
    "political_agitation": 4,  # era_4
    "mass_propaganda": 5,      # era_5
}

BRANCH_TECH_ZH = {
    "rationalism": "理性主义",
    "democracy": "民主制度",
    "mass_communication": "大众传媒",
    "egalitarianism": "平权主义",
    "nationalism": "民族主义",
    "labor_movement": "劳工运动",
    "organized_sports": "大众体育",
    "human_rights": "人权思想",
    "feminism": "女权主义",
    "anarchism": "无政府主义",
    "socialism": "社会主义",
    "corporatism": "法团主义",
    "political_agitation": "政治动员",
    "mass_propaganda": "大众宣传",
}

# 满分 = 1+1+1+2+2+2+1+3+3+3+3+3+4+5 = 34
TIER_NAMES = {
    1: "守成",
    2: "改良",
    3: "现代",
    4: "进步",
    5: "先锋",
}

ERA_LABELS = {
    1: "传统时代",
    2: "启蒙与改良时代",
    3: "现代大众时代",
    4: "进步变革时代",
    5: "先锋思潮时代",
}


def _tier_from_score(score):
    """科技分 → 基础档位 (未含政体/投票权修正)。"""
    if score <= 1:
        return 1
    if score <= 4:
        return 2
    if score <= 10:
        return 3
    if score <= 18:
        return 4
    return 5


# Distribution of Power 法律 (game/common/laws/00_distribution_of_power.txt)
DOP_LAWS = (
    "law_autocracy", "law_neo_absolutism", "law_bakufu",
    "law_technocracy", "law_oligarchy", "law_organic_regulation",
    "law_elder_council", "law_landed_voting", "law_wealth_voting",
    "law_census_voting", "law_universal_suffrage", "law_anarchy",
    "law_single_party_state",
)

# 投票权加权: 法律越开明, 文风可越现代 (数值取自游戏 progressiveness 的档位化)
DOP_ADJ = {
    "law_anarchy": 2,
    "law_universal_suffrage": 2,
    "law_census_voting": 1,
    "law_single_party_state": 1,
    "law_wealth_voting": 0,
    "law_technocracy": 0,
    "law_landed_voting": -1,
    "law_elder_council": -1,
    "law_oligarchy": -1,
    "law_organic_regulation": -1,
    "law_autocracy": -2,
    "law_neo_absolutism": -2,
    "law_bakufu": -2,
}

DOP_NOTES = {
    "law_anarchy": "当前实行无政府式民众自治，报纸无官方管制，可尖锐批评一切权力。",
    "law_universal_suffrage": "当前实行普选制，舆论开放，报纸可面向全体公民自由报道与评议。",
    "law_census_voting": "当前实行按识字与财产的人口普查投票，舆论较为开放，报纸面向有产与识字阶层。",
    "law_single_party_state": "当前为一党制国家，报纸须与执政党路线保持一致，报道以建设成就为主线。",
    "law_wealth_voting": "当前实行财富投票，舆论由有产者主导，报纸措辞审慎、偏向工商利益。",
    "law_landed_voting": "当前实行地产投票，舆论由地主与乡绅主导，报纸行文须顾及土地贵族的体面。",
    "law_elder_council": "当前由长老会议主政，报纸行文尊重长老与传统。",
    "law_technocracy": "当前为技术官僚治国，报纸宜重视统计、工程与专业知识。",
    "law_oligarchy": "当前为寡头政治，报纸措辞谨慎，须顾及权贵体面。",
    "law_organic_regulation": "当前为有机体规制政体，报纸行文须服从整体秩序叙事。",
    "law_autocracy": "当前为专制政体，报纸拥护君主与现行体制。",
    "law_neo_absolutism": "当前为新专制政体，报纸须拥护君主与现行体制。",
    "law_bakufu": "当前为幕府政体，报纸须服从幕府权威与武士秩序。",
}

# 政体类别 (与 magazine._govt_category 同一口径)
GOVT_BASE_ADJ = {
    "council_republic": 1,
    "parliamentary_republic": 1,
    "presidential_republic": 1,
    "social_monarchy": 0,
    "monarchy": 0,
    "theocracy": -1,
    "chiefdom": -2,
    "other": 0,
}

GOVT_STANCE = {
    "council_republic": "当前为委员会制共和国，报名与行文宜带集体与劳动色彩。",
    "parliamentary_republic": "当前为议会制共和国，报名宜带宪政与公共色彩。",
    "presidential_republic": "当前为总统制共和国，报名宜带自由与进步色彩。",
    "social_monarchy": "当前为社会君主制，报名宜带王室与改良色彩。",
    "monarchy": "当前为君主制，报名宜庄重典雅、体现正统与等级。",
    "theocracy": "当前为神权制，报名宜带神圣与教化色彩。",
    "chiefdom": "当前为酋邦/部族政体，报名宜带传统与社群色彩。",
    "other": "",
}


# 治理原则法律 -> 政体类别 (最可靠口径: 存档现行治理法)
GOVT_LAW_TO_CAT = {
    "law_chiefdom": "chiefdom",
    "law_monarchy": "monarchy",
    "law_social_monarchy": "social_monarchy",
    "law_presidential_republic": "presidential_republic",
    "law_parliamentary_republic": "parliamentary_republic",
    "law_theocracy": "theocracy",
    "law_council_republic": "council_republic",
    "law_corporate_state": "other",
    "law_colonial_administration": "other",
}

GOVT_LAWS = tuple(GOVT_LAW_TO_CAT)

# 兜底: 政体键子串匹配 (仅当 govt_law 缺失时使用, 如旧 raw JSON)
GOVT_KEY_HINTS = {
    "council_republic": ("council", "commune", "soviet", "anarch", "phalanstere"),
    "parliamentary_republic": ("parliament",),
    "presidential_republic": ("president", "republic", "democracy", "technate",
                              "junta", "free_city", "dominion"),
    "theocracy": ("theocra", "papal", "caliph", "imam", "priest", "patriarch",
                  "dalai", "lama", "bishopric", "massina", "sunanate",
                  "imamate", "papacy"),
    "chiefdom": ("chief", "tribe", "clan", "khan", "horde", "emir", "sheikh",
                 "sharif", "captaincy", "hakimate"),
    "social_monarchy": ("social", "welfare", "liberal"),
    "monarchy": ("monarch", "empire", "kingdom", "duchy", "principality",
                 "regency", "shah", "bakufu", "shogun", "crown", "tsar",
                 "kaiser", "khedive", "sultan", "maharaja", "raja", "nawab",
                 "rajya", "wilayah", "guberniya", "bey", "ethiopia", "prince"),
}


def govt_category(data):
    """政体类别: 优先存档现行治理法 (govt_law), 缺失时按政体键子串兜底。"""
    law = data.get("govt_law")
    if law in GOVT_LAW_TO_CAT:
        return GOVT_LAW_TO_CAT[law]
    key = str(data.get("govt_key") or data.get("govt") or "").lower()
    for cat, hints in GOVT_KEY_HINTS.items():
        if any(h in key for h in hints):
            return cat
    return "other"


def dop_law(data):
    """当前 Distribution of Power 法律 key; 缺省返回 None。"""
    law = data.get("dop_law")
    if law:
        return law
    return next((l for l in (data.get("laws") or []) if l in DOP_LAWS), None)


def modernity_score(tech_keys):
    """Rationalism 政治分支已解锁科技的时代加权分。"""
    keys = set(tech_keys or [])
    return sum(w for k, w in RATIONALISM_BRANCH.items() if k in keys)


def build_era_profile(tech_keys, tier):
    """由已解锁分支科技生成「时代定位」句, 注入 voice。"""
    unlocked = [BRANCH_TECH_ZH[k] for k in RATIONALISM_BRANCH
                if k in set(tech_keys or [])]
    label = ERA_LABELS.get(tier, "变革时代")
    if not unlocked:
        return f"本国尚未解锁理性主义，社会仍处于传统秩序之中，属{label}。"
    return f"本国已解锁{'、'.join(unlocked)}，社会正处于{label}。"


def resolve_tier(score, cat, dop):
    """基础档位 + 政体/投票权修正 + 硬性封顶。

    修正规则:
      - 进步政体(各共和国)+1, 神权-1, 酋邦-2;
      - 投票权法律按开明度 ±2~-2;
      - 酋邦封顶 3; 神权在保守投票权下封顶 3、其余封顶 4;
      - 君主/社会君主在专制投票权下封顶 3。
    """
    adj = GOVT_BASE_ADJ.get(cat, 0) + DOP_ADJ.get(dop, 0)
    tier = _tier_from_score(score) + adj
    tier = max(1, min(5, tier))
    if cat == "chiefdom":
        tier = min(tier, 3)
    if cat == "theocracy":
        cap = 3 if DOP_ADJ.get(dop, 0) < 0 else 4
        tier = min(tier, cap)
    if cat in ("monarchy", "social_monarchy") and DOP_ADJ.get(dop, 0) <= -2:
        tier = min(tier, 3)
    return tier


# ---------------------------------------------------------------------------
# 新系统: 五档报纸风格模板
# 模板占位符: {GOVT_STANCE} {VOTE} {ERA} 在 resolve_newspaper_style 中填充。
# ---------------------------------------------------------------------------

_MASTHEAD_BASE = (
    "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
    "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
    "报名须与国名或都城相关。"
)

MODERNITY_TIERS = {
    1: {
        "name": "邸报（守成·传统时代）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX邸报》"
            "《XX官报》《XX政闻录》《XX公报》等体例，如都城罗马可作《罗马邸报》、"
            "都城巴黎可作《巴黎政闻录》；可再结合【政体】微调（如《巴黎宫廷公报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西官报》《日本邸报》。"
        ),
        "voice": (
            "你是一位生活在传统时代的邸报/官报总编纂，文风以文言为主、间用半文半白："
            "措辞古雅庄重、讲究等级仪节，善用「谨按」「伏惟」「本馆」「朝廷」等语汇，"
            "凡涉君上、教长、长老皆以敬辞。{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本馆」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部奏报，国用出入以……计」（填入给定GDP数值）"
            "引出经济总量，如「据户部奏报，国用出入以四千六百余万{CURRENCY}计」；"
            "人口、生活水平、识字率等其余指标以旧式公文笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为传统告示体：店铺告白、行会晓谕、学堂启事、敬神祈福告示皆可，"
            "措辞文言典雅，可带「谨此告白」「伏乞周知」「惠顾」等语汇，篇幅短小。"
        ),
        "number_format": "chinese",
        "number_guide": (
            "大数一律用汉字数字（如「四千六百零七万七千二百六十七」），"
            "百分比等现代度量可用阿拉伯数字（如 69.45%）。"
        ),
        "section_titles": {
            "headline": "头版",
            "war": "军务专报",
            "diplo": "邦交纪要",
            "econ": "度支要闻",
            "politics": "朝政动态",
            "society": "风俗与教化",
            "epidemic": "疫情邸报",
            "family": "乡里访谈",
            "peer": "富室纪闻",
            "unemployed": "流民情形",
            "comment": "本馆评说",
            "ads": "告白与告示",
        },
    },
    2: {
        "name": "公报（改良·启蒙与改良时代）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX公报》"
            "《XX时报》《XX政闻录》《XX回声报》等体例，如都城罗马可作《罗马公报》、"
            "都城巴黎可作《巴黎回声报》；可再结合【政体】微调（如《巴黎共和公报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西新闻》《日本新闻》。"
        ),
        "voice": (
            "你是一位生活于19世纪中后期至20世纪上半叶的报纸总编辑，文风「半文半白」："
            "以白话为主体、晓畅明白，又保留文言的凝练庄重（梁启超、鲁迅及民国初年"
            "《申报》《大公报》笔法）。{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部消息，我国国民生产总值为……」（填入给定GDP数值）"
            "引出经济总量，如「据户部消息，我国国民生产总值为430,521,263{CURRENCY}」；"
            "人口、生活水平、识字率等其余指标同样以旧式公文笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为20世纪初报刊告白体：商品告白、工艺铺面招贴、学堂晓谕、书画社启事皆可，"
            "措辞半文半白、文雅得体，可带「本店」「特此告白」「惠顾」等语汇，篇幅短小有趣。"
        ),
        "number_format": "chinese",
        "number_guide": (
            "大数一律用汉字数字（如「四千六百零七万七千二百六十七」），"
            "百分比等现代度量可用阿拉伯数字（如69.45%）。"
        ),
        "section_titles": {
            "headline": "头版",
            "war": "战事专电",
            "diplo": "外交风云",
            "econ": "经济要闻",
            "politics": "政界动态",
            "society": "民族宗教与社会",
            "epidemic": "疫情专电",
            "family": "民生访谈",
            "peer": "邻里富户",
            "unemployed": "失业民生",
            "comment": "本报评论",
            "ads": "广告与启示",
        },
    },
    3: {
        "name": "日报（现代·现代大众时代）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX日报》"
            "《XX早报》《XX晨报》《XX时报》等体例，如都城巴黎可作《巴黎日报》、"
            "都城京都可作《京都早报》；可再结合【政体】微调（如《巴黎共和日报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西日报》《日本日报》。"
        ),
        "voice": (
            "你是一位生活于20世纪的权威大报总编辑，供职于立场端正、面向全体国民的报纸。"
            "你的文风现代规范、庄重客观：白话为主、句式完整，善用「据悉」「报道」「各界」"
            "等语汇，消息客观、评论持重，措辞审慎；有喜报喜、有忧报忧，"
            "以建设与发展为主线。{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，如「国家统计局最新数据显示，我国GDP为430,521,263{CURRENCY}」；"
            "人口、生活水平、识字率等其余指标以官方书面语展开。"
        ),
        "ads_guide": (
            "广告栏须为现代报纸广告/启事体：国营厂矿与工商产品广告、展览会通知、"
            "招生启事、征订启事等，措辞正式简明，突出产品与服务。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如46,077,267{CURRENCY}、21,862,816人、69.45%）。"
        ),
        "section_titles": {
            "headline": "今日要闻",
            "war": "军事报道",
            "diplo": "国际要闻",
            "econ": "经济建设",
            "politics": "时政要闻",
            "society": "社会新闻",
            "epidemic": "疫情报道",
            "family": "人民生活",
            "peer": "先富观察",
            "unemployed": "就业民生",
            "comment": "社论",
            "ads": "广告启事",
        },
    },
    4: {
        "name": "新华报（进步·进步变革时代）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX新华报》"
            "《XX电讯》《XX评论报》等体例，如都城巴黎可作《巴黎新华报》、"
            "都城京都可作《京都电讯》；可再结合【政体】微调（如《巴黎共和新华报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西新华报》《日本电讯》。"
        ),
        "voice": (
            "你是一位供职于现代通讯社/新闻集团的资深记者与评论员，写作通稿体与深度报道："
            "消息开门见山，首段即时间、地点、事件三要素；事实准确、行文凝练、措辞规范，"
            "标题朴实有力；社论与调查报道发达，重视数据、逻辑与公共政策讨论，"
            "注重权威与可信。{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本社」指代本通讯社。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，其余数据以通稿体如实报道，可引用分析师观点与数据对比。"
        ),
        "ads_guide": (
            "广告栏须为现代新闻媒体分类广告/公告体：产品服务信息、展会通知、公益公告等，"
            "信息要素齐全（名称、地点、方式），标题简明，措辞平实。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如46,077,267{CURRENCY}、21,862,816人、69.45%）。"
        ),
        "section_titles": {
            "headline": "要闻",
            "war": "军事新闻",
            "diplo": "国际新闻",
            "econ": "经济新闻",
            "politics": "时政新闻",
            "society": "社会新闻",
            "epidemic": "疫情新闻",
            "family": "民生一线",
            "peer": "富户见闻",
            "unemployed": "就业观察",
            "comment": "新华时评",
            "ads": "分类广告",
        },
    },
    5: {
        "name": "思潮周刊（先锋·先锋思潮时代）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX思潮》"
            "《XX周刊》《XX评论》《XX论坛》等体例，如都城巴黎可作《巴黎思潮》、"
            "都城京都可作《京都评论周刊》；可再结合【政体】微调（如《巴黎共和评论》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西思潮》《日本评论》。"
        ),
        "voice": (
            "你是一位供职于先锋思潮刊物（评论周刊/文化杂志）的主笔，面向受过教育、"
            "关心思潮与制度的公众。你的文风锋利而有学养：善用概念、长于思辨，"
            "评论敢于触及制度与人心的深层结构；报道兼顾个案与结构，专题化、可带副刊笔调，"
            "标题新颖且庄重。{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本刊」指代本刊名。"
        ),
        "econ_guide": (
            "经济板块以深度观察笔法展开：首句可以「据最新统计，我国国民经济总量为……」"
            "或「纵观今年经济大势……」引出给定GDP数值，再分析结构变迁、阶层收益与制度影响，"
            "行文兼顾专业与可读。"
        ),
        "ads_guide": (
            "广告栏须为文化刊物启事体：新书出版、思想沙龙、讲座征稿、剧团演出、"
            "期刊征订等，措辞精炼有格调，可夹评论腔调，篇幅短小。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如46,077,267{CURRENCY}、21,862,816人、69.45%）。"
        ),
        "section_titles": {
            "headline": "本期焦点",
            "war": "战争观察",
            "diplo": "世界大势",
            "econ": "经济纵深",
            "politics": "政论",
            "society": "思潮与社会",
            "epidemic": "疫情观察",
            "family": "凡人列传",
            "peer": "资本观察",
            "unemployed": "失业问题研究",
            "comment": "主编评论",
            "ads": "文化启事",
        },
    },
}


# 「股市动态」板块标题: 旧系统 4 档 + 新系统 5 档各补缺省标题
_STOCK_SECTION_TITLES = {
    1: "市价行情",
    2: "股市动态",
    3: "股市动态",
    4: "财经行情",
    5: "市况观察",
}
# 「疫情专电」板块标题: 同上, 缺省兜底 (疫情年才出现)
_EPIDEMIC_SECTION_TITLES = {
    1: "疫情专电",
    2: "疫情报道",
    3: "疫情新闻",
    4: "疫情专讯",
    5: "疫情观察",
}
for _styles in (NEWSPAPER_STYLES, MODERNITY_TIERS):
    for _k, _s in _styles.items():
        _st = _s.setdefault("section_titles", {})
        _st.setdefault("stock", _STOCK_SECTION_TITLES.get(_k, "股市动态"))
        _st.setdefault("epidemic", _EPIDEMIC_SECTION_TITLES.get(_k, "疫情专电"))


def resolve_newspaper_style(data, cfg=None):
    """动态解析报纸风格, 返回与旧系统同构的风格 dict。
    额外附带 tier/score/govt_category/dop_law 供测试清单使用。"""
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    cat = govt_category(data)
    dop = dop_law(data)
    tier = resolve_tier(score, cat, dop)
    tmpl = MODERNITY_TIERS[tier]
    stance = GOVT_STANCE.get(cat, "")
    vote = DOP_NOTES.get(dop, "")
    # 时代定位按科技实际水平(基础档)描述; 政体/投票权只决定最终文风档位
    era = build_era_profile(tech_keys, _tier_from_score(score))
    st = {}
    for k, v in tmpl.items():
        if isinstance(v, str):
            v = (v.replace("{GOVT_STANCE}", stance)
                   .replace("{VOTE}", vote)
                   .replace("{ERA}", era)
                   .replace("{CURRENCY}", currency_unit(
                       tag=data.get("player_tag"),
                       player_name=data.get("player"))))
        st[k] = v
    st["tier"] = tier
    st["tier_name"] = TIER_NAMES.get(tier, "")
    st["score"] = score
    st["era_profile"] = era
    st["govt_category"] = cat
    st["dop_law"] = dop
    st["style_system"] = "dynamic"
    return st


def resolve_magazine_voice(data):
    """动态杂志基调: 政体底色 + 投票权现状 + 时代定位。"""
    cat = govt_category(data)
    base = GOVT_PROMPTS.get(cat, GOVT_PROMPTS["other"])
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    dop = dop_law(data)
    tier = resolve_tier(score, cat, dop)
    parts = [base]
    note = DOP_NOTES.get(dop)
    if note:
        parts.append(f"投票权现状：{note}")
    parts.append(f"时代定位：{build_era_profile(tech_keys, _tier_from_score(score))}")
    return "\n".join(parts)


def style_tier_from_data(data):
    """按当前存档数据解析文风档位 (1~5, 与 resolve_newspaper_style 同口径)。
    供州情速写等数据层按档位切换措辞 (低档传统、高档现代);
    解析失败返回 None。"""
    try:
        tech_keys = data.get("tech_keys") or []
        score = modernity_score(tech_keys)
        cat = govt_category(data)
        dop = dop_law(data)
        return resolve_tier(score, cat, dop)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 新系统: 杂志文章标题指南 (按文风档位)
# 每期文章标题不写死, 由模型依本指南拟题; 档位越低越庄重, 越高越现代/先锋。
# ---------------------------------------------------------------------------

MAGAZINE_TITLE_GUIDES = {
    1: (
        "文章标题宜古朴庄重，多用四至六字、对仗或典故化用（如《铁轨上的州》"
        "《门槛与选票》《街垒与公文》）。"
    ),
    2: (
        "文章标题宜半文半白、凝练典雅，四至八字皆可，可用对仗或意象"
        "（如《货架上的价签》《海外的来信》）。"
    ),
    3: (
        "文章标题宜现代规范、信息明确，四至十字皆可，允许主副题或冒号句式"
        "（如《铁道上的州：蒸汽与民生的时速》）。"
    ),
    4: (
        "文章标题宜新闻感强、有锐度，可用主副题、疑问或对比句式"
        "（如《光辉以外：动乱州的旗帜与衙门》），标题本身可点明矛盾。"
    ),
    5: (
        "文章标题宜先锋新颖、允许意象化与长标题，可用反讽、悖论或文学化表达"
        "（如《从货架里长出来的帝国》《在光辉以外的地方》），标题本身即观点。"
    ),
}


def resolve_magazine_title_guide(data):
    """按当前文风档位返回文章标题拟题指南。"""
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    cat = govt_category(data)
    dop = dop_law(data)
    tier = resolve_tier(score, cat, dop)
    return MAGAZINE_TITLE_GUIDES.get(tier, MAGAZINE_TITLE_GUIDES[3])
