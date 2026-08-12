#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维多利亚3 年度报纸生成器 (V3 Journal)
=======================================

原理:
  游戏端 mod (v3journal) 在每年年初通过 debug_log 把玩家国家的
  经济 / 战争 / 外交数据写入:
      <文档>/Paradox Interactive/Victoria 3/logs/debug.log
  当前主入口为 journal_save.py（存档直读）; 本文件主要承担「渲染」:
  把数据打包成 Prompt, 调用 DeepSeek API 生成指定风格报纸。
  报纸按会话分文件夹保存(重名加数字), 统一放在 output/ 下:
      D:/Journal/output/<国名>/报纸_<年份>.md

用法:
  python journal.py watch              持续监控游戏日志(建议后台运行)
  python journal.py watch --force      发现新数据时强制重新生成
  python journal.py once [日志路径]    处理一份已有的日志文件(测试用)
  python journal.py regen <年份>       用已保存的原始数据重新生成某年报纸
  python journal.py test-llm           测试 DeepSeek API 连通性
  python journal.py check              诊断 mod 数据是否正常写入日志
  python journal.py config             打印当前配置(隐藏密钥)
"""

import argparse
import datetime
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import requests
except ImportError:
    sys.exit("缺少依赖 requests, 请先运行:  python -m pip install requests")

# 控制台编码安全: 无论终端是 GBK/UTF-8, 都避免因编码抛异常而崩溃
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = {
    # DeepSeek API 配置
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com/chat/completions",
    # 游戏日志(debug.log)路径; 留空则自动检测
    "game_log_path": "",
    # 报纸输出目录: 所有存档开局会话统一放在 <项目目录>/output 下
    "journal_dir": os.path.join(SCRIPT_DIR, "output"),
    # 监控轮询间隔(秒)
    "poll_interval_seconds": 5,
    # LLM 生成参数
    "max_tokens": 8000,   # 推理模型(deepseek-v4-flash等)会把预算花在思考上, 需留足余量
    "temperature": 1.0,
    # 报纸风格: 1=大公报(20世纪初) 2=人民日报(20世纪) 3=新华网(新华社风格) 4=泰晤士报(中文)
    # 各风格的完整提示词与栏目名见 NEWSPAPER_STYLES
    "newspaper_style": 1,
}

def detect_default_log_path():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "Paradox Interactive", "Victoria 3", "logs", "debug.log")

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.join(SCRIPT_DIR, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            for k, v in user_cfg.items():
                if v not in (None, ""):
                    cfg[k] = v
        except Exception as e:
            log(f"警告: 读取 config.json 失败 ({e}), 使用默认配置。")
    if not cfg["game_log_path"]:
        cfg["game_log_path"] = detect_default_log_path()
    # 报纸风格: 只接受 1~4 的整数, 非法时回退默认
    try:
        style = int(cfg.get("newspaper_style", DEFAULT_STYLE))
    except (TypeError, ValueError):
        style = DEFAULT_STYLE
    if style not in NEWSPAPER_STYLES:
        log(f"警告: newspaper_style={cfg.get('newspaper_style')!r} 无效, "
            f"回退到默认风格 {DEFAULT_STYLE}（{NEWSPAPER_STYLES[DEFAULT_STYLE]['name']}）。")
        style = DEFAULT_STYLE
    cfg["newspaper_style"] = style
    return cfg

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "journal.log")
PROMPT_LOG = os.path.join(SCRIPT_DIR, "logs", "prompts.log")
PROMPT_LOG_MAX_BYTES = 50 * 1024 * 1024
_LOG_LOCK = threading.Lock()

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass

def _log_prompt(messages):
    """把每次整理好、发送给模型的 messages 原文写入 logs/prompts.log。
    超过 50MB 时先自动清空再写入 (按调用一次记一份, 重试不重复记录)。"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(PROMPT_LOG), exist_ok=True)
        with _LOG_LOCK:
            if os.path.exists(PROMPT_LOG) and os.path.getsize(PROMPT_LOG) > PROMPT_LOG_MAX_BYTES:
                open(PROMPT_LOG, "w", encoding="utf-8").close()
            with open(PROMPT_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n===== {ts} =====\n")
                for m in messages or []:
                    role = m.get("role", "?") if isinstance(m, dict) else "?"
                    content = m.get("content", "") if isinstance(m, dict) else str(m)
                    f.write(f"--- [{role}] ---\n{content}\n")
    except Exception:
        pass

def check_api_key(cfg):
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key or "sk-" not in key or "这里" in key or "填写" in key:
        sys.exit(
            "未配置 DeepSeek API Key。\n"
            "请编辑 D:/Journal/config.json, 在 deepseek_api_key 中填入你的 Key "
            "(在 https://platform.deepseek.com 申请, 形如 sk-xxxxxxxx)。"
        )
    return key

# ---------------------------------------------------------------------------
# 会话文件夹: 每个 watch/once 运行对应一个"存档期", 报纸按国名分文件夹
# ---------------------------------------------------------------------------

SESSION = {"folder": None}
_FOLDER_LOCK = threading.Lock()

def sanitize_folder_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().strip(".")
    return name or "未知名国家"

def determine_folder(player, journal_dir):
    """以国名命名输出文件夹; 若重名则加数字 (法兰西, 法兰西2, 法兰西3...)。"""
    base = sanitize_folder_name(player)
    if os.path.exists(os.path.join(journal_dir, base)):
        i = 2
        while os.path.exists(os.path.join(journal_dir, f"{base}{i}")):
            i += 1
        return f"{base}{i}"
    return base

def find_latest_session_folder(player, journal_dir):
    """返回该国已存在的编号最大的会话文件夹 (海地 → 海地2 → 海地3...)。
    仅用于「continue/续传」模式; 没有历史文件夹时返回 None。"""
    base = sanitize_folder_name(player)
    found = []
    i = 1
    while True:
        cand = base if i == 1 else f"{base}{i}"
        if os.path.isdir(os.path.join(journal_dir, cand)):
            found.append(cand)
            i += 1
            continue
        if i > 1:
            break
        i += 1
    return found[-1] if found else None

def resolve_session_folder(data, cfg):
    """决定本年数据应放入哪个文件夹(同一会话内保持一致)。"""
    with _FOLDER_LOCK:
        if SESSION["folder"]:
            return SESSION["folder"]
        existing = data.get("output_dir")
        if existing and os.path.isdir(os.path.join(cfg["journal_dir"], existing)):
            SESSION["folder"] = existing
            return existing
        folder = determine_folder(data.get("player", "未知"), cfg["journal_dir"])
        SESSION["folder"] = folder
        return folder

def find_raw_files(year, journal_dir):
    """在 output/ 各会话文件夹的 data/ 中查找某年的原始数据文件。"""
    matches = []
    try:
        for d in os.listdir(journal_dir):
            dp = os.path.join(journal_dir, d, "data", f"raw_{year}.json")
            if os.path.isfile(dp):
                matches.append(dp)
    except Exception:
        pass
    return matches

# ---------------------------------------------------------------------------
# 日志解析
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"(\d{4})[.\-/_](\d{1,2})[.\-/_](\d{1,2})")
CN_DATE_RE = re.compile(r"(\d{1,2})月\s*(\d{1,2})[，,]?\s*(\d{4})")
YEAR_RE = re.compile(r"\b(1[0-9]{3})\b")

def strip_loc_formatting(text):
    """去除 Paradox 本地化格式标记(#Vxxx#! / #red 等)与动态占位符($NAME$/$ADJECTIVE$ 等)。
    整串为 $key$ 引用且清理后为空时, 退回保留 key(如 generic_revolt_unions), 避免空名。"""
    if not isinstance(text, str):
        return text
    orig = text.strip()
    text = re.sub(r"#[A-Za-z0-9_\-+]+#!", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\$[A-Za-z_][A-Za-z_0-9]*\$", "", text)
    text = re.sub(r"\$+", "", text)
    text = text.strip()
    if not text and orig.startswith("$") and orig.endswith("$"):
        return orig[1:-1]
    return text.strip()

def extract_date(before_text):
    """从 |JOURNAL| 前缀文本中提取游戏日期字符串(兼容 1836.1.1 与 9月 14, 1836)。"""
    m = DATE_RE.search(before_text)
    if m:
        return f"{m.group(1)}.{int(m.group(2))}.{int(m.group(3))}"
    m = CN_DATE_RE.search(before_text)
    if m:
        return f"{m.group(3)}.{int(m.group(1))}.{int(m.group(2))}"
    m = YEAR_RE.search(before_text)
    if m:
        return m.group(1)
    return "未知"

def year_from_date(date_str):
    m = re.search(r"(\d{4})", str(date_str))
    return int(m.group(1)) if m else None

def date_tuple(date_str):
    """把 '1836.9.14' 转成可比较的 (年,月,日) 元组。"""
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", str(date_str))
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{4})", str(date_str))
    return (int(m.group(1)), 0, 0) if m else None

def parse_journal_line(line):
    """解析一行含 |JOURNAL| 的日志, 返回 (kind, raw_parts, fields, before_text)。"""
    idx = line.find("|JOURNAL|")
    if idx < 0:
        return None
    before = line[:idx]
    body = line[idx + len("|JOURNAL|"):]
    raw_parts = [p.strip() for p in body.split("|")]
    kind = raw_parts[0]
    fields = {}
    for kv in raw_parts[1:]:
        if "=" in kv:
            k, v = kv.split("=", 1)
            fields[k.strip()] = v.strip()
    return kind, raw_parts, fields, before

class BlockBuilder:
    """把连续的 |JOURNAL| 行组装成一个年度数据块。
    战争结束(WAREND)事件出现在两次年度报告之间, 累积到 pending_events,
    在下一个年度块完成时并入该年的"本年度战事"数据。
    """

    def __init__(self):
        self.pending_events = []     # 年度块之间的战争结束事件
        self._warend_pending = None  # 未配对的 WAREND actor/target
        self._last_player = None     # 上一个块的国名(日志轮转导致块头丢失时继承)
        self.reset()

    def reset(self):
        self.in_block = False
        self.data = {}
        self._powers = []
        self._relations = []
        self._subjects = []
        self._war_opponents = []
        self._war_casualties = []
        self._cultures = []
        self._religions = []
        self._laws = []
        self._professions = []

    def feed(self, kind, raw_parts, fields, before_text):
        if kind == "MIGR":
            # 移民目的地事件: 出现在年度块之间, 累积后并入当年报纸
            date = extract_date(before_text)
            self.pending_events.append({
                "kind": "migration",
                "state": strip_loc_formatting(fields.get("state", "?")),
                "date": date, "year": year_from_date(date), "dt": date_tuple(date),
            })
            return None
        if kind == "WAREND":
            # 战争结束事件: 两条连续行(actor / target), 配对后进 pending_events
            date = extract_date(before_text)
            dt = date_tuple(date)
            if "actor" in fields:
                self._warend_pending = {
                    "kind": "war_end", "actor": strip_loc_formatting(fields["actor"]),
                    "date": date, "year": year_from_date(date), "dt": dt,
                }
            elif "target" in fields:
                t = strip_loc_formatting(fields["target"])
                if self._warend_pending:
                    self._warend_pending["target"] = t
                    self.pending_events.append(dict(self._warend_pending))
                    self._warend_pending = None
                else:
                    self.pending_events.append({"kind": "war_end", "target": t,
                                                "date": date, "year": year_from_date(date), "dt": dt})
            return None
        if kind == "START":
            self.reset()
            self.in_block = True
            self.data["date"] = extract_date(before_text)
            self.data["year"] = year_from_date(self.data.get("date"))
            self.data["player"] = strip_loc_formatting(fields.get("player", "未知"))
            self._last_player = self.data["player"]
            return None
        if not self.in_block:
            # 隐式开始: 若 START 行失败/缺失/被日志轮转截断, 用首个内容行的日期重建数据块
            if kind in ("GDP", "POP", "SOL", "SOLBELOW", "INFAMY", "ATWAR",
                        "SUBJECT", "POWER", "PWAR", "REL", "GOOD", "RULER",
                        "PLAYER", "GOVT", "CAPITAL", "WAROPP", "WARCAS",
                        "CULT", "CULTSHARE", "RELIGION", "LAW", "PROF"):
                self.reset()
                self.in_block = True
                self.data["date"] = extract_date(before_text)
                self.data["year"] = year_from_date(self.data.get("date"))
                self.data["player"] = self._last_player or "未知"
            else:
                return None
        if kind == "END":
            self.in_block = False
            self.data["powers"] = self._powers
            self.data["relations"] = self._relations
            self.data["subjects"] = self._subjects
            self.data["war_opponents"] = list(dict.fromkeys(self._war_opponents))
            self.data["war_casualties"] = self._war_casualties
            self.data["cultures"] = self._cultures
            self.data["religions"] = self._religions
            self.data["laws"] = self._laws
            self.data["professions"] = self._professions
            # 并入"年度报告日期之前"发生的战争结束事件(同一历年年初到报告日之间的事件)
            bdt = date_tuple(self.data.get("date"))
            byear = self.data.get("year")
            evs, kept = [], []
            for e in self.pending_events:
                edt, ey = e.get("dt"), e.get("year")
                if (bdt and edt and edt < bdt) or (not bdt and byear and ey and ey < byear):
                    evs.append(e)
                else:
                    kept.append(e)
            self.pending_events = kept
            self.data["events"] = evs
            return self.data
        if kind == "RULER":
            self.data["ruler"] = strip_loc_formatting(fields.get("name", "未知"))
        elif kind == "GDP":
            self.data["gdp"] = fields.get("value") or fields.get("bucket", "未知")
        elif kind == "POP":
            self.data["pop"] = fields.get("value") or fields.get("bucket", "未知")
        elif kind == "SOL":
            self.data["sol"] = fields.get("value") or fields.get("bucket", "未知")
        elif kind == "SOLBELOW":
            self.data["sol_below"] = fields.get("below", "no") == "yes"
        elif kind == "INFAMY":
            self.data["infamy"] = fields.get("value") or fields.get("bucket", "未知")
        elif kind == "GOVT":
            self.data["govt"] = fields.get("type", "other")
        elif kind == "CAPITAL":
            name = strip_loc_formatting(fields.get("name", "") or "")
            city = strip_loc_formatting(fields.get("city", "") or "")
            prov = strip_loc_formatting(fields.get("province", "") or "")
            self.data["capital"] = city or prov or name or "未知"
        elif kind == "LAW":
            self._laws.append(fields.get("law", "?"))
        elif kind == "WAROPP":
            self._war_opponents.append(strip_loc_formatting(fields.get("name", "?")))
        elif kind == "WARCAS":
            self._war_casualties.append(fields.get("level", "?"))
        elif kind == "CULT":
            self._cultures.append({
                "rank": fields.get("rank", "?"),
                "name": strip_loc_formatting(fields.get("name", "")),
                "share": None,
            })
        elif kind == "CULTSHARE":
            r = fields.get("rank")
            found = False
            for c in self._cultures:
                if c["rank"] == r:
                    c["share"] = fields.get("share", "?")
                    found = True
                    break
            # CULT(GetKey)可能Data error被过滤, 从CULTSHARE直接创建
            if not found:
                self._cultures.append({
                    "rank": r,
                    "name": f"（第{r}大族）",
                    "share": fields.get("share", "?"),
                })
        elif kind == "RELIGION":
            self._religions.append({
                "name": fields.get("name", "?"),
                "share": fields.get("share", "?"),
            })
        elif kind == "PROF":
            self._professions.append({
                "name": fields.get("name", "?"),
                "share": fields.get("share", "?"),
            })
        elif kind == "SUBJECT":
            self._subjects.append(strip_loc_formatting(fields.get("name", "?")))
        elif kind == "POWER":
            self._powers.append({
                "name": strip_loc_formatting(fields.get("name", "?")),
                "war": fields.get("war") == "yes",
                "opponents": [],
            })
        elif kind == "PWAR":
            if self._powers:
                self._powers[-1]["opponents"].append(strip_loc_formatting(fields.get("opponent", "?")))
        elif kind == "REL":
            self._relations.append({
                "name": strip_loc_formatting(fields.get("name", "?")),
                "pact": fields.get("pact", "none"),
            })
        return None

# ---------------------------------------------------------------------------
# Prompt 构建
# ---------------------------------------------------------------------------

PACT_NAMES = {
    # 附庸关系 (pacts 中 first=宗主, second=附庸)
    "colony": "殖民地",
    "dominion": "自治领",
    "protectorate": "保护国",
    "puppet": "傀儡国",
    "tributary": "朝贡国",
    "vassal": "附庸",
    "crown_land": "王室领地",
    "chartered_company": "特许公司",
    "personal_union": "共主邦联",
    # 其他条约
    "alliance": "同盟",
    "defensive_pact": "防御条约",
    "rivalry": "敌对",
    "embargo": "禁运",
    "guarantee_independence": "独立保障",
    "trade_agreement": "贸易协定",
    "da_knowledge_sharing": "知识共享",
    "da_support_regime": "支持政权",
    "da_overlord_grant_investment_rights": "宗主授予投资权",
    "da_evangelize": "传教",
    "increase_relations": "改善关系",
    "damage_relations": "损害关系",
    "expel_diplomats": "驱逐外交官",
    "fund_lobbies": "资助游说集团",
    "raiding_pact": "袭击协议",
    "disapproval_pact": "不满协议",
    "exempt_from_service": "豁免服役",
    "grant_own_market": "自主市场",
    "decrease_payments": "减少付款",
    "none": "无特殊关系",
}

GOVT_NAMES = {
    "council_republic": "委员会制共和国",
    "parliamentary_republic": "议会制共和国",
    "presidential_republic": "总统制共和国",
    "social_monarchy": "社会君主立宪制",
    "monarchy": "君主制",
    "theocracy": "神权制",
    "chiefdom": "酋邦制",
    "other": "其他政体",
}

RELIGION_NAMES = {
    "catholic": "天主教", "protestant": "新教", "orthodox": "东正教",
    "oriental_orthodox": "东方正统教会", "sunni": "逊尼派", "shiite": "什叶派",
    "ibadi": "伊巴德派", "jewish": "犹太教", "mahayana": "大乘佛教",
    "gelugpa": "格鲁派(藏传佛教)", "theravada": "上座部佛教",
    "confucian": "儒教(儒家)", "hindu": "印度教", "shinto": "神道教",
    "sikh": "锡克教", "animist": "泛灵信仰", "atheist": "无神论",
}

SHARE_NAMES = {
    "majority": "占人口过半",
    "large": "占比可观",
    "notable": "有一定占比",
    "minor": "占比有限",
}

# 全部法律名称取自游戏官方简体中文本地化
# (F:\Game\steamapps\common\Victoria 3\game\common\laws\*.txt +
#  localization\simp_chinese\laws_l_simp_chinese.yml), 兼容旧存档遗留 key。
LAW_NAMES = {
    # 政体 / 治理
    "law_anarchy": "无政府", "law_autocracy": "独裁制", "law_oligarchy": "寡头制",
    "law_chiefdom": "酋邦制", "law_elder_council": "长老议会",
    "law_monarchy": "君主制", "law_theocracy": "神权制",
    "law_presidential_republic": "总统共和制", "law_parliamentary_republic": "议会共和制",
    "law_council_republic": "委员会共和制", "law_single_party_state": "一党制国家",
    "law_technocracy": "技术治国", "law_corporate_state": "法团国家",
    "law_neo_absolutism": "新专制主义", "law_social_monarchy": "社会君主制",
    "law_organic_regulation": "组织法规", "law_guaranteed_liberties": "保障自由",
    "law_bakufu": "幕府", "law_shinsengumi": "新选组",
    # 选举 / 权力分配
    "law_landed_voting": "地产投票", "law_wealth_voting": "财产投票",
    "law_census_voting": "资格性选举制", "law_universal_suffrage": "普选制",
    "law_appointed_bureaucrats": "任命官僚制", "law_elected_bureaucrats": "选举官僚制",
    "law_hereditary_bureaucrats": "世袭官僚制",
    # 宗教
    "law_state_religion": "国教", "law_freedom_of_conscience": "信仰自由",
    "law_state_atheism": "国家无神论", "law_total_separation": "完全分离",
    "law_millet_system": "米勒特制", "law_people_of_the_book": "有经人",
    # 奴隶制 / 公民权
    "law_slavery_banned": "禁止蓄奴", "law_legacy_slavery": "遗留奴隶制",
    "law_debt_slavery": "债务奴隶制", "law_slave_trade": "奴隶贸易",
    "law_colonial_slavery": "殖民地奴隶制",
    "law_racial_segregation": "种族隔离", "law_cultural_exclusion": "文化排斥",
    "law_national_supremacy": "民族至上", "law_ethnostate": "族裔国家",
    "law_multicultural": "文化多元", "law_subjecthood": "臣民身份",
    "law_hindu_caste_codified": "种姓制度法典化", "law_hindu_caste_enforced": "实施种姓制度",
    "law_hindu_caste_not_enforced": "不实施种姓制度", "law_warrior_caste": "武士阶级",
    # 言论自由
    "law_right_of_assembly": "集会权", "law_protected_speech": "言论保护",
    "law_outlawed_dissent": "异议非法", "law_censorship": "出版物审查",
    "law_free_speech": "言论自由",  # 旧版本遗留 key
    # 经济制度
    "law_agrarianism": "农本主义", "law_interventionism": "经济干预",
    "law_laissez_faire": "自由放任", "law_command_economy": "计划经济",
    "law_traditionalism": "传统主义", "law_mercantilism": "重商主义",
    "law_protectionism": "贸易保护", "law_free_trade": "自由贸易",
    "law_isolationism": "孤立主义", "law_extraction_economy": "盘剥经济",
    "law_industry_banned": "禁止工业", "law_cooperative_ownership": "合作社所有制",
    "law_regulatory_bodies": "监管机构",
    # 土地改革
    "law_tenant_farmers": "佃农", "law_commercialized_agriculture": "商品化农业",
    "law_serfdom": "农奴制", "law_homesteading": "宅地法",
    "law_land_based_taxation": "土地税制", "law_manorialism": "庄园制",
    "law_peasant_proprietorship": "农民产权", "law_collectivized_agriculture": "集体化农业",
    "law_latifundias": "大庄园制", "law_expanded_latifundias": "扩大大庄园制",
    "law_crownland_diets": "王冠领地议会",
    # 殖民事务
    "law_colonial_administration": "殖民政府", "law_colonial_exploitation": "殖民剥削",
    "law_colonial_resettlement": "殖民安置", "law_no_colonial_affairs": "无殖民事务",
    "law_frontier_colonization": "边疆殖民",
    # 教育
    "law_public_schools": "公立学校", "law_private_schools": "私立学校",
    "law_no_schools": "无学校", "law_religious_schools": "教会学校",
    "law_compulsory_primary_school": "义务小学", "law_terakoya": "寺子屋",
    "law_public_schools_only": "公立学校",  # 旧版本遗留 key
    # 警察 / 内务
    "law_no_police": "无警察", "law_local_police": "地方警察部队",
    "law_dedicated_police": "专职警察部队", "law_secret_police": "秘密警察",
    "law_militarized_police": "军事化警察部队", "law_no_home_affairs": "无内务机构",
    # 医疗
    "law_no_health_system": "无卫生系统", "law_charitable_health_system": "慈善医院",
    "law_private_health_insurance": "私人医疗保险", "law_public_health_insurance": "公共医疗保险",
    # 军队 / 海军
    "law_peasant_levies": "征召农兵", "law_professional_army": "职业军队",
    "law_national_guard": "国民警卫队", "law_national_militia": "国家民兵",
    "law_mass_conscription": "大规模征兵",
    "law_diplomatic_navy": "外交舰队", "law_professional_navy": "主力舰队",
    "law_merchant_navy": "商业海军", "law_jeune_ecole": "绿水学派",
    # 劳工 / 工会
    "law_no_workers_rights": "无劳动者权利", "law_worker_protections": "劳动者保障",
    "law_rights_of_workers": "劳工权利",  # 旧版本遗留 key
    "law_combination_acts": "结社法", "law_right_to_associate": "组织工会权",
    "law_corporatized_unions": "法团化工会", "law_anti_strike_laws": "反罢工法",
    "law_factory_councils": "工厂委员会",
    # 儿童 / 妇女权利
    "law_child_labor_allowed": "允许童工", "law_restricted_child_labor": "限制童工",
    "law_child_labor_forbidden": "禁止童工",  # 旧版本遗留 key
    "law_no_womens_rights": "法定监护", "law_womens_suffrage": "妇女选举权",
    "law_women_in_the_fields": "女性耕作", "law_women_in_the_workplace": "女性工作",
    "law_women_own_property": "有产妇女",
    # 福利
    "law_no_social_security": "无社会保障", "law_poor_laws": "济贫法",
    "law_old_age_pension": "养老金", "law_wage_subsidies": "工资补贴",
    "law_chiefs_distribute_aid": "首领家长式管理",
    # 移民
    "law_migration_controls": "移民控制", "law_no_migration_controls": "无移民控制",
    "law_closed_borders": "关闭边境",
    # 税收 / 贸易
    "law_consumption_based_taxation": "消费税制", "law_per_capita_based_taxation": "人均税制",
    "law_proportional_taxation": "比例税制", "law_graduated_taxation": "累进税制",
    # 日本特有
    "law_canton_system": "广州一口通商", "law_sakoku": "锁国",
    "law_strict_edo_system": "严格等级秩序", "law_intermediate_edo_system": "松动等级秩序",
    "law_lax_edo_system": "宽松等级秩序",
    # 其它
    "law_affirmative_action": "平权法案", "law_guild_system": "行会制度",
}

def law_zh(law):
    return LAW_NAMES.get(law, law.replace("law_", ""))

POP_TYPE_NAMES = {
    "peasants": "自给农", "laborers": "劳工", "farmers": "农民",
    "aristocrats": "贵族", "officers": "军官", "clergymen": "神职人员",
    "capitalists": "资本家", "bureaucrats": "官僚", "clerks": "职员",
    "engineers": "工程师", "machinists": "机械师", "shopkeepers": "店主",
    "soldiers": "士兵", "slaves": "奴隶", "academics": "学者",
}

SOL_GUIDE = ("生活水平(SoL)为0~30量级的民生指数：5以下=赤贫潦倒，5~10=艰难糊口，"
             "10~15=温饱尚可，15~20=小康殷实，20以上=富足安乐。请据此在行文中体现民生状况。")

FOOD_SECURITY_NAMES = {
    "secure": "充足", "secured": "充足", "moderate": "尚可",
    "insecure": "紧张", "starving": "饥荒",
    "starvation": "饥荒", "severe_starvation": "严重饥荒",
    "moderate_starvation": "轻度饥饿",
}

def food_security_zh(fs):
    """粮食安全状态本地化: 存档原始状态 → 中文。未知值原样返回。"""
    return FOOD_SECURITY_NAMES.get(fs, fs)

# 收成条件(Harvest Condition)本地化: 取自游戏官方简体中文本地化,
# 海洋类条件(naval_condition_*)已解析为对应中文名
HARVEST_NAMES = {
    "drought": "干旱", "flood": "洪水", "frost": "霜冻", "wildfire": "野火",
    "hailstorm": "雹暴", "locust_swarm": "蝗群", "heatwave": "热浪",
    "disease_outbreak": "疫病爆发", "extreme_winds": "强风",
    "torrential_rains": "暴雨", "pollinator_surge": "授粉昆虫激增",
    "optimal_sunlight": "阳光极佳", "moderate_rainfall": "降雨适中",
    "tsunami": "海啸", "earthquake": "地震",
    "strong_winds": "强风", "fog": "浓雾", "ice": "浮冰",
    "cyclone": "气旋", "tropical_storm": "热带风暴",
    "calm_waters": "风平浪静", "rough_waters": "汹涌",
}

# 自由言论(Free Speech)法律组：提示词风味用（含当前版本的 law_right_of_assembly）
FREE_SPEECH_LAWS = ("law_outlawed_dissent", "law_censorship",
                    "law_right_of_assembly", "law_free_speech",
                    "law_protected_speech")

# 各言论自由法律对应的新闻自由风味文案（提示词用）。集会权在本法律组中
# 处于「无审查但无明文保障」的次宽松档位，故文案侧重新闻自由而非集会本身。
FREE_SPEECH_FLAVOR = {
    "law_outlawed_dissent": "批评政府被视为叛国而属非法，报纸只可刊发拥护现行体制的内容。",
    "law_censorship": "新闻出版受主动审查，报纸稿件须经审查机关许可方可刊发，报道须自行把关。",
    "law_right_of_assembly": "报纸无须事前送审，可较为自由地报道与评论，惟言论自由尚无明文法律保护，报道宜有分寸。",
    "law_protected_speech": "言论自由已载入法律并受明文保护，报纸可依法自由报道与批评，唯须不逾诽谤、泄密等法律界限。",
    "law_free_speech": "报纸享有完全的言论与出版自由，可自由报道、评论国政，无须事前送审。",
}


def _press_freedom_line(data):
    """返回当前言论自由法律的风味提示行；法律缺失时返回空串。"""
    fs_law = data.get("free_speech_law")
    if not fs_law:
        fs_law = next((l for l in (data.get("laws") or []) if l in FREE_SPEECH_LAWS), None)
    if not fs_law:
        return ""
    flavor = FREE_SPEECH_FLAVOR.get(fs_law)
    if flavor:
        return f"- 当前的言论自由法律为：{law_zh(fs_law)}，{flavor}"
    # 未知法律兜底：维持原有通用口径
    return f"- 当前的言论自由法律为：{law_zh(fs_law)}，报社务必在法律允许的底线内行使新闻自由。"

# 社会地位(Acceptance)本地化：存档里 acceptance_status 是英文 key，映射为模型易懂的中文
ACCEPTANCE_NAMES = {
    "full_acceptance": "完全接纳",
    "open_prejudice": "公开歧视",
    "second_rate_citizen": "二等公民",
    "cultural_erasure": "文化抹除",
    "violent_hostility": "暴力敌视",
}

# 利益集团本地化：存档给出 ig_xxx key，映射为中文名称
IG_NAMES = {
    # 八大基础利益集团
    "ig_armed_forces": "军队", "ig_devout": "虔信者",
    "ig_industrialists": "实业家", "ig_intelligentsia": "知识分子",
    "ig_landowners": "地主", "ig_petty_bourgeoisie": "小市民",
    "ig_rural_folk": "乡村民众", "ig_trade_unions": "工会",
    # 常见变体/特色利益集团
    "ig_landed_gentry": "有地贵族", "ig_anglican_church": "圣公会",
    "ig_catholic_church": "天主教会", "ig_orthodox_church": "东正教会",
    "ig_evangelical_church": "福音派教会", "ig_sunni_madrasahs": "逊尼派乌理玛",
    "ig_shia_madrasahs": "什叶派乌理玛", "ig_ibadi_madrasahs": "伊巴德派乌理玛",
    "ig_hindu_priesthood": "印度教上师", "ig_confucian": "儒生",
    "ig_mahayana_monks": "大乘佛教僧侣", "ig_theravada_monks": "上座部佛教僧侣",
    "ig_vajrayana_monks": "金刚乘佛教僧侣", "ig_shinto_monks": "神道教祠官",
    "ig_pagan_shamans": "原始宗教萨满", "ig_rabbinical_council": "犹太教议会",
    "ig_boyars": "波雅尔", "ig_junkers": "容克",
    "ig_east_india_company": "东印度公司", "ig_national_guard": "国民自卫军",
    "ig_red_army": "红军", "ig_roman_curia": "罗马教廷",
    "ig_roman_landowners": "公民贵族", "ig_peasants": "平民",
    "ig_samurai": "武士", "ig_daimyo": "大名", "ig_chonin": "町人",
    "ig_gosho": "豪商", "ig_shogunate": "幕府", "ig_kazoku": "华族",
    "ig_zamindars": "柴明达尔", "ig_jats": "贾特斯人", "ig_ryots": "莱特",
    "ig_kisanharu": "基桑哈鲁", "ig_fellahin": "费拉",
    "ig_civil_servants": "公务员", "ig_bhadralok": "巴德拉罗克",
    "ig_presidency_armies": "管辖区部队", "ig_indian_army": "印度军队",
    "ig_government_of_india": "印度政府", "ig_literati": "文人",
    "ig_scholar_officials": "士大夫", "ig_yeoman_farmers": "自耕农",
    "ig_southern_planters": "南方种植园主", "ig_squattocracy": "大牧场主",
    "ig_evangelicals": "福音派", "ig_local_governors": "地方总督",
    "ig_magnates": "权贵", "ig_landvolk": "有地民",
    "ig_gentry_assembly": "士绅会议", "ig_aristocracy_of_officials": "官僚贵族",
    "ig_kleinburger": "小资产阶级", "ig_church_of_sweden": "瑞典教会",
    "ig_church_of_denmark": "丹麦教会", "ig_church_of_norway": "挪威教会",
    "ig_church_of_finland": "芬兰教会", "ig_oriental_orthodox_church": "东方正统教会",
    "ig_granthis": "格兰蒂斯", "ig_khalsaji": "卡尔萨吉",
    "ig_taiping_god_worshippers": "拜上帝会", "ig_wamanga": "瓦曼加",
    "ig_alii": "阿利伊", "ig_maka_ainana": "马卡阿伊纳纳",
    "ig_hawaiian_democrats": "民主派", "ig_christian_missionaries": "基督教传教士",
    "ig_guardia_civil": "国民警卫队", "ig_ilustrados": "启蒙者",
    "ig_shipping_magnates": "航运巨头", "ig_powerbrokers": "政治掮客",
}

JOB_SATISFACTION_GUIDE = ("职业满意度为该POP对当前工作/薪水的满意程度："
                          "正值=满意，负值=不满，数值越大情绪越强烈。")

def load_history(data, cfg, years_back=6):
    """加载当前年份之前若干年的原始数据, 供模型做发展对比。
    仅读取当前会话文件夹的 data/（中央 data/ 逻辑已弃用）。"""
    folder = data.get("output_dir") or SESSION.get("folder") or ""
    cur = data.get("year")
    hist = []
    if not folder or not cur:
        return hist
    seen = set()
    rd = os.path.join(cfg["journal_dir"], folder, "data")
    for y in range(cur - years_back, cur):
        p = os.path.join(rd, f"raw_{y}.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    h = json.load(f)
                if h.get("year") == y and y not in seen:
                    hist.append(h)
                    seen.add(y)
            except Exception:
                pass
    return hist

def _ruler_name(data):
    """统治者名: 日志链路拿不到时 debug_log 输出 (统治者 id N) 占位符, 视为缺失。"""
    ruler = data.get('ruler', '') or ''
    if re.fullmatch(r"（统治者 id \d+）", ruler.strip()):
        return ""
    return ruler


# ---------------------------------------------------------------------------
# 分板块生成: 每次请求只生成一个板块, 最后由程序组合成完整报纸
# ---------------------------------------------------------------------------

SECTION_DEFS = [
    ("headline", "头版", "一句话导语，概括本年度最大事态；须点名国名与年份。"),
    ("war", "战事专电", "报道去年（上一历年）发生的战事：对阵双方（玩家参战或列强参战，仅列主要参加者）、"
     "死伤规模、耗资、是否已结束。传输的数据只有去年发生的战争，不含今年是否处于交战状态，"
     "不得推断或编造当前战况。"),
    ("diplo", "外交风云", "报道本国与列强的外交：同盟/敌对/禁运等条约关系、附庸国、世界八强态势。"),
    ("econ", "经济要闻", "报道本国经济：GDP、人口、生活水平(SoL)、识字率。"),
    ("politics", "政界动态", "报道政体、统治者、当前执政利益集团（标注「执政」者即组阁集团，"
     "数据含其政治力量占比、首领姓名与首领个人意识形态）、主要利益集团力量格局、"
     "当前影响最大的政治运动，"
     "含名称、核心意识形态、活跃度档位、支持者规模与支持度，"
     "、本年度法律变化(新施行/废除的法律)。"
     "每期**必须**至少有一条以「（头衔）（统治者姓名）……」为主干的统治者活动新闻，"
     "若数据给出「本期统治者活动」一行，必须以该行事实为基础（人物、头衔、地点、事件不得改写），"
     "在其上扩写细节；该行缺失时头衔按政体与国名常识选用，"
     "可在不编造具体国名与数字的前提下合理演绎统治者行踪。"),
    ("society", "民族宗教与社会", "报道民族构成、宗教构成、移民动向、社会风尚。"),
    ("family", "民生访谈", "记者在随机州随机建筑内，采访生活水平最低的人群，"
     "以访谈体写衣食住行、收入支出、受抚养人口与生活水平；须体现该人群政治倾向"
     "（激进派/效忠派占该人群百分比）与参与比例最高的两个政治运动，"
     "须基于给定数据，不得编造具体数字。"),
    ("peer", "邻里富户", "与民生访谈同一建筑内生活水平最高的人群（富户），"
     "以同样的访谈体写其衣食住行与收支，并体现该人群政治倾向与参与比例最高的两个政治运动，"
     "须与民生访谈形成贫富对照，不得编造具体数字。"),
    ("unemployed", "失业民生", "仅当随机州失业率>5%时发送：报道该州失业状况，"
     "采访失业POP中人口最多的一群（同访谈体），必须体现给定失业率，并体现该人群政治倾向"
     "与参与比例最高的两个政治运动，不得编造具体数字。"),
    ("comment", "本报评论", "编辑部评论，结合历年发展对照，评述国运与民生之变迁。"),
    ("ads", "广告与启示", "围绕本期提供的已研发科技创作一两条趣味广告：可为商品、工艺、铺面告白，"
     "也可为文学沙龙、社科研讨会、新政晓谕、学堂启事等非商品形式；至少一条须直接体现科技，富有时代气息。"),
]

# 所有风格共用的「数据解读规则」：与具体风格无关, 保证各风格拿到的事实口径一致
FACT_GUIDE = (
    "「执政利益集团」指当前组阁执政的利益集团（即数据中标注「执政」的集团），"
    "其政治力量为该集团在政坛的影响力占比；报道政界动态时应以执政集团为核心，"
    "结合其力量消长说明朝局与施政倾向，但不得虚构具体数字。"
    "政治运动的活跃度分四档：消极(低于25)、不满(25~50)、抗议(50~75)、武斗(75及以上)。"
)

# 只有本期确实存在抗议/武斗档(激进指数≥0.5)或附带内战/分离进程的运动时才追加,
# 避免模型在无此类运动时也收到「抗议档起…」的解读
MOVEMENT_ESCALATION_GUIDE = (
    "抗议档起每月会使部分支持者激进化并在州内制造抗拒，"
    "只有抗议及以上档位的运动才可能附带内战/分离进程；"
    "数据给出该进程时须如实报道其进度，不得自行推断战争爆发。"
)


def has_escalated_movement(data):
    """本期是否存在达到抗议/武斗档或附带内战/分离进程的政治运动。"""
    for mv in (data.get("political_movements") or []):
        if not isinstance(mv, dict):
            continue
        if mv.get("activism") in ("抗议", "武斗"):
            return True
        rad = mv.get("radicalism")
        if isinstance(rad, (int, float)) and rad >= 0.5:
            return True
        cw = mv.get("civil_war")
        if isinstance(cw, dict) and cw.get("type"):
            return True
    return False


DEFAULT_STYLE = 1

# 四种报纸风格。config.json 的 newspaper_style 取 1~4 对应下表;
# 各风格只影响「报名规则 / 文风 / 栏目名」, 传入模型的数据内容完全相同。
NEWSPAPER_STYLES = {
    1: {
        "name": "大公报（20世纪初）",
        "masthead": (
            "【报名】报名必须由【首都/都城】名直接派生，如《罗马公报》《巴黎回声报》"
            "《江户政闻录》，可再结合【政体】微调（如《巴黎共和公报》），"
            "并随其变迁而调整，以体现时代推移。"
            "【首都】数据取自游戏中的都城名（优先城市名，如「巴黎」「京都」；"
            "若为州名如「法兰西岛」，请改用该国更广为人知的都城名来拟报名）。"
            "不得使用「世界纪闻」这类与任何国家无关的通用报名。"
            "示例：都城罗马可作《罗马公报》，都城巴黎可作《巴黎回声报》，"
            "都城京都可作《京都新闻》；若首都或政体数据缺失，则退而用国名拟定，"
            "如《法兰西新闻》《日本新闻》。"
        ),
        "voice": (
            "你是一位生活于19世纪至20世纪上半叶的报纸总编辑，文风「半文半白」："
            "以白话为主体、晓畅明白，又保留文言的凝练庄重（梁启超、鲁迅及民国初年"
            "《申报》《大公报》笔法）。使用简体中文与 Markdown。"
            "铁律：只能基于给定事实合理演绎，不编造具体数字或国家名；"
            "数据缺失时相应内容简写或略去，不得编造；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部消息，我国国民生产总值为……」（填入给定GDP数值）"
            "引出经济总量，如「据户部消息，我国国民生产总值为四千六百余万英镑」；"
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
            "不得使用「世界纪闻」这类与任何国家无关的通用报名。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西日报》《日本日报》。"
        ),
        "voice": (
            "你是一位生活于20世纪的权威大报总编辑，供职于以人民立场为根本、"
            "服务社会主义建设与人民生活的报纸。你的文风端正庄重、朴实有力："
            "善用「人民」「群众」「建设」「发展」「团结」等语汇，消息客观、社论有高度，"
            "措辞审慎而不空喊口号；有喜报喜、有忧报忧，以建设与发展为主线，不轻佻浮夸。"
            "使用简体中文与 Markdown。"
            "铁律：只能基于给定事实合理演绎，不编造具体数字或国家名；"
            "数据缺失时相应内容简写或略去，不得编造；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，如「国家统计局最新数据显示，我国GDP为四千六百零七万英镑」；"
            "人口、生活水平、识字率等其余指标以官方书面语展开。"
        ),
        "ads_guide": (
            "广告栏须为20世纪党报广告体：国营厂矿产品广告、展览会通知、招生启事、征订启事等，"
            "措辞正式简明，突出为人民生活服务与建设成果（如「为人民生活服务」「欢迎选购」），"
            "不得使用旧式文言告白腔。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如 46,077,267 英镑、21,862,816 人、69.45%），"
            "不得使用汉字数字。"
        ),
        "section_titles": {
            "headline": "今日要闻",
            "war": "军事报道",
            "diplo": "国际要闻",
            "econ": "经济建设",
            "politics": "时政要闻",
            "society": "民族与宗教",
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
            "不得使用「世界纪闻」这类与任何国家无关的通用报名。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西新华报》《日本新华电讯》。"
        ),
        "voice": (
            "你是一位供职于国家通讯社的资深记者与编辑，写作新华社通稿体："
            "消息开门见山，首段即时间、地点、事件三要素；事实准确、行文凝练、"
            "措辞规范，标题朴实有力，不堆砌形容词，不用网络用语；报道以事实说话，"
            "注重权威与可信，不渲染、不夸张。使用简体中文与 Markdown。"
            "铁律：只能基于给定事实合理演绎，不编造具体数字或国家名；"
            "数据缺失时相应内容简写或略去，不得编造；行文中以「本社」指代本通讯社。"
        ),
        "econ_guide": (
            "经济板块首句必须以「国家统计局最新数据显示，我国GDP为……」（填入给定GDP数值）"
            "引出经济总量，其余数据以新华社通稿体如实报道。"
        ),
        "ads_guide": (
            "广告栏须为现代新闻媒体分类广告/公告体：产品服务信息、展会通知、公益公告等，"
            "信息要素齐全（名称、地点、方式），标题简明，措辞平实，不得使用旧式文言告白腔。"
        ),
        "number_format": "arabic",
        "number_guide": (
            "一律使用阿拉伯数字并加千分位分隔符（如 46,077,267 英镑、21,862,816 人、69.45%），"
            "不得使用汉字数字。"
        ),
        "section_titles": {
            "headline": "要闻",
            "war": "军事新闻",
            "diplo": "国际新闻",
            "econ": "经济新闻",
            "politics": "时政新闻",
            "society": "社会新闻",
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
            "不得使用「世界纪闻」这类与任何国家无关的通用报名。"
            "若首都或政体数据缺失，则退而用国名拟定，如《法兰西泰晤士报》《日本泰晤士报》。"
        ),
        "voice": (
            "你是一位供职于英伦百年大报的中文版总编辑（风格仿《泰晤士报》）。"
            "你的文风庄重冷静、含蓄克制，以绅士笔调叙述世事：句子结构完整、措辞考究，"
            "善用「据悉」「据可靠消息」「观乎」「有识之士」等书面语；报道重事实、重细节，"
            "评论持重、不偏不倚，偶带英式含蓄的讽喻，标题典雅而不夸张。"
            "使用简体中文与 Markdown。"
            "铁律：只能基于给定事实合理演绎，不编造具体数字或国家名；"
            "数据缺失时相应内容简写或略去，不得编造；行文中以「本报」指代本报刊名。"
        ),
        "econ_guide": (
            "经济板块首句必须以「据户部消息，我国国民生产总值为……」（填入给定GDP数值）"
            "引出经济总量，如「据户部消息，我国国民生产总值为四千六百余万英镑」；"
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
            "family": "民间专访",
            "peer": "富室专访",
            "unemployed": "失业调查",
            "comment": "社评",
            "ads": "启事与广告",
        },
    },
}

_TERRITORY_CAP = 8

def _v3_date_zh(v3date):
    """把存档日期 '1836.5.14' 转成 '1836年5月14日'; 空或无效时返回空串。"""
    if not v3date:
        return ""
    parts = str(v3date).split(".")
    if len(parts) == 3:
        try:
            y, m, d = (int(x) for x in parts)
            return f"{y}年{m}月{d}日"
        except ValueError:
            return str(v3date)
    return str(v3date)

def _state_change_line(verb, state):
    """生成一条疆域变动行。verb: '新获' / '失去'。"""
    name = state.get("name") or f"州{state.get('id')}"
    culture = state.get("top_culture")
    if verb == "新获":
        if culture and not state.get("empty"):
            return f"我国新获「{name}」，该地居民以{culture}为主"
        if culture:
            return f"我国新获「{name}」，该地尚少人烟（本土为{culture}）"
        return f"我国新获「{name}」"
    if culture and not state.get("empty"):
        return f"我国失去「{name}」，该地原以{culture}为主"
    if culture:
        return f"我国失去「{name}」，该地原少人烟（本土为{culture}）"
    return f"我国失去「{name}」"

def _render_territory_change(data, history=None):
    """对比本年与上一份年度存档的州列表, 生成「去年疆域变动」行; 无变化返回 []。"""
    cur = data.get("states") or []
    if not cur or not history:
        return []
    prev = history[-1]
    prev_states = prev.get("states") or []
    if not prev_states:
        return []
    prev_year = prev.get("year")
    cur_ids = {s.get("id") for s in cur}
    prev_ids = {s.get("id") for s in prev_states}
    gained = [s for s in cur if s.get("id") not in prev_ids]
    lost = [s for s in prev_states if s.get("id") not in cur_ids]
    if not gained and not lost:
        return []
    label = f"与{prev_year}年相比" if prev_year else "与上一年度相比"
    lines = [f"- 去年疆域变动（{label}）："]
    for s in gained[:_TERRITORY_CAP]:
        lines.append("  - " + _state_change_line("新获", s))
    if len(gained) > _TERRITORY_CAP:
        lines.append(f"  - 新获地区共 {len(gained)} 个，其余从略")
    for s in lost[:_TERRITORY_CAP]:
        lines.append("  - " + _state_change_line("失去", s))
    if len(lost) > _TERRITORY_CAP:
        lines.append(f"  - 失去地区共 {len(lost)} 个，其余从略")
    return lines

def _merged_last_year_wars(data, history):
    """去年战争: 当前存档记录 + 上一年存档中仍在进行的战争(按 id 去重)。
    V3 存档的 war_manager 只保留仍在进行的战争, 去年开打但在今年存档前已
    结束的战争会从存档消失; 上一年存档中的战争必然覆盖上一历年, 据此补回。"""
    wars = list(data.get("last_year_wars") or [])
    seen = {w.get("id") for w in wars if w.get("id") is not None}
    if history:
        for w in (history[-1].get("wars") or []):
            wid = w.get("id")
            if wid is not None and wid in seen:
                continue
            ps = [p for p in (w.get("participants") or []) if p.get("primary")]
            if not ps:
                continue
            w2 = dict(w)
            w2["participants"] = ps
            wars.append(w2)
            if wid is not None:
                seen.add(wid)
    wars.sort(key=lambda x: str(x.get("start_date") or ""))
    return wars


def _merged_prev_year_player_wars(data, history):
    """前一年玩家参战的战争: 当前存档记录 + 上一年存档补回(按 id 去重)。"""
    wars = list(data.get("prev_year_wars") or [])
    seen = {w.get("id") for w in wars if w.get("id") is not None}
    if history:
        for w in (history[-1].get("wars") or []):
            wid = w.get("id")
            if not w.get("player_involved"):
                continue
            if wid is not None and wid in seen:
                continue
            wars.append(w)
            if wid is not None:
                seen.add(wid)
    return wars


def _war_parties_line(participants):
    """把一场战争的参战方拼成直接句式：发起方与应战方之间用「与」连接, 同侧用顿号。
    例如「东印度公司与卡尔萨帝国开战」「大不列颠、东印度公司与大清开战」；
    无 side 数据时退化为顿号名单 + 「交战」。"""
    named = []
    for p in (participants or []):
        if not isinstance(p, dict):
            continue
        nm = strip_loc_formatting(p.get("name", "")).strip()
        if nm:
            named.append((p, nm))
    if not named:
        return ""
    init = [nm for p, nm in named if p.get("side") == "initiator"]
    tgt = [nm for p, nm in named if p.get("side") == "target"]
    if init and tgt and len(init) + len(tgt) == len(named):
        return f"{'、'.join(init)}与{'、'.join(tgt)}开战"
    return "、".join(nm for _, nm in named) + "交战"


def render_overview(data, history=None):
    L = []
    capital = data.get('capital', '') or '（数据缺失，请根据国名常识补填该国的广为人知的都城名）'
    govt_zh = GOVT_NAMES.get(data.get("govt", ""), data.get("govt", "未知"))
    L.append(f"【国家】{data.get('player', '未知')}  【都城】{capital}  【政体】{govt_zh}  【年份】{data.get('year', '?')}（{data.get('date', '')}）")
    L.append(f"- GDP：{data.get('gdp', '未知')}英镑；人口：{data.get('pop', '未知')}；生活水平：{data.get('sol', '未知')};识字率：{data.get('literacy', '未知')}")
    L.append(f"- 国际声望(恶名)：{data.get('infamy', '未知')}")
    if data.get("radicals_pct") is not None or data.get("loyalists_pct") is not None:
        L.append(f"- 政治倾向：激进派占人口约{data.get('radicals_pct', '?')}%，"
                 f"效忠派占人口约{data.get('loyalists_pct', '?')}%")
    igs = data.get("interest_groups") or []
    ruling = [g for g in igs if g.get("in_government")]
    if ruling:
        L.append("- 当前执政利益集团：" + "、".join(
            f"{IG_NAMES.get(g.get('name'), IG_NAMES.get(g.get('definition'), g.get('name')))}"
            f"（政治力量约{g['clout_pct']:.1f}%）" if isinstance(g.get('clout_pct'), (int, float))
            else f"{IG_NAMES.get(g.get('name'), IG_NAMES.get(g.get('definition'), g.get('name')))}"
            for g in ruling))
    L.extend(_render_territory_change(data, history))
    # 列强之间的战事 = 国际背景, 与本国无关: 每场战争单独一行,
    # 只列主要参与方; 多个列强在同一场战争则写在同一行;
    # 本国参战的战争不在此列, 由下面的「我国…交战」行覆盖
    bg_wars = [w for w in _merged_last_year_wars(data, history)
               if not w.get("player_involved")
               and any(p.get("rank") == "great_power" for p in (w.get("participants") or []))]
    if bg_wars:
        for w in bg_wars:
            L.append(f"- 列强之间的战事：{_war_parties_line(w.get('participants') or [])}")
    # 本国战事: 只读取前一年(上一历年)玩家参战的战争(含开战日期),
    # 已过去两年及更早的战争不传递给模型
    player_id = data.get("player_country_id")
    player_tag = data.get("tag")
    player_name = data.get("player", "")
    player_wars = sorted(_merged_prev_year_player_wars(data, history),
                         key=lambda x: str(x.get("start_date") or ""))
    for w in player_wars:
        opps = []
        for p in (w.get("participants") or []):
            if not p.get("primary"):
                continue
            if player_id is not None and p.get("id") == player_id:
                continue
            if player_tag and p.get("definition") == player_tag:
                continue
            if player_name and p.get("name") == player_name:
                continue
            opps.append(strip_loc_formatting(p.get("name", "?")))
        start = _v3_date_zh(w.get("start_date"))
        suffix = ""
        if w.get("ended"):
            pz = _v3_date_zh(w.get("peace_date"))
            suffix = f"，已于{pz}结束" if pz else "，已结束"
        if opps:
            L.append(f"- 我国于{start}与{'、'.join(opps)}交战{suffix}")
        elif start:
            L.append(f"- 我国于{start}参战{suffix}")
    # 日志解析路径回退: war_opponents 无开战日期, 只给对手
    opponents = data.get("war_opponents") or []
    if opponents and not player_wars:
        L.append(f"- 我国与{'、'.join(opponents)}交战")
    ended = [e for e in (data.get("events") or []) if e.get("kind") == "war_end"]
    if ended:
        L.append("- 结束战事：" + "；".join(f"{e.get('actor', '?')}对{e.get('target', '?')}" for e in ended))
    pf = _press_freedom_line(data)
    if pf:
        L.append(pf)
    return "\n".join(L)

def render_war(data, history=None):
    L = []
    # 只传去年发生的战争: 玩家参战或列强参战, 仅主要参加者; 不含当前交战状态
    L.append("- 以下战事为去年（上一历年）发生的战争记录（玩家参战或列强参战，"
             "仅列主要参加者）；数据不含今年是否处于交战状态，请勿推断今年战况。")
    wars = _merged_last_year_wars(data, history)
    if not wars:
        L.append("  (去年无相关战事记录)")
    for w in wars:
        parties = _war_parties_line(w.get('participants') or [])
        status = f"已结束（和约 {w.get('peace_date')}）" if w.get('ended') else "仍在进行"
        start = w.get('start_date')
        line = f"- {parties}：{status}" if parties else f"- 交战方未知：{status}"
        if start:
            line += f"（始于{start}）"
        extra = []
        cas = w.get('casualties_total')
        if cas is not None:
            extra.append(f"双方死伤{cas:.2f}万" if cas >= 10 else f"双方死伤{cas:.2f}")
        cost = w.get('total_cost')
        if cost:
            extra.append(f"耗资{cost:.0f}英镑")
        if extra:
            line += "（" + "、".join(extra) + "）"
        L.append(line)
    return "\n".join(L)

def render_diplo(data):
    L = []
    rivals = data.get("rivals") or []
    if rivals:
        L.append("- 宿敌（互相敌对的国家）：" + "、".join(strip_loc_formatting(r.get('name', '?')) for r in rivals))
    else:
        L.append("- 宿敌：(无)")
    treaties = data.get("treaties") or []
    if treaties:
        L.append("- 本国条约：")
        for t in treaties:
            L.append(f"  - {strip_loc_formatting(t['name'])}：{strip_loc_formatting(t['first_name'])}"
                     f"与{strip_loc_formatting(t['second_name'])}签订于{t.get('date') or '?'}")
            for a in t.get("articles") or []:
                meta = a.get("meta") or {}
                kind = meta.get("kind")
                if kind == "free_text":
                    note = meta.get("text") or a.get("detail")
                    if note:
                        L.append(f"    · 备注：{note}")
                    continue
                if kind == "goods" and a.get("from") and a.get("to"):
                    gz = meta.get("goods")
                    qty = meta.get("quantity")
                    if gz:
                        if qty is not None:
                            L.append(f"    · {a['from']}向{a['to']}移交{qty}单位的{gz}")
                        else:
                            L.append(f"    · {a['from']}向{a['to']}移交{gz}")
                        continue
                line = f"    · {a['zh']}"
                if a.get('from') and a.get('to'):
                    line += f": {a['from']}→{a['to']}"
                if a.get('detail'):
                    line += f" ({a['detail']})"
                L.append(line)
    else:
        L.append("- 本国条约：(无数据)")
    subs = data.get("subjects") or []
    if subs:
        L.append("- 附庸国：" + "、".join(
            f"{strip_loc_formatting(s['name'])}({PACT_NAMES.get(s.get('type'), s.get('type'))})"
            if isinstance(s, dict) else str(s)
            for s in subs))
    else:
        L.append("- 附庸国：(无)")
    L.append(f"- 国际声望(恶名)：{data.get('infamy', '未知')}")
    powers = data.get("powers") or []
    if powers:
        L.append("- 世界前八强战况(外交背景)（其中标注「我国」者即本报所属国家）：")
        for p in powers:
            nm = strip_loc_formatting(p['name'])
            if p.get("is_player"):
                nm += "（我国）"
            L.append(f"  - {nm}：{'交战中' if p.get('war') else '和平'}")
    return "\n".join(L)

def _yoy_pct(prev, cur):
    """同比变化率 (%), 上年数据缺失或为 0 时返回 None。"""
    if prev is None or cur is None:
        return None
    try:
        prev = float(prev)
        cur = float(cur)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        return None
    return (cur - prev) / prev * 100

def render_econ(data, history=None):
    L = []
    prev = (history[-1] or {}) if history else {}
    gdp = data.get('gdp', '未知')
    gdp_line = f"- GDP：{gdp}英镑"
    gdp_pct = _yoy_pct(prev.get("gdp"), gdp if isinstance(gdp, (int, float)) else None)
    if gdp_pct is not None:
        gdp_line += f"（比去年同期{'增长' if gdp_pct >= 0 else '减少'}{abs(gdp_pct):.1f}%）"
    L.append(gdp_line)
    pop = data.get('pop', '未知')
    pop_line = f"- 人口：{pop}"
    pop_pct = _yoy_pct(prev.get("pop"), pop if isinstance(pop, (int, float)) else None)
    if pop_pct is not None:
        pop_line += f"（比去年同期{'增长' if pop_pct >= 0 else '减少'}{abs(pop_pct):.1f}%）"
    L.append(pop_line)
    L.append(f"- 平均生活水平：{data.get('sol', '未知')}")
    L.append(f"  - {SOL_GUIDE}")
    if data.get("sol_below"):
        L.append("  - 注：当前生活水平**低于民众预期**，民生怨望上升")
    L.append(f"- 识字率：{data.get('literacy', '未知')}")
    return "\n".join(L)

def render_politics(data, history=None):
    L = []
    L.append(f"- 政体：{GOVT_NAMES.get(data.get('govt', ''), data.get('govt', '未知'))}")
    ruler = _ruler_name(data)
    extra = "，".join(x for x in (data.get("ruler_title"),
                                  data.get("ruler_ideology"),
                                  data.get("ruler_status")) if x)
    if ruler and extra:
        ruler += f"（{extra}）"
    if not ruler:
        ruler = '（未知，当前年度统治者）'
    L.append(f"- 统治者：{ruler}")
    ruler_act = data.get("ruler_activity")
    if ruler_act:
        L.append(f"- 本期统治者活动（须据此如实报道，人物/地点/事件不得改写）：{ruler_act}")
    if data.get("radicals_pct") is not None or data.get("loyalists_pct") is not None:
        L.append(f"- 民意倾向：激进派占人口约{data.get('radicals_pct', '?')}%，"
                 f"效忠派占人口约{data.get('loyalists_pct', '?')}%")
    igs = data.get("interest_groups") or []
    if igs:
        L.append("- 主要利益集团（按政治力量占比降序，执政者标注「执政」）：")
        for g in igs[:5]:
            nm = IG_NAMES.get(g.get('name'), IG_NAMES.get(g.get('definition'), g.get('name')))
            cl = g.get('clout_pct')
            cl_s = f"约{cl:.1f}%" if isinstance(cl, (int, float)) else "占比未知"
            gov = "，执政" if g.get("in_government") else ""
            lead = ""
            if g.get("leader_name"):
                lead = f"，首领：{g['leader_name']}"
                if g.get("leader_ideology"):
                    lead += f"（{g['leader_ideology']}）"
            L.append(f"  - {nm}（{cl_s}{gov}{lead}）")
        ruling = [g for g in igs if g.get("in_government")]
        if ruling:
            L.append("- 当前执政利益集团：" + "、".join(
                IG_NAMES.get(g.get('name'), IG_NAMES.get(g.get('definition'), g.get('name')))
                for g in ruling))
    mvs = data.get("political_movements") or []
    if mvs:
        extra = [mv for mv in mvs[3:]
                 if (mv.get("radicalism") or 0) >= 0.5]
        extra.sort(key=lambda mv: -(mv.get("radicalism") or 0))
        shown = list(mvs[:3]) + extra
        if extra:
            L.append("- 政治运动（支持度前三，另列出已达抗议/武斗档的运动）：")
        else:
            L.append("- 政治运动（支持度前三）：")
        for mv in shown:
            nm = mv.get("name") or mv.get("type") or "未知运动"
            line = f"  - {nm}"
            if mv.get("ideology"):
                line += f"（核心意识形态：{mv['ideology']}）"
            bits = []
            if isinstance(mv.get("support_pct"), (int, float)):
                bits.append(f"支持度约{mv['support_pct']:.1f}%")
            if mv.get("supporters"):
                bits.append(f"支持者约{mv['supporters'] / 10000:.1f}万人")
            if mv.get("activism") and mv["activism"] != "消极":
                bits.append(f"活跃度：{mv['activism']}")
            if bits:
                line += "：" + "，".join(bits)
            cw = mv.get("civil_war")
            rad = mv.get("radicalism")
            if cw and isinstance(rad, (int, float)) and rad >= 0.5:
                cwt = "革命" if cw.get("type") == "revolution" else "分裂"
                prog = cw.get("progress", 0)
                if isinstance(prog, (int, float)):
                    if cw.get("type") == "revolution":
                        if prog <= 0.005:
                            line += "；街头冲突愈演愈烈"
                        else:
                            line += f"；革命酝酿进程约{prog * 100:.0f}%"
                    else:
                        if prog <= 0.005:
                            line += "；街头冲突愈演愈烈"
                        else:
                            line += f"；分离进程约{prog * 100:.0f}%"
            L.append(line)
    if "laws_enacted" in data or "laws_repealed" in data:
        # 存档直读: laws 已只含本年度变化的法律, 直接展示新施行/废除
        enacted = data.get("laws_enacted") or []
        repealed = data.get("laws_repealed") or []
        if enacted:
            L.append("- 本年度新施行法律：" + "、".join(law_zh(l) for l in enacted))
        if repealed:
            L.append("- 本年度废除法律：" + "、".join(law_zh(l) for l in repealed))
        if not enacted and not repealed:
            L.append("- 法律：本年度无变动")
    else:
        laws = data.get("laws") or []
        if laws:
            L.append("- 现行关键法律：" + "、".join(law_zh(l) for l in laws))
        if history:
            old = set((history[-1] or {}).get("laws") or [])
            cur = set(laws)
            added, removed = sorted(cur - old), sorted(old - cur)
            if added:
                L.append("- 本年度新施行法律：" + "、".join(law_zh(l) for l in added))
            if removed:
                L.append("- 本年度废除法律：" + "、".join(law_zh(l) for l in removed))
            if not added and not removed:
                L.append("- 法律：与上年无异")
    return "\n".join(L)

def render_society(data):
    L = []
    if data.get("radicals_pct") is not None or data.get("loyalists_pct") is not None:
        L.append(f"- 政治倾向(占总人群比例)：激进派约{data.get('radicals_pct', '?')}%，"
                 f"效忠派约{data.get('loyalists_pct', '?')}%")
    # 国教(国家官方宗教)与主流文化(国族): 存档直读自国家对象, 供模型把握社会基调
    religion = data.get("religion")
    if religion:
        L.append(f"- 国教（国家官方宗教）：{RELIGION_NAMES.get(religion, religion)}")
    prim = data.get("primary_cultures") or []
    prim_names = [p if isinstance(p, str) else (p.get("name") if isinstance(p, dict) else "")
                  for p in prim]
    prim_names = [n for n in prim_names if n]
    if prim_names:
        L.append("- 主流文化（国族/主体文化）：" + "、".join(prim_names))
    cultures = data.get("pop_cultures") or data.get("cultures") or []
    weight = {"majority": 3, "large": 2, "notable": 1, "minor": 0}
    if cultures:
        names = []
        for c in sorted(cultures, key=lambda x: -(x.get('count') or 0) if x.get('count') else int(str(x.get('rank', 9))))[:3]:
            nm = c.get('name', '') or f"（第{c.get('rank','?')}大族，请据国名常识补填）"
            names.append(nm)
        L.append(f"- 主要民族：{'、'.join(names)}")
    else:
        L.append("- 民族构成：(无数据)")
    religions = data.get("pop_religions") or data.get("religions") or []
    if religions:
        L.append("- 主要宗教(按占比取前三)：")
        for r in sorted(religions,
                        key=lambda x: (x.get('count') or 0) if x.get('count')
                        else weight.get(x.get('share'), 0), reverse=True)[:3]:
            if r.get('pct') is not None:
                sh = f"占人口{r['pct']:.1f}%"
            else:
                sh = SHARE_NAMES.get(r.get('share'), r.get('share')) if r.get('share') else '(占比数据缺)'
            L.append(f"  - {RELIGION_NAMES.get(r.get('name'), r.get('name'))}（{sh}）")
    profs = data.get("professions") or []
    if profs:
        L.append("- 主要职业(按占比取前三)：")
        for p in sorted(profs,
                        key=lambda x: (x.get('count') or 0) if x.get('count')
                        else weight.get(x.get('share'), 0), reverse=True)[:3]:
            if p.get('pct') is not None:
                sh = f"占人口{p['pct']:.1f}%"
            else:
                sh = SHARE_NAMES.get(p.get('share'), p.get('share')) if p.get('share') else '(占比数据缺)'
            L.append(f"  - {POP_TYPE_NAMES.get(p.get('name'), p.get('name'))}（{sh}）")
    migr = [e for e in (data.get("events") or []) if e.get("kind") == "migration"]
    if migr:
        L.append(f"- 移民动向：本年度有 {len(migr)} 处地区成为新的移民目的地")
    return "\n".join(L)

def _pollution_band(p):
    """污染影响档位 (百分比)。"""
    if p < 5:
        return "轻微"
    if p < 15:
        return "中等"
    if p < 30:
        return "严重"
    return "极重"


def _devastation_band(d):
    """荒废度档位 (0~100 点)。"""
    if d < 10:
        return "轻微"
    if d < 25:
        return "明显"
    if d < 50:
        return "严重"
    return "近乎废墟"


def _render_vital_stats(obj):
    """出生/死亡信息: 修正后的年化估算率 + 污染/荒废度 + (本土) 医疗/教育制度。"""
    L = []
    incorp = obj.get("incorporation")
    if not isinstance(incorp, (int, float)):
        incorp = None
    birth = obj.get("birth_rate_pct")
    death = obj.get("death_rate_pct")
    if birth is not None and death is not None:
        if incorp is None or incorp < 1:
            note = "结合生活水平、污染、荒废度与劳动条件的年化估算率，该州未完全并入本土，未计入卫生机构与相关法律"
        else:
            note = "结合生活水平、污染、荒废度、卫生机构与相关法律修正的年化估算率"
        L.append(f"- 出生率/死亡率（{note}）：约{birth:.2f}% / 约{death:.2f}%")
    hx = obj.get("hazard_excess_pct")
    hpms = obj.get("hazard_pms_zh")
    if hx is not None and hpms:
        L.append(f"- 劳动条件：该人群所在工作场所采用{'、'.join(hpms)}等生产方式，"
                 f"劳动条件极为恶劣，壮年男子死伤甚多，死亡率较该州其他人群高约{hx:.0f}%")
    pol = obj.get("pollution_pct")
    if isinstance(pol, (int, float)) and pol > 0:
        L.append(f"- 污染影响：约{pol:.1f}%（{_pollution_band(pol)}）")
    dev = obj.get("devastation")
    if isinstance(dev, (int, float)) and dev > 0:
        L.append(f"- 荒废度：约{dev:.0f}点（{_devastation_band(dev)}）")
    # 卫生/教育机构只对完全并入本土的州生效: 殖民地与合并中州不展示法律与机构
    if incorp is None or incorp < 1:
        if incorp is None or incorp <= 0:
            L.append("- 该州为殖民地，未设有本土的卫生和教育机构")
        else:
            L.append("- 该州尚在合并中，卫生和教育机构尚未生效")
    else:
        hl = obj.get("health_law")
        if hl:
            hline = f"- 医疗制度：{law_zh(hl)}"
            if obj.get("health_investment") is not None:
                hline += f"（卫生机构 {obj.get('health_investment')} 级）"
            if obj.get("sewerage"):
                hline += "，已普及现代下水道"
            L.append(hline)
        el = obj.get("education_law")
        if el:
            eline = f"- 教育制度：{law_zh(el)}"
            if obj.get("schools_investment") is not None:
                eline += f"（教育机构 {obj.get('schools_investment')} 级）"
            L.append(eline)
    return L


def _render_pop_politics(obj):
    """政治倾向（激进/效忠派占该人群百分比）与该人群参与比例最高的两个政治运动。
    存档口径: loyalists_and_radicals 为每 10 万人净值,
    效忠人数 = max(0,净值)×10万, 激进人数 = max(0,-净值)×10万。"""
    L = []
    lr = obj.get("loyalists_and_radicals")
    lp = obj.get("loyalists_pct")
    rp = obj.get("radicals_pct")
    if isinstance(lp, (int, float)) and lp > 0:
        L.append(f"- 政治倾向：效忠派占该人群约{lp:.1f}%")
    elif isinstance(rp, (int, float)) and rp > 0:
        L.append(f"- 政治倾向：激进派占该人群约{rp:.1f}%")
    elif lr is not None:
        L.append("- 政治倾向：无明显效忠/激进倾向")
    items = [(m.get("name", "未知运动"), m.get("pct"))
             for m in (obj.get("political_movements") or [])[:2]
             if isinstance(m.get("pct"), (int, float))]
    if items:
        segs = [f"{pct:.1f}%参加{name}" for name, pct in items]
        L.append("- 政治运动：人群中" + "，".join(segs))
    return L


def render_family(data):
    """民生访谈: 记者跟踪采访一个随机选取的平民家庭 (存档直读)。"""
    fi = data.get("family_interview")
    if not fi:
        return "- (存档直读数据缺：本期未提供家庭采访样本)"
    L = []
    region = fi.get("region_name") or "（州名数据缺）"
    pop_zh = POP_TYPE_NAMES.get(fi.get("pop_type"), fi.get("pop_type") or "平民")
    culture = fi.get("culture") or "（族属数据缺）"
    rel_zh = RELIGION_NAMES.get(fi.get("religion"), fi.get("religion") or "（信仰数据缺）")
    hub = fi.get("hub_name")
    loc = f"{hub}（{region}）" if hub else region
    L.append(f"- 采访对象：{loc}的一户{culture}{rel_zh}{pop_zh}家庭")
    if fi.get("ruler_visited"):
        who = (data.get("ruler_title") or "") + (data.get("ruler") or "")
        if who:
            L.append(f"- 统治者走访：{who}近日曾走访本州（详见政界动态「本期统治者活动」），"
                     f"受访者对此记忆犹新，可在访谈中自然提及")
    # 本土归属: 存档直读时按“该州域是否是该族本土(add_homeland)”判定
    homeland = fi.get("is_homeland")
    if homeland is not None:
        if homeland:
            L.append(f"- 本土归属：此地（{region}）是{culture}的本土故土，世代居住")
        else:
            L.append(f"- 本土归属：此地（{region}）并非{culture}的本土，系外来/迁徙定居")
    # 行政地位: 合并州 = 本土, 未合并 = 殖民地/边疆 (存档 incorporation 进度 0~1)
    incorp = fi.get("incorporation")
    if incorp is not None:
        if isinstance(incorp, (int, float)):
            if incorp >= 1:
                L.append("- 行政地位：本土")
            elif incorp > 0:
                L.append(f"- 行政地位：合并中（进度约{incorp * 100:.0f}%，尚未完全并入本土）")
            else:
                L.append("- 行政地位：殖民地/边疆")
        else:
            L.append("- 行政地位：本土" if incorp
                     else "- 行政地位：殖民地/边疆")
    # 收成状况: 存档 harvest_condition_manager 匹配该州域; 无活跃条件 = 正常
    if "harvest_conditions" in fi:
        hv = fi.get("harvest_conditions") or []
        if hv:
            L.append("- 收成状况：" + "、".join(HARVEST_NAMES.get(t, t) for t in hv))
        else:
            L.append("- 收成状况：正常（无旱涝、灾害等异常）")
    cgoods = fi.get("consumption_goods") or []
    if cgoods:
        names = [g.get("name") for g in cgoods if g.get("name")]
        if names:
            L.append("- 主要消费商品（按需求权重降序）：" + "、".join(names))
        trends = []
        for g in cgoods:
            d = g.get("dev_pct")
            nm = g.get("name")
            if d is None or not nm:
                continue
            if d >= 5:
                trends.append(f"{nm}高于正常价约{d:.0f}%")
            elif d <= -5:
                trends.append(f"{nm}低于正常价约{-d:.0f}%")
            else:
                trends.append(f"{nm}与正常价基本持平")
        if trends:
            L.append("- 主要消费品市价（本州所在市场，对比正常价）：" + "、".join(trends))
    if fi.get("unemployed"):
        L.append("- 工作状况：失业")
    elif fi.get("workplace"):
        L.append(f"- 工作场所：{fi.get('workplace')}")
    engel = fi.get("engel_coefficient")
    if engel is not None:
        L.append(f"- 恩格尔系数（按需求权重估算）：约{engel}%"
                 f"（食品与基本糊口需求占需求结构比重；>60%≈赤贫，50~60%≈温饱，"
                 f"40~50%≈小康，<40%≈宽裕）")
    literacy = fi.get("literacy_pct")
    if literacy is not None:
        L.append(f"- 识字率：约{literacy:.2f}%（该POP识字人口占比）")
    acc_status = fi.get("acceptance_status")
    if acc_status:
        L.append(f"- 社会地位：{ACCEPTANCE_NAMES.get(acc_status, acc_status)}")
    ig = fi.get("interest_group")
    if ig:
        ig_zh = IG_NAMES.get(ig.get("name"), ig.get("name")) if isinstance(ig, dict) else str(ig)
        ig_line = f"- 利益集团（政治倾向占比最高）：{ig_zh}"
        share_pct = ig.get("share_pct") if isinstance(ig, dict) else None
        if isinstance(share_pct, (int, float)):
            ig_line += f"（占该群体政治倾向约{share_pct:.1f}%）"
        L.append(ig_line)
    job_sat = fi.get("job_satisfaction")
    if job_sat is not None:
        mood = "满意" if job_sat > 0 else ("不满" if job_sat < 0 else "一般")
        L.append(f"- 职业满意度：{mood}（{job_sat:+.2f}；{JOB_SATISFACTION_GUIDE}）")
    L.extend(_render_vital_stats(fi))
    dr = fi.get("dependent_ratio")
    workforce = fi.get("workforce")
    dependents = fi.get("dependents")
    pop_total = (workforce or 0) + (dependents or 0)
    if dr is not None:
        L.append(f"- 该POP人口构成：共约{pop_total}人（劳动力{workforce}人，"
                 f"受抚养人口{dependents}人，受抚养比例约{dr * 100:.1f}%）"
                 f"——以下收支为该POP全体居民合计，采访家庭为其代表")
    income = fi.get("income")
    expense = fi.get("expense")
    if income is not None and expense is not None:
        parts = fi.get("income_parts") or []
        inc_line = f"- 每周收入(该POP合计)：约{income}英镑"
        if parts:
            inc_line += "（" + "、".join(parts) + "）"
        L.append(inc_line)
        exp_parts = fi.get("expense_parts") or []
        if exp_parts:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑（" + "、".join(exp_parts) + "）")
        else:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑")
        L.append(f"- 收支结余：约{income - expense:+.2f}英镑/周"
                 f"（人均约{income / pop_total:.4f}镑收入 / {expense / pop_total:.4f}镑支出，按周计）"
                 if pop_total else f"- 收支结余：约{income - expense:+.2f}英镑/周")
    L.extend(_render_pop_politics(fi))
    fs = fi.get("food_security")
    if fs:
        L.append(f"- 粮食安全：{food_security_zh(fs)}")
    return "\n".join(L)


def render_peer(data):
    """邻里富户: 在民生访谈目标同建筑(失业则同州)中 SoL 最高的 POP (存档直读)。
    与 render_family 同风格渲染, 供模型写作贫富对照访谈。"""
    peer = data.get("top_sol_peer")
    if not peer:
        return "- (存档直读数据缺：本期未提供邻里富户样本)"
    L = []
    region = peer.get("region_name") or "（州名数据缺）"
    pop_zh = POP_TYPE_NAMES.get(peer.get("pop_type"), peer.get("pop_type") or "平民")
    culture = peer.get("culture") or "（族属数据缺）"
    rel_zh = RELIGION_NAMES.get(peer.get("religion"), peer.get("religion") or "（信仰数据缺）")
    hub = peer.get("hub_name")
    loc = f"{hub}（{region}）" if hub else region
    sol = peer.get("sol")
    sol_guide = SOL_GUIDE if isinstance(sol, (int, float)) else ""
    L.append(f"- 追踪对象：{loc}中生活水平最高的一群{culture}{rel_zh}{pop_zh}"
             f"【生活水平约{sol}，{sol_guide}】" if isinstance(sol, (int, float))
             else f"- 追踪对象：{loc}中生活水平最高的一群{culture}{rel_zh}{pop_zh}")
    # 与民生访谈的关联: 同建筑或同州对照
    fi = data.get("family_interview")
    if fi:
        fi_zh = POP_TYPE_NAMES.get(fi.get("pop_type"), fi.get("pop_type") or "平民")
        if peer.get("workplace_id") is not None and fi.get("workplace_id") == peer.get("workplace_id"):
            L.append(f"- 对照关系：与《民生访谈》的{fi_zh}家庭同在一处谋生（同一工作场所）")
        else:
            L.append(f"- 对照关系：与《民生访谈》的{fi_zh}家庭同处{region}一地（本州之内）")
    homeland = peer.get("is_homeland")
    if homeland is not None:
        if homeland:
            L.append(f"- 本土归属：此地（{region}）是{culture}的本土故土，世代居住")
        else:
            L.append(f"- 本土归属：此地（{region}）并非{culture}的本土，系外来/迁徙定居")
    incorp = peer.get("incorporation")
    if incorp is not None:
        if isinstance(incorp, (int, float)):
            if incorp >= 1:
                L.append("- 行政地位：本土")
            elif incorp > 0:
                L.append(f"- 行政地位：合并中（进度约{incorp * 100:.0f}%，尚未完全并入本土）")
            else:
                L.append("- 行政地位：殖民地/边疆")
        else:
            L.append("- 行政地位：本土" if incorp else "- 行政地位：殖民地/边疆")
    if "harvest_conditions" in peer:
        hv = peer.get("harvest_conditions") or []
        if hv:
            L.append("- 收成状况：" + "、".join(HARVEST_NAMES.get(t, t) for t in hv))
        else:
            L.append("- 收成状况：正常（无旱涝、灾害等异常）")
    cgoods = peer.get("consumption_goods") or []
    if cgoods:
        names = [g.get("name") for g in cgoods if g.get("name")]
        if names:
            L.append("- 主要消费商品（按需求权重降序）：" + "、".join(names))
        trends = []
        for g in cgoods:
            d = g.get("dev_pct")
            nm = g.get("name")
            if d is None or not nm:
                continue
            if d >= 5:
                trends.append(f"{nm}高于正常价约{d:.0f}%")
            elif d <= -5:
                trends.append(f"{nm}低于正常价约{-d:.0f}%")
            else:
                trends.append(f"{nm}与正常价基本持平")
        if trends:
            L.append("- 主要消费品市价（本州所在市场，对比正常价）：" + "、".join(trends))
    if peer.get("unemployed"):
        L.append("- 工作状况：失业")
    elif peer.get("workplace"):
        L.append(f"- 工作场所：{peer.get('workplace')}")
    engel = peer.get("engel_coefficient")
    if engel is not None:
        L.append(f"- 恩格尔系数（按需求权重估算）：约{engel}%"
                 f"（食品与基本糊口需求占需求结构比重；>60%≈赤贫，50~60%≈温饱，"
                 f"40~50%≈小康，<40%≈宽裕）")
    literacy = peer.get("literacy_pct")
    if literacy is not None:
        L.append(f"- 识字率：约{literacy:.2f}%（该POP识字人口占比）")
    acc_status = peer.get("acceptance_status")
    if acc_status:
        L.append(f"- 社会地位：{ACCEPTANCE_NAMES.get(acc_status, acc_status)}")
    ig = peer.get("interest_group")
    if ig:
        ig_zh = IG_NAMES.get(ig.get("name"), ig.get("name")) if isinstance(ig, dict) else str(ig)
        ig_line = f"- 利益集团（政治倾向占比最高）：{ig_zh}"
        share_pct = ig.get("share_pct") if isinstance(ig, dict) else None
        if isinstance(share_pct, (int, float)):
            ig_line += f"（占该群体政治倾向约{share_pct:.1f}%）"
        L.append(ig_line)
    job_sat = peer.get("job_satisfaction")
    if job_sat is not None:
        mood = "满意" if job_sat > 0 else ("不满" if job_sat < 0 else "一般")
        L.append(f"- 职业满意度：{mood}（{job_sat:+.2f}；{JOB_SATISFACTION_GUIDE}）")
    L.extend(_render_vital_stats(peer))
    dr = peer.get("dependent_ratio")
    workforce = peer.get("workforce")
    dependents = peer.get("dependents")
    pop_total = (workforce or 0) + (dependents or 0)
    if dr is not None:
        L.append(f"- 该POP人口构成：共约{pop_total}人（劳动力{workforce}人，"
                 f"受抚养人口{dependents}人，受抚养比例约{dr * 100:.1f}%）"
                 f"——以下收支为该POP全体居民合计，采访家庭为其代表")
    income = peer.get("income")
    expense = peer.get("expense")
    if income is not None and expense is not None:
        parts = peer.get("income_parts") or []
        inc_line = f"- 每周收入(该POP合计)：约{income}英镑"
        if parts:
            inc_line += "（" + "、".join(parts) + "）"
        L.append(inc_line)
        exp_parts = peer.get("expense_parts") or []
        if exp_parts:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑（" + "、".join(exp_parts) + "）")
        else:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑")
        L.append(f"- 收支结余：约{income - expense:+.2f}英镑/周"
                 f"（人均约{income / pop_total:.4f}镑收入 / {expense / pop_total:.4f}镑支出，按周计）"
                 if pop_total else f"- 收支结余：约{income - expense:+.2f}英镑/周")
    L.extend(_render_pop_politics(peer))
    fs = peer.get("food_security")
    if fs:
        L.append(f"- 粮食安全：{food_security_zh(fs)}")
    return "\n".join(L)


def render_unemployed(data):
    """失业民生: 随机州失业率>5% 时发送, 采访该州失业POP中人口最多的一群。
    与 render_family 同风格, 另附该州失业率。"""
    uni = data.get("unemployed_interview")
    if not uni:
        return "- (该州失业率未超过5%，本期不发送失业民生板块)"
    L = []
    region = uni.get("region_name") or "（州名数据缺）"
    pop_zh = POP_TYPE_NAMES.get(uni.get("pop_type"), uni.get("pop_type") or "平民")
    culture = uni.get("culture") or "（族属数据缺）"
    rel_zh = RELIGION_NAMES.get(uni.get("religion"), uni.get("religion") or "（信仰数据缺）")
    hub = uni.get("hub_name")
    loc = f"{hub}（{region}）" if hub else region
    rate = uni.get("unemployment_rate_pct")
    rate_s = f"约{rate:.1f}%" if isinstance(rate, (int, float)) else "（数据缺）"
    L.append(f"- 追踪对象：{loc}的一群失业的{culture}{rel_zh}{pop_zh}")
    L.append(f"- 该州失业率（失业人口/该州总人口）：{rate_s}")
    homeland = uni.get("is_homeland")
    if homeland is not None:
        if homeland:
            L.append(f"- 本土归属：此地（{region}）是{culture}的本土故土，世代居住")
        else:
            L.append(f"- 本土归属：此地（{region}）并非{culture}的本土，系外来/迁徙定居")
    incorp = uni.get("incorporation")
    if incorp is not None:
        if isinstance(incorp, (int, float)):
            if incorp >= 1:
                L.append("- 行政地位：本土")
            elif incorp > 0:
                L.append(f"- 行政地位：合并中（进度约{incorp * 100:.0f}%，尚未完全并入本土）")
            else:
                L.append("- 行政地位：殖民地/边疆")
        else:
            L.append("- 行政地位：本土" if incorp else "- 行政地位：殖民地/边疆")
    if "harvest_conditions" in uni:
        hv = uni.get("harvest_conditions") or []
        if hv:
            L.append("- 收成状况：" + "、".join(HARVEST_NAMES.get(t, t) for t in hv))
        else:
            L.append("- 收成状况：正常（无旱涝、灾害等异常）")
    cgoods = uni.get("consumption_goods") or []
    if cgoods:
        names = [g.get("name") for g in cgoods if g.get("name")]
        if names:
            L.append("- 主要消费商品（按需求权重降序）：" + "、".join(names))
        trends = []
        for g in cgoods:
            d = g.get("dev_pct")
            nm = g.get("name")
            if d is None or not nm:
                continue
            if d >= 5:
                trends.append(f"{nm}高于正常价约{d:.0f}%")
            elif d <= -5:
                trends.append(f"{nm}低于正常价约{-d:.0f}%")
            else:
                trends.append(f"{nm}与正常价基本持平")
        if trends:
            L.append("- 主要消费品市价（本州所在市场，对比正常价）：" + "、".join(trends))
    if uni.get("unemployed"):
        L.append("- 工作状况：失业")
    elif uni.get("workplace"):
        L.append(f"- 工作场所：{uni.get('workplace')}")
    engel = uni.get("engel_coefficient")
    if engel is not None:
        L.append(f"- 恩格尔系数（按需求权重估算）：约{engel}%"
                 f"（食品与基本糊口需求占需求结构比重；>60%≈赤贫，50~60%≈温饱，"
                 f"40~50%≈小康，<40%≈宽裕）")
    literacy = uni.get("literacy_pct")
    if literacy is not None:
        L.append(f"- 识字率：约{literacy:.2f}%（该POP识字人口占比）")
    acc_status = uni.get("acceptance_status")
    if acc_status:
        L.append(f"- 社会地位：{ACCEPTANCE_NAMES.get(acc_status, acc_status)}")
    ig = uni.get("interest_group")
    if ig:
        ig_zh = IG_NAMES.get(ig.get("name"), ig.get("name")) if isinstance(ig, dict) else str(ig)
        ig_line = f"- 利益集团（政治倾向占比最高）：{ig_zh}"
        share_pct = ig.get("share_pct") if isinstance(ig, dict) else None
        if isinstance(share_pct, (int, float)):
            ig_line += f"（占该群体政治倾向约{share_pct:.1f}%）"
        L.append(ig_line)
    job_sat = uni.get("job_satisfaction")
    if job_sat is not None:
        mood = "满意" if job_sat > 0 else ("不满" if job_sat < 0 else "一般")
        L.append(f"- 职业满意度：{mood}（{job_sat:+.2f}；{JOB_SATISFACTION_GUIDE}）")
    L.extend(_render_vital_stats(uni))
    dr = uni.get("dependent_ratio")
    workforce = uni.get("workforce")
    dependents = uni.get("dependents")
    pop_total = (workforce or 0) + (dependents or 0)
    if dr is not None:
        L.append(f"- 该POP人口构成：共约{pop_total}人（劳动力{workforce}人，"
                 f"受抚养人口{dependents}人，受抚养比例约{dr * 100:.1f}%）"
                 f"——以下收支为该POP全体居民合计，采访家庭为其代表")
    income = uni.get("income")
    expense = uni.get("expense")
    if income is not None and expense is not None:
        parts = uni.get("income_parts") or []
        inc_line = f"- 每周收入(该POP合计)：约{income}英镑"
        if parts:
            inc_line += "（" + "、".join(parts) + "）"
        L.append(inc_line)
        exp_parts = uni.get("expense_parts") or []
        if exp_parts:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑（" + "、".join(exp_parts) + "）")
        else:
            L.append(f"- 每周支出(该POP合计)：约{expense}英镑")
        L.append(f"- 收支结余：约{income - expense:+.2f}英镑/周"
                 f"（人均约{income / pop_total:.4f}镑收入 / {expense / pop_total:.4f}镑支出，按周计）"
                 if pop_total else f"- 收支结余：约{income - expense:+.2f}英镑/周")
    L.extend(_render_pop_politics(uni))
    fs = uni.get("food_security")
    if fs:
        L.append(f"- 粮食安全：{food_security_zh(fs)}")
    return "\n".join(L)


def _clean_pop_name(name):
    """清理旧存档里的本地化格式/tooltip 残留, 返回可用的显示名。"""
    if not isinstance(name, str):
        return ""
    name = strip_loc_formatting(name)
    name = re.sub(r"\x15.*?\x15", "", name)
    name = re.sub(r"tooltip:[^\s\x15]+", "", name)
    name = name.strip(" \t\r\n!?。，,、")
    if not re.search(r"[A-Za-z0-9_\u4e00-\u9fff]", name):
        return ""
    return name


def _top_culture_name(cs):
    """取第一大族：优先按 count 降序, 其次按 rank（兼容 str/int 与旧存档杂数据）。"""
    items = []
    for c in cs or []:
        if not isinstance(c, dict):
            continue
        nm = _clean_pop_name(c.get("name"))
        if nm:
            items.append((nm, c))
    if not items:
        return "—"

    def key(pair):
        nm, c = pair
        cnt = c.get("count")
        if isinstance(cnt, (int, float)):
            return (0, -cnt, nm)
        rank = c.get("rank")
        try:
            r = int(str(rank)) if rank not in (None, "") else 99
        except (TypeError, ValueError):
            r = 99
        return (1, r, nm)

    return sorted(items, key=key)[0][0]


def _top_religion_name(rs):
    """取第一大教：优先按 count 降序, 其次按 share 权重(majority>large>notable>minor)。"""
    items = []
    for r in rs or []:
        if not isinstance(r, dict):
            continue
        nm = _clean_pop_name(r.get("name"))
        if nm:
            items.append((nm, r))
    if not items:
        return "—"
    weight = {"majority": 3, "large": 2, "notable": 1, "minor": 0}

    def key(pair):
        nm, r = pair
        cnt = r.get("count")
        if isinstance(cnt, (int, float)):
            return (0, -cnt, nm)
        return (1, -weight.get(r.get("share"), -1), nm)

    top = sorted(items, key=key)[0][0]
    return RELIGION_NAMES.get(top, top)


def render_history_table(data, history=None, include_flavor=True):
    L = ["历年发展对照："]
    if include_flavor:
        pf = _press_freedom_line(data)
        if pf:
            L.append(pf)
    L.append("| 年份 | GDP | 人口 | 生活水平 | 识字率 | 激进派% | 效忠派% | 第一大族 | 第一大教 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    rows = (history or []) + [data]
    for h in rows:
        cs = h.get("pop_cultures") or h.get("cultures") or []
        rs = h.get("pop_religions") or h.get("religions") or []
        topc = _top_culture_name(cs)
        top_r = _top_religion_name(rs)
        rad = h.get("radicals_pct")
        loy = h.get("loyalists_pct")
        rad_s = f"{rad}%" if isinstance(rad, (int, float)) else '—'
        loy_s = f"{loy}%" if isinstance(loy, (int, float)) else '—'
        L.append(f"| {h.get('year', '?')} | {h.get('gdp', '?')} | {h.get('pop', '?')} | {h.get('sol', '?')} | "
                 f"{h.get('literacy', '?')} | {rad_s} | {loy_s} | {topc} | {top_r} |")
    return "\n".join(L)

def render_ads(data, history=None):
    """广告板块：优先用“本年新研发科技”（与上一年存档对比得出）；无新增则随机抽取已研发科技。

    广告不限于商品：工艺、铺面可作货品告白，制度/思潮类科技可作文学沙龙、
    社科研讨会、新政晓谕、学堂启事等非商品形式。
    """
    techs = data.get("techs") or []
    if not techs:
        return "(无需数据，纯趣味创作)"
    new_techs = []
    if history:
        prev = max(history, key=lambda h: h.get("year") or 0)
        prev_techs = prev.get("techs")
        if prev_techs:
            prev_set = set(prev_techs)
            new_techs = [t for t in techs if t not in prev_set]
    source = new_techs or techs
    picked = random.sample(source, min(3, len(source)))
    if new_techs:
        note = "本年新研发（与上一年存档对比得出）"
    else:
        note = "随机取自本国已研发科技（本年无新增或缺少上年存档）"
    return (f"- 广告创作素材：{note}。必须围绕其创作，可作“最新发明”“时代进步”等宣传：\n"
            f"  {'、'.join(picked)}\n"
            "- 形式不限：商品/工艺/铺面可作货品告白；制度、思潮类科技"
            "（如民主、中央集权、理性主义、学术界）可作文学沙龙、社科研讨会、"
            "新政晓谕、学堂启事等非商品形式；至少一条广告须直接体现所选科技。")

def render_section_facts(key, data, history=None):
    if key == "headline":
        return render_overview(data, history)
    if key == "war":
        return render_war(data, history)
    if key == "diplo":
        return render_diplo(data)
    if key == "econ":
        return render_econ(data, history)
    if key == "politics":
        return render_politics(data, history)
    if key == "society":
        return render_society(data)
    if key == "family":
        return render_family(data)
    if key == "peer":
        return render_peer(data)
    if key == "unemployed":
        return render_unemployed(data)
    if key == "comment":
        # overview 已含新闻自由风味行，历史表不再重复输出
        return render_overview(data, history) + "\n\n" + render_history_table(data, history, include_flavor=False)
    if key == "ads":
        return render_ads(data, history)
    return render_overview(data, history)

def build_masthead_messages(data, style=DEFAULT_STYLE):
    st = NEWSPAPER_STYLES.get(style, NEWSPAPER_STYLES[DEFAULT_STYLE])
    govt_zh = GOVT_NAMES.get(data.get("govt", ""), data.get("govt", "未知"))
    country = data.get("player", "未知")
    year = data.get("year", "?")
    # 若首都缺失, 提示模型据国名常识选用该国广为人知的都城名
    capital = data.get("capital", "")
    cap_note = capital if capital else "（数据缺失，请根据国名常识选用该国广为人知的都城名）"
    sys_msg = (
        f"你是这份{st['name']}报纸的总编辑。本期报纸的关键变量如下，抬头必须**原样保留**国名：\n"
        f"【国名】{country}\n"
        f"【都城】{cap_note}\n"
        f"【政体】{govt_zh}\n"
        f"【年份】{year}\n\n"
        f"{st['masthead']}\n\n"
        "请据此取报名并撰写抬头。要求：\n"
        "1. 国名**一字不改**地写入抬头（不得自创、不得替换）。\n"
        "2. 都城若缺失，请用该国广为人知的都城名。\n"
        f"3. 只输出 Markdown 抬头，格式：\n# 《报名》\n国名：{country}｜都城：{cap_note}｜政体：{govt_zh}｜年份：{year}"
    )
    user_msg = (
        f"本期报纸：【国名】={country}，【都城】={cap_note}，【政体】={govt_zh}，【年份】={year}。"
        "请据此撰写抬头（国名必须原样出现；都城若缺失，请根据常识补填该国广为人知的都城名）。"
    )
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]

def build_section_messages(key, data, cfg, history, masthead, style=None):
    style = style or cfg.get("newspaper_style", DEFAULT_STYLE)
    st = NEWSPAPER_STYLES.get(style, NEWSPAPER_STYLES[DEFAULT_STYLE])
    spec = next(s for s in SECTION_DEFS if s[0] == key)
    title = st["section_titles"].get(key, spec[1])
    country = data.get("player", "未知")
    capital = data.get("capital", "未知")
    req = spec[2]
    if key == "econ":
        econ_guide = st.get("econ_guide")
        if econ_guide:
            req = f"{req}\n{econ_guide}"
    elif key == "ads":
        ads_guide = st.get("ads_guide")
        if ads_guide:
            req = f"{req}\n{ads_guide}"
    parts = [st["voice"], FACT_GUIDE]
    if has_escalated_movement(data):
        parts.append(MOVEMENT_ESCALATION_GUIDE)
    num_guide = st.get("number_guide")
    if num_guide:
        parts.append(f"数字格式要求：{num_guide}")
    parts.append(f"本期报纸：【国名】={country}，【都城】={capital}。抬头如下，行文须与之呼应：\n{masthead}\n\n"
                 f"请撰写「{title}」板块。要求：{req}")
    sys_msg = "\n\n".join(parts)
    facts = render_section_facts(key, data, history)
    user_msg = f"以下是本期报纸关于「{title}」板块的相关数据（涉及国名、都城请用上述变量，不得改动）：\n{facts}\n\n请撰写该板块正文。"
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]

_MASTHEAD_ECHO_RE = re.compile(r"^#\s*《.+》\s*$")
_HEADER_INFO_RE = re.compile(r"^\*{0,2}国名：.+｜都城：.+｜政体：.+｜年份：\d{4}\*{0,2}\s*$")
_HEAD_RE = re.compile(r"^#{1,6}\s+")

def _normalize_section_text(text, title, use_separators=False, paper_name=None):
    """规范化板块正文的标题层级:
    - 剔除模型回显的报名(# 《报名》)与抬头信息行(**国名：...｜都城：...**), 避免正文重复报头;
    - 板块内的一级标题一律降为二级(保证 # 只留给报名);
    - 正文没有标题时补上规范的 ## 板块名。"""
    out = []
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if _MASTHEAD_ECHO_RE.match(s) or _HEADER_INFO_RE.match(s):
            continue
        if s.startswith("# "):
            s = "## " + s[2:]
        if paper_name and s.startswith("#"):
            s = re.sub(r"^(#{1,6})\s*《" + re.escape(paper_name) + r"》",
                       r"\1 ", s).strip()
        out.append(s)
    body = "\n".join(out).strip()
    if use_separators:
        body = _insert_thousand_separators(body)
    if not body:
        return f"## {title}\n\n(本板块生成失败)"
    first = next((ln for ln in body.split("\n") if ln.strip()), "")
    if not _HEAD_RE.match(first):
        return f"## {title}\n\n{body}"
    return body

def _insert_thousand_separators(text):
    """给阿拉伯数字串补千分位分隔符(提示词的兜底): 46077267 -> 46,077,267; 2186万 -> 2,186万。
    只处理纯整数串, 不碰小数/百分比/4位年份(如 1861), 已带分隔符的也不重复处理。"""
    text = re.sub(r"(?<![\d,])(\d{5,})(?![\d,])",
                  lambda m: format(int(m.group(1)), ","), text)
    text = re.sub(r"(?<![\d,])(\d{4})(?=万)",
                  lambda m: format(int(m.group(1)), ","), text)
    return text

def generate_newspaper(data, cfg, history=None):
    """分板块生成: 先定抬头, 再并发调用各板块, 最后按序组合。"""
    style = cfg.get("newspaper_style", DEFAULT_STYLE)
    st = NEWSPAPER_STYLES.get(style, NEWSPAPER_STYLES[DEFAULT_STYLE])
    use_sep = st.get("number_format") == "arabic"
    masthead = call_deepseek(build_masthead_messages(data, style), cfg).strip()
    m = re.search(r"《([^《》]+)》", masthead)
    paper_name = m.group(1) if m else None
    section_cfg = dict(cfg)
    section_cfg["max_tokens"] = min(cfg.get("max_tokens", 8000), 4000)

    def _gen_section(key, title):
        try:
            msg = build_section_messages(key, data, cfg, history, masthead)
            text = call_deepseek(msg, section_cfg).strip()
            return _normalize_section_text(text, title, use_separators=use_sep,
                                           paper_name=paper_name)
        except Exception as e:
            log(f"板块「{title}」生成失败: {e}")
            return f"## {title}\n\n(本板块生成失败)"

    parts = [masthead]
    # 条件板块: 失业民生仅在随机州失业率>5%且有样本数据时发送
    sections = [(k, st["section_titles"].get(k, t)) for k, t, _d in SECTION_DEFS
                if not (k == "unemployed" and not data.get("unemployed_interview"))]
    # 各板块彼此独立, 并发请求 (DeepSeek 并发充足时大幅提速)
    with ThreadPoolExecutor(max_workers=len(SECTION_DEFS)) as ex:
        futures = [ex.submit(_gen_section, key, title)
                   for key, title in sections]
        for f in futures:
            try:
                parts.append(f.result())
            except Exception as e:
                log(f"板块结果获取失败: {e}")
                parts.append("## 未命名板块\n\n(本板块生成失败)")
    return "\n\n---\n\n".join(parts)

# ---------------------------------------------------------------------------
# DeepSeek API
# ---------------------------------------------------------------------------

def call_deepseek(messages, cfg, retries=3):
    _log_prompt(messages)
    url = cfg["deepseek_base_url"]
    headers = {
        "Authorization": f"Bearer {cfg['deepseek_api_key']}",
        "Content-Type": "application/json",
    }
    max_tokens = cfg.get("max_tokens", 2500)
    last_err = None
    for i in range(retries):
        payload = {
            "model": cfg.get("deepseek_model", "deepseek-chat"),
            "messages": messages,
            "temperature": cfg.get("temperature", 1.0),
            "max_tokens": max_tokens,
            "thinking": {"type": "disabled"},   # 关闭思考模式, 加快生成并避免 reasoning 占满预算
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason")
            if content.strip():
                return content
            if finish == "length":
                # 推理模型可能把预算全花在 reasoning 上, 翻倍输出预算重试
                max_tokens = min(max_tokens * 2, 16000)
                log(f"输出因 max_tokens 不足被截断(推理模型占满预算), 提高预算至 {max_tokens} 重试")
                continue
            if finish == "stop":
                return content  # 极罕见: 模型明确返回空
            last_err = Exception(f"模型返回空内容 (finish_reason={finish})")
        except Exception as e:
            last_err = e
            log(f"DeepSeek 调用失败 (第{i + 1}/{retries}次): {e}")
        if i < retries - 1:
            time.sleep(3 * (i + 1))
    raise last_err if last_err else Exception("生成失败")

# ---------------------------------------------------------------------------
# 块处理: 保存原始数据 + 生成报纸
# ---------------------------------------------------------------------------

def on_block_complete(data, cfg, force=False):
    year = data.get("year")
    if not year:
        log("跳过: 无法从数据块解析年份。")
        return

    folder = resolve_session_folder(data, cfg)
    data["output_dir"] = folder
    base_dir = os.path.join(cfg["journal_dir"], folder)
    raw_dir = os.path.join(base_dir, "data")
    try:
        os.makedirs(raw_dir, exist_ok=True)
    except Exception:
        pass
    raw_path = os.path.join(raw_dir, f"raw_{year}.json")
    try:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存原始数据失败: {e}")

    md_path = os.path.join(base_dir, f"报纸_{year}.md")
    if os.path.exists(md_path) and not force:
        log(f"[{year}年] 报纸已存在, 跳过 (加 --force 或使用 regen 重新生成): {md_path}")
        return

    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key or "sk-" not in key or "这里" in key or "填写" in key:
        log(f"[{year}年] 未配置 DeepSeek API Key, 已跳过生成。"
            f"请在 D:/Journal/config.json 填写 deepseek_api_key 后用 regen {year} 重试。")
        return

    log(f"[{year}年] 数据块完整, 开始分板块调用 DeepSeek 生成报纸...")
    try:
        history = load_history(data, cfg)
        text = generate_newspaper(data, cfg, history)
    except Exception as e:
        log(f"[{year}年] 生成失败: {e} (原始数据已保存到 {raw_path}, 可用 regen 重试)")
        return

    header = f"<!-- 数据来源: 维多利亚3 报纸Mod | 报告日期: {data.get('date', '未知')} | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(header + text.rstrip() + "\n")
        log(f"[{year}年] 报纸已生成: {md_path}")
    except Exception as e:
        log(f"[{year}年] 写入 md 失败: {e}")

def handle_line(ln, builder, cfg, force=False):
    ln = ln.rstrip("\r\n")
    if "|JOURNAL|" not in ln:
        return
    # 跳过插值失败的错误行: 它们会回显未插值的原始字符串, 不是真实数据
    if "Data error" in ln or "pdx_data_localize" in ln:
        return
    parsed = parse_journal_line(ln)
    if not parsed:
        return
    kind, raw_parts, fields, before = parsed
    result = builder.feed(kind, raw_parts, fields, before)
    if result is not None:
        on_block_complete(result, cfg, force)

# ---------------------------------------------------------------------------
# 日志监控 (tail)
# ---------------------------------------------------------------------------

def read_new_bytes(path, last_pos):
    """读取自 last_pos 以来的新字节, 处理文件被截断/轮转的情况。"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size < last_pos:          # 文件被清空/轮转
            last_pos = 0
        f.seek(last_pos)
        chunk = f.read()
        last_pos = f.tell()
    return last_pos, chunk.decode("utf-8", errors="replace")

def cmd_watch(cfg, force=False):
    SESSION["folder"] = None   # 新的一次 watch 运行 = 新的存档期, 新建/复用国家文件夹
    path = cfg["game_log_path"]
    if not os.path.exists(path):
        log(f"找不到日志文件: {path}")
        log("请确认: 1) 已启动维多利亚3并游玩过一段时间; 2) mod 已在启动器 playset 中启用; 3) config.json 中 game_log_path 正确。")
        return 1
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        last_pos = f.tell()
    pending = ""
    builder = BlockBuilder()
    log(f"开始监控: {path}")
    log(f"每 {cfg['poll_interval_seconds']} 秒检查一次, 按 Ctrl+C 停止。")
    while True:
        try:
            last_pos, text = read_new_bytes(path, last_pos)
            if text:
                pending += text
                lines = pending.split("\n")
                pending = lines.pop()          # 最后一个可能是不完整行
                for ln in lines:
                    handle_line(ln, builder, cfg, force)
            time.sleep(cfg["poll_interval_seconds"])
        except KeyboardInterrupt:
            log("已停止监控。")
            return 0
        except Exception as e:
            log(f"监控出错: {e}")
            time.sleep(5)

def cmd_once(cfg, logfile=None, force=False):
    SESSION["folder"] = None   # 新的一次 once 运行 = 新的存档期
    path = logfile or cfg["game_log_path"]
    if not os.path.exists(path):
        log(f"找不到文件: {path}")
        return 1
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    builder = BlockBuilder()
    count = 0
    for ln in text.split("\n"):
        if "|JOURNAL|" in ln:
            count += 1
        handle_line(ln, builder, cfg, force)
    log(f"扫描完成, 共处理 {count} 行 |JOURNAL| 标记。")

def cmd_regen(cfg, year, player=None):
    matches = find_raw_files(year, cfg["journal_dir"])
    if not matches:
        log(f"没有 {year} 年的原始数据。先用 watch 或 once 捕获数据, 或在游戏中推进到该年份。")
        return 1
    SESSION["folder"] = None
    for raw_path in matches:
        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if player:
            data["player"] = player
            data.pop("output_dir", None)   # 按新国名重新决定文件夹
        on_block_complete(data, cfg, force=True)
    return 0

def cmd_test_llm(cfg):
    check_api_key(cfg)
    log("正在测试 DeepSeek API...")
    try:
        out = call_deepseek([{"role": "user", "content": "请只回复\"连接成功\"四个字。"}], cfg, retries=1)
        log(f"API 连接成功, 模型回复: {out.strip()[:100]}")
    except Exception as e:
        log(f"API 连接失败: {e}")
        return 1
    return 0

def cmd_check(cfg):
    path = cfg["game_log_path"]
    print(f"游戏日志路径: {path}")
    if not os.path.exists(path):
        print("  [缺失] 日志文件不存在。请先启动游戏游玩一段时间。")
    else:
        size = os.path.getsize(path)
        print(f"  [存在] 大小 {size / 1024:.1f} KB")
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8", errors="replace")
            tail_text = ""
            f.seek(0, os.SEEK_END)
            n = min(f.tell(), 4096)
            f.seek(-n, os.SEEK_END)
            tail_text = f.read().decode("utf-8", errors="replace")
        if "|JOURNAL|" in tail_text or "|JOURNAL|" in head:
            print("  [成功] 日志中已出现 |JOURNAL| 标记 → mod 数据正常写入!")
        else:
            print("  [警告] 日志中暂无 |JOURNAL| 标记。可能原因:")
            print("          1. mod 未在启动器 playset 中启用;")
            print("          2. 年份尚未滚动(需等到每年 1 月 1 日);")
            print("          3. 游戏版本与 supported_version 不匹配。")
            print("          debug_log 在正常游玩下即可写入(已验证), 无需 -debug_mode。")
    style = cfg.get("newspaper_style", DEFAULT_STYLE)
    print(f"报纸输出目录: {cfg['journal_dir']}  (按国名分文件夹, 如 output/<国名>/报纸_<年份>.md)")
    print(f"报纸风格: {style} - {NEWSPAPER_STYLES.get(style, NEWSPAPER_STYLES[DEFAULT_STYLE])['name']}")
    print(f"API Key: {('已配置 ' + cfg['deepseek_api_key'][:6] + '...') if cfg.get('deepseek_api_key', '').startswith('sk-') else '未配置'}")
    return 0

def cmd_config(cfg):
    for k, v in cfg.items():
        if k == "deepseek_api_key" and v:
            v = v[:6] + "..." + v[-4:]
        print(f"{k}: {v}")

# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="维多利亚3 年度报纸生成器 (V3 Journal)")
    parser.add_argument("command", nargs="?", default="watch",
                        choices=["watch", "once", "regen", "test-llm", "check", "config"])
    parser.add_argument("arg", nargs="?", help="once 的日志路径, 或 regen 的年份")
    parser.add_argument("--force", action="store_true", help="发现新数据时强制重新生成已存在的报纸")
    parser.add_argument("--player", default=None, help="regen 时覆盖玩家国家名(旧数据玩家名为未知时用)")
    args = parser.parse_args()

    cfg = load_config()

    if args.command == "watch":
        return cmd_watch(cfg, force=args.force)
    if args.command == "once":
        return cmd_once(cfg, logfile=args.arg, force=args.force)
    if args.command == "regen":
        if not args.arg or not args.arg.isdigit():
            print("用法: python journal.py regen <年份> [--player 国家名], 例如 python journal.py regen 1837 --player 法兰西")
            return 1
        return cmd_regen(cfg, int(args.arg), player=args.player)
    if args.command == "test-llm":
        return cmd_test_llm(cfg)
    if args.command == "check":
        return cmd_check(cfg)
    if args.command == "config":
        cmd_config(cfg)
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
