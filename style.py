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
    "law_single_party_state": "当前为一党制国家，刊物与执政党路线保持一致，报道以建设成就、工业化与群众动员为主线。",
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


# ---------------------------------------------------------------------------
# 文风文化圈 (sphere) 轴
# ---------------------------------------------------------------------------
# 背景 (2026): 动态文风原先只有「档位」一条轴, 任何国家落到 1~2 档都套用中式
# 邸报体 (伏惟/谨按/本馆/朝廷), 非中华文化圈国家 (如西方专制国、哈萨克汗国)
# 因此写出文言与农历纪年。此处补一条文化圈轴, 只覆盖 1~2 档 (前期) 的语域,
# sinic 完全沿用 MODERNITY_TIERS 原文 (逐字节不变)。
#
#   sinic  中华文化圈: 汉/满/蒙古/藏/苗/彝/朝鲜/日本/越南…
#   west   西方: 欧洲/美洲/大洋洲/殖民定居社会
#   islam  伊斯兰世界: 阿拉伯/波斯/突厥/柏柏尔/萨赫勒穆斯林政权
#   other  其余: 南亚/东南亚/非洲/美洲原住民/太平洋 (中性王廷公报体)
#
# 判定主表 data/country_sphere.json 由 tools/gen_country_sphere.py 从游戏
# common/cultures 的 heritage 生成; 运行时以存档 player_tag 为主信号,
# 宗教与文化中文名兜底。

SPHERE_SINIC = "sinic"
SPHERE_WEST = "west"
SPHERE_ISLAM = "islam"
SPHERE_OTHER = "other"
SPHERES = (SPHERE_SINIC, SPHERE_WEST, SPHERE_ISLAM, SPHERE_OTHER)

SPHERE_NAMES = {
    SPHERE_SINIC: "中华文化圈",
    SPHERE_WEST: "西方",
    SPHERE_ISLAM: "伊斯兰世界",
    SPHERE_OTHER: "其他文化圈",
}

ISLAMIC_RELIGIONS = ("sunni", "shiite", "ibadi")

# 宗教 → 文化圈 (player_tag 不在主表时的兜底; islam 已由前置规则处理)
RELIGION_SPHERE = {
    "confucian": SPHERE_SINIC,
    "mahayana": SPHERE_SINIC,
    "gelugpa": SPHERE_SINIC,
    "shinto": SPHERE_SINIC,
    "catholic": SPHERE_WEST,
    "protestant": SPHERE_WEST,
    "orthodox": SPHERE_WEST,
    "oriental_orthodox": SPHERE_WEST,
    "jewish": SPHERE_WEST,
    "hindu": SPHERE_OTHER,
    "sikh": SPHERE_OTHER,
    "theravada": SPHERE_OTHER,
    "animist": SPHERE_OTHER,
}

# 文化中文名关键词 (仅当主表无此文化时使用; 主要覆盖 mod 新增文化)
_CULTURE_NAME_HINTS = (
    ("汉", SPHERE_SINIC), ("满", SPHERE_SINIC), ("蒙古", SPHERE_SINIC),
    ("藏", SPHERE_SINIC), ("苗", SPHERE_SINIC), ("彝", SPHERE_SINIC),
    ("朝鲜", SPHERE_SINIC), ("大和", SPHERE_SINIC), ("日本", SPHERE_SINIC),
    ("越南", SPHERE_SINIC), ("京族", SPHERE_SINIC),
    ("阿拉伯", SPHERE_ISLAM), ("波斯", SPHERE_ISLAM), ("土耳其", SPHERE_ISLAM),
    ("奥斯曼", SPHERE_ISLAM), ("库尔德", SPHERE_ISLAM), ("鞑靼", SPHERE_ISLAM),
    ("哈萨克", SPHERE_ISLAM), ("吉尔吉斯", SPHERE_ISLAM),
    ("乌兹别克", SPHERE_ISLAM), ("土库曼", SPHERE_ISLAM),
    ("维吾尔", SPHERE_ISLAM), ("柏柏尔", SPHERE_ISLAM), ("索马里", SPHERE_ISLAM),
    ("普什图", SPHERE_ISLAM), ("俾路支", SPHERE_ISLAM),
    ("阿塞拜疆", SPHERE_ISLAM), ("车臣", SPHERE_ISLAM), ("切尔克斯", SPHERE_ISLAM),
    ("法兰西", SPHERE_WEST), ("德意志", SPHERE_WEST), ("英吉利", SPHERE_WEST),
    ("英格兰", SPHERE_WEST), ("苏格兰", SPHERE_WEST), ("爱尔兰", SPHERE_WEST),
    ("西班牙", SPHERE_WEST), ("葡萄牙", SPHERE_WEST), ("意大利", SPHERE_WEST),
    ("荷兰", SPHERE_WEST), ("丹麦", SPHERE_WEST), ("瑞典", SPHERE_WEST),
    ("挪威", SPHERE_WEST), ("芬兰", SPHERE_WEST), ("波兰", SPHERE_WEST),
    ("匈牙利", SPHERE_WEST), ("罗马尼亚", SPHERE_WEST), ("希腊", SPHERE_WEST),
    ("俄罗斯", SPHERE_WEST), ("乌克兰", SPHERE_WEST), ("立陶宛", SPHERE_WEST),
    ("拉脱维亚", SPHERE_WEST), ("爱沙尼亚", SPHERE_WEST), ("美利坚", SPHERE_WEST),
    ("墨西哥", SPHERE_WEST), ("巴西", SPHERE_WEST), ("安的列斯", SPHERE_WEST),
)

_SPHERE_TABLE = None


def load_country_sphere_table():
    """读取 data/country_sphere.json; 缺失时返回空表 (全部走运行时兜底)。"""
    global _SPHERE_TABLE
    if _SPHERE_TABLE is not None:
        return _SPHERE_TABLE
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "country_sphere.json")
    try:
        with open(path, encoding="utf-8") as f:
            _SPHERE_TABLE = json.load(f) or {}
    except Exception:
        _SPHERE_TABLE = {}
    return _SPHERE_TABLE


def _culture_names_of(data):
    """存档数据里的文化中文名 (国族文化优先, 再取人口构成前三)。"""
    names = [str(c) for c in (data.get("primary_cultures") or []) if c]
    for c in (data.get("pop_cultures") or [])[:3]:
        if isinstance(c, dict) and c.get("name"):
            names.append(str(c["name"]))
    return names


def style_sphere_from_data(data):
    """解析当前存档的文风文化圈: player_tag 主表 → 国教 → 文化中文名 → other。

    伊斯兰国教优先于主表的 west/other/islam 判定 (巴厘这类印度教主体、
    穆斯林次文化政权因此留在 other), 中华文化圈不受宗教改写。
    """
    data = data or {}
    table = load_country_sphere_table()
    tags = table.get("tags") or {}
    tag = str(data.get("player_tag") or data.get("tag") or "").upper()
    sp = tags.get(tag)
    if sp == SPHERE_SINIC:
        return SPHERE_SINIC
    rel = str(data.get("religion") or "").lower()
    if rel in ISLAMIC_RELIGIONS:
        return SPHERE_ISLAM
    if sp in SPHERES:
        return sp
    cultures = table.get("cultures") or {}
    for name in _culture_names_of(data):
        if cultures.get(name) in SPHERES:
            return cultures[name]
    for name in _culture_names_of(data):
        for hint, sphere in _CULTURE_NAME_HINTS:
            if hint in name:
                return sphere
    return RELIGION_SPHERE.get(rel, SPHERE_OTHER)


# ---------------------------------------------------------------------------
# 极权主义政权 (一党制) 专属现代化文风
# 一党制国家不走文风档位的仿古/自由派基调, 一律使用现代机关报/宣传路线:
# 明快刚健的现代白话, 报道以建设成就与群众动员为主线。
# 极权政体未必是法西斯/法团主义 (还可能是共产主义), 文风按意识形态色彩分流:
#   communist   (苏维埃/委员会/公社类政体键) → 先锋·集体叙事
#   corporatist (长枪党/法西斯/法团类政体键) → 统合·民族复兴叙事
#   generic     (无法归类的其余一党制)        → 中性机关报叙事
# ---------------------------------------------------------------------------

TOTALITARIAN_DOPS = ("law_single_party_state",)


def totalitarian_flavor(data):
    """一党制政权的文风色彩: communist / corporatist / generic。
    主信号 = 存档政体键 (govt_key); 政党模板解析落地后可按唯一合法党模板作辅信号。"""
    gk = str(data.get("govt_key") or data.get("govt") or "").lower()
    if any(k in gk for k in ("soviet", "council", "commune", "cybernetic",
                             "anarchist")):
        return "communist"
    if any(k in gk for k in ("falangist", "fascist", "corporate",
                             "volksgemeinschaft", "folkhemmet", "technate")):
        return "corporatist"
    return "generic"


TOTALITARIAN_STYLES = {
    "communist": {
        "name": "人民之声报（先锋·现代）",
        "stance": "当前为一党制国家，报名与行文宜带先锋与集体色彩，使用现代白话。",
        "voice": (
            "你是一位供职于现代人民机关刊物（党报/先锋报）的总编辑，面向全体劳动人民。"
            "文风明快刚健、组织化，以现代白话书写；"
            "报道以建设成就、工业化与群众动员为主线，"
            "把个人命运纳入人民事业的集体叙事，行文肯定而昂扬。"
            "年份一律按公历纪年书写（如1878年）。{ERA}{VOTE}"
            "使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "masthead": (
            "【报名】报名须与国名或都城相关，本政权宜采用《XX日报》《XX先锋报》"
            "《XX人民报》《XX工人报》等现代体例，如都城墨西哥城可作《墨西哥城人民报》。"
            "若首都或政体数据缺失，则退而用国名拟定，如《墨西哥人民报》。"
        ),
        "mag_voice": (
            "本刊为执政党领导的现代机关刊物，编辑立场与执政党路线一致。"
            "文风明快刚健、组织化，以现代白话书写；"
            "叙事重心放在建设现场——工厂、铁路、课堂、诊室与街巷，"
            "把个人命运纳入人民事业的集体叙事，报道以建设成就、工业化与群众动员为主线。"
            "年份一律按公历纪年书写（如1878年）。"
        ),
    },
    "corporatist": {
        "name": "国家建设报（统合·现代）",
        "stance": "当前为一党制国家，报名与行文宜带统合与动员色彩，使用现代白话。",
        "voice": (
            "你是一位供职于现代国家机关刊物（党报/建设报）的总编辑，面向全体国民。"
            "文风明快刚健、组织化，以现代白话书写；"
            "报道以建设成就、工业化与群众动员为主线，"
            "把个人命运纳入民族复兴的集体叙事，行文肯定而昂扬。"
            "年份一律按公历纪年书写（如1878年）。{ERA}{VOTE}"
            "使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "masthead": (
            "【报名】报名须与国名或都城相关，本政权宜采用《XX日报》《XX建设报》"
            "《XX先锋报》《XX统合报》等现代体例，如都城墨西哥城可作《墨西哥城日报》。"
            "若首都或政体数据缺失，则退而用国名拟定，如《墨西哥日报》。"
        ),
        "mag_voice": (
            "本刊为国家统合运动旗下的现代机关刊物，编辑立场与执政党路线一致。"
            "文风明快刚健、组织化，以现代白话书写；"
            "叙事重心放在建设现场——工厂、铁路、课堂、诊室与街巷，"
            "把个人命运纳入民族复兴的集体叙事，报道以建设成就、工业化与群众动员为主线。"
            "年份一律按公历纪年书写（如1878年）。"
        ),
    },
    "generic": {
        "name": "国家建设报（现代）",
        "stance": "当前为一党制国家，报名与行文宜带国家动员色彩，使用现代白话。",
        "voice": (
            "你是一位供职于现代国家机关刊物（党报/建设报）的总编辑，面向全体国民。"
            "文风明快刚健、组织化，以现代白话书写；"
            "报道以建设成就、工业化与群众动员为主线，"
            "把个人命运纳入国家事业的集体叙事，行文肯定而昂扬。"
            "年份一律按公历纪年书写（如1878年）。{ERA}{VOTE}"
            "使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；"
            "数据缺失时相应内容简写或略去；行文中以「本报」指代本报刊名。"
        ),
        "masthead": (
            "【报名】报名须与国名或都城相关，本政权宜采用《XX日报》《XX建设报》"
            "《XX先锋报》《XX公报》等现代体例，如都城墨西哥城可作《墨西哥城日报》。"
            "若首都或政体数据缺失，则退而用国名拟定，如《墨西哥日报》。"
        ),
        "mag_voice": (
            "本刊为执政党领导的现代机关刊物，编辑立场与执政党路线一致。"
            "文风明快刚健、组织化，以现代白话书写；"
            "叙事重心放在建设现场——工厂、铁路、课堂、诊室与街巷，"
            "把个人命运纳入国家事业的集体叙事，报道以建设成就、工业化与群众动员为主线。"
            "年份一律按公历纪年书写（如1878年）。"
        ),
    },
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


# ---------------------------------------------------------------------------
# 非中华文化圈: 1~2 档语域覆盖 (前期文风)
# 合并规则见 _apply_sphere_override: 基础档位模板 → 覆盖层 → 变量替换。
# 覆盖层字段与 MODERNITY_TIERS 同构; voice_extra 追加到基础 voice 之后。
# 所有非 sinic 文化圈统一追加公历纪年规则 (_SPHERE_CALENDAR), 与 voice 去重。
# ---------------------------------------------------------------------------

_SPHERE_CALENDAR = (
    "纪年一律用公历，日期写作「1836年7月1日」，年份写作「1836年」。"
)
_CALENDAR_MARK = "纪年一律用公历"

_ARABIC_NUMBER_GUIDE = (
    "一律使用阿拉伯数字并加千分位分隔符"
    "（如27,515,352{CURRENCY}、621,211人、8.65%）。"
)

# 政体称谓句: 共和政体用总统/内阁/法令, 君主政体用君主/王室/敕令,
# 由 {SPHERE_TITLES} 占位符注入 (共和国的称谓因此与君主国区分)。
_REPUBLIC_CATS = ("council_republic", "parliamentary_republic",
                  "presidential_republic")

_SPHERE_TITLES = {
    SPHERE_WEST: {
        "monarchy": ("称君主为「陛下」、称王室为「宫廷」，"
                     "政令称「敕令」「公告」「通令」，"),
        "republic": ("称国家元首为「总统」、称政府为「内阁」「各部」，"
                     "政令称「法令」「公告」「通令」，"),
    },
    SPHERE_ISLAM: {
        "monarchy": ("称君主为「苏丹」「沙阿」「汗」「埃米尔」"
                     "（按政体与国名常识选用）并以敬辞，称王室为「王廷」「宫廷」，"
                     "政令称「敕令」「上谕」「御前会议决议」，"),
        "republic": ("称国家元首为「总统」「主席」（按政体与国名常识选用），"
                     "称政府为「内阁」「各部」，"
                     "政令称「法令」「公告」「御前会议决议」，"),
    },
    SPHERE_OTHER: {
        "monarchy": ("称君主与首领为「国王」「苏丹」「酋长」「可汗」「长老」"
                     "（按政体与国名常识选用）并以敬辞，"
                     "政令称「敕令」「公告」「议事会决议」，"),
        "republic": ("称国家元首为「总统」「主席」（按政体与国名常识选用），"
                     "称政府为「内阁」「各部」，"
                     "政令称「法令」「公告」「议事会决议」，"),
    },
}


def _sphere_titles(sphere, cat):
    """政体称谓句: 共和政体 → 总统/内阁/法令, 其余 → 君主/王室/敕令。"""
    table = _SPHERE_TITLES.get(sphere) or {}
    key = "republic" if cat in _REPUBLIC_CATS else "monarchy"
    return table.get(key, "")

# 西方: 1 档旧制度官报体 / 2 档党派大报体 / 3 档现代大报(只换机构称谓与纪年)
_WEST_TIERS = {
    1: {
        "name": "官报（守成·旧制度）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX官报》"
            "《XX公报》《XX宫廷公报》《XX纪事报》等体例，如都城维也纳可作"
            "《维也纳官报》、都城柏林可作《柏林公报》、都城圣彼得堡可作"
            "《圣彼得堡公报》；可再结合【政体】微调（如《维也纳王国公报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《普鲁士官报》《俄罗斯公报》。"
        ),
        "voice": (
            "你是一位供职于旧制度官方公报的总编辑。本报经王室或政府特许出版，"
            "稿件由审查官核准。你的文风是庄重克制的官报公文体：以第三人称记述，"
            "句法完整、语序平正，多用被动式与程式化套语；"
            "{SPHERE_TITLES}议会称「议院」「两院」，财政称「国库」「财政部」；"
            "全篇一律使用上述称谓。消息一律注明来源（如「据官方公报」"
            "「据政府发布」「据某部呈报」），评论置于官方部分之外、措辞审慎。"
            "纪年一律用公历，日期写作「1836年7月1日」，年份写作「1836年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据财政部与官方统计公报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，如「据财政部与官方统计公报，"
            "我国国民生产总值为27,515,352{CURRENCY}」；人口、生活水平、识字率等"
            "其余指标以官方公报笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为官报公告与告白体：专利特许、招标公告、船期通告、书籍出版、"
            "债票发行、土地房产出售、赏格与寻人启事皆可，措辞正式简明，"
            "可带「兹公告」「敬请赐顾」「函询」等语汇，篇幅短小。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版公告",
            "war": "战事公报",
            "diplo": "外交通报",
            "econ": "财政与商务",
            "politics": "宫廷与内阁",
            "society": "教会与社会",
            "epidemic": "疫病通报",
            "family": "本报访问",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "本报评论",
            "ads": "公告与广告",
            "stock": "行情公报",
        },
    },
    2: {
        "name": "时报（改良·党派与公共舆论）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX时报》"
            "《XX每日新闻》《XX纪事报》《XX邮报》《XX广告报》等体例，"
            "如都城伦敦可作《伦敦时报》、都城巴黎可作《巴黎纪事报》；"
            "可再结合【政体】微调（如《巴黎共和时报》），并随其变迁而调整。"
            "{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《普鲁士时报》《俄罗斯纪事报》。"
        ),
        "voice": (
            "你是一位生活于19世纪中后期的大报总编辑，报纸以社论与通讯取胜，"
            "立场带有党派色彩。你的文风是庄重的书面语：句子较长、多用从句与被动式，"
            "社论以「本报」第一人称发言，消息冠以「据悉」「据可靠消息」"
            "「本报驻某地通讯员报道」等语汇；评论敢于表态，兼有道德判断与含蓄讽刺，"
            "措辞典雅。纪年一律用公历，日期写作「1857年3月4日」，年份写作「1857年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据官方统计，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，再以社论笔法分析财政、贸易与民生。"
        ),
        "ads_guide": (
            "广告栏须为19世纪大报分类广告体：船期、拍卖、招工、专利药品、书籍出版、"
            "铁路时刻、银行与保险告白皆可，措辞简明，信息要素齐全（名称、地点、方式）。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版要闻",
            "war": "战地通讯",
            "diplo": "国外消息",
            "econ": "商务与金融",
            "politics": "议会与内阁",
            "society": "社会新闻",
            "epidemic": "疫病通报",
            "family": "本报专访",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "社论",
            "ads": "广告",
            "stock": "行情",
        },
    },
    3: {
        "econ_guide": (
            "经济板块首句必须以「据官方统计公报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，如「据官方统计公报，"
            "我国国民生产总值为430,521,263{CURRENCY}」；人口、生活水平、识字率等"
            "其余指标以官方书面语展开。"
        ),
        "voice_extra": _SPHERE_CALENDAR,
    },
}

# 伊斯兰世界: 1 档王廷公报体 / 2 档改良立宪报刊 / 3 档只换机构称谓与纪年
_ISLAM_TIERS = {
    1: {
        "name": "王廷公报（守成·传统秩序）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX公报》"
            "《XX王廷公报》《XX官报》《XX纪事》等体例，如都城伊斯坦布尔可作"
            "《伊斯坦布尔公报》、都城德黑兰可作《德黑兰王廷公报》、都城布哈拉可作"
            "《布哈拉官报》；可再结合【政体】微调（如《伊斯坦布尔苏丹公报》），"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《奥斯曼公报》《波斯官报》。"
        ),
        "voice": (
            "你是一位供职于王廷公报的总编辑。本报经君主特许出版，稿件由官署核准。"
            "你的文风是庄重简明的公文体：以第三人称记述，句法完整、语序平正，"
            "{SPHERE_TITLES}官署称「迪万」「维齐尔」「各部」，"
            "宗教事务称「教法」「乌理玛」「教团」；全篇一律使用上述称谓。"
            "消息一律注明来源（如「据官方公报」「据迪万呈报」），评论措辞审慎。"
            "纪年一律用公历，日期写作「1836年7月1日」，年份写作「1836年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据国库与迪万呈报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，如「据国库与迪万呈报，"
            "我国国民生产总值为27,515,352{CURRENCY}」；人口、生活水平、识字率等"
            "其余指标以王廷公报笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为王廷公告与市集告白体：商队通告、市集招贴、工匠行会告白、"
            "清真寺学堂启事、赏格与寻人启事皆可，措辞正式简明，"
            "可带「谨此公告」「敬请周知」「惠顾」等语汇，篇幅短小。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版公告",
            "war": "战事公报",
            "diplo": "邦交通报",
            "econ": "国库与市集",
            "politics": "王廷与迪万",
            "society": "教团与社会",
            "epidemic": "疫病通报",
            "family": "本报访问",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "本报评论",
            "ads": "公告与告白",
            "stock": "行情公报",
        },
    },
    2: {
        "name": "公报（改良·立宪与报刊）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX公报》"
            "《XX时报》《XX新闻》《XX纪事》等体例，如都城伊斯坦布尔可作"
            "《伊斯坦布尔时报》、都城德黑兰可作《德黑兰新闻》；"
            "可再结合【政体】微调（如《伊斯坦布尔立宪公报》），并随其变迁而调整。"
            "{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《奥斯曼时报》《波斯新闻》。"
        ),
        "voice": (
            "你是一位生活于19世纪中后期的改良报刊总编辑，报纸主张立宪、教育与自强。"
            "你的文风庄重典雅：兼采古典辞令与近代术语，句子较长、结构完整，"
            "社论以「本报」第一人称发言，消息冠以「据悉」「据本埠消息」"
            "「本报驻某地访员报道」等语汇；评论敢于建言，措辞审慎而坚定。"
            "纪年一律用公历，日期写作「1857年3月4日」，年份写作「1857年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据官方统计，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，再以论说笔法分析财政、商贸与民生。"
        ),
        "ads_guide": (
            "广告栏须为近代报刊告白体：商行招贴、船期、书籍出版、学堂招生、"
            "银行与保险告白皆可，措辞简明，信息要素齐全（名称、地点、方式）。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版要闻",
            "war": "战事通讯",
            "diplo": "国外消息",
            "econ": "商务与金融",
            "politics": "内阁与议会",
            "society": "社会新闻",
            "epidemic": "疫病通报",
            "family": "本报专访",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "社论",
            "ads": "广告",
            "stock": "行情",
        },
    },
    3: {
        "econ_guide": (
            "经济板块首句必须以「据官方统计公报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，其余指标以官方书面语展开。"
        ),
        "voice_extra": _SPHERE_CALENDAR,
    },
}

# 其余文化圈: 1 档王廷/部族公报体 / 2 档近代报刊 / 3 档只换纪年
_OTHER_TIERS = {
    1: {
        "name": "王廷公报（守成·传统秩序）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX公报》"
            "《XX官报》《XX王廷公报》《XX纪事》等体例，如都城曼谷可作《曼谷公报》、"
            "都城加德满都可作《加德满都王廷公报》；可再结合【政体】微调"
            "（如《曼谷王国公报》），并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《暹罗公报》《尼泊尔官报》。"
        ),
        "voice": (
            "你是一位供职于王廷或部族议事会公报的总编辑。你的文风是庄重简明的公文体："
            "以第三人称记述，句法完整、语序平正，{SPHERE_TITLES}"
            "官署称「官署」「各部」；全篇一律使用上述称谓。"
            "消息一律注明来源（如「据官方公报」「据官署呈报」），评论措辞审慎。"
            "纪年一律用公历，日期写作「1836年7月1日」，年份写作「1836年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据官署与市集呈报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，如「据官署与市集呈报，"
            "我国国民生产总值为27,515,352{CURRENCY}」；人口、生活水平、识字率等"
            "其余指标以公报笔法展开。"
        ),
        "ads_guide": (
            "广告栏须为王廷公告与市集告白体：商队通告、市集招贴、行会告白、"
            "寺庙或学堂启事、赏格与寻人启事皆可，措辞正式简明，篇幅短小。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版公告",
            "war": "战事公报",
            "diplo": "邦交通报",
            "econ": "物产与市集",
            "politics": "王廷与议事",
            "society": "部族与社会",
            "epidemic": "疫病通报",
            "family": "本报访问",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "本报评论",
            "ads": "公告与告白",
            "stock": "行情公报",
        },
    },
    2: {
        "name": "公报（改良·报刊初兴）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，本风格宜采用《XX公报》"
            "《XX时报》《XX新闻》《XX纪事》等体例，如都城曼谷可作《曼谷时报》、"
            "都城亚的斯亚贝巴可作《亚的斯亚贝巴新闻》；可再结合【政体】微调，"
            "并随其变迁而调整。{GOVT_STANCE}" + _MASTHEAD_BASE +
            "若首都或政体数据缺失，则退而用国名拟定，如《暹罗时报》《埃塞俄比亚新闻》。"
        ),
        "voice": (
            "你是一位生活于19世纪中后期的报刊总编辑，报纸以消息与评论并举。"
            "你的文风庄重平实：句子结构完整，社论以「本报」第一人称发言，"
            "消息冠以「据悉」「据本埠消息」等语汇，评论敢于建言而措辞审慎。"
            "纪年一律用公历，日期写作「1857年3月4日」，年份写作「1857年」。"
            "{ERA}{VOTE}使用简体中文与 Markdown。"
            "铁律：仅基于给定事实合理演绎；数据缺失时相应内容简写或略去；"
            "行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据官方统计，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，再以论说笔法分析物产、商贸与民生。"
        ),
        "ads_guide": (
            "广告栏须为近代报刊告白体：商行招贴、船期、书籍出版、学堂招生皆可，"
            "措辞简明，信息要素齐全（名称、地点、方式）。"
        ),
        "number_format": "arabic",
        "number_guide": _ARABIC_NUMBER_GUIDE,
        "section_titles": {
            "headline": "头版要闻",
            "war": "战事通讯",
            "diplo": "国外消息",
            "econ": "商务与物产",
            "politics": "王廷与议会",
            "society": "社会新闻",
            "epidemic": "疫病通报",
            "family": "本报专访",
            "peer": "富室访问",
            "unemployed": "失业调查",
            "comment": "社论",
            "ads": "广告",
            "stock": "行情",
        },
    },
    3: {
        "econ_guide": (
            "经济板块首句必须以「据官方统计公报，我国国民生产总值为……」"
            "（填入给定GDP数值）引出经济总量，其余指标以官方书面语展开。"
        ),
        "voice_extra": _SPHERE_CALENDAR,
    },
}

SPHERE_TIER_OVERRIDES = {
    SPHERE_WEST: _WEST_TIERS,
    SPHERE_ISLAM: _ISLAM_TIERS,
    SPHERE_OTHER: _OTHER_TIERS,
}


def _apply_sphere_override(tmpl, sphere, tier):
    """基础档位模板 → 文化圈覆盖层; 非 sinic 统一追加公历纪年规则。"""
    ov = (SPHERE_TIER_OVERRIDES.get(sphere) or {}).get(tier)
    st = dict(tmpl)
    if ov:
        for k, v in ov.items():
            if k == "voice_extra":
                st["voice"] = str(st.get("voice") or "") + str(v)
            elif k == "section_titles":
                merged = dict(st.get("section_titles") or {})
                merged.update(v or {})
                st["section_titles"] = merged
            else:
                st[k] = v
    if sphere != SPHERE_SINIC:
        voice = str(st.get("voice") or "")
        if "公历" not in voice:
            st["voice"] = voice + _SPHERE_CALENDAR
    return st


def resolve_newspaper_style(data, cfg=None):
    """动态解析报纸风格, 返回与旧系统同构的风格 dict。
    额外附带 tier/score/govt_category/dop_law/sphere 供测试清单使用。"""
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    cat = govt_category(data)
    dop = dop_law(data)
    tier = resolve_tier(score, cat, dop)
    sphere = style_sphere_from_data(data)
    tmpl = _apply_sphere_override(MODERNITY_TIERS[tier], sphere, tier)
    stance = GOVT_STANCE.get(cat, "")
    if dop in TOTALITARIAN_DOPS:
        # 极权主义政权 (一党制): 现代机关报文风, 数字一律阿拉伯, 不随档位仿古
        tot = TOTALITARIAN_STYLES[totalitarian_flavor(data)]
        tmpl = dict(tmpl)
        tmpl["name"] = tot["name"]
        tmpl["voice"] = tot["voice"]
        tmpl["masthead"] = tot["masthead"]
        tmpl["number_format"] = "arabic"
        tmpl["number_guide"] = (
            "一律使用阿拉伯数字并加千分位分隔符（如46,077,267{CURRENCY}、"
            "21,862,816人、69.45%）。"
        )
        stance = tot["stance"]
    vote = DOP_NOTES.get(dop, "")
    titles = _sphere_titles(sphere, cat)
    # 时代定位按科技实际水平(基础档)描述; 政体/投票权只决定最终文风档位
    era = build_era_profile(tech_keys, _tier_from_score(score))
    st = {}
    for k, v in tmpl.items():
        if isinstance(v, str):
            v = (v.replace("{GOVT_STANCE}", stance)
                   .replace("{SPHERE_TITLES}", titles)
                   .replace("{VOTE}", vote)
                   .replace("{ERA}", era)
                   .replace("{CURRENCY}", currency_unit(
                       tag=data.get("player_tag"))))
        st[k] = v
    st["tier"] = tier
    st["tier_name"] = TIER_NAMES.get(tier, "")
    st["score"] = score
    st["era_profile"] = era
    st["govt_category"] = cat
    st["dop_law"] = dop
    # 共和政体的板块名去掉「宫廷」类君主措辞 (west/islam/other 1~2 档模板)
    if cat in _REPUBLIC_CATS and sphere != SPHERE_SINIC:
        titles = dict(st.get("section_titles") or {})
        for old, new in (("宫廷与内阁", "政府与内阁"),
                         ("王廷与迪万", "内阁与议会"),
                         ("王廷与议事", "政府与议会")):
            if titles.get("politics") == old:
                titles["politics"] = new
        st["section_titles"] = titles
    st["sphere"] = sphere
    st["sphere_name"] = SPHERE_NAMES.get(sphere, "")
    st["style_system"] = "dynamic"
    return st


# ---------------------------------------------------------------------------
# 非中华文化圈: 杂志刊物语域与政体立场 (1~2 档)
# 政体立场逐条对应 GOVT_PROMPTS 的八个类别, 但用该文化圈的制度词汇表述。
# ---------------------------------------------------------------------------

_MAGAZINE_SPHERE_REGISTER = {
    SPHERE_WEST: {
        1: ("本刊为旧制度下的官方或半官方刊物，受特许与审查；文风庄重克制，"
            "以第三人称记述，纪年一律用公历（如1836年）。"),
        2: ("本刊为19世纪中后期的评论刊物，文风庄重典雅，长于论说与书评，"
            "以「本刊」自称，纪年一律用公历（如1857年）。"),
        3: ("本刊为面向公众的现代刊物，文风现代规范、庄重客观，"
            "纪年一律用公历（如1890年）。"),
    },
    SPHERE_ISLAM: {
        1: ("本刊为伊斯兰政权的官方或半官方刊物，文风庄重，称君主以苏丹、沙阿、"
            "汗、埃米尔等尊号，纪年一律用公历（如1836年）。"),
        2: ("本刊为伊斯兰世界的改良报刊，文风庄重典雅，兼采古典辞令与近代术语，"
            "纪年一律用公历（如1857年）。"),
        3: ("本刊为面向公众的现代刊物，文风现代规范，兼采本国制度词汇，"
            "纪年一律用公历（如1890年）。"),
    },
    SPHERE_OTHER: {
        1: ("本刊为传统王廷或部族议事会的公报，文风庄重简明，"
            "纪年一律用公历（如1836年）。"),
        2: ("本刊为近代报刊，文风庄重平实，以「本刊」自称，"
            "纪年一律用公历（如1857年）。"),
        3: ("本刊为面向公众的现代刊物，文风现代规范平实，"
            "纪年一律用公历（如1890年）。"),
    },
}

_MAGAZINE_GOVT_STANCE = {
    SPHERE_WEST: {
        "council_republic": "编辑立场站在劳动与共和一边，叙事重心放在工厂、工会与市政。",
        "parliamentary_republic": "编辑立场尊重议会程序与公民权利，叙事重心放在内阁、法案与民意。",
        "presidential_republic": "编辑立场崇尚宪法与个人自由，叙事重心放在行政、市场与边疆。",
        "social_monarchy": "编辑立场主张君民调和与渐进改良，叙事重心放在王室、立法与社会福利。",
        "monarchy": "编辑立场忠于王室与正统，叙事重心放在宫廷、内阁与帝国事务。",
        "theocracy": "编辑立场以教会教义为准绳，叙事重心放在教区、礼拜与信徒生活。",
        "chiefdom": "编辑立场尊重社群与长老，叙事重心放在部族事务与土地。",
        "other": "编辑立场中立克制，叙事重心放在具体人物的命运与时代大势。",
    },
    SPHERE_ISLAM: {
        "council_republic": "编辑立场站在劳动与共和一边，叙事重心放在行会、市集与市政。",
        "parliamentary_republic": "编辑立场尊重协商与公共事务，叙事重心放在内阁、议会与民意。",
        "presidential_republic": "编辑立场崇尚宪政与秩序，叙事重心放在行政、商贸与边疆。",
        "social_monarchy": "编辑立场主张君民调和与渐进改良，叙事重心放在王廷、立法与社会福利。",
        "monarchy": "编辑立场忠于君主与教法，叙事重心放在王廷、迪万与疆域。",
        "theocracy": "编辑立场以教法为准绳，叙事重心放在教义、教团与信众生活。",
        "chiefdom": "编辑立场尊重长老与部族，叙事重心放在议事、牧场与征战。",
        "other": "编辑立场中立克制，叙事重心放在具体人物的命运与时代大势。",
    },
    SPHERE_OTHER: {
        "council_republic": "编辑立场站在劳动与社群一边，叙事重心放在工坊、村社与市政。",
        "parliamentary_republic": "编辑立场尊重议事与公共事务，叙事重心放在会议、法案与民意。",
        "presidential_republic": "编辑立场崇尚秩序与进步，叙事重心放在行政、商贸与边疆。",
        "social_monarchy": "编辑立场主张君民调和与渐进改良，叙事重心放在王廷、立法与社会福利。",
        "monarchy": "编辑立场忠于君主与传统，叙事重心放在王廷、官署与疆域。",
        "theocracy": "编辑立场以教义为准绳，叙事重心放在寺庙、教团与信众生活。",
        "chiefdom": "编辑立场尊重长老与部族，叙事重心放在议事、土地与社群。",
        "other": "编辑立场中立克制，叙事重心放在具体人物的命运与时代大势。",
    },
}


def _sphere_magazine_base(sphere, cat, tier):
    """文化圈刊物语域 + 该文化圈的政体立场 (1 / 2 / 3+ 档)。"""
    reg = (_MAGAZINE_SPHERE_REGISTER.get(sphere) or {}).get(
        1 if tier <= 1 else (2 if tier == 2 else 3), "")
    table = _MAGAZINE_GOVT_STANCE.get(sphere) or {}
    stance = table.get(cat) or table.get("other", "")
    return reg + stance


def resolve_magazine_voice(data):
    """动态杂志基调: 文化圈语域 + 政体底色 + 投票权现状 + 时代定位。
    非中华文化圈全部档位改用该文化圈刊物语域 (与报纸同口径);
    非中华文化圈一律附公历纪年规则, 防止导言写出农历/干支。"""
    cat = govt_category(data)
    dop = dop_law(data)
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    tier = resolve_tier(score, cat, dop)
    sphere = style_sphere_from_data(data)
    if dop in TOTALITARIAN_DOPS:
        # 极权主义政权 (一党制): 现代机关刊物文风, 按意识形态色彩分流, 不走仿古基调
        base = TOTALITARIAN_STYLES[totalitarian_flavor(data)]["mag_voice"]
    elif sphere != SPHERE_SINIC:
        # 非中华文化圈: 全部档位走本文化圈刊物语域 (1~2 档仿古, 3 档以上现代)
        base = _sphere_magazine_base(sphere, cat, tier)
    else:
        base = _strip_name_guide(GOVT_PROMPTS.get(cat, GOVT_PROMPTS["other"]))
    parts = [base]
    note = DOP_NOTES.get(dop)
    if note:
        parts.append(f"投票权现状：{note}")
    parts.append(f"时代定位：{build_era_profile(tech_keys, _tier_from_score(score))}")
    if sphere != SPHERE_SINIC and "公历" not in base:
        parts.append(_SPHERE_CALENDAR)
    return "\n".join(parts)


def _strip_name_guide(prompt):
    """剥离基调文本中的「刊名…」句子: 杂志刊名已由程序派生 (derive_magazine_name)
    并以【刊名】变量下发, 不再把拟名规则交给模型, 避免与既定刊名重复/误导。"""
    if not prompt:
        return prompt
    sents = [s for s in str(prompt).split("。") if s.strip()]
    keep = [s for s in sents if "刊名" not in s]
    return "。".join(keep) + ("。" if keep else "")


# 杂志刊名后缀: 按文风档位派生 (与 MAGAZINE_TITLE_GUIDES / MODERNITY_TIERS 呼应)。
# 档位 resolve_tier 由科技分支 (score) + 政体法律 (cat) + 投票权法律 (dop) 共同
# 决定, 故法律或科技变化时刊名后缀随之变化; 未变化时全年稳定, 不再逐年重拟。
_MAGAZINE_NAME_SUFFIX = {
    1: "纪事",
    2: "月刊",
    3: "杂志",
    4: "评论",
    5: "思潮",
}


def derive_magazine_name(data):
    """本期杂志刊名: 首都名 (缺省国名) + 文风档位后缀, 确定性派生。"""
    base = str(data.get("capital") or data.get("player") or "未知").strip()
    try:
        tier = style_tier_from_data(data)
    except Exception:
        tier = 3
    suffix = _MAGAZINE_NAME_SUFFIX.get(tier, "月刊")
    return f"{base}{suffix}"


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


MAGAZINE_TITLE_GUIDES_SPHERE = {
    SPHERE_WEST: {
        1: ("文章标题宜庄重简练，可用「论……」「……述略」「……纪事」等论说体，"
            "四至十字皆可（如《论谷物法》《国库岁入述略》）。"),
        2: ("文章标题宜带评论与通讯色彩，可用「论……之弊」「一个……的来信」"
            "「……见闻录」等体例（如《论关税之弊》《一个工厂工人的来信》）。"),
    },
    SPHERE_ISLAM: {
        1: ("文章标题宜庄重典雅，多用「论……」「……纪事」「……述略」等体例，"
            "四至十字皆可（如《论教法与市集》《迪万纪事》）。"),
        2: ("文章标题宜带论说与通讯色彩，可用「论……」「……见闻录」等体例"
            "（如《论立宪之益》《伊斯坦布尔见闻录》）。"),
    },
    SPHERE_OTHER: {
        1: ("文章标题宜庄重简明，多用「……纪事」「……述略」等体例，"
            "四至十字皆可（如《王廷纪事》《市集述略》）。"),
        2: ("文章标题宜平实明确，可用「……见闻录」「论……」等体例"
            "（如《曼谷见闻录》《论稻米之利》）。"),
    },
}


def resolve_magazine_title_guide(data):
    """按当前文风档位与文化圈返回文章标题拟题指南。
    非中华文化圈的 1~2 档用该文化圈的标题体例, 其余回落到档位指南。"""
    tech_keys = data.get("tech_keys") or []
    score = modernity_score(tech_keys)
    cat = govt_category(data)
    dop = dop_law(data)
    tier = resolve_tier(score, cat, dop)
    sphere = style_sphere_from_data(data)
    if sphere != SPHERE_SINIC:
        guide = (MAGAZINE_TITLE_GUIDES_SPHERE.get(sphere) or {}).get(tier)
        if guide:
            return guide
    return MAGAZINE_TITLE_GUIDES.get(tier, MAGAZINE_TITLE_GUIDES[3])
