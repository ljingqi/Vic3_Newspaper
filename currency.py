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
    # 米雷伊斯 — 巴西
    ("米雷伊斯", ["BRZ", "MNG", "PRA", "AGJ", "PNI", "PAU",
                  "EQT", "CTR", "BHI", "AMZ"]),
    # 瑞尔 — 葡萄牙
    ("瑞尔", ["POR"]),
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

# 旧存档无 TAG 时的中文国名兜底 (与 countries_l_simp_chinese.yml 同名)
CURRENCY_BY_NAME_ZH = {
    "古巴": "比索", "巴西": "米雷伊斯", "玻利维亚": "比索",
    "大清": "银两", "中国": "银两", "卢卡": "里拉", "中美洲": "比索",
    "大不列颠": "英镑", "英格兰": "英镑", "法兰西": "法郎",
    "俄罗斯": "卢布", "美利坚": "美元", "美国": "美元", "日本": "两",
    "德意志": "马克", "普鲁士": "马克", "尼德兰": "荷兰盾",
    "西班牙": "比塞塔", "葡萄牙": "瑞尔", "意大利": "里拉",
    "墨西哥": "比索", "瑞典": "克朗", "丹麦": "克朗", "挪威": "克朗",
    "斯堪的纳维亚": "克朗", "瑞士": "法郎", "比利时": "法郎",
    "奥地利": "古尔登", "匈牙利": "福林", "波兰": "兹罗提",
    "波兰‑立陶宛": "兹罗提", "希腊": "德拉克马", "罗马尼亚": "列伊",
    "保加利亚": "列弗", "塞尔维亚": "第纳尔", "土耳其": "库鲁什",
    "奥斯曼": "库鲁什", "波斯": "里亚尔", "埃及": "里亚尔",
    "摩洛哥": "里亚尔", "突尼斯": "里亚尔", "阿尔及利亚": "里亚尔",
    "埃塞俄比亚": "塔勒", "阿富汗": "卢比", "尼泊尔": "卢比",
    "印度": "卢比", "印度斯坦": "卢比", "东印度": "卢比", "锡兰": "卢比",
    "大韩": "银两", "大南": "银两", "西藏": "银两", "满洲": "银两",
    "菲律宾": "比索", "加拿大": "英镑", "澳大利亚": "英镑",
    "新西兰": "英镑", "南非": "英镑", "智利": "比索", "秘鲁": "比索",
    "阿根廷": "比索", "哥伦比亚": "比索", "乌拉圭": "比索",
    "巴拉圭": "比索", "委内瑞拉": "比索", "厄瓜多尔": "比索",
    "海地": "古德",
}

DEFAULT_CURRENCY = "英镑"


def currency_unit(country_obj=None, tag=None, player_name=None):
    """按国家 TAG 取货币单位; TAG 缺失时按中文国名兜底, 再无则默认英镑。

    参数任选其一, 优先级: country_obj.definition > tag > player_name。
    """
    if isinstance(country_obj, dict):
        tag = country_obj.get("definition") or tag
    if tag:
        return CURRENCY_BY_TAG.get(tag, DEFAULT_CURRENCY)
    if player_name:
        return CURRENCY_BY_NAME_ZH.get(player_name, DEFAULT_CURRENCY)
    return DEFAULT_CURRENCY
