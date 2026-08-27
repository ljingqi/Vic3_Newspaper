"""动态货币单位表 (维多利亚 3 存档 → 叙事货币单位)。

游戏内所有金额本身是同一套「镑」数值, 本项目只做单位字样的本地化,
不做汇率换算。货币按「同名共享」原则分组: 一个币名对应多个国家 TAG,
未收录的国家一律回退默认「英镑」。

TAG 清单来自 tools/gen_country_table.py 爬取的 game/common/country_definitions,
中文国名来自 localization/simp_chinese/countries_l_simp_chinese.yml。
币名取 19 世纪常用叫法, 静态选择 (不随时间线切换, 如日本两→日元)。
"""

# (币名, [国家TAG]) 共享分组
CURRENCY_GROUPS = [
    # 英镑 — 英国及其殖民地/自治领
    ("英镑", [
        "GBR", "ENG", "CNW", "COL", "IRE", "MLT",
        "SCO", "ULS", "WLS",
        "CAN", "NEW", "ONT", "NBS", "NVS",
        "NSW", "WAS", "SAS", "AST", "TAS", "NZL",
        "SAF", "SIL", "JAM", "BAH", "WIN",
        "NAL", "ORA", "TRN",
    ]),
    # 美元 — 美国及其分裂政权/领地
    ("美元", [
        "USA", "FSA", "CSA", "CAL", "DES", "NEN", "ORG", "UOM",
        "TEX", "NCR", "SCR", "CLI", "GRG", "FLR", "LOU",
        "HAW", "ASA", "LIB", "IRO", "CHE", "MTC", "SEQ", "MSC",
        "PUE", "NNV",
    ]),
    # 比索 — 拉美各国 + 西属殖民地 + 菲律宾
    ("比索", [
        "MEX", "YUC", "RIO", "UCA", "COS", "ELS", "GUA", "ALT",
        "HON", "NIC", "PNM", "CUB", "DOM", "ATL", "PCO",
        "CHL", "PEU", "NPU", "SPU", "PBC", "BOL", "ARG", "CLM",
        "ECU", "VNZ", "PRG", "URU", "GCO",
        "SC1", "SC2", "SC3", "SC4", "PHI",
        "FND", "PLT", "MAY", "NAH", "MKT", "TWT", "AYM", "GRI",
    ]),
    # 比塞塔 — 西班牙本土及伊比利亚诸政权
    ("比塞塔", [
        "SPA", "SPC", "IBE", "CAS", "ANL", "ARN", "LEO", "ASU",
        "NAV", "CAT", "GLI",
    ]),
    # 法郎 — 法国及法语区
    ("法郎", [
        "FRA", "PRC", "BRI", "COR", "QUE", "BEL", "FLA", "SWI",
        "SAV", "LUX", "WLL", "OCC", "AFS", "MAD",
    ]),
    # 马克 — 德意志诸邦
    ("马克", [
        "GER", "PRU", "WES", "POM", "ANH", "BRA", "BRE", "DZG",
        "FRM", "HAM", "HAN", "HES", "HOL", "LUB", "MEC", "NAS",
        "OLD", "SAX", "NGF", "COB", "MEI", "WEI", "SCW", "HEK",
        "LIP", "SCM", "MST", "WLD", "SCH", "RHE", "HRE", "RHN",
        "BAD", "BAV", "WUR", "SGF", "HOH", "SRB",
    ]),
    # 荷兰盾 — 尼德兰及荷兰东印度
    ("荷兰盾", ["NET", "UNL", "LIM", "DEI", "IDN",
                "JAV", "ACE", "BAL", "KLT"]),
    # 古尔登 — 奥地利/奥匈体系
    ("古尔登", ["AUS", "KUK", "BNT", "BOH", "SLV", "CRO", "SLO"]),
    # 里拉 — 意大利诸邦
    ("里拉", [
        "ITA", "LOM", "LUC", "MOD", "PAR", "SAR", "TRE", "TUS",
        "VEN", "RSM", "PAP", "SIC", "ISR",
    ]),
    # 克朗 — 斯堪的纳维亚诸国
    ("克朗", ["SCA", "SWE", "SCN", "DEN", "GRN", "NOR", "JAN", "ICL",
              "CZH", "SMI"]),
    # 卢布 — 俄国及其属地/中亚受控政权
    ("卢布", [
        "RUS", "DON", "URL", "UKR", "BYE", "KRL", "EST", "LAT",
        "UBD", "LIT", "FIN", "GEO", "AZB", "CAU", "ARM",
        "BKR", "CHV", "MRI", "BRY", "KYR", "TJI", "UZB", "TRC",
        "DAG", "IUS", "NCA", "TAR", "KMC", "CKC", "ALI", "KNT",
        "UDM", "MRD", "ABK", "CRI", "PRM",
        "SIB", "YAK", "TUV", "TNS", "FER",
        "BUK", "KHI", "KOK", "KAZ",
        "CHC", "CIR", "KLM", "KZH", "UZH", "OZH", "TRH", "MAI",
        "KUN", "IQU", "TIS",
    ]),
    # 卢比 — 印度次大陆及周边
    ("卢比", [
        "HND", "MUG", "IDS", "BHT", "MHR", "PAN", "TRA", "COC",
        "MYS", "BGL", "COO", "BHO", "GWA", "IND", "NAG", "SAT",
        "KHP", "PUD", "CAR", "DRA", "BIK", "JAI", "JAS", "JOD",
        "MEW", "ALW", "KOT", "RAJ", "BER", "KUT", "IDA", "NAW",
        "DHA", "JUN", "BHV", "PLP", "GUJ", "ORI", "JEY", "MYB",
        "PTN", "NAR", "ASM", "BCE", "NEP", "BIC",
        "AFG", "KAB", "KAN", "HER", "DIR", "SWT", "BLH",
        "BUR", "ARK", "KRN", "KHN", "KHM", "CEY",
        "HYD", "SIN", "KAS", "AWA", "BUN", "BAS", "KAL", "MAK",
        "MNP", "TOB", "HTH", "HZJ",
        "PAK", "CHT", "BHW", "KAF", "GAR", "PTA", "SHS", "JHN",
        "BAG", "SUR", "KNO", "KHR", "LBL", "KPR", "MLD", "BIH",
        "ZAN",
    ]),
    # 银两 — 中华文化圈
    ("银两", ["CHI", "MCH", "FRS", "LAN", "KOR", "DAI", "TIB",
              "LAD", "SIK", "BHU", "MGL", "XIN",
              "QIA", "YUN", "YUE", "HNA", "AHU", "ZHI", "SHN",
              "GUI", "GNG", "SIH", "SHA", "TPG", "XIB", "BEI",
              "RYU", "YUZ"]),
    # 两 — 日本 (江户时代币制)
    ("两", ["JAP", "EZO"]),
    # 里亚尔 — 波斯/阿拉伯/马格里布
    ("里亚尔", [
        "PER", "OMA", "YEM", "HDJ", "NEJ", "ARA", "ARB",
        "MOR", "MGB", "ALD", "CON", "MAS", "TRI", "TUN",
        "FZN", "CYR", "LBY", "TUA", "TUG", "AIT", "MZB", "EGY",
        "ABU", "BHN", "MAH", "ZAI", "LAH", "KAT", "JAB", "ASS",
        "LUR", "MAZ",
    ]),
    # 库鲁什 — 奥斯曼体系
    ("库鲁什", ["TUR", "KUR", "IRQ", "SYR", "LEB", "EOT",
                "ALB", "BOS", "MON"]),
    # 德拉克马 — 希腊世界
    ("德拉克马", ["GRE", "CRE", "CYP", "ION", "BYZ"]),
    # 兹罗提 — 波兰
    ("兹罗提", ["POL", "PLC", "KRA", "GAL"]),
    # 列伊 — 罗马尼亚诸公国
    ("列伊", ["ROM", "MOL", "WAL", "ALA", "TRS"]),
    # 第纳尔 — 塞尔维亚
    ("第纳尔", ["SER", "YUG"]),
    # 列弗 — 保加利亚
    ("列弗", ["BUL"]),
    # 福林 — 匈牙利
    ("福林", ["HUN"]),
    # 米雷伊斯 — 巴西 (+葡萄牙, 史实同用米雷伊斯/瑞尔体系)
    ("米雷伊斯", ["BRZ", "MNG", "PRA", "AGJ", "PNI", "PAU",
                  "EQT", "CTR", "BHI", "AMZ", "POR"]),
    # 古德 — 海地
    ("古德", ["HAI"]),
    # 塔勒 — 埃塞俄比亚诸政权
    ("塔勒", ["ETH", "SHW", "HAR", "GJM", "WLO", "BGM", "QWR",
              "WSG", "GLD", "MJT", "ISQ", "HOB", "AWS", "KFA",
              "SDM", "WLG", "TGR", "WLT", "HDY", "ARS"]),
    # 荷兰盾 — 印度尼西亚诸苏丹国
    ("荷兰盾", ["KTI", "SAK", "PON", "SMB", "JMB", "YOG", "SRK",
                "BTN", "SUL", "TID", "STG", "BNJ", "MGD"]),
    # 列弗 — 保加利亚相关政权
    ("列弗", ["PHL"]),
    # 泰铢 — 暹罗诸政权
    ("泰铢", ["SIA", "CMI", "CAM", "KLO", "LAO", "LUA", "CHP",
              "VIE", "MPH"]),
]

CURRENCY_BY_TAG = {
    tag: unit
    for unit, tags in CURRENCY_GROUPS
    for tag in tags
}

DEFAULT_CURRENCY = "英镑"


def currency_unit(country_obj=None, tag=None):
    """按国家 TAG 取货币单位; 无 TAG 时回退默认英镑。
    2026-08-27: 移除中文国名兜底匹配 (中文国名不稳定, 合并政体/改名后查不到
    会静默回退英镑), 一律按 TAG (country_obj.definition 或 tag) 匹配。
    """
    if isinstance(country_obj, dict):
        tag = country_obj.get("definition") or tag
    if tag:
        return CURRENCY_BY_TAG.get(tag, DEFAULT_CURRENCY)
    return DEFAULT_CURRENCY


# ---------------------------------------------------------------------------
# 主辅币制 (2026-08-23 增加): 每个币种的主币→辅币层级, 取 19 世纪史实比例。
# levels = [(辅币名, 上一级倍数), ...], 自大到小; 末级即最小辅币。
# 例: 英镑 [("先令",20),("便士",12)] → 1镑=20先令=240便士 (史实, 1971 前);
#     法郎 [("生丁",100)]            → 1法郎=100生丁 (十进制);
#     银两 [("钱",10),("分",10)]     → 1两=10钱=100分 (史实十进);
#     两   [("分",4),("朱",4)]       → 1両=4分=16朱 (江户金两)。
# 注释标注「游戏化」者为史实无 100/十进制对应、按统一 100 口径折衷的币种。
CURRENCY_SYSTEMS = {
    "英镑": [("先令", 20), ("便士", 12)],        # 史实 1镑=20先令=240便士
    "美元": [("分", 100)],
    "比索": [("分", 100)],
    "比塞塔": [("分", 100)],
    "法郎": [("生丁", 100)],
    "马克": [("分尼", 100)],
    "荷兰盾": [("分", 100)],
    "古尔登": [("克罗伊茨", 60)],                 # 史实 1857 前 1古尔登=60克罗伊茨
    "里拉": [("分", 100)],
    "克朗": [("欧尔", 100)],
    "卢布": [("戈比", 100)],
    "卢比": [("安那", 16), ("派", 12)],           # 史实 1卢比=16安那=192派
    "银两": [("钱", 10), ("分", 10)],             # 史实 1两=10钱=100分
    "两": [("分", 4), ("朱", 4)],                 # 史实 1両=4分=16朱
    "里亚尔": [("第纳尔", 100)],                  # 游戏化 (波斯史实 1托曼=10克朗=200沙希=1000第纳尔)
    "库鲁什": [("帕拉", 40)],                     # 史实 1库鲁什=40帕拉
    "德拉克马": [("勒普塔", 100)],
    "兹罗提": [("格罗希", 30)],                   # 史实 1924 前 1兹罗提=30格罗希
    "列伊": [("巴尼", 100)],
    "第纳尔": [("帕拉", 100)],
    "列弗": [("斯托丁卡", 100)],
    "福林": [("菲勒", 100)],                      # 游戏化 (奥匈 1892 后克朗=100菲勒)
    "米雷伊斯": [("瑞尔", 1000)],                 # 史实 1米雷伊斯=1000瑞尔
    "古德": [("分", 100)],
    "塔勒": [("分", 100)],                        # 游戏化 (埃塞俄比亚银塔勒)
    "泰铢": [("萨当", 100)],                      # 游戏化 (泰铢 1897 起 1铢=100萨当)
}

# 未收录币种回退的辅币制
_DEFAULT_SYSTEM = [("分", 100)]

# 主币计量字样: 币种名 ≠ 计量单位 (如「英镑」计数写作「镑」、「银两」计数写作「两」)
_MAIN_SHORT = {"英镑": "镑", "银两": "两"}


def currency_system(currency):
    """币种 → 主辅币层级表 [(辅币名, 上一级倍数)...]; 未收录回退十进制分。"""
    return CURRENCY_SYSTEMS.get(currency or DEFAULT_CURRENCY, _DEFAULT_SYSTEM)


def currency_system_text(currency):
    """主辅币换算说明文本, 如 "1法郎=100生丁" / "1英镑=20先令=240便士"。"""
    main = currency or DEFAULT_CURRENCY
    parts = []
    prod = 1
    for name, per in currency_system(main):
        prod *= per
        parts.append(f"{prod}{name}")
    return "1" + main + "=" + "=".join(parts)


def format_money(value, currency=DEFAULT_CURRENCY, rate=None):
    """游戏镑金额 → 主辅币自然语言文本 (2026-08-23 增加)。

    value: 游戏镑数值 (换算前); rate: 该币种兑英镑汇率 (1英镑=X主币), 缺省 1.0。
    先按汇率换算, 再按史实主辅币制格式化:
      |换算值| >= 1000 主币 → 千分位主币 (如 "88,742,047法郎")
      主币为 0             → 纯辅币 (0.79法郎 → "79生丁"; 0.03镑 → "7便士")
      主币非 0             → 主币+辅币 (1.75法郎 → "1法郎75生丁"; 1镑5先令10便士)
      整数                 → 主币+"整" (2.00法郎 → "2法郎整")
      极小值               → "不足1最小辅币"
      负值                 → 前缀 "-" (结余等)
    """
    main = currency or DEFAULT_CURRENCY
    main_name = _MAIN_SHORT.get(main, main)
    if value == 0:
        return f"0{main_name}"
    converted = value * (rate if isinstance(rate, (int, float)) and rate > 0 else 1.0)
    neg = converted < 0
    converted = abs(converted)
    levels = currency_system(main)
    prod = 1
    for _name, per in levels:
        prod *= per
    total = int(round(converted * prod))
    if total == 0:
        return f"不足1{levels[-1][0]}"
    prefix = "-" if neg else ""
    # 分解: 从最小辅币往上
    parts = []
    rem = total
    for _name, per in reversed(levels):
        parts.append(rem % per)
        rem //= per
    parts.reverse()
    main_v, subs = rem, parts
    if main_v >= 1000:
        return f"{prefix}{main_v:,}{main_name}"
    if main_v == 0:
        nz = [i for i, v in enumerate(subs) if v]
        if not nz:
            return f"{prefix}0{main_name}"
        first, last = nz[0], nz[-1]
        return prefix + "".join(f"{subs[i]}{levels[i][0]}"
                                for i in range(first, last + 1))
    up_to = max(i for i, v in enumerate(subs) if v) if any(subs) else -1
    out = [f"{main_v}{main_name}"]
    out.extend(f"{subs[i]}{levels[i][0]}" for i in range(0, up_to + 1))
    if up_to < 0:
        return f"{prefix}{main_v}{main_name}整"
    return prefix + "".join(out)


# ---------------------------------------------------------------------------
# 汇率体系 (2026-08-23 增加): 1 英镑 = X 主币 的历史铸币平价锚。
# 数值取 19 世纪常见铸币平价 (金本位/拉丁同盟等), 标「约」者为按银本位
# 折算或资料区间取中的校准值, 实现时可再调。
FX_ANCHOR = {
    "英镑": 1.0,      # 本位
    "美元": 4.87,     # 金平价 4.8665
    "比索": 4.87,     # 银比索 ≈ 美元
    "比塞塔": 25.0,   # 1868 起按 1 比塞塔 ≈ 1 法郎 定义
    "法郎": 25.22,    # 拉丁同盟金平价
    "马克": 20.43,    # 1873 帝国马克金平价 (游戏期德意志诸邦简化)
    "荷兰盾": 12.1,   # 金平价
    "古尔登": 10.0,   # 奥匈弗罗林 ≈ 2 先令 (约)
    "里拉": 25.22,    # 拉丁同盟
    "克朗": 18.0,     # 斯堪的纳维亚同盟 (约)
    "卢布": 9.46,     # 金卢布平价 (纸卢布时期实际大幅贬值)
    "卢比": 10.0,     # 银卢比按金银比折算 (约)
    "银两": 3.0,      # 银两按金银比折算 (约)
    "两": 6.0,        # 江户金两 (约)
    "里亚尔": 28.0,   # 波斯克朗折算 (约)
    "库鲁什": 110.0,  # 奥斯曼 1844 前 (约)
    "德拉克马": 25.0, # 希腊银德拉克马 ≈ 法郎 (约)
    "兹罗提": 64.0,   # 波兰兹罗提小银币折算 (约)
    "列伊": 25.2,     # 罗马尼亚 1867 列伊 ≈ 法郎 (约)
    "第纳尔": 25.2,   # 塞尔维亚 1873 第纳尔 ≈ 法郎 (约)
    "列弗": 25.2,     # 保加利亚列弗 ≈ 法郎 (约)
    "福林": 10.0,     # 匈牙利福林 = 奥匈古尔登 (约)
    "米雷伊斯": 8.9,  # 1 米雷伊斯 ≈ 27 便士 (约)
    "古德": 5.5,      # 海地古德 (约)
    "塔勒": 4.87,     # 埃塞俄比亚银塔勒 ≈ 银元 (约)
    "泰铢": 15.0,     # 暹罗泰铢银币折算 (约)
}

# 各币种的锚定国 TAG (汇率由锚定国的经济数据驱动); 列表为回退顺序,
# 取第一个有 GDP 数据的国家 (如 马克→普鲁士, 里拉→撒丁)。
FX_ANCHOR_TAG = {
    "英镑": ["GBR"],
    "美元": ["USA"],
    "比索": ["MEX"],
    "比塞塔": ["SPA"],
    "法郎": ["FRA"],
    "马克": ["PRU", "GER"],
    "荷兰盾": ["NET"],
    "古尔登": ["AUS"],
    "里拉": ["SAR", "ITA"],
    "克朗": ["SWE", "SCA"],
    "卢布": ["RUS"],
    "卢比": ["HND", "IND", "MUG"],
    "银两": ["CHI"],
    "两": ["JAP"],
    "里亚尔": ["PER"],
    "库鲁什": ["TUR"],
    "德拉克马": ["GRE"],
    "兹罗提": ["PLC", "POL", "KRA"],
    "列伊": ["WAL", "MOL", "ROM"],
    "第纳尔": ["SER"],
    "列弗": ["BUL"],
    "福林": ["HUN"],
    "米雷伊斯": ["BRZ"],
    "古德": ["HAI"],
    "塔勒": ["ETH"],
    "泰铢": ["SIA"],
}

FX_DEFAULT_RATE = 10.0  # 锚定国无 GDP 数据时的回退汇率 (1 英镑 = X 主币)
