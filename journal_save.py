#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维多利亚3 存档直读分支 (journal_save.py)
===========================================
不依赖 debug_log, 直接用 Rakaly melter 熔化 .v3 存档, 提取**精确**数据
(GDP / 生活水平 / 识字率 / 人口 / 法律 / 统治者 / 首都), 并复用
journal.py 的分板块报纸生成管线。

依赖:
  - rakaly.exe  (https://github.com/rakaly/cli/releases, 解压到
                D:/Journal/tools/rakaly.exe)
  - python -m pip install ijson

用法:
  python journal_save.py check             检测存档格式与 rakaly 是否就绪
  python journal_save.py melt              熔化最新存档 → tools/melt.json (缓存)
  python journal_save.py sniff             从熔化结果提取玩家国家精确数据
  python journal_save.py newspaper <年份>  用存档数据生成一份报纸 (复用 journal.py)
  python journal_save.py watch             监控 autosave, 每年生成报纸
  python journal_save.py continue          续传: 沿用该国家最新文件夹(海地→海地2),
                                           停止后重启不再新建文件夹; 缺当年报纸则先补生成
"""
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
RAKALY = os.path.join(TOOLS_DIR, "rakaly.exe")
MELT_CACHE = os.path.join(TOOLS_DIR, "melt.json")
SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents",
                        "Paradox Interactive", "Victoria 3", "save games")

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _skip_string(data, j):
    """跳过 JSON 字符串, 返回字符串结束后的位置。"""
    j += 1
    while j < len(data):
        b = data[j]
        if b == 0x5c:      # backslash
            j += 2
            continue
        if b == 0x22:      # double quote
            return j + 1
        j += 1
    return j

def extract_json_object(data, open_brace_idx):
    """从 '{' 起匹配完整 JSON 对象, 返回 (bytes, end_idx)。"""
    depth = 0
    j = open_brace_idx
    while j < len(data):
        b = data[j]
        if b == 0x22:
            j = _skip_string(data, j)
            continue
        if b == 0x7b:      # {
            depth += 1
        elif b == 0x7d:    # }
            depth -= 1
            if depth == 0:
                return data[open_brace_idx:j + 1], j + 1
        j += 1
    return None, len(data)

def _object_end(data, brace_idx):
    """只计算 '{' 起完整 JSON 对象的结束位置 (不复制数据)。"""
    depth = 0
    j = brace_idx
    while j < len(data):
        b = data[j]
        if b == 0x22:
            j = _skip_string(data, j)
            continue
        if b == 0x7b:
            depth += 1
        elif b == 0x7d:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(data)

def find_latest_v3():
    if not os.path.isdir(SAVE_DIR):
        return None
    v3s = [os.path.join(SAVE_DIR, f) for f in os.listdir(SAVE_DIR) if f.endswith(".v3")]
    return max(v3s, key=os.path.getmtime) if v3s else None

# ---------------------------------------------------------------------------
# Rakaly 熔化
# ---------------------------------------------------------------------------

def melt_with_rakaly(v3_path, force=False):
    """用 rakaly 把二进制存档熔化为 JSON, 缓存到 MELT_CACHE。"""
    if not os.path.exists(RAKALY):
        return None, f"未找到 {RAKALY}, 请下载 rakaly-cli 并解压"
    if os.path.exists(MELT_CACHE) and not force:
        return MELT_CACHE, None
    print(f"熔化存档: {v3_path}")
    with open(MELT_CACHE, "wb") as out:
        try:
            proc = subprocess.run([RAKALY, "json", v3_path], stdout=out,
                                  stderr=subprocess.PIPE, timeout=600)
        except FileNotFoundError:
            return None, f"无法执行 {RAKALY}"
    if proc.returncode != 0:
        return None, proc.stderr.decode("utf-8", "replace")[:300]
    print(f"熔化完成: {MELT_CACHE} ({os.path.getsize(MELT_CACHE)/1e6:.0f} MB)")
    return MELT_CACHE, None

# ---------------------------------------------------------------------------
# 国家名映射 (游戏本地化 → TAG)
# ---------------------------------------------------------------------------

GAME_LOCALIZATION = r"F:\Game\steamapps\common\Victoria 3\game\localization\simp_chinese"
WORKSHOP_DIR = r"F:\Game\steamapps\workshop\content\529340"
GOVERNMENT_TYPES_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\government_types"
CHARACTER_TEMPLATES_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\character_templates"

_NAME_CACHE = None
_LOC_ALL = None
_LOC_PLACEHOLDER_RE = re.compile(r"\$[A-Za-z_][A-Za-z_0-9]*\$")

def _loc_dirs():
    """本地化目录列表: 游戏原版 + 当前 playset 已启用的 mod (mod 覆盖原版)。

    只读取 content_load.json 里的 enabledMods, 避免把已安装但未启用的 mod
    (例如 Divergences CN) 的本地化混入, 导致国名与游戏内不一致。
    """
    dirs = [GAME_LOCALIZATION]
    enabled = _enabled_mod_dirs()
    if enabled:
        for base in enabled:
            p = os.path.join(base, "localization", "simp_chinese")
            if os.path.isdir(p):
                dirs.append(p)
        return dirs
    # 读不到启用的 playset 时退回旧逻辑: 扫描全部已安装 mod 目录
    for base in (WORKSHOP_DIR,
                 os.path.join(os.path.expanduser("~"), "Documents",
                              "Paradox Interactive", "Victoria 3", "mod")):
        if not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base)):
            p = os.path.join(base, d, "localization", "simp_chinese")
            if os.path.isdir(p):
                dirs.append(p)
    return dirs


def _enabled_mod_dirs():
    """读取启动器当前 playset 的 enabledMods → 已启用 mod 根目录列表。"""
    doc_root = os.path.join(os.path.expanduser("~"), "Documents",
                            "Paradox Interactive", "Victoria 3")
    content = os.path.join(doc_root, "content_load.json")
    dirs = []
    try:
        with open(content, encoding="utf-8") as fp:
            obj = json.load(fp)
        for mod in (obj.get("enabledMods") or []):
            p = mod.get("path") if isinstance(mod, dict) else None
            if not p:
                continue
            p = os.path.normpath(p)
            if not os.path.isabs(p):
                p = os.path.join(doc_root, p)
            dirs.append(p)
    except Exception:
        pass
    return dirs

def _load_loc_all():
    """加载游戏+全部 mod 的 simp_chinese 本地化 → {key: 中文名}。
    递归含 replace/ 子目录, 后加载的 mod 覆盖原版同名 key。"""
    global _LOC_ALL
    if _LOC_ALL is not None:
        return _LOC_ALL
    loc = {}
    for base in _loc_dirs():
        if not os.path.isdir(base):
            continue
        for root, _sub, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".yml"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8-sig",
                              errors="replace") as fp:
                        for line in fp:
                            m = re.match(r"\s*([A-Za-z_][A-Za-z_0-9]*)(?::\d+)?:\s*\"([^\"]+)\"\s*(?:#.*)?$",
                                         line)
                            if m:
                                loc[m.group(1)] = m.group(2).strip()
                except Exception:
                    continue
    _LOC_ALL = loc
    return loc

def _clean_loc_name(value, loc=None):
    """清理本地化名: 解析 $KEY$ 引用并去掉运行时占位符($NAME$/$ADJECTIVE$ 等)。
    例: '卡洛斯派$NAME$' → '卡洛斯派'; '$generic_revolt_unions$' → '无产阶级起义'。"""
    if not isinstance(value, str) or "$" not in value:
        return value
    loc = _load_loc_all() if loc is None else loc
    v = value.strip()
    # 整串是 $key$ 引用(游戏内未解析的动态名): 反查本地化后再清理
    if v.startswith("$") and v.endswith("$") and _LOC_PLACEHOLDER_RE.fullmatch(v):
        v = loc.get(v[1:-1], v)
    v = _LOC_PLACEHOLDER_RE.sub("", v)
    v = re.sub(r"\$+", "", v)
    return v.strip()

def load_country_names():
    """从本地化(含 mod 覆盖)加载 {TAG: 中文名} 映射。"""
    global _NAME_CACHE
    if _NAME_CACHE is not None:
        return _NAME_CACHE
    names = {}
    for k, v in _load_loc_all().items():
        if re.fullmatch(r"[A-Z]{3}", k) and len(v) <= 12:
            names[k] = _clean_loc_name(v)
    _NAME_CACHE = names
    return names

def load_current_country_names(data, index=None):
    """加载 {TAG: 当前中文名}: 默认本地化名 + 存档中 dynamic_name 覆盖。
    存档国家对象带 dynamic_name.dynamic_country_name (如 dyn_c_great_qing),
    本地化映射到当前名 (如 大清), 覆盖默认名 (如 中华)。"""
    names = load_country_names()
    if index is None:
        index, _, _ = _build_indexes(data)
    loc = _load_loc_all()
    for entry in index.values():
        tag = entry.get("definition")
        dyn_key = entry.get("dyn_name")
        if tag and dyn_key and loc.get(dyn_key):
            names[tag] = _clean_loc_name(loc[dyn_key], loc)
    return names

# ---------------------------------------------------------------------------
# 玩家国家提取
# ---------------------------------------------------------------------------

def _first_player_name(raw):
    """从熔化的 JSON 开头提取 meta_data.name。"""
    m = re.search(rb'"name":"([^"]+)"', raw[:200000])
    return m.group(1).decode("utf-8", "replace") if m else None

def _autosave_player(v3):
    """从存档信封头读玩家名(快速, 不熔化)。"""
    try:
        with open(v3, "rb") as fp:
            head = fp.read(400000)
        m = re.search(rb'"name":"([^"]+)"', head)
        return m.group(1).decode("utf-8", "replace") if m else None
    except Exception:
        return None

def load_melted(auto_melt=True):
    """读取熔化的 JSON; 若 autosave 玩家与缓存不一致(新开局/换国), 自动重新熔化。"""
    v3 = find_latest_v3()
    if v3 and os.path.exists(MELT_CACHE):
        try:
            with open(MELT_CACHE, "rb") as fp:
                cache_head = fp.read(200000)
            cache_player = _first_player_name(cache_head)
            save_player = _autosave_player(v3)
            if (save_player and cache_player and save_player != cache_player
                    and auto_melt):
                print(f"[存档] 检测到玩家变化 {cache_player} -> {save_player}, 重新熔化...")
                melt_with_rakaly(v3, force=True)
        except Exception:
            pass
    if not os.path.exists(MELT_CACHE):
        return None, "尚未熔化存档, 请先运行 melt"
    try:
        with open(MELT_CACHE, "rb") as fp:
            return fp.read(), None
    except Exception as e:
        return None, f"读取失败: {e}"

def _parse_meta(data):
    md_start = data.find(b'"meta_data"')
    if md_start < 0:
        return {}
    ob = data.find(b'{', md_start)
    raw, _ = extract_json_object(data, ob)
    try:
        return json.loads(raw)
    except Exception:
        return {}

def _find_country_by_definition(data, tag):
    """在 country_manager.database 中按 definition 找国家对象, 返回 (obj, id)。
    用精确 '"数字":{' 遍历 (rfind 回溯在数据库以 '"0":"none"' 开头/嵌套对象时不可靠)。"""
    cm = data.find(b'"country_manager"')
    if cm < 0:
        return None, None
    cm_brace = data.find(b'{', cm)
    cm_end = _object_end(data, cm_brace)
    db = data.find(b'"database"', cm)
    j = data.find(b'{', db)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, cm_end - 1)
        if not m:
            return None, None
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return None, None
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("definition") == tag:
            return obj, int(m.group(1))
        j = end

def _find_country_by_dynamic_name(data, dyn_key):
    """在 country_manager.database 中按 dynamic_name.dynamic_country_name 找国家对象。
    用于 meta.name 是 mod 动态名(如 dyn_c_papal_states → "教宗国")的情况。"""
    cm = data.find(b'"country_manager"')
    if cm < 0:
        return None, None
    cm_brace = data.find(b'{', cm)
    cm_end = _object_end(data, cm_brace)
    db = data.find(b'"database"', cm)
    j = data.find(b'{', db)
    pat = ('"' + dyn_key + '"').encode()
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, cm_end - 1)
        if not m:
            return None, None
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return None, None
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict):
            dn = obj.get("dynamic_name") or {}
            if dn.get("dynamic_country_name") == dyn_key:
                return obj, int(m.group(1))
        j = end

def _find_player_by_flag(data):
    """存档中找带 v3journal_player 标记的国家对象 (v3journal_player_flag mod 开局打标记)。
    标记存为国家对象 variables.data 里的 flag, 100% 可靠, 不依赖国名。"""
    cm = data.find(b'"country_manager"')
    if cm < 0:
        return None, None
    cm_brace = data.find(b'{', cm)
    cm_end = _object_end(data, cm_brace)
    db = data.find(b'"database"', cm)
    j = data.find(b'{', db)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, cm_end - 1)
        if not m:
            return None, None
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return None, None
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("v3journal_player"):
            return obj, int(m.group(1))
        vars_data = (obj.get("variables") or {}).get("data") or []
        if any(isinstance(v, dict) and v.get("flag") == "v3journal_player" for v in vars_data):
            return obj, int(m.group(1))
        j = end

def find_player_country(data):
    """定位玩家国家对象, 三级识别:
    0. 存档国家对象带 v3journal_player 标记 (v3journal_player_flag mod) — 100% 可靠
    1. meta_data.name 反查本地化 → TAG → definition 匹配 (原版国家名)
    2. meta_data.name 反查本地化 → 动态名 key → dynamic_name 匹配 (mod/动态命名改名, 如 dyn_c_papal_states)
    匹配失败不再猜 is_main_tag (会误认成英国等首个大国), 返回 None 让上层明确报错。"""
    md_obj = _parse_meta(data)
    player_name = md_obj.get("name", "")
    country, country_id = _find_player_by_flag(data)
    if country:
        return country, md_obj, None, country_id
    loc = _load_loc_all()
    # 收集 meta.name 对应的所有 key (可能多个: 原版名 + 动态名)
    keys = [k for k, v in loc.items() if v == player_name]
    tag = None
    for key in keys:
        if re.fullmatch(r"[A-Z]{3}", key):
            tag = key
            country, country_id = _find_country_by_definition(data, key)
        elif key.startswith("dyn_"):
            country, country_id = _find_country_by_dynamic_name(data, key)
        if country:
            return country, md_obj, tag, country_id
    if keys:
        print(f"(警告: 本地化匹配 {player_name!r} 的 key {keys} 在存档中未找到对应国家)")
    else:
        print(f"(警告: 无法用本地化匹配玩家名 {player_name!r})")
    return None, md_obj, tag, None

def snapshot_from_country(country, meta):
    """从玩家国家对象提取报纸所需精确数据。"""
    snap = {}
    if meta:
        snap["date"] = meta.get("game_date", "")
        m = re.match(r"(\d{4})", str(meta.get("game_date", "")))
        snap["year"] = int(m.group(1)) if m else None
        snap["player"] = meta.get("name", "未知")
    if not country:
        return snap
    snap["govt"] = country.get("government", "other")
    snap["ruler_id"] = country.get("ruler")
    snap["capital_id"] = country.get("capital")
    snap["religion"] = country.get("religion")
    snap["country_type"] = country.get("country_type")
    # 精确数值: gdp/prestige/literacy/avgsoltrend 是时序, 取最后值
    for key, field in [("gdp", "gdp"), ("prestige", "prestige"),
                       ("literacy", "literacy"), ("sol", "avgsoltrend")]:
        series = country.get(field)
        if isinstance(series, dict):
            chans = series.get("channels", {})
            if chans:
                last = None
                for ch in chans.values():
                    vals = ch.get("values") or []
                    if vals:
                        last = vals[-1]
                if last is not None:
                    # 注意：这里全部用回 snap[field]
                    if key == "literacy":
                        snap[field] = f"{round(last * 100, 2)}%" if isinstance(last, (int, float)) else last
                    elif key == "gdp" or key == "prestige":
                        # GDP 和 威望：舍去小数
                        snap[field] = int(round(last)) if isinstance(last, (int, float)) else last
                    else:
                        # 其他（包括 avgsoltrend / sol）：保留两位小数
                        snap[field] = round(last, 2) if isinstance(last, (int, float)) else last
    # 人口
    ps = country.get("pop_statistics") or {}
    raw_pop = sum(v for k, v in ps.items()
                  if k.startswith("population_") and "workforce" not in k and
                  "radicals" not in k and "participants" not in k and
                  "eligible" not in k and "wealth" not in k and
                  "by_strata" not in k and "accepted" not in k
                  and isinstance(v, (int, float)))
                  
    # 注意：这里用回 snap["total_population"]，只强制转为整数
    snap["total_population"] = int(round(raw_pop))
    
    snap["population_radicals"] = ps.get("population_radicals")
    snap["population_loyalists"] = ps.get("population_loyalists")
    snap["population_participants"] = ps.get("population_political_participants")
    # cultures 是 culture id 列表 → 转成 journal 兼容格式 (用本地化转中文名)
    raw_cultures = country.get("cultures") or []
    if isinstance(raw_cultures, list) and raw_cultures and isinstance(raw_cultures[0], int):
        snap["cultures"] = [{"rank": str(i + 1),
                             "key": culture_id_to_key(c),
                             "name": culture_id_to_name(c),
                             "share": None} for i, c in enumerate(raw_cultures)]
    else:
        snap["cultures"] = raw_cultures
    return snap

def query_laws_by_player(data, country_id):
    """便捷包装。"""
    return query_laws(data, country_id)

CULTURE_FILES = r"F:\Game\steamapps\common\Victoria 3\game\common\cultures"
# 本土定义: 州域 → 本土文化, 见 common/history/states/00_states.txt 的 add_homeland
HOMELAND_STATES_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\history\states"
# 商品定义: 用于消费权重聚合与市价对比
GOODS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\goods"
_CULTURE_MAP = None
_HOMELAND_CACHE = None
_GOODS_CACHE = None

# 需求条目顺序 (与 common/pop_needs/00_pop_needs.txt 及存档 pop_needs 完全一致)
_NEED_KEYS = (
    "popneed_simple_clothing", "popneed_crude_items", "popneed_basic_food",
    "popneed_heating", "popneed_household_items", "popneed_standard_clothing",
    "popneed_services", "popneed_intoxicants", "popneed_luxury_drinks",
    "popneed_free_movement", "popneed_communication", "popneed_luxury_food",
    "popneed_luxury_items", "popneed_leisure", "popneed_stimulants",
)
# 恩格尔系数估算: 计入"糊口类"的需求条目下标 (基础食品=2, 加热供暖=3, 简朴衣物=0)
_ENGEL_NEED_INDEXES = (2, 3, 0)
# SoL 档位 → 该档位已消费的需求条目数 (近似, 只用于把奢侈品挡在穷人画像外)
_NEEDS_BY_SOL = ((10, 4), (20, 8), (999, 15))
# hub 名顺序: 存档 naming_data.localized_hub_names 固定为 city/port/farm/mine/wood
HUB_ORDER = ("city", "port", "farm", "mine", "wood")

def build_culture_map():
    """建立 culture id → 中文名 映射。
    wiki 确认: culture id 从 0 开始, north_german=0, 按 /common/cultures/ 文件顺序递增。
    id → key: 解析 culture 文件行首 'key = {'。
    key → 中文: 从 simp_chinese 本地化 'key: "中文名"'。
    """
    global _CULTURE_MAP
    if _CULTURE_MAP is not None:
        return _CULTURE_MAP
    keys = []
    try:
        import glob
        for fn in sorted(glob.glob(os.path.join(CULTURE_FILES, "*.txt"))):
            with open(fn, encoding="utf-8-sig") as fp:
                for m in re.finditer(r"^([a-z_]+)\s*=\s*\{", fp.read(), re.M):
                    k = m.group(1)
                    if k not in keys:
                        keys.append(k)
    except Exception:
        pass
    # key → 中文名 (本地化)
    zh = {}
    loc_dir = GAME_LOCALIZATION
    try:
        for fn in os.listdir(loc_dir):
            if not fn.endswith(".yml"):
                continue
            with open(os.path.join(loc_dir, fn), encoding="utf-8-sig", errors="replace") as fp:
                for line in fp:
                    m = re.match(r"\s*([a-z_]+):\s*\"([^\"]+)\"\s*(?:#.*)?$", line)
                    if m:
                        zh[m.group(1)] = m.group(2).strip()
    except Exception:
        pass
    _CULTURE_MAP = {i: (keys[i] if i < len(keys) else None) for i in range(500)}
    _CULTURE_MAP["_zh"] = zh
    return _CULTURE_MAP

def culture_id_to_name(cid):
    """culture 数字 id → 中文名。"""
    m = build_culture_map()
    key = m.get(int(cid))
    if not key:
        return None
    return m.get("_zh", {}).get(key, key)

def culture_id_to_key(cid):
    """culture 数字 id → 游戏 culture key (如 hausa), 供本土判定。"""
    if cid is None:
        return None
    m = build_culture_map()
    return m.get(int(cid))

def _matching_brace(text, open_idx):
    """返回与 text[open_idx] 处左花括号配对的右花括号下标。"""
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text)

def _homeland_dirs():
    """本土定义目录: 原版 + workshop mod + 用户 mod (mod 覆盖原版)。"""
    dirs = [HOMELAND_STATES_DIR]
    for base in (WORKSHOP_DIR,
                 os.path.join(os.path.expanduser("~"), "Documents",
                              "Paradox Interactive", "Victoria 3", "mod")):
        if not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base)):
            p = os.path.join(base, d, "common", "history", "states")
            if os.path.isdir(p):
                dirs.append(p)
    return dirs

def build_homeland_map():
    """建立 州域 key → 该州域视为本土的 culture key 集合。
    数据源: common/history/states/*.txt 的 s:STATE_X = { ... add_homeland = cu:xxx ... }。
    后加载的 mod 覆盖原版同名州域条目。"""
    global _HOMELAND_CACHE
    if _HOMELAND_CACHE is not None:
        return _HOMELAND_CACHE
    hm = {}
    for base in _homeland_dirs():
        for fn in sorted(os.listdir(base)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(base, fn), encoding="utf-8-sig") as fp:
                    text = fp.read()
            except Exception:
                continue
            for m in re.finditer(r"s:([A-Z][A-Z0-9_]*)\s*=\s*\{", text):
                end = _matching_brace(text, m.end() - 1)
                block = text[m.end():end]
                cults = set(re.findall(r"add_homeland\s*=\s*cu:([a-z_]+)", block))
                if cults:
                    hm[m.group(1)] = cults
    _HOMELAND_CACHE = hm
    return hm

def build_goods_map():
    """建立 商品id → key / key → 基准价(cost) / key → 中文名 映射。
    商品 id 按 common/goods 文件顺序递增, 与存档 price report / pop_needs 权重一致。"""
    global _GOODS_CACHE
    if _GOODS_CACHE is not None:
        return _GOODS_CACHE
    order, cost, zh = [], {}, {}
    try:
        import glob
        for fn in sorted(glob.glob(os.path.join(GOODS_DIR, "*.txt"))):
            cur = None
            with open(fn, encoding="utf-8-sig") as fp:
                for line in fp:
                    m = re.match(r"^([a-z_]+)\s*=\s*\{", line)
                    if m:
                        cur = m.group(1)
                        if cur not in order:
                            order.append(cur)
                        continue
                    mc = re.match(r"^\s*cost\s*=\s*([0-9.]+)", line)
                    if mc and cur:
                        cost[cur] = float(mc.group(1))
    except Exception:
        pass
    try:
        for fn in os.listdir(GAME_LOCALIZATION):
            if not fn.endswith(".yml"):
                continue
            with open(os.path.join(GAME_LOCALIZATION, fn), encoding="utf-8-sig",
                      errors="replace") as fp:
                for line in fp:
                    m = re.match(r"\s*([a-z_]+):\s*\"([^\"]+)\"\s*(?:#.*)?$", line)
                    if m and m.group(1) in order:
                        zh[m.group(1)] = m.group(2).strip()
    except Exception:
        pass
    _GOODS_CACHE = {"order": order, "cost": cost, "zh": zh}
    return _GOODS_CACHE

def _resolve_loc_template(value, loc, depth=0):
    """解析本地化模板值中的 $KEY$ 引用 (如 $HUB_NAME_STATE_X_city$)。"""
    if not isinstance(value, str) or "$" not in value or depth > 5:
        return value
    def repl(m):
        key = m.group(1)
        if key in loc:
            return _resolve_loc_template(loc[key], loc, depth + 1)
        return m.group(0)
    return re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)\$", repl, value)

def _hub_name_bad(v):
    """hub 名解析失败判定: 空 / 含未替换占位符 / 仍是本地化键或全大写 key。"""
    return (not isinstance(v, str) or not v or "$" in v
            or v.startswith(("HUB_NAME_", "STATE_"))
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", v))

def _hub_names(state_obj):
    """州对象 → 5 个 hub 名 (city/port/farm/mine/wood 顺序); 缺失项为 None。
    优先 custom_hub_names(玩家改名), 其次 localized_hub_names(动态命名州, 带后缀),
    最后回退默认本地化 key HUB_NAME_<STATE_REGION>_<hub> —— 存档里普通州不写 hub key。"""
    if not state_obj:
        return [None] * 5
    nd = state_obj.get("naming_data") or {}
    keys = nd.get("localized_hub_names") or []
    custom = nd.get("custom_hub_names") or []
    loc = _load_loc_all()
    region = state_obj.get("region") or ""
    out = []
    for i, hub in enumerate(HUB_ORDER):
        c = custom[i] if i < len(custom) else ""
        if c:
            out.append(c)
            continue
        k = keys[i] if i < len(keys) else ""
        if not k and region:
            k = f"HUB_NAME_{region}_{hub}"
        if not k:
            out.append(None)
            continue
        v = _resolve_loc_template(loc.get(k, k), loc)
        if _hub_name_bad(v) and region:
            k2 = f"HUB_NAME_{region}_{hub}"
            if k2 != k:
                v = _resolve_loc_template(loc.get(k2, k2), loc)
        out.append(v if not _hub_name_bad(v) else None)
    return out

def _hub_for_building(btype):
    """建筑类型 key → hub 类别 (city/port/farm/mine/wood); 无法归类返回 None。
    归类规则: 矿山/油井→mine, 伐木场→wood, 港口/船坞/渔业/海军→port,
    农场/种植园/牧场→farm, 其余(城市/工业/政府/铁路等)→city。"""
    if not btype:
        return None
    if btype.endswith("_mine") or btype in ("gold_field", "oil_rig"):
        return "mine"
    if btype.endswith("_logging_camp"):
        return "wood"
    if (btype.endswith(("_wharf", "_whaling_station", "_port", "_shipyard"))
            or "_naval" in btype or "_fishing_village" in btype
            or btype in ("port", "shipyard")):
        return "port"
    if (btype.endswith(("_farm", "_plantation", "_ranch"))
            or "_orchard" in btype or "_pasture" in btype
            or btype == "vineyard"):
        return "farm"
    return "city"

def _consumption_profile(pop_needs_entry, sol):
    """从州 pop_needs[文化id] 聚合该家庭消费画像。
    返回 {"goods": [{"id","key","name","weight"}], "engel": 0~100}
    方法: 每条需求内部按最大权重归一化使各需求等权, 只统计该 SoL 档位已消费的需求;
    恩格尔系数按 基础食品+加热供暖+简朴衣物 的权重占比估算。"""
    gm = build_goods_map()
    order, zh = gm["order"], gm["zh"]
    entries = (pop_needs_entry or {}).get("pop_need_entry_data") or []
    n_consume = len(entries)
    for sol_th, n in _NEEDS_BY_SOL:
        if sol is None or sol < sol_th:
            n_consume = n
            break
    n_consume = min(n_consume, len(entries))
    agg = {}
    engel_num = 0.0
    engel_den = 0.0
    for idx in range(n_consume):
        ws = entries[idx].get("weights") or {}
        if not ws:
            continue
        mx = max(ws.values()) or 1
        for gid, w in ws.items():
            gid = int(gid)
            v = w / mx
            agg[gid] = agg.get(gid, 0.0) + v
            if idx in _ENGEL_NEED_INDEXES:
                engel_num += v
            engel_den += v
    engel = round(engel_num / engel_den * 100) if engel_den else None
    goods = []
    for gid, w in sorted(agg.items(), key=lambda kv: -kv[1])[:5]:
        key = order[gid] if gid < len(order) else None
        goods.append({"id": gid, "key": key,
                      "name": zh.get(key, key or str(gid)) if key else str(gid),
                      "weight": round(w, 3)})
    return {"goods": goods, "engel": engel}

def _price_report_to_map(report):
    """price report 对象 → {商品id: 市价}。"""
    out = {}
    for gid, g in ((report or {}).get("goods") or {}).items():
        if isinstance(g, dict) and isinstance(g.get("value"), (int, float)):
            out[int(gid)] = g["value"]
    return out

def _market_price_map(data, country):
    """玩家所在市场的商品市价 {id: 价格}。
    优先取玩家国家 budget.current_price_report; 缺失时回退 previous_price_report;
    若玩家无本市场报告(附庸/关税同盟), 找市场拥有者的报告。"""
    budget = (country or {}).get("budget") or {}
    prices = _price_report_to_map(budget.get("current_price_report"))
    if not prices:
        prices = _price_report_to_map(budget.get("previous_price_report"))
    if prices:
        return prices
    market_id = (country or {}).get("market")
    if market_id is None:
        return {}
    cm = data.find(b'"country_manager"')
    if cm < 0:
        return {}
    db = data.find(b'"database"', cm)
    ob = data.find(b'{', db)
    cm_end = _object_end(data, ob)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    pat = ('"market":' + str(market_id) + ',').encode()
    j = ob
    while True:
        m = _IDOBJ.search(data, j, cm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        head = data[ob2:min(ob2 + 800, len(data))]
        if pat in head:
            raw, _ = extract_json_object(data, ob2)
            if raw:
                try:
                    c = json.loads(raw)
                    prices = _price_report_to_map(
                        (c.get("budget") or {}).get("current_price_report")) or \
                        _price_report_to_map(
                            (c.get("budget") or {}).get("previous_price_report"))
                    if prices:
                        return prices
                except Exception:
                    pass
        j = data.find(b'}', ob2) + 1
    return {}

_GOV_CACHE = None

def build_gov_map():
    """建立 gov_key → 中文名 映射(从 simp_chinese 本地化 gov_ 开头的 key)。"""
    global _GOV_CACHE
    if _GOV_CACHE is not None:
        return _GOV_CACHE
    gov = {}
    loc_dir = GAME_LOCALIZATION
    try:
        for fn in os.listdir(loc_dir):
            if not fn.endswith(".yml"):
                continue
            with open(os.path.join(loc_dir, fn), encoding="utf-8-sig", errors="replace") as fp:
                for line in fp:
                    m = re.match(r"\s*(gov_[a-z_]+):\s*\"([^\"]+)\"\s*(?:#.*)?$", line)
                    if m:
                        gov[m.group(1)] = m.group(2).strip()
    except Exception:
        pass
    _GOV_CACHE = gov
    return gov

def gov_to_name(gov_key):
    """政体键 → 中文名, 失败则去掉前缀。"""
    if not gov_key:
        return "未知"
    g = build_gov_map()
    return g.get(gov_key, gov_key.replace("gov_", ""))

def _get_primary_cultures(data, state_ids):
    """从全局州对象收集 culture key 列表(用于把 pop 的 culture id 映射成可读 key)。
    存档里 pop 用 culture 数字 id, 州用 culture_types_present(key)。此处收集所有出现过的
    key, 按出现频率降序, 供 top culture 匹配。"""
    state_ids = set(state_ids or [])
    keys = []
    # 先精确找玩家州
    for m in re.finditer(rb'"culture_types_present":\[([^\]]*)\]', data):
        pre = data[max(0, m.start() - 300):m.start()]
        m_id = re.findall(rb'"(\d+)":\{', pre)
        if m_id and int(m_id[-1].group(1)) in state_ids:
            for k in re.findall(rb'"([a-z_]+)"', m.group(1)):
                if k.decode() not in keys:
                    keys.append(k.decode())
    return keys

# ---------------------------------------------------------------------------
# Pop 统计: 民族/宗教/职业占比
# ---------------------------------------------------------------------------

def _aggregate_pops(data, state_ids):
    """遍历 pops.database, 统计给定州内的民族/宗教/职业占比。
    pop 对象: {type, workforce, dependents, location, culture, religion, ...}
    返回 {cultures, religions, professions, total} 各为 [{"name","count","pct"}]。
    pct 为占总人口的百分比。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return {"cultures": [], "religions": [], "professions": []}
    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return {"cultures": [], "religions": [], "professions": []}
    db = data.find(b'"database"', pop_db)
    ob = data.find(b'{', db)
    # 逐个 pop 对象
    cult = {}
    reli = {}
    prof = {}
    j = ob
    while True:
        i = data.find(b'":{', j)
        if i < 0:
            break
        ob2 = data.find(b'{', i)
        # 快速检查 location 是否在目标州内 (用正则找 "location":N 和 "type"/"culture"/"religion")
        seg_end = data.find(b'}', ob2)
        head = data[ob2:min(ob2 + 600, len(data))]
        m_loc = re.search(rb'"location":(\d+)', head)
        if not m_loc or int(m_loc.group(1)) not in state_ids:
            j = data.find(b'}', ob2) + 1
            continue
        m_type = re.search(rb'"type":"([^"]+)"', head)
        m_cult = re.search(rb'"culture":(\d+)', head)
        m_reli = re.search(rb'"religion":"([^"]+)"', head)
        m_wf = re.search(rb'"workforce":([\d.]+)', head)
        m_dep = re.search(rb'"dependents":([\d.]+)', head)
        wf = float(m_wf.group(1)) if m_wf else 0
        dep = float(m_dep.group(1)) if m_dep else 0
        total = wf + dep
        if m_type:
            prof[m_type.group(1).decode()] = prof.get(m_type.group(1).decode(), 0) + total
        if m_cult:
            cult[int(m_cult.group(1))] = cult.get(int(m_cult.group(1)), 0) + total
        if m_reli:
            reli[m_reli.group(1).decode()] = reli.get(m_reli.group(1).decode(), 0) + total
        j = data.find(b'}', ob2) + 1
    total = sum(cult.values()) or sum(reli.values()) or sum(prof.values()) or 1
    def top3(d):
        out = []
        for k, v in sorted(d.items(), key=lambda x: -x[1])[:3]:
            out.append({"name": str(k), "count": round(v),
                        "pct": round(v / total * 100, 1) if total else 0})
        return out
    return {"cultures": top3(cult), "religions": top3(reli),
            "professions": top3(prof), "total": round(total)}

# ---------------------------------------------------------------------------
# 家庭采访: 随机选一个玩家州的一个 POP, 提取其生活水平/收支/消费结构
# ---------------------------------------------------------------------------

# weekly_budget 13 分量的经验含义 (存档引擎内部顺序):
#   收入: 0=工资, 2=被抚养者收入, 4=分红/投资收入, 5=自给/其他收入, 6=政府转移支付
#   支出: 7=商品消费, 9=所得税, 10=消费税, 11=红利税, 12=人头税(农民/自耕农按土地税)
_FAMILY_INCOME_SLOTS = ((0, "工资"), (2, "被抚养者收入"), (4, "分红/投资收入"),
                        (5, "自给/其他收入"), (6, "政府转移支付"))
_FAMILY_EXPENSE_SLOTS = ((7, "商品消费"), (9, "所得税"), (10, "消费税"),
                         (11, "红利税"), (12, "人头税"))

# 游戏出生/死亡率基础公式常数 (00_defines.txt, NPops 段, 按月)
_GROWTH_MIN_BIRTH = 0.00060
_GROWTH_MAX_BIRTH = 0.00450
_GROWTH_MIN_MORT = 0.00045
_GROWTH_MAX_MORT = 0.00550
_GROWTH_EQ_SOL = 5      # 增长平衡点: 从这起净增长转正
_GROWTH_TRANS_SOL = 10  # 出生率开始下降的 SoL
_GROWTH_MAX_SOL = 15    # 净增长最高点 (仅影响死亡率)
_GROWTH_STABLE_SOL = 25 # 出生/死亡率触底

def _estimate_growth_rates(sol):
    """按游戏定义的分段线性公式, 由生活水平估算每月基础出生率/死亡率。
    返回 (birth_per_month, death_per_month); sol 缺失时返回 (None, None)。
    注意: 这是未含修正器(modifier)的基础率, 仅供报纸行文参考。"""
    if sol is None or not isinstance(sol, (int, float)):
        return None, None
    b_trans = _GROWTH_MAX_BIRTH * 1.0
    r_eq = (_GROWTH_EQ_SOL * (b_trans - _GROWTH_MAX_BIRTH) / _GROWTH_TRANS_SOL
            + _GROWTH_MAX_BIRTH)
    b_growth_max = ((_GROWTH_MAX_SOL - _GROWTH_TRANS_SOL)
                    * (_GROWTH_MIN_BIRTH - b_trans)
                    / (_GROWTH_STABLE_SOL - _GROWTH_TRANS_SOL) + b_trans)
    m_growth_max = b_growth_max * 0.35
    # 出生率
    if sol < _GROWTH_TRANS_SOL:
        birth = _GROWTH_MAX_BIRTH
    elif sol < _GROWTH_STABLE_SOL:
        slope = (_GROWTH_MIN_BIRTH - b_trans) / (_GROWTH_STABLE_SOL - _GROWTH_TRANS_SOL)
        birth = sol * slope - slope * _GROWTH_STABLE_SOL + _GROWTH_MIN_BIRTH
    else:
        birth = _GROWTH_MIN_BIRTH
    # 死亡率
    if sol < _GROWTH_EQ_SOL:
        slope = (r_eq - _GROWTH_MAX_MORT) / _GROWTH_EQ_SOL
        death = sol * slope + _GROWTH_MAX_MORT
    elif sol < _GROWTH_MAX_SOL:
        slope = (m_growth_max - r_eq) / (_GROWTH_MAX_SOL - _GROWTH_EQ_SOL)
        death = sol * slope - slope * _GROWTH_EQ_SOL + r_eq
    elif sol < _GROWTH_STABLE_SOL:
        slope = (_GROWTH_MIN_MORT - m_growth_max) / (_GROWTH_STABLE_SOL - _GROWTH_MAX_SOL)
        death = sol * slope - slope * _GROWTH_STABLE_SOL + _GROWTH_MIN_MORT
    else:
        death = _GROWTH_MIN_MORT
    return round(birth, 6), round(death, 6)


# ---------------------------------------------------------------------------
# 出生/死亡率修正: 污染 / 荒废度 / 卫生与教育机构 / 相关法律 / 生产方式 / 工作条件
# 数值来源: 游戏本体文件
#   - common/static_modifiers/00_code_static_modifiers.txt
#     (state_region_pollution_health / state_region_devastation / working_conditions)
#   - common/laws/00_health_system.txt, 00_rights_of_women.txt,
#     00_childrens_rights.txt, 00_education_system.txt, 00_labor_rights.txt
#   - common/institutions/00_institutions.txt
#   - common/technology/technologies/30_society.txt (modern_sewerage)
#   - common/production_methods/*.txt (生产方式死亡修正)
# ---------------------------------------------------------------------------

# 污染健康影响: 每 1% 污染影响 +0.5% 死亡率 (state_region_pollution_health)
_MORT_PER_POLLUTION_PCT = 0.005
# 荒废度: 每 1 点 +1% 死亡率 (state_region_devastation)
_MORT_PER_DEVASTATION = 0.01
# 卫生机构每级削减污染健康影响 (state_pollution_reduction_health_mult, 按卫生法)
_HEALTH_POLLUTION_REDUCTION = {
    "law_charitable_health_system": -0.10,
    "law_private_health_insurance": -0.10,
    "law_public_health_insurance": -0.15,
}
# 卫生机构直接死亡率修正 (每级, institution_modifier)
_HEALTH_MORTALITY_PER_LEVEL = {
    "law_charitable_health_system": -0.03,
    "law_public_health_insurance": -0.05,
}
# 私人医保: 死亡率随 POP 财富缩放 (每级每财富)
_HEALTH_MORTALITY_WEALTH = -0.002
# 女性权利法对出生率的修正 (state_birth_rate_mult)
_WOMEN_RIGHTS_BIRTH_MULT = {
    "law_no_womens_rights": 0.05,
    "law_women_in_the_fields": -0.10,
    "law_women_in_the_workplace": -0.05,
    "law_womens_suffrage": -0.05,
}
# 童工法对相应职业的死亡率修正 (state_<职业>_mortality_mult)
_CHILD_LABOR_MORTALITY = {
    "law_child_labor_allowed": (("laborers", "machinists", "farmers", "peasants"), 0.05),
    "law_restricted_child_labor": (("laborers", "farmers", "peasants"), 0.02),
}
# 识字率对出生率的惩罚: -0.1 × 识字率, 最高 -0.05 (识字率 >= 50% 封顶)
_LITERACY_BIRTH_PENALTY_SCALE = 0.1
_LITERACY_BIRTH_PENALTY_MAX = 0.05
# 工作安全机构每级削减工作条件死亡率 (building_working_conditions_mult)
_WORKPLACE_SAFETY_PER_LEVEL = -0.2
# 现代下水道科技削减污染健康影响
_SEWERAGE_POLLUTION_REDUCTION = -0.10
# 生产方式死亡率贡献达到该值(≥10%)即视为"高危生产方式" (硝化甘油/剥削压榨等)
_HAZARD_PM_THRESHOLD = 0.10

# 工作条件死亡修正 (来源: working_conditions, 按建筑组 × POP 职业)
_WORKING_CONDITIONS_MORT = {
    ("bg_mining", "laborers"): 0.10, ("bg_mining", "machinists"): 0.05,
    ("bg_mining", "engineers"): 0.02, ("bg_mining", "slaves"): 0.20,
    ("bg_plantations", "laborers"): 0.05, ("bg_plantations", "slaves"): 0.10,
    ("bg_rubber", "laborers"): 0.05, ("bg_rubber", "slaves"): 0.10,
    ("bg_logging", "laborers"): 0.10, ("bg_logging", "machinists"): 0.05,
    ("bg_logging", "engineers"): 0.02, ("bg_logging", "slaves"): 0.20,
    ("bg_oil_extraction", "laborers"): 0.10, ("bg_oil_extraction", "machinists"): 0.05,
    ("bg_oil_extraction", "engineers"): 0.02,
    ("bg_light_industry", "laborers"): 0.05, ("bg_light_industry", "machinists"): 0.02,
    ("bg_heavy_industry", "laborers"): 0.10, ("bg_heavy_industry", "machinists"): 0.05,
    ("bg_heavy_industry", "engineers"): 0.02,
    ("bg_military_industry", "laborers"): 0.10, ("bg_military_industry", "machinists"): 0.05,
    ("bg_military_industry", "engineers"): 0.02,
    ("bg_infrastructure", "laborers"): 0.10, ("bg_infrastructure", "machinists"): 0.05,
    ("bg_infrastructure", "engineers"): 0.02,
    ("bg_whaling", "laborers"): 0.10, ("bg_whaling", "machinists"): 0.05,
    ("bg_fishing", "laborers"): 0.05, ("bg_fishing", "machinists"): 0.02,
    ("bg_fishing", "engineers"): 0.02,
}

BUILDINGS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\buildings"
PRODUCTION_METHODS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\production_methods"

_BG_CACHE = None
_PM_MORT_CACHE = None


def _clausewitz_blocks(text):
    """浅解析 Clausewitz 文本, 产出 (块名, 块文本) 序列 (仅顶层 'name = {' 块)。"""
    pos = 0
    while True:
        m = re.search(rb'([A-Za-z0-9_]+)\s*=\s*\{', text[pos:])
        if not m:
            return
        name = m.group(1).decode()
        start = pos + m.end() - 1
        depth = 1
        j = start + 1
        while j < len(text) and depth:
            c = text[j:j + 1]
            if c == b'{':
                depth += 1
            elif c == b'}':
                depth -= 1
            j += 1
        yield name, text[start:j]
        pos = j


def _load_building_groups():
    """建筑类型 → 建筑组 (bg_*) 映射, 读取 game/common/buildings/*.txt。"""
    global _BG_CACHE
    if _BG_CACHE is None:
        _BG_CACHE = {}
        if os.path.isdir(BUILDINGS_DIR):
            for fn in os.listdir(BUILDINGS_DIR):
                if not fn.endswith(".txt"):
                    continue
                with open(os.path.join(BUILDINGS_DIR, fn), "rb") as f:
                    text = f.read()
                for name, block in _clausewitz_blocks(text):
                    m = re.search(rb'building_group\s*=\s*"?([a-z0-9_]+)"?', block)
                    if m:
                        _BG_CACHE[name] = m.group(1).decode()
    return _BG_CACHE


def _load_pm_mortality():
    """生产方式 key → {POP职业: 死亡率修正}, 读取 game/common/production_methods/*.txt。"""
    global _PM_MORT_CACHE
    if _PM_MORT_CACHE is None:
        _PM_MORT_CACHE = {}
        if os.path.isdir(PRODUCTION_METHODS_DIR):
            for fn in os.listdir(PRODUCTION_METHODS_DIR):
                if not fn.endswith(".txt"):
                    continue
                with open(os.path.join(PRODUCTION_METHODS_DIR, fn), "rb") as f:
                    text = f.read()
                for name, block in _clausewitz_blocks(text):
                    mort = {}
                    for m in re.finditer(
                            rb'building_(laborers|machinists|engineers|slaves|farmers|peasants)'
                            rb'_mortality_mult\s*=\s*(-?\d+(?:\.\d+)?)', block):
                        mort[m.group(1).decode()] = float(m.group(2))
                    if mort:
                        _PM_MORT_CACHE[name] = mort
    return _PM_MORT_CACHE


def _state_region_pollution_map(data):
    """一次扫描 state_region_manager.database → {州域模板key: 污染影响百分比}。"""
    out = {}
    srm = data.find(b'"state_region_manager"')
    if srm < 0:
        return out
    srm_end = _object_end(data, data.find(b'{', srm))
    db = data.find(b'"database"', srm)
    if db < 0:
        return out
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, srm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("template"):
            out[obj["template"]] = obj.get("pollution") or 0.0
        j = end
    return out


def _country_institution_levels(data, country_id):
    """国家 id → {机构key: 投资等级}, 读取 institutions.database。"""
    insts = {}
    if not country_id:
        return insts
    idx = data.find(b'"institutions"')
    if idx < 0:
        return insts
    inst_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return insts
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, inst_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("institution") and obj.get("country") == country_id:
            insts[obj["institution"]] = obj.get("investment") or 0
        j = end
    return insts


def _growth_law_bits(laws, health_inv, safety_inv, sewerage):
    """从现行法律 + 机构等级提取出生/死亡修正所需参数。"""
    laws = set(laws or [])
    bits = {
        "health_law": None,
        "education_law": None,
        "birth_law_mult": 0.0,
        "child_labor": None,
        "safety_level": 0,
        "sewerage": bool(sewerage),
        "health_inv": health_inv or 0,
    }
    for l in ("law_charitable_health_system", "law_private_health_insurance",
              "law_public_health_insurance", "law_no_health_system"):
        if l in laws:
            bits["health_law"] = l
            break
    for l in ("law_public_schools", "law_private_schools", "law_religious_schools",
              "law_no_schools", "law_public_schools_only", "law_terakoya"):
        if l in laws:
            bits["education_law"] = l
            break
    for l, mult in _WOMEN_RIGHTS_BIRTH_MULT.items():
        if l in laws:
            bits["birth_law_mult"] = mult
            break
    for l in _CHILD_LABOR_MORTALITY:
        if l in laws:
            bits["child_labor"] = l
            break
    if "law_regulatory_bodies" in laws or "law_worker_protections" in laws:
        bits["safety_level"] = safety_inv or 0
    return bits


def _growth_rates_with_modifiers(sol, literacy_pct, wealth, pop_type, pollution_pct,
                                 devastation, bits, building_group=None, active_pms=None,
                                 institutions_active=True):
    """基础出生/死亡率 × 污染/荒废度/法律/机构/生产方式/工作条件修正。
    返回 (年化出生率%, 年化死亡率%, 高危死亡率增幅%, 高危生产方式key列表);
    sol 缺失时返回 (None, None, None, [])。
    高危增幅 = 生产方式+工作条件带来的死亡率相对增幅 (相对无高危劳动条件的同类人群)。
    修正项为同类型百分比相加后乘到基础率上 (与游戏 modifier 系统一致)。
    institutions_active=False 时 (殖民地/未完全并入州) 不套用卫生机构与卫生法律修正:
    机构只对完全并入的州生效, 其余修正 (污染/荒废度/童工法/生产方式/工作条件) 照常。"""
    birth_m, death_m = _estimate_growth_rates(sol)
    if birth_m is None:
        return None, None, None, []
    bits = bits or {}
    # 非高危死亡率修正 (污染/荒废度/卫生机构/童工法)
    poll_red = 0.0
    if institutions_active:
        poll_red = (_HEALTH_POLLUTION_REDUCTION.get(bits.get("health_law"), 0.0)
                    * (bits.get("health_inv") or 0))
    if bits.get("sewerage"):
        poll_red += _SEWERAGE_POLLUTION_REDUCTION
    death_mult = 1.0
    death_mult += _MORT_PER_POLLUTION_PCT * (pollution_pct or 0.0) * (1.0 + poll_red)
    death_mult += _MORT_PER_DEVASTATION * (devastation or 0.0)
    if institutions_active:
        death_mult += _HEALTH_MORTALITY_PER_LEVEL.get(bits.get("health_law"), 0.0) \
            * (bits.get("health_inv") or 0)
        if bits.get("health_law") == "law_private_health_insurance":
            death_mult += _HEALTH_MORTALITY_WEALTH * (wealth or 0) * (bits.get("health_inv") or 0)
    child_labor = bits.get("child_labor")
    if child_labor and pop_type:
        types, mult = _CHILD_LABOR_MORTALITY[child_labor]
        if pop_type in types:
            death_mult += mult
    # 高危死亡率修正: 工作条件(按建筑组) + 生产方式
    hazard_mort = 0.0
    if building_group and pop_type:
        wc = _WORKING_CONDITIONS_MORT.get((building_group, pop_type))
        if wc:
            hazard_mort += wc * (1.0 + _WORKPLACE_SAFETY_PER_LEVEL * (bits.get("safety_level") or 0))
    pm_mort = _load_pm_mortality()
    hazard_pms = []
    for pm in (active_pms or []):
        m = pm_mort.get(pm, {}).get(pop_type, 0.0)
        if not m and pop_type == "slaves":
            # 奴隶填充劳工岗位: 无显式 slaves 修正时直接套用劳工倍率
            m = pm_mort.get(pm, {}).get("laborers", 0.0)
        if m:
            hazard_mort += m
            if m >= _HAZARD_PM_THRESHOLD:
                hazard_pms.append(pm)
    death_mult += hazard_mort
    # 出生率修正
    lit_pen = min(_LITERACY_BIRTH_PENALTY_MAX,
                  _LITERACY_BIRTH_PENALTY_SCALE * (literacy_pct or 0.0) / 100.0)
    birth_mult = 1.0 + (bits.get("birth_law_mult") or 0.0) - lit_pen
    base_mult = death_mult - hazard_mort
    hazard_excess_pct = (hazard_mort / base_mult * 100
                         if hazard_mort > 0 and base_mult > 0 else None)
    return (birth_m * 12 * 100 * birth_mult,
            death_m * 12 * 100 * max(death_mult, 0.0),
            hazard_excess_pct, hazard_pms)


def _building_production_methods(data, bid):
    """建筑 id → 当前生产方式 key 列表 (存档建筑对象 production_methods 字段)。"""
    idx = data.find(b'"building_manager"')
    if idx < 0:
        return []
    bm_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return []
    pat = ('"' + str(bid) + '":{').encode()
    i = data.find(pat, db, bm_end)
    if i < 0:
        return []
    ob2 = i + len(pat) - 1
    raw, _end = extract_json_object(data, ob2)
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    pms = obj.get("production_methods") if isinstance(obj, dict) else None
    return [p for p in pms if isinstance(p, str)] if isinstance(pms, list) else []


def _state_object(data, state_id):
    """州 id → 完整 state 对象 (含 region/incorporation 等字段); 找不到返回 None。

    注意: states.database 内嵌其他数字键对象 (如某州对象 trade.goods 的商品 id
    映射, 键形如 "13":{value, prestige_goods}), 不能直接返回第一个 'N':{ 匹配;
    须解析后校验对象像州 (含 capital/region 字段) 才返回, 否则继续往后找。"""
    sd = data.find(b'"states":{"database"')
    if sd < 0:
        return None
    db = data.find(b'"database"', sd)
    sob = data.find(b'{', db)
    so_end = _object_end(data, sob)
    pat = ('"' + str(state_id) + '":{').encode()
    idx = data.find(pat, sob, so_end)
    while idx >= 0:
        ob2 = data.find(b'{', idx)
        raw, _end = extract_json_object(data, ob2)
        if raw:
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None
            if isinstance(obj, dict) and ("capital" in obj or "region" in obj):
                return obj
        idx = data.find(pat, idx + 1, so_end)
    return None


def _state_incorporation(data, state_id):
    """州合并进度 (0~1 浮点); 未合并殖民地 (无 incorporation 字段) 记作 0。"""
    obj = _state_object(data, state_id)
    if not obj:
        return None
    incorp = obj.get("incorporation")
    if incorp is None:
        return 0.0
    try:
        return float(incorp)
    except (TypeError, ValueError):
        return 0.0


def _state_region_key(data, state_id):
    """州 id → 州域 key (如 STATE_HAUSALAND), 供本地化转中文名。"""
    obj = _state_object(data, state_id)
    return obj.get("region") if obj else None

def _capital_name(data, country):
    """首都 state → 中文名: 优先城市 hub 名(本地化/玩家改名), 失败回退州域名。"""
    cap_id = (country or {}).get("capital")
    if not cap_id:
        return ""
    sobj = _state_object(data, cap_id)
    if sobj:
        hubs = _hub_names(sobj)
        if hubs and hubs[0]:
            return hubs[0]
    rk = _state_region_key(data, cap_id)
    if rk:
        loc = _load_loc_all()
        return loc.get(rk, "") or ""
    return ""

def _harvest_conditions_for(data, region_key):
    """返回该州域当前活跃的收成条件 type 列表 (如 drought/heatwave); 无则 []。
    数据源: 存档 harvest_condition_manager.database 的 state_region_template 匹配。"""
    if not region_key:
        return []
    idx = data.find(b'"harvest_condition_manager"')
    if idx < 0:
        return []
    ob = data.find(b'{', idx)
    raw, _end = extract_json_object(data, ob)
    if not raw:
        return []
    try:
        mgr = json.loads(raw)
    except Exception:
        return []
    types = []
    for v in (mgr.get("database") or {}).values():
        if isinstance(v, dict) and v.get("state_region_template") == region_key and v.get("type"):
            t = v["type"]
            if t not in types:
                types.append(t)
    return types

# 利益集团支持数组的槽位顺序：与游戏内 8 大利益集团类型一致（存档按此顺序存储）
IG_TYPE_ORDER = [
    "ig_armed_forces", "ig_devout", "ig_industrialists", "ig_intelligentsia",
    "ig_landowners", "ig_petty_bourgeoisie", "ig_rural_folk", "ig_trade_unions",
]

# 自由言论(Free Speech)法律组（含当前版本的 law_right_of_assembly）
FREE_SPEECH_LAWS = ("law_outlawed_dissent", "law_censorship",
                    "law_right_of_assembly", "law_free_speech",
                    "law_protected_speech")

def _country_ig_slots(data, country_id):
    """解析存档 interest_groups.database，返回该国的 {槽位: IG key}。

    每个国家的 8 个利益集团实例按固定类型顺序落槽(0~7)，
    与 pop 的 interest_group_support_array 索引一一对应。
    """
    slots = {}
    if not country_id:
        return slots
    idx = data.find(b'"interest_groups"')
    if idx < 0:
        return slots
    ig_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return slots
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, ig_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("country") == country_id:
            definition = obj.get("definition")
            if definition in IG_TYPE_ORDER:
                slots[IG_TYPE_ORDER.index(definition)] = obj.get("name") or definition
        j = end
    return slots

def _movement_type_names(data):
    """扫描 political_movement_manager.database → {运动id: {type, religion?, culture?}}。"""
    names = {}
    idx = data.find(b'"political_movement_manager"')
    if idx < 0:
        return names
    mgr_brace = data.find(b'{', idx)
    mgr_end = _object_end(data, mgr_brace)
    db = data.find(b'"database"', idx)
    if db < 0:
        return names
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, mgr_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict):
            ident = obj.get("identity")
            if isinstance(ident, dict) and str(ident.get("type", "")).startswith("movement_"):
                names[int(m.group(1))] = {"type": ident["type"],
                                          "religion": ident.get("religion"),
                                          "culture": ident.get("culture")}
        j = end
    return names

def _movement_display_name(mtype, ident, loc, player_tag=None):
    """政治运动显示名: 游戏面板取 <类型>_name 本地化键并解析动态占位符
    ([COUNTRY.GetAdjectiveNoFormatting] / [RELIGION.GetNameNoFormatting] /
    [CULTURE.GetNameNoFormatting]), 无该键时回退基础类型名。
    例: movement_cultural_majority_name → "旁遮普至上主义运动"。"""
    key = f"{mtype}_name"
    val = loc.get(key)
    if not val:
        return _clean_loc_name(loc.get(mtype, mtype), loc)
    if isinstance(ident, dict):
        rel = ident.get("religion")
        if rel:
            val = val.replace("[RELIGION.GetNameNoFormatting]",
                              _clean_loc_name(loc.get(rel, rel), loc))
        cul = ident.get("culture")
        if cul:
            val = val.replace("[CULTURE.GetNameNoFormatting]",
                              _clean_loc_name(loc.get(cul, cul), loc))
    if "[COUNTRY.GetAdjectiveNoFormatting]" in val:
        adj = ""
        if player_tag:
            adj = (loc.get(f"{player_tag}_ADJ")
                   or loc.get(f"{player_tag}_ADJ_NO_FORMAT") or "")
        val = val.replace("[COUNTRY.GetAdjectiveNoFormatting]", adj)
    val = _clean_loc_name(val, loc)
    return val.strip() or _clean_loc_name(loc.get(mtype, mtype), loc)

def _movement_names_zh(data, player_tag=None):
    """所有政治运动 id → 中文显示名（<类型>_name 本地化 + 动态占位符解析）。"""
    loc = _load_loc_all()
    return {mid: _movement_display_name(info.get("type"), info, loc, player_tag)
            for mid, info in _movement_type_names(data).items()}

def _civil_war_progress(data, country_id):
    """civil_war.database 中该国运动的内战/分离进程 → {运动id: {"type","progress"}}。"""
    out = {}
    key = b'"civil_war"'
    pos = 0
    found = None
    while True:
        idx = data.find(key, pos)
        if idx < 0:
            break
        j = idx + len(key)
        if j < len(data) and data[j:j + 1] == b':':
            j += 1
        while j < len(data) and data[j:j + 1] in b" \t\r\n":
            j += 1
        if data[j:j + 1] == b'{':
            brace = j
            mgr_end = _object_end(data, brace)
            if data.find(b'"database"', brace, mgr_end) >= 0:
                found = (idx, brace, mgr_end)
                break
        pos = idx + 1
    if not found:
        return out
    idx, mgr_brace, mgr_end = found
    db = data.find(b'"database"', idx, mgr_end)
    if db < 0:
        return out
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, mgr_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("origin_country") == country_id:
            mid = obj.get("political_movement")
            if mid is not None:
                out[int(mid)] = {"type": obj.get("type"),
                                 "progress": round(obj.get("progress") or 0.0, 4)}
        j = end
    return out

def _localize_character_name(first, last, loc):
    """角色名中文化: 存档存英文名, 游戏 names_l 本地化提供英文名→中文表。
    优先整词匹配 (如 Karam_Singh→卡拉姆·辛格), 否则按空格/下划线拆词逐个查表,
    查不到保留原文。存档姓氏里的连字符 (如 of_Saxe-Coburg-Gotha) 会先归一为
    下划线再整词查表 (→萨克森‑科堡‑哥达)。"""
    parts = []
    for raw in (first, last):
        if not raw:
            continue
        cand = raw.replace("-", "_")
        if cand in loc:
            parts.append(loc[cand])
            continue
        for tok in re.split(r"[ _]+", raw):
            parts.append(loc.get(tok, tok))
    return " ".join(p for p in parts if p)

def _player_characters(data, country_id):
    """character_manager.database 该国角色 → {id: {"name"(中文), "ideology", "template"}}。"""
    chars = {}
    if not country_id:
        return chars
    loc = _load_loc_all()
    idx = data.find(b'"character_manager"')
    if idx < 0:
        return chars
    mgr_brace = data.find(b'{', idx)
    mgr_end = _object_end(data, mgr_brace)
    db = data.find(b'"database"', idx)
    if db < 0:
        return chars
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, mgr_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("country") == country_id:
            nm = _localize_character_name(str(obj.get("first_name") or ""),
                                          str(obj.get("last_name") or ""), loc)
            chars[int(m.group(1))] = {"name": nm or None,
                                      "ideology": obj.get("ideology"),
                                      "template": obj.get("template")}
        j = end
    return chars


_RULER_TITLES_CACHE = None
_FEMALE_TEMPLATES_CACHE = None

_RULER_TITLE_FALLBACK = [
    # (gov key 关键字, 男头衔, 女头衔) — 用于 gov 键在游戏文件里查不到时的兜底
    ("shogun", "征夷大将军", "征夷大将军"),
    ("empire", "皇帝", "女皇"),
    ("emperor", "皇帝", "女皇"),
    ("kingdom", "国王", "女王"),
    ("monarchy", "国王", "女王"),
    ("president", "总统", "总统"),
    ("republic", "总统", "总统"),
    ("dictator", "独裁者", "独裁者"),
    ("theocracy", "教宗", "教宗"),
    ("pope", "教宗", "教宗"),
    ("caliph", "哈里发", "哈里发"),
    ("chiefdom", "酋长", "女酋长"),
    ("council", "主席", "主席"),
]


def _gov_block_body(txt, key):
    """在政府类型文本里定位 gov_xxx = { ... } 并返回块内内容(含嵌套)。"""
    m = re.search(r"\b" + re.escape(key) + r"\s*=\s*\{", txt)
    if not m:
        return None
    i = txt.find("{", m.start())
    depth = 0
    j = i
    while j < len(txt):
        c = txt[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return txt[i + 1:j]
        j += 1
    return None


def _load_ruler_titles():
    """解析游戏 government_types → {gov_key: {"male": 中文头衔, "female": 中文头衔}}。
    头衔原文取自游戏 simp_chinese 本地化 (government_l_simp_chinese.yml 的 RULER_TITLE_* 等)。"""
    global _RULER_TITLES_CACHE
    if _RULER_TITLES_CACHE is not None:
        return _RULER_TITLES_CACHE
    loc = _load_loc_all()
    out = {}
    try:
        for fn in os.listdir(GOVERNMENT_TYPES_DIR):
            if not fn.endswith(".txt"):
                continue
            with open(os.path.join(GOVERNMENT_TYPES_DIR, fn), encoding="utf-8",
                      errors="replace") as fp:
                txt = fp.read()
            for m in re.finditer(r"\b(gov_[a-z0-9_]+)\s*=\s*\{", txt):
                key = m.group(1)
                body = _gov_block_body(txt, key)
                if not body:
                    continue
                mm = re.search(r"male_ruler\s*=\s*\"([^\"]*)\"", body)
                mf = re.search(r"female_ruler\s*=\s*\"([^\"]*)\"", body)
                male_key = mm.group(1) if mm else ""
                female_key = mf.group(1) if mf else male_key
                out[key] = {
                    "male": loc.get(male_key, "") if male_key else "",
                    "female": loc.get(female_key, "") if female_key else "",
                }
    except Exception:
        pass
    _RULER_TITLES_CACHE = out
    return out


def _load_female_templates():
    """历史角色模板中 female = yes 的模板名集合 (用于识别女王/女皇等)。"""
    global _FEMALE_TEMPLATES_CACHE
    if _FEMALE_TEMPLATES_CACHE is not None:
        return _FEMALE_TEMPLATES_CACHE
    names = set()
    try:
        for fn in os.listdir(CHARACTER_TEMPLATES_DIR):
            if not fn.endswith(".txt"):
                continue
            with open(os.path.join(CHARACTER_TEMPLATES_DIR, fn), encoding="utf-8",
                      errors="replace") as fp:
                txt = fp.read()
            for m in re.finditer(r"\b([a-z0-9_]+)\s*=\s*\{", txt):
                key = m.group(1)
                i = txt.find("{", m.start())
                depth = 0
                j = i
                while j < len(txt):
                    c = txt[j]
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            body = txt[i + 1:j]
                            if re.search(r"\bfemale\s*=\s*yes\b", body):
                                names.add(key)
                            break
                    j += 1
    except Exception:
        pass
    _FEMALE_TEMPLATES_CACHE = names
    return names


def _ruler_title(gov_key, is_female=False):
    """政体键 → 统治者中文头衔 (男/女), 查不到游戏数据时按关键字兜底。"""
    if not gov_key:
        return ""
    t = _load_ruler_titles().get(gov_key)
    if t:
        title = (t.get("female") or t.get("male")) if is_female else (t.get("male") or t.get("female"))
        if title:
            return title
    low = gov_key.lower()
    for kw, male, female in _RULER_TITLE_FALLBACK:
        if kw in low:
            return female if is_female else male
    return ""


def _ruler_info(data, country_id, ruler_id, gov_key, chars=None):
    """用与利益集团首领相同的方式解析统治者: 姓名 / 意识形态 / 在位状态 / 头衔。
    头衔由政体键决定; 性别仅对历史角色模板可判 (存档无性别字段, 随机角色默认男性)。"""
    if ruler_id is None:
        return None
    if chars is None:
        chars = _player_characters(data, country_id)
    ch = chars.get(ruler_id)
    if not ch:
        return None
    loc = _load_loc_all()
    lideo = ch.get("ideology")
    is_female = (ch.get("template") or "") in _load_female_templates()
    title = _ruler_title(gov_key, is_female=is_female)
    return {
        "name": ch.get("name") or None,
        "ideology": (_clean_loc_name(loc.get(lideo, lideo), loc) if lideo else None),
        "status": "在位",
        "title": title,
        "is_female": is_female,
    }

def _iter_pops_in_states(data, state_ids):
    """单次扫描 pops.database，产出位于指定州集合内的全部 POP 对象。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return
    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return
    mgr_brace = data.find(b'{', pop_db)
    mgr_end = _object_end(data, mgr_brace)
    db = data.find(b'"database"', pop_db)
    if db < 0:
        return
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, mgr_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("location") in state_ids:
            yield obj
        j = end

def _extract_political_movements(data, country_id, state_ids, pop_stats, player_tag=None):
    """提取玩家政治运动列表（按支持度降序）。

    存档字段口径（经实测校准，与游戏面板一致）：
      - POP 的 political_movement_support 为“每 10 万人的支持人数”：
        支持者人数 = Σ(比例) × 100000；军人支持数 = Σ(军人POP比例) × 100000。
      - 大众支持% = 支持者/全国政治参与人口；
        军人支持% = 军人支持数/(军队政治力量×10000)；
        财富支持% = Σ(财富×比例)×100000/(国家总财富×100000)。
      - 支持度 = 0.34×大众% + 0.33×军人% + 0.33×财富%。
    """
    moves = []
    if not country_id:
        return moves
    loc = _load_loc_all()
    idx = data.find(b'"political_movement_manager"')
    if idx < 0:
        return moves
    mgr_brace = data.find(b'{', idx)
    mgr_end = _object_end(data, mgr_brace)
    db = data.find(b'"database"', idx)
    if db < 0:
        return moves
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    objs = {}
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, mgr_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("country") == country_id:
            ident = obj.get("identity")
            if isinstance(ident, dict) and str(ident.get("type", "")).startswith("movement_"):
                objs[int(m.group(1))] = obj
        j = end
    if not objs:
        return moves
    sums = {mid: [0.0, 0.0, 0.0] for mid in objs}  # [Σ比例, Σ军人比例, Σ财富×比例]
    for obj in _iter_pops_in_states(data, state_ids):
        wl = obj.get("wealth") or 0
        ismil = obj.get("type") in ("officers", "soldiers")
        pms = obj.get("political_movement_support") or {}
        for k, v in pms.items():
            try:
                mid = int(k)
            except (TypeError, ValueError):
                continue
            if mid in sums and isinstance(v, (int, float)):
                sums[mid][0] += v
                if ismil:
                    sums[mid][1] += v
                sums[mid][2] += wl * v
    participants = pop_stats.get("population_political_participants") or 0
    wealth_total = (pop_stats.get("total_wealth") or 0) * 100000
    army_total = (pop_stats.get("military_political_strength") or 0) * 10000
    cw = _civil_war_progress(data, country_id)
    for mid, obj in objs.items():
        ident = obj.get("identity") or {}
        mtype = ident.get("type") if isinstance(ident, dict) else None
        rad = obj.get("radicalism") or 0.0
        if rad < 0.25:
            tier = "消极"
        elif rad < 0.5:
            tier = "不满"
        elif rad < 0.75:
            tier = "抗议"
        else:
            tier = "武斗"
        s = sums[mid]
        supporters = s[0] * 100000
        popular_pct = supporters / participants * 100 if participants else None
        military_pct = (s[1] * 100000 / army_total * 100) if army_total else None
        wealth_pct = (s[2] * 100000 / wealth_total * 100) if wealth_total else None
        if popular_pct is not None and military_pct is not None and wealth_pct is not None:
            support_pct = 0.34 * popular_pct + 0.33 * military_pct + 0.33 * wealth_pct
        else:
            support_pct = None
        ideology = obj.get("ideology")
        # 只有抗议(50)及以上档位的运动才允许附带内战/分离进程,
        # 避免存档里存在进程对象但运动活跃度不足时误导模型。
        mov_cw = cw.get(mid) if rad >= 0.5 else None
        moves.append({
            "id": mid,
            "type": mtype,
            "name": _movement_display_name(mtype, ident, loc, player_tag) if mtype else None,
            "ideology": (_clean_loc_name(loc.get(ideology, ideology), loc)
                         if ideology else None),
            "radicalism": round(rad, 4),
            "activism": tier,
            "supporters": int(round(supporters)),
            "popular_pct": round(popular_pct, 2) if popular_pct is not None else None,
            "military_supporters": int(round(s[1] * 100000)),
            "military_pct": round(military_pct, 2) if military_pct is not None else None,
            "wealth_support": int(round(s[2] * 100000)),
            "wealth_pct": round(wealth_pct, 2) if wealth_pct is not None else None,
            "support_pct": round(support_pct, 2) if support_pct is not None else None,
            "civil_war": mov_cw,
        })
    moves.sort(key=lambda m: -(m.get("support_pct") or 0))
    return moves

def _building_type_map(data, state_ids):
    """解析 building_manager.database，返回 {建筑id: 建筑类型key}（仅玩家州内）。"""
    state_ids = set(state_ids or [])
    bm = {}
    idx = data.find(b'"building_manager"')
    if idx < 0:
        return bm
    bm_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return bm
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, bm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        head = data[ob2:min(ob2 + 400, len(data))]
        m_st = re.search(rb'"state":(\d+)', head)
        if not m_st or int(m_st.group(1)) not in state_ids:
            j = data.find(b'}', ob2) + 1
            continue
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("state") in state_ids and obj.get("building"):
            bm[int(m.group(1))] = obj["building"]
        j = end
    return bm

def _country_technologies(data, country_id):
    """返回该国已研发科技 key 列表。

    存档只记录 acquired_technologies（全部已研发），没有逐项完成日期，
    无法区分“去年完成研发”，由上层回退为随机抽取已研发科技。
    """
    techs = []
    if not country_id:
        return techs
    idx = data.find(b'"technology"')
    if idx < 0:
        return techs
    tech_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return techs
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, tech_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("country") == country_id:
            techs = obj.get("acquired_technologies") or []
            break
        j = end
    return list(dict.fromkeys(techs))

def _family_from_pop(pop, region_name, region_key=None, ig_slots=None,
                     building_map=None, incorporation=None, harvest_conditions=None,
                     pop_needs=None, hub_names=None, price_map=None, vital=None,
                     movement_names=None):
    """把单个 pop 对象整理成「家庭采访」数据块。"""
    wf = pop.get("workforce") or 0
    dep = pop.get("dependents") or 0
    total = wf + dep
    def _grp_pct(n):
        return round(min(100.0, n / total * 100), 2) if total else None
    # 识字率口径与游戏一致: 存档 num_literate 是按劳动力统计的识字人数,
    # Pop.GetLiteracyRate = num_literate / workforce (不含被抚养人口)。
    num_lit = pop.get("num_literate") or 0
    literacy = round(num_lit / wf * 100, 2) if wf else None
    sol = pop.get("previous_quality_of_life")
    vital = vital or {}
    birth_pct, death_pct, hazard_excess_pct, hazard_pms = _growth_rates_with_modifiers(
        sol, literacy, pop.get("wealth"), pop.get("type"),
        vital.get("pollution_pct"), vital.get("devastation"),
        vital.get("bits"),
        building_group=vital.get("building_group"),
        active_pms=vital.get("active_pms"),
        institutions_active=vital.get("institutions_active", True))
    # 高危生产方式的中文名 (本地化, 含 $引用$ 解析)
    hazard_pms_zh = None
    if hazard_pms:
        loc = _load_loc_all()
        names = []
        for pm in hazard_pms:
            nm = loc.get(pm) or pm
            seen = {pm}
            while isinstance(nm, str) and nm.startswith("$") and nm.endswith("$"):
                ref = nm[1:-1]
                if ref in seen or ref not in loc:
                    break
                seen.add(ref)
                nm = loc[ref]
            if nm and nm not in names:
                names.append(nm)
        hazard_pms_zh = names
    wb = pop.get("weekly_budget") or []
    income = sum(v for v in wb if isinstance(v, (int, float)) and v > 0)
    expense = -sum(v for v in wb if isinstance(v, (int, float)) and v < 0)
    income_parts = []
    for idx, name in _FAMILY_INCOME_SLOTS:
        if idx < len(wb) and isinstance(wb[idx], (int, float)) and wb[idx]:
            income_parts.append(f"{name} {wb[idx]:.2f}")
    expense_parts = []
    for idx, name in _FAMILY_EXPENSE_SLOTS:
        if idx < len(wb) and isinstance(wb[idx], (int, float)) and wb[idx]:
            expense_parts.append(f"{name} {abs(wb[idx]):.2f}")
    lr = pop.get("loyalists_and_radicals")
    loy_n = round(max(0.0, lr) * 100000) if isinstance(lr, (int, float)) else 0
    rad_n = round(max(0.0, -lr) * 100000) if isinstance(lr, (int, float)) else 0
    mov_list = []
    pms = pop.get("political_movement_support") or {}
    if isinstance(pms, dict) and pms:
        items = sorted(((int(k), v) for k, v in pms.items()
                        if isinstance(k, str) and k.isdigit() and isinstance(v, (int, float))),
                       key=lambda kv: -kv[1])[:2]
        for mid, v in items:
            nm = (movement_names or {}).get(mid)
            mov_list.append({"id": mid, "name": nm or f"运动{mid}",
                             "pct": _grp_pct(v * 100000)})
    food = pop.get("food_security") or {}
    culture = culture_id_to_name(pop.get("culture")) if pop.get("culture") is not None else None
    # 本土判定: 该 pop 所在州域是否是其 culture 的 add_homeland
    culture_key = culture_id_to_key(pop.get("culture"))
    is_homeland = None
    if region_key and culture_key:
        hm = build_homeland_map()
        is_homeland = culture_key in hm.get(region_key, ())
    # 社会地位(Acceptance)与职业满意度：存档可见时一并带出
    acc = pop.get("acceptance_data") or {}
    job_sat = pop.get("job_satisfaction")
    # 利益集团：取该 POP 支持度占比最高的一个
    ig_support = (pop.get("interest_group_support_data") or {}).get("interest_group_support_array") or []
    top_ig = None
    if (isinstance(ig_support, list) and len(ig_support) >= 2
            and isinstance(ig_support[1], dict) and ig_support[1]):
        items = [(int(k), v) for k, v in ig_support[1].items()
                 if isinstance(k, str) and k.isdigit() and isinstance(v, (int, float))]
        if items:
            idx, val = max(items, key=lambda kv: kv[1])
            name = (ig_slots or {}).get(idx)
            if name:
                ig_total = sum(v for _, v in items) or 0
                share_pct = round(val / ig_total * 100, 1) if ig_total else None
                top_ig = {"name": name, "share_pct": share_pct}
    # 工作建筑：POP 有 workplace 时按建筑id查类型并本地化；无 workplace 视为失业
    wp_id = pop.get("workplace")
    btype = (building_map or {}).get(wp_id)
    if wp_id is None:
        workplace, unemployed = None, True
    else:
        unemployed = False
        workplace = _load_loc_all().get(btype, btype) if btype else None
    # 消费画像: 州 pop_needs 按该 pop 文化 id 取需求权重
    profile = _consumption_profile((pop_needs or {}).get(str(pop.get("culture"))), sol)
    # 消费商品市价对比 (市价 vs 商品基准价 cost)
    gm = build_goods_map()
    for g in profile["goods"]:
        base = gm["cost"].get(g["key"]) if g.get("key") else None
        price = (price_map or {}).get(g.get("id"))
        if base and price is not None:
            g["dev_pct"] = round((price - base) / base * 100)
        else:
            g["dev_pct"] = None
    # 访谈地点: 优先用工作建筑所属 hub 的城市名
    hub_name = None
    hub_cat = _hub_for_building(btype)
    if hub_cat and hub_names:
        hub_name = hub_names[HUB_ORDER.index(hub_cat)]
    return {
        "location": pop.get("location"),
        "workplace_id": pop.get("workplace"),
        "region_name": region_name,
        "hub_name": hub_name,
        "pop_type": pop.get("type"),
        "culture": culture,
        "culture_key": culture_key,
        "religion": pop.get("religion"),
        "is_homeland": is_homeland,
        "incorporation": incorporation,
        "harvest_conditions": harvest_conditions or [],
        "consumption_goods": profile["goods"],
        "engel_coefficient": profile["engel"],
        "sol": pop.get("previous_quality_of_life"),
        "wealth": pop.get("wealth"),
        "literacy_pct": literacy,
        "acceptance_status": acc.get("acceptance_status"),
        "interest_group": top_ig,
        "job_satisfaction": round(job_sat, 2) if isinstance(job_sat, (int, float)) else None,
        "workplace": workplace,
        "unemployed": unemployed,
        "birth_rate_pct": round(birth_pct, 2) if birth_pct is not None else None,
        "death_rate_pct": round(death_pct, 2) if death_pct is not None else None,
        "pollution_pct": round(vital.get("pollution_pct") or 0.0, 2),
        "devastation": round(vital.get("devastation") or 0.0, 2),
        "health_law": vital.get("bits", {}).get("health_law"),
        "education_law": vital.get("bits", {}).get("education_law"),
        "health_investment": vital.get("bits", {}).get("health_inv"),
        "schools_investment": vital.get("schools_inv"),
        "sewerage": bool(vital.get("bits", {}).get("sewerage")),
        "hazard_excess_pct": round(hazard_excess_pct, 1) if hazard_excess_pct is not None else None,
        "hazard_pms_zh": hazard_pms_zh,
        "workforce": int(round(wf)),
        "dependents": int(round(dep)),
        "dependent_ratio": round(dep / total, 3) if total else None,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "income_parts": income_parts,
        "expense_parts": expense_parts,
        "loyalists_and_radicals": round(lr, 4) if isinstance(lr, (int, float)) else None,
        "loyalists": loy_n or None,
        "radicals": rad_n or None,
        "loyalists_pct": _grp_pct(loy_n),
        "radicals_pct": _grp_pct(rad_n),
        "political_movements": mov_list,
        "food_security": food.get("state"),
    }

def _pops_in_state(data, state_id):
    """迭代玩家指定州内的全部 POP 原始对象 (含 location/workplace/SoL 等字段)。"""
    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return
    db = data.find(b'"database"', pop_db)
    ob = data.find(b'{', db)
    j = ob
    while True:
        i = data.find(b'":{', j)
        if i < 0:
            break
        ob2 = data.find(b'{', i)
        head = data[ob2:min(ob2 + 600, len(data))]
        m_loc = re.search(rb'"location":(\d+)', head)
        if not m_loc or int(m_loc.group(1)) != state_id:
            j = data.find(b'}', ob2) + 1
            continue
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("location") == state_id:
            yield obj
        j = end

def _extract_player_states(data, state_ids):
    """提取玩家每个州的 [州id, 州域名(中文), 主要居民文化(中文)]。
    单次扫描 pops 按州聚合各族人口, 取人口最多的文化; 州内完全无人时
    回退州域本土文化(add_homeland)。返回按州 id 升序的
    [{id, name, top_culture, empty}]。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return []
    cult_by_state = {sid: {} for sid in state_ids}
    pop_db = data.find(b'"pops"')
    if pop_db >= 0:
        db = data.find(b'"database"', pop_db)
        ob = data.find(b'{', db)
        j = ob
        while True:
            i = data.find(b'":{', j)
            if i < 0:
                break
            ob2 = data.find(b'{', i)
            head = data[ob2:min(ob2 + 600, len(data))]
            m_loc = re.search(rb'"location":(\d+)', head)
            if not m_loc:
                j = data.find(b'}', ob2) + 1
                continue
            sid = int(m_loc.group(1))
            counts = cult_by_state.get(sid)
            if counts is None:
                j = data.find(b'}', ob2) + 1
                continue
            m_cult = re.search(rb'"culture":(\d+)', head)
            if m_cult:
                m_wf = re.search(rb'"workforce":([\d.]+)', head)
                m_dep = re.search(rb'"dependents":([\d.]+)', head)
                wf = float(m_wf.group(1)) if m_wf else 0
                dep = float(m_dep.group(1)) if m_dep else 0
                cid = int(m_cult.group(1))
                counts[cid] = counts.get(cid, 0) + wf + dep
            j = data.find(b'}', ob2) + 1
    loc = _load_loc_all()
    zh_map = (build_culture_map() or {}).get("_zh") or {}
    hm = build_homeland_map()
    result = []
    for sid in sorted(state_ids):
        rk = _state_region_key(data, sid)
        name = loc.get(rk) if rk else None
        counts = cult_by_state.get(sid) or {}
        top = None
        empty = True
        if counts:
            empty = False
            top = culture_id_to_name(max(counts, key=counts.get))
        elif rk and hm.get(rk):
            keys = sorted(hm[rk])
            top = "、".join(zh_map.get(k, k) for k in keys)
        result.append({"id": sid, "name": name or f"州{sid}",
                       "top_culture": top, "empty": empty})
    return result

def _buildings_in_state(data, state_id):
    """building_manager.database 中属于该州的建筑 id 迭代器。"""
    idx = data.find(b'"building_manager"')
    if idx < 0:
        return
    bm_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, bm_end - 1)
        if not m:
            return
        ob2 = m.start() + len(m.group(0)) - 1
        head = data[ob2:min(ob2 + 400, len(data))]
        m_st = re.search(rb'"state":(\d+)', head)
        if not m_st or int(m_st.group(1)) != state_id:
            j = data.find(b'}', ob2) + 1
            continue
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("state") == state_id and obj.get("building"):
            yield int(m.group(1))
        j = end


def _buildings_by_state(data, state_ids):
    """单次扫描 building_manager → {state_id: [建筑id]} (仅玩家州)。
    供家庭采访与统治者活动多次取用, 避免每个州反复整文件扫描。"""
    state_ids = set(state_ids or [])
    out = {s: [] for s in state_ids}
    if not state_ids:
        return out
    idx = data.find(b'"building_manager"')
    if idx < 0:
        return out
    bm_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return out
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, bm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        head = data[ob2:min(ob2 + 400, len(data))]
        m_st = re.search(rb'"state":(\d+)', head)
        if not m_st or int(m_st.group(1)) not in state_ids:
            j = data.find(b'}', ob2) + 1
            continue
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("state") in state_ids and obj.get("building"):
            out[int(obj["state"])].append(int(m.group(1)))
        j = end
    return out


def _pops_by_state(data, state_ids):
    """单次扫描 pops → {state_id: [POP对象]} (仅玩家州)。
    供家庭采访随机重试时直接取样, 避免每次尝试都整文件重扫 pops。"""
    state_ids = set(state_ids or [])
    out = {s: [] for s in state_ids}
    if not state_ids:
        return out
    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return out
    db = data.find(b'"database"', pop_db)
    ob = data.find(b'{', db)
    j = ob
    while True:
        i = data.find(b'":{', j)
        if i < 0:
            break
        ob2 = data.find(b'{', i)
        head = data[ob2:min(ob2 + 600, len(data))]
        m_loc = re.search(rb'"location":(\d+)', head)
        if not m_loc:
            j = data.find(b'}', ob2) + 1
            continue
        sid = int(m_loc.group(1))
        if sid not in state_ids:
            j = data.find(b'}', ob2) + 1
            continue
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("location") == sid:
            out[sid].append(obj)
        j = end
    return out


def _pick_interview_set(data, state_ids, ig_slots=None, building_map=None, price_map=None,
                        cid=None, player_tag=None, max_tries=300,
                        preferred_state=None, ruler_visited=False,
                        pops_index=None, buildings_index=None):
    """随机选一个州 → 随机选该州一个建筑 → 取建筑内 SoL 最低与最高两个 POP(人口>10)
    分别作为「民生访谈」与「邻里富户」数据块。
    preferred_state: 优先在该州取材 (统治者走访联动); ruler_visited=True 且确实用到
    该州时, 在民生访谈块上打 ruler_visited 标记, 供渲染时让受访者提及统治者到访。
    若该州失业率(失业POP劳动力/该州总人口)>5%, 再附加「失业民生」块:
    该州人口最多的失业 POP + 失业率。建筑内合格 POP 不足 2 个时重新随机。
    返回 {"family_interview", "top_sol_peer", "unemployed_interview"} (缺失为 None)。"""
    state_ids = set(state_ids or [])
    result = {"family_interview": None, "top_sol_peer": None, "unemployed_interview": None}
    if not state_ids:
        return result
    # 一次性索引 (单文件扫描), 之后所有随机重试只从内存取样
    if pops_index is None:
        pops_index = _pops_by_state(data, state_ids)
    if buildings_index is None:
        buildings_index = _buildings_by_state(data, state_ids)
    state_order = sorted(state_ids)
    # 走访联动: 前几次尝试固定用统治者走访的州, 取材失败再退回随机州
    try_states = []
    if preferred_state is not None and preferred_state in state_ids:
        try_states = [preferred_state] * min(5, max_tries)
    sid = None
    lowest = highest = None
    for _ in range(max_tries):
        if try_states:
            sid = try_states.pop(0)
        else:
            sid = random.choice(state_order)
        buildings = buildings_index.get(sid) or []
        if not buildings:
            continue
        bid = random.choice(buildings)
        cands = []
        for obj in pops_index.get(sid) or []:
            if obj.get("workplace") != bid:
                continue
            sz = (obj.get("workforce") or 0) + (obj.get("dependents") or 0)
            if sz < 10:
                continue
            sol = obj.get("previous_quality_of_life")
            if sol is None or not isinstance(sol, (int, float)):
                continue
            cands.append((sol, sz, obj))
        if len(cands) < 2:
            continue
        # SoL 升序; 同 SoL 时取人口较少者作最穷、人口较多者作最富
        cands.sort(key=lambda x: (x[0], x[1]))
        lowest, highest = cands[0][2], cands[-1][2]
        break
    if lowest is None or highest is None:
        return result
    # 州级上下文
    region_key = _state_region_key(data, sid)
    region_name = _load_loc_all().get(region_key) if region_key else None
    state_obj = _state_object(data, sid)
    incorporation = state_obj.get("incorporation") if state_obj else None
    if incorporation is None and state_obj:
        # 未合并殖民地: 存档不写 incorporation, 以 colony_progress 等字段标记 → 记作 0
        incorporation = 0.0
    harvest_conditions = _harvest_conditions_for(data, region_key)
    pop_needs = (state_obj or {}).get("pop_needs") or {}
    hub_names = _hub_names(state_obj)
    # 出生/死亡修正上下文: 州污染/荒废度 + 全国机构/法律/科技 + 建筑生产方式
    pollution_pct = (_state_region_pollution_map(data).get(region_key, 0.0)
                     if region_key else 0.0)
    devastation = (state_obj.get("devastation") or 0.0) if state_obj else 0.0
    laws = query_laws(data, cid)
    insts = _country_institution_levels(data, cid)
    health_inv = insts.get("institution_health_system", 0)
    schools_inv = insts.get("institution_schools", 0)
    safety_inv = insts.get("institution_workplace_safety", 0)
    sewerage = "modern_sewerage" in _country_technologies(data, cid)
    bits = _growth_law_bits(laws, health_inv, safety_inv, sewerage)
    btype = (building_map or {}).get(bid)
    active_pms = _building_production_methods(data, bid)
    building_group = (_load_building_groups().get(btype) if btype else None)
    movement_names = _movement_names_zh(data, player_tag)
    common = dict(region_name=region_name, region_key=region_key, ig_slots=ig_slots,
                  building_map=building_map, incorporation=incorporation,
                  harvest_conditions=harvest_conditions, pop_needs=pop_needs,
                  hub_names=hub_names, price_map=price_map,
                  vital=dict(pollution_pct=pollution_pct, devastation=devastation,
                             bits=bits, schools_inv=schools_inv,
                             building_group=building_group, active_pms=active_pms,
                             institutions_active=bool(incorporation and incorporation >= 1)),
                  movement_names=movement_names)
    family = _family_from_pop(lowest, **common)
    if ruler_visited and preferred_state is not None and sid == preferred_state:
        family["ruler_visited"] = True
    result["family_interview"] = family
    result["top_sol_peer"] = _family_from_pop(highest, **common)
    # 失业率: (该州失业POP的劳动力) / (该州总人口)
    total_pop = 0
    unemployed_work = 0
    unemployed_big = None
    unemployed_big_sz = 0
    for obj in pops_index.get(sid) or []:
        wf = obj.get("workforce") or 0
        dep = obj.get("dependents") or 0
        total_pop += wf + dep
        if obj.get("workplace") is None:
            unemployed_work += wf
            sz = wf + dep
            if sz >= 10 and sz > unemployed_big_sz:
                unemployed_big_sz = sz
                unemployed_big = obj
    rate = unemployed_work / total_pop if total_pop else 0.0
    if rate > 0.05 and unemployed_big is not None:
        uni = _family_from_pop(unemployed_big, **common)
        uni["unemployment_rate_pct"] = round(rate * 100, 2)
        result["unemployed_interview"] = uni
    return result

# ---------------------------------------------------------------------------
# 战争解析
# ---------------------------------------------------------------------------

def _build_indexes(data):
    """一次遍历构建三种索引, 供列强判定与战争解析共用:
      index   : {cid: {"definition", "prestige"(最后值), "is_main_tag"}}
      gp_ids  : 列强国家 id 集合 (prestige 排名前 8)
      dp_index: {dp_id: dp对象} (diplomatic_plays.database, 含伤亡/花费数据)
    """
    index = {}
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    cm = data.find(b'"country_manager"')
    if cm >= 0:
        # 只遍历 country_manager 对象内部 (其后是 pops/states 等, 数字对象可能混入)
        cm_brace = data.find(b'{', cm)
        cm_end = _object_end(data, cm_brace)
        db = data.find(b'"database"', cm)
        ob = data.find(b'{', db)
        j = ob
        while True:
            # 精确匹配 '"数字":{' (database 里可能有 '"0":"none"' 等字符串值, 不能用范围取 id)
            m = _IDOBJ.search(data, j, cm_end - 1)
            if not m:
                break
            ob2 = m.start() + len(m.group(0)) - 1
            raw, end = extract_json_object(data, ob2)
            if not raw:
                break
            try:
                obj = json.loads(raw)
            except Exception:
                j = end
                continue
            if isinstance(obj, dict) and (obj.get("definition") or obj.get("is_main_tag")):
                entry = {"definition": obj.get("definition"),
                         "is_main_tag": bool(obj.get("is_main_tag"))}
                dyn_name = (obj.get("dynamic_name") or {}).get("dynamic_country_name")
                if dyn_name:
                    entry["dyn_name"] = dyn_name
                pre = obj.get("prestige")
                if isinstance(pre, dict):
                    chans = pre.get("channels") or {}
                    last = None
                    for ch in chans.values():
                        vals = ch.get("values") or []
                        if vals:
                            last = vals[-1]
                    if last is not None:
                        entry["prestige"] = last
                index[int(m.group(1))] = entry
            j = end
    # 列强 = prestige 排名前 8 (V3 无 rank 字段, 列强由声望动态决定)
    ranked = sorted([cid for cid, e in index.items()
                     if e.get("prestige") is not None],
                    key=lambda c: -index[c]["prestige"])
    gp_ids = set(ranked[:8])
    # diplomatic_plays.database: war 的伤亡/花费存在关联的 dp 对象里
    dp_index = {}
    dm = data.find(b'"diplomatic_plays":{"database"')
    if dm >= 0:
        dp_brace = data.find(b'{', dm)
        dp_end = _object_end(data, dp_brace)
        dob = data.find(b'{', data.find(b'"database"', dm))
        j = dob
        while True:
            m = _IDOBJ.search(data, j, dp_end - 1)
            if not m:
                break
            ob2 = m.start() + len(m.group(0)) - 1
            raw, end = extract_json_object(data, ob2)
            if not raw:
                break
            try:
                obj = json.loads(raw)
            except Exception:
                j = end
                continue
            if isinstance(obj, dict) and ("war" in obj or "casualties" in obj):
                dp_index[int(m.group(1))] = obj
            j = end
    return index, gp_ids, dp_index

def _dp_casualties(dp_obj):
    """从 diplomatic_play 对象提取伤亡: {cid: 总伤亡}。
    累加所有 casualties_from_* 值(含 attrition/battles, 按文化与战线),
    不含 wounded_from_* (伤员不算死亡)。存档值为浮点, 原样保留。"""
    cas = {}
    for c in dp_obj.get("casualties") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("country")
        if cid is None:
            continue
        total = 0.0
        for k, v in c.items():
            if k in ("country", "side") or not k.startswith("casualties"):
                continue
            if isinstance(v, dict):
                total += sum(x for x in v.values() if isinstance(x, (int, float)))
            elif isinstance(v, (int, float)):
                total += v
        if total:
            cas[cid] = round(cas.get(cid, 0) + total, 3)
    return cas

def _dp_costs(dp_obj):
    """从 diplomatic_play 的 country_records 提取总花费:
    每国 materiel_cost_of_war.goods.<id>.value 之和 + wage_cost_of_war。"""
    total = 0.0
    for r in dp_obj.get("country_records") or []:
        if not isinstance(r, dict):
            continue
        goods = ((r.get("materiel_cost_of_war") or {}).get("goods")) or {}
        if isinstance(goods, dict):
            for g in goods.values():
                if isinstance(g, dict) and isinstance(g.get("value"), (int, float)):
                    total += g["value"]
        wage = r.get("wage_cost_of_war")
        if isinstance(wage, (int, float)):
            total += wage
    return round(total, 2)

def parse_wars(data, names, player_id=None, index=None, gp_ids=None, dp_index=None):
    """解析 war_manager.database 中的战争, 只保留玩家或列强参与的。
    伤亡/花费从关联的 diplomatic_play 对象读取(war.diplomatic_play → dp)。
    返回 [{start_date, peace_date, participants:[{id,definition,name,side,rank}],
           casualties, casualties_total, total_cost, ended, player_involved}]"""
    if index is None or gp_ids is None or dp_index is None:
        index, gp_ids, dp_index = _build_indexes(data)
    wars = []
    wm = data.find(b'"war_manager"')
    if wm < 0:
        return wars
    wm_brace = data.find(b'{', wm)
    wm_end = _object_end(data, wm_brace)
    db = data.find(b'"database"', wm)
    ob = data.find(b'{', db)
    j = ob
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, wm_end - 1)
        if not m:
            break
        wid = m.group(1).decode()
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            wobj = json.loads(raw)
        except Exception:
            j = end
            continue
        if not isinstance(wobj, dict) or "war_participants" not in wobj:
            j = end
            continue
        # 关联的外交博弈: 提供双方阵营(side)与主要方(initiator/target)
        dp_id = wobj.get("diplomatic_play")
        dp = dp_index.get(dp_id) if dp_id is not None else None
        side_by_cid = {}
        primary_ids = set()
        if player_id is not None:
            primary_ids.add(player_id)
        if dp:
            side_by_cid = {r.get("country"): r.get("side", "")
                           for r in dp.get("country_records") or [] if isinstance(r, dict)}
            for k in ("initiator", "target"):
                v = dp.get(k)
                if isinstance(v, int):
                    primary_ids.add(v)
        parts = []
        for p in wobj.get("war_participants", []):
            if isinstance(p, dict):
                cid = p.get("country")
                entry = index.get(cid) or {}
                tag = entry.get("definition")
                ws = p.get("war_support")
                is_gp = cid in gp_ids
                parts.append({
                    "id": cid, "definition": tag,
                    "name": names.get(tag, tag) if tag else str(cid),
                    "side": side_by_cid.get(cid, p.get("side", "")),
                    "rank": "great_power" if is_gp else "minor_power",
                    "prestige": entry.get("prestige"),
                    "war_support": round(ws, 1) if isinstance(ws, (int, float)) else None,
                    "primary": is_gp or cid in primary_ids,
                })
        # 伤亡/花费: 关联的 diplomatic_play (dp id 4294967295 = 无关联)
        cas_by_cid = _dp_casualties(dp) if dp else {}
        total_cost = _dp_costs(dp) if dp else None
        player_involved = player_id is not None and any(p.get("id") == player_id for p in parts)
        has_great_power = any(p.get("rank") == "great_power" for p in parts)
        # 只保留玩家参与 或 有列强参与的战争
        if not (player_involved or has_great_power):
            j = end
            continue
        wars.append({
            "id": wid,
            "start_date": wobj.get("start_date"),
            "peace_date": wobj.get("peace_date"),
            "ended": bool(wobj.get("peace_date")) and wobj.get("peace_date") != "1.1.1",
            "player_involved": player_involved,
            "casualties": cas_by_cid,
            "casualties_total": round(sum(cas_by_cid.values()), 3) if cas_by_cid else None,
            "total_cost": total_cost,
            "participants": parts,
        })
        j = end
    return wars

def _prev_year_player_wars(wars, year):
    """筛选「前一年玩家国家发生的战争」及其结果。
    战争区间与上一历年 [year-1.1.1, year.1.1) 有交集且玩家参战即保留:
      - 上一历年开战且仍进行中的战争(本年继续)也会保留;
      - 上一历年之前就已结束的战争不保留。
    返回原 wars 条目的子集。"""
    if not year or not wars:
        return []
    prev_start = (year - 1, 1, 1)
    cur_start = (year, 1, 1)
    out = []
    for w in wars:
        if not w.get("player_involved"):
            continue
        start = _v3_date_tuple(w.get("start_date"))
        if not start:
            continue
        peace = w.get("peace_date")
        w_end = _v3_date_tuple(peace) if peace and peace != "1.1.1" else (9999, 12, 31)
        # 开始于本年之前, 且结束不早于上一历年年初 → 与上一历年有交集
        if start < cur_start and w_end >= prev_start:
            out.append(w)
    return out


def _last_year_wars(wars, year):
    """筛选去年(上一历年)发生的战争: 区间与 [year-1.1.1, year.1.1) 有交集。
    输入 wars 已由 parse_wars 限定为玩家参战或列强参战的战争;
    此处只保留主要参加者(玩家 / 列强 / 外交博弈的主要方 initiator+target,
    去掉英方一长串附庸等非主要参与者), 并按开始日期排序。
    返回含 participants(已过滤) 的 wars 子集, 供「战事专电」渲染。"""
    if not year or not wars:
        return []
    prev_start = (year - 1, 1, 1)
    cur_start = (year, 1, 1)
    out = []
    for w in wars:
        start = _v3_date_tuple(w.get("start_date"))
        if not start:
            continue
        peace = w.get("peace_date")
        w_end = _v3_date_tuple(peace) if peace and peace != "1.1.1" else (9999, 12, 31)
        # 开始于本年之前, 且结束不早于上一历年年初 → 与上一历年有交集
        if not (start < cur_start and w_end >= prev_start):
            continue
        ps = [p for p in w.get("participants", []) if p.get("primary")]
        if not ps:
            continue
        w2 = dict(w)
        w2["participants"] = ps
        out.append(w2)
    out.sort(key=lambda x: _v3_date_tuple(x.get("start_date")) or (0, 0, 0))
    return out

def _merge_prev_year_wars(snap, journal_dir, folder):
    """存档层落盘: 生成本年快照时, 把上一年存档中仍在进行的战争并入
    last_year_wars / prev_year_wars, 补回 V3 war_manager 只保留进行中战争
    而丢失的「去年战争」。仅并入报告字段, 不改 wars, 避免影响基于进行中
    战争的列强交战状态等判定。"""
    year = snap.get("year")
    if not year:
        return
    prev_dirs = []
    if folder:
        prev_dirs.append(os.path.join(journal_dir, folder, "data"))
    prev_wars = []
    for rd in prev_dirs:
        p = os.path.join(rd, f"raw_{year - 1}.json")
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fp:
                prev = json.load(fp)
        except Exception:
            continue
        prev_wars = prev.get("wars") or []
        if prev_wars:
            break
    if not prev_wars:
        return
    lyw = list(snap.get("last_year_wars") or [])
    lyw_seen = {w.get("id") for w in lyw if w.get("id") is not None}
    for w in prev_wars:
        wid = w.get("id")
        if wid is not None and wid in lyw_seen:
            continue
        ps = [p for p in (w.get("participants") or []) if p.get("primary")]
        if not ps:
            continue
        w2 = dict(w)
        w2["participants"] = ps
        lyw.append(w2)
        if wid is not None:
            lyw_seen.add(wid)
    snap["last_year_wars"] = lyw
    pyw = list(snap.get("prev_year_wars") or [])
    pyw_seen = {w.get("id") for w in pyw if w.get("id") is not None}
    for w in prev_wars:
        wid = w.get("id")
        if not w.get("player_involved"):
            continue
        if wid is not None and wid in pyw_seen:
            continue
        pyw.append(w)
        if wid is not None:
            pyw_seen.add(wid)
    snap["prev_year_wars"] = pyw

# ---------------------------------------------------------------------------
# 法律查询 (laws.database)
# ---------------------------------------------------------------------------

def query_laws(data, country_id):
    """从 laws.database 找该国的法律。每项 {law, country, ...}
    单次顺序扫描 (与 query_laws_changed 同款), 避免旧的 rfind 反向查找造成 O(n²)。"""
    laws = []
    idx = data.find(b'"laws"')
    if idx < 0 or not country_id:
        return laws
    laws_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return laws
    j = data.find(b'{', db)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, laws_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if (isinstance(obj, dict) and obj.get("country") == country_id
                and obj.get("law") and obj.get("active")):
            laws.append(obj["law"])
        j = end
    # 去重
    return list(dict.fromkeys(laws))

def _v3_date_tuple(s):
    """'Y.M.D' → (y, m, d) 元组, 用于日期比较; 无法解析返回 None。"""
    try:
        return tuple(int(x) for x in str(s).split(".")[:3])
    except Exception:
        return None

def query_laws_changed(data, country_id, report_date=None):
    """从 laws.database 提取**本年度内发生变化**的法律。

    存档中每个法律对象带有 activation_date (施行日期); 现行法律 active=true。
    本年度窗口取 [报告年份-1 的 1 月 1 日, 报告日期):
      - enacted (新施行) : active 且 activation_date 落在窗口内、且晚于该国
                           现行法律的基线日期(开局默认法, 如 1836.1.1);
      - repealed (废除)  : 上述新施行法律 replace 掉的旧法。
    返回 (enacted, repealed) 两个 law key 列表。"""
    enacted, repealed = [], []
    if not country_id:
        return enacted, repealed
    idx = data.find(b'"laws"')
    if idx < 0:
        return enacted, repealed
    laws_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return enacted, repealed
    j = data.find(b'{', db)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    objs = []
    while True:
        m = _IDOBJ.search(data, j, laws_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("law") and obj.get("country") == country_id:
            objs.append(obj)
        j = end
    active = [o for o in objs if o.get("active") and o.get("activation_date")]
    if not active:
        return enacted, repealed
    baseline = min(_v3_date_tuple(o["activation_date"]) for o in active)
    rdate = _v3_date_tuple(report_date) or (9999, 12, 30)
    window_start = (rdate[0] - 1, 1, 1)
    active_laws = {o["law"] for o in active}
    for o in sorted(active, key=lambda x: str(x.get("activation_date", ""))):
        ad = _v3_date_tuple(o.get("activation_date"))
        if not ad or ad <= baseline or not (window_start <= ad < rdate):
            continue
        if o["law"] not in enacted:
            enacted.append(o["law"])
        rep = o.get("replace")
        if rep and rep not in active_laws and rep not in repealed:
            repealed.append(rep)
    return enacted, repealed

# ---------------------------------------------------------------------------
# 对接报纸生成 (复用 journal.py)
# ---------------------------------------------------------------------------

_RULER_ACTIVITY_POOL = [
    # (权重, 活动类型)
    (25, "inspect_building"),
    (25, "cabinet_meeting"),
    (20, "visit_pop"),
    (15, "receive_envoys"),
    (10, "review_troops"),
    (5, "religious_ceremony"),
]


def _pick_state(snap, rnd=None, prefer_capital=True):
    """从玩家州里挑一个: 优先首都所在州, 其次任一非空州。"""
    states = snap.get("states") or []
    if not states:
        return None
    rnd = rnd or random
    if prefer_capital:
        cap = snap.get("capital") or ""
        for s in states:
            if cap and s.get("name") and cap in (s.get("name") or ""):
                return s
    nonempty = [s for s in states if not s.get("empty")]
    return rnd.choice(nonempty or states)


def _pick_building(melted, state_id, rnd=None, buildings_index=None, building_type_map=None):
    """随机挑一个该州建筑, 返回本地化中文名; 挑不到或名字没本地化则返回 None。"""
    if state_id is None:
        return None
    rnd = rnd or random
    if building_type_map is None:
        building_type_map = _building_type_map(melted, [state_id])
    if buildings_index is None:
        bids = list(_buildings_in_state(melted, state_id))
    else:
        bids = buildings_index.get(state_id) or []
    loc = _load_loc_all()
    types = [building_type_map.get(b) for b in bids]
    types = [t for t in types
             if t and (loc.get(t) or "") not in ("", t)
             and not t.startswith("building_company_")
             and not t.startswith("building_port")]
    if not types:
        return None
    return loc.get(rnd.choice(types))


def _religion_zh(key):
    """宗教 key → 中文名 (复用 journal.py 的映射表)。"""
    if not key:
        return ""
    try:
        from journal import RELIGION_NAMES
        return RELIGION_NAMES.get(key, key)
    except Exception:
        return key


def _assemble_ruler_activity(melted, snap, country_id, buildings_index=None,
                             building_type_map=None):
    """按概率拼装一条「统治者活动」事实 (程序侧完成, 直接作为数据传给模型)。

    活动池: 视察某地建筑 / 召集内阁会议 / 走访某州某文化某宗教的 POP 家庭 /
    接见外国使节 / 检阅驻军 / 出席宗教典礼。以年份为随机种子, 同年重生成结果稳定。
    任一素材缺失时自动换下一候选, 全部不可用返回 (None, None, None)。
    返回 (事实文本, 活动类型, 走访州id); 走访类返回的州id供家庭采访联动取材。
    """
    ri = snap.get("ruler_info") or {}
    name = ri.get("name")
    title = ri.get("title") or ""
    if not name:
        return None, None, None
    ruler = (title + name) if title else name
    rnd = random.Random(snap.get("year") or 0)
    states = snap.get("states") or []
    capital = snap.get("capital") or ""
    igs = snap.get("interest_groups") or []
    powers = snap.get("powers") or []
    pool = list(_RULER_ACTIVITY_POOL)
    tried = set()
    while pool:
        kind = rnd.choices(pool, weights=[w for w, _t in pool])[0][1]
        pool = [p for p in pool if p[1] != kind]
        if kind in tried:
            continue
        tried.add(kind)
        if kind == "inspect_building":
            st = _pick_state(snap, rnd=rnd) or {}
            bld = _pick_building(melted, st.get("id"), rnd=rnd,
                                 buildings_index=buildings_index,
                                 building_type_map=building_type_map)
            if bld:
                where = st.get("name") or capital or "某地"
                return f"{ruler}视察了位于{where}的{bld}", kind, None
        elif kind == "cabinet_meeting":
            leaders = [g.get("leader_name") for g in igs
                       if g.get("in_government") and g.get("leader_name")]
            if leaders:
                names = "、".join(list(dict.fromkeys(leaders))[:3])
                where = capital or "宫中"
                return f"{ruler}在{where}召集内阁会议，与{names}等共商国是", kind, None
            if capital:
                return f"{ruler}在{capital}召集内阁会议，与各部大臣共商国是", kind, None
        elif kind == "visit_pop":
            # 优先挑有建筑的非空州, 提高家庭采访联动成功率; 再优先首都州
            cands = [s for s in states if not s.get("empty")
                     and (buildings_index or {}).get(s.get("id"))]
            if not cands:
                cands = [s for s in states if not s.get("empty")]
            cap_st = next((s for s in cands
                           if capital and s.get("name") and capital in (s.get("name") or "")), None)
            st = cap_st or (rnd.choice(cands) if cands else None) or {}
            culture = st.get("top_culture") or ""
            rel = snap.get("religion")
            rel_zh = _religion_zh(rel)
            stname = st.get("name") or ""
            if stname and culture and rel_zh:
                return (f"{ruler}走访了{stname}的{culture}人家，"
                        f"在信奉{rel_zh}的居民家中体察民情", kind, st.get("id"))
            if stname and culture:
                return f"{ruler}走访了{stname}的{culture}人家，体察民情", kind, st.get("id")
        elif kind == "receive_envoys":
            foreign = next((p.get("name") for p in powers
                            if not p.get("is_player")), "")
            if not foreign and snap.get("treaties"):
                foreign = next((t.get("second_name") for t in snap.get("treaties") or []
                                if t.get("second_name")), "")
            if foreign:
                where = capital or "宫中"
                return f"{ruler}在{where}接见了{foreign}的使节，就两国邦交交换意见", kind, None
        elif kind == "review_troops":
            where = capital or "京师"
            return f"{ruler}检阅了驻防{where}的禁卫部队", kind, None
        elif kind == "religious_ceremony":
            rel_zh = _religion_zh(snap.get("religion"))
            if rel_zh:
                where = capital or "国都"
                return f"{ruler}在{where}出席了{rel_zh}的宗教典礼", kind, None
    return None, None, None


def build_journal_data(snap):
    """把存档快照转成 journal.py 兼容的 data dict。"""
    data = {}
    data["date"] = snap.get("date", "")
    data["year"] = snap.get("year")
    data["player"] = snap.get("player", "未知")
    # 玩家国家标识: 供 render_overview 从战争参与者中识别「我国」,
    # 避免把列强之间的战事误报成本国参战
    data["tag"] = snap.get("tag")
    data["player_country_id"] = snap.get("player_country_id")
    data["govt"] = snap.get("govt_zh") or gov_to_name(snap.get("govt", "other"))
    # 首都: 由首都 state 的 hub 名(城市)解析, 失败回退州域名; 不再让模型凭空猜测
    data["capital"] = snap.get("capital") or ""
    data["gdp"] = snap.get("gdp", "未知")
    data["pop"] = snap.get("total_population", "未知")
    data["sol"] = snap.get("avgsoltrend", "未知")
    data["literacy"] = snap.get("literacy", "未知")
    data["prestige"] = snap.get("prestige", "未知")
    data["religion"] = snap.get("religion", "未知")
    # 统治者: 姓名/头衔/意识形态/在位状态来自 character_manager 解析(见 ruler_info);
    # 首都名已由存档 state hub 解析(见 data["capital"])
    ri = snap.get("ruler_info") or {}
    data["ruler"] = ri.get("name") or ""
    data["ruler_title"] = ri.get("title") or ""
    data["ruler_ideology"] = ri.get("ideology")
    data["ruler_status"] = ri.get("status")
    data["ruler_activity"] = snap.get("ruler_activity")
    # 主流文化(国族): 来自国家对象的 primary cultures 列表(本地化中文名),
    # 与按人口占比排序的 pop_cultures 分开传递, 供社会板块提示词使用
    prim = []
    for c in (snap.get("cultures") or []):
        if isinstance(c, dict) and c.get("name"):
            prim.append(c["name"])
    data["primary_cultures"] = prim or None
    # 存档直读: laws 只含本年度变化的法律 (新施行 + 废除), 另附 enacted/repealed 明细
    data["laws"] = snap.get("laws") or []
    data["laws_enacted"] = snap.get("laws_enacted") or []
    data["laws_repealed"] = snap.get("laws_repealed") or []
    data["free_speech_law"] = snap.get("free_speech_law")
    data["techs"] = snap.get("techs") or []
    data["powers"] = snap.get("powers") or []
    data["treaties"] = snap.get("treaties") or []
    data["subjects"] = snap.get("subjects") or []
    data["rivals"] = snap.get("rivals") or []
    data["interest_groups"] = snap.get("interest_groups") or []
    data["political_movements"] = snap.get("political_movements") or []
    data["states"] = snap.get("states") or []
    data["events"] = []
    # 存档直读扩展字段
    data["literacy"] = snap.get("literacy")
    data["prestige"] = snap.get("prestige")
    data["pop_cultures"] = snap.get("pop_cultures")
    data["pop_religions"] = snap.get("pop_religions")
    data["professions"] = snap.get("professions")
    data["wars"] = snap.get("wars")
    # 新增: 激进派/效忠派占比 (占总人群), 家庭采访样本, 前一年本国战事
    data["radicals_pct"] = snap.get("radicals_pct")
    data["loyalists_pct"] = snap.get("loyalists_pct")
    data["family_interview"] = snap.get("family_interview")
    data["top_sol_peer"] = snap.get("top_sol_peer")
    data["unemployed_interview"] = snap.get("unemployed_interview")
    data["prev_year_wars"] = snap.get("prev_year_wars")
    data["last_year_wars"] = snap.get("last_year_wars")
    return data

def extract_full_snapshot(melted):
    """从熔化数据提取玩家完整快照 (精确数值 + 本年度法律变化 + pop占比 + 战争 + 政体中文)。"""
    country, meta, tag, cid = find_player_country(melted)
    snap = snapshot_from_country(country, meta)
    if not country:
        return snap
    snap["tag"] = tag
    snap["country_id"] = cid
    player_tag = tag or (country or {}).get("definition")
    snap["govt_zh"] = gov_to_name(snap.get("govt"))
    snap["capital"] = _capital_name(melted, country)
    # 法律: 只保留本年度内发生变化的法律 (新施行 + 废除), 不再输出全部现行法
    enacted, repealed = query_laws_changed(melted, cid, snap.get("date"))
    snap["laws_enacted"] = enacted
    snap["laws_repealed"] = repealed
    snap["laws"] = list(dict.fromkeys(enacted + repealed))
    snap["free_speech_law"] = next(
        (l for l in query_laws(melted, cid) if l in FREE_SPEECH_LAWS), None)
    snap["player_country_id"] = cid
    index, gp_ids, dp_index = _build_indexes(melted)
    names = load_current_country_names(melted, index)
    state_ids = (country or {}).get("states") or []
    pops = _aggregate_pops(melted, state_ids)
    prim_cultures = _get_primary_cultures(melted, state_ids)
    snap["states"] = _extract_player_states(melted, state_ids)
    mapped = []
    for i, c in enumerate(pops["cultures"]):
        cname = culture_id_to_name(c["name"])
        if cname:
            name = cname
        elif i < len(prim_cultures):
            name = prim_cultures[i]
        else:
            name = "（据国名常识补填）"
        mapped.append({"rank": str(i + 1), "name": name,
                       "count": c.get("count"), "pct": c.get("pct")})
    snap["pop_total"] = pops.get("total")
    snap["pop_cultures"] = mapped
    snap["pop_religions"] = pops["religions"]
    snap["professions"] = pops["professions"]
    snap["wars"] = parse_wars(melted, names, cid, index=index, gp_ids=gp_ids, dp_index=dp_index)
    # 前一年玩家国家发生的战争及结果
    snap["prev_year_wars"] = _prev_year_player_wars(snap.get("wars") or [], snap.get("year"))
    # 去年发生的战争(玩家/列强参战, 仅主要参加者), 供战事专电
    snap["last_year_wars"] = _last_year_wars(snap.get("wars") or [], snap.get("year"))
    # 单文件扫描一次建索引: 角色 / 建筑 / POP, 供首领、统治者与家庭采访复用
    chars = _player_characters(melted, cid)
    buildings_index = _buildings_by_state(melted, state_ids)
    pops_index = _pops_by_state(melted, state_ids)
    ig_slots = _country_ig_slots(melted, cid)
    building_map = _building_type_map(melted, state_ids)
    price_map = _market_price_map(melted, country)
    snap["interest_groups"] = _extract_interest_groups(melted, cid, chars=chars)
    snap["powers"] = _extract_powers(melted, names, index=index, gp_ids=gp_ids,
                                     player_id=cid, player_tag=player_tag)
    # 统治者: 用与利益集团首领相同的方式解析姓名/意识形态, 再据政体键读游戏头衔;
    # 程序侧拼装统治者活动 (走访类先定州, 供家庭采访联动)
    snap["ruler_info"] = _ruler_info(melted, cid, (country or {}).get("ruler"),
                                     snap.get("govt"), chars=chars)
    ruler_act, act_kind, visit_state = _assemble_ruler_activity(
        melted, snap, cid, buildings_index=buildings_index,
        building_type_map=building_map)
    snap["ruler_activity"] = ruler_act
    # 家庭采访样本: 随机州 → 随机建筑 → SoL 最低/最高两篇 + 条件失业篇
    # 走访联动: 只有完全合并(incorporation>=1)的州才与家庭采访同州取材;
    # 未合并/合并中的州另随机取材, 不把采访硬凑到走访州
    link_visit = (act_kind == "visit_pop" and visit_state is not None
                  and (_state_incorporation(melted, visit_state) or 0.0) >= 1.0)
    interview = _pick_interview_set(melted, state_ids, ig_slots, building_map, price_map,
                                    cid=cid, player_tag=player_tag,
                                    preferred_state=visit_state if link_visit else None,
                                    ruler_visited=link_visit,
                                    pops_index=pops_index, buildings_index=buildings_index)
    snap["family_interview"] = interview.get("family_interview")
    snap["top_sol_peer"] = interview.get("top_sol_peer")
    snap["unemployed_interview"] = interview.get("unemployed_interview")
    # 已研发科技 (单份存档无完成日期, 无法识别去年新研发; 上层用逐年 raw JSON 对比
    # 得出本年新增, 无新增时随机抽取; 本地化后供广告板块使用)
    loc = _load_loc_all()
    snap["techs"] = [loc.get(t, t) for t in _country_technologies(melted, cid)]
    # 激进派/效忠派占全国人口比例
    tot = snap.get("total_population") or 0
    ps = (country.get("pop_statistics") or {})
    if tot:
        snap["radicals_pct"] = round((ps.get("population_radicals") or 0) / tot * 100, 2)
        snap["loyalists_pct"] = round((ps.get("population_loyalists") or 0) / tot * 100, 2)
    snap["treaties"] = _extract_treaties(melted, names, index=index, gp_ids=gp_ids, player_id=cid)
    snap["subjects"] = _extract_subjects(melted, cid, names, index=index)
    snap["rivals"] = _extract_rivals(melted, cid, names, index=index)
    snap["political_movements"] = _extract_political_movements(
        melted, cid, state_ids, (country.get("pop_statistics") or {}),
        player_tag=player_tag)
    # 列强交战状态: 依据进行中战争的参与者
    gp_war_ids = {p.get("id") for w in snap["wars"] if not w.get("ended")
                  for p in w.get("participants", []) if p.get("rank") == "great_power"}
    tag_to_id = {e.get("definition"): cid for cid, e in index.items() if e.get("definition")}
    for pw in snap["powers"]:
        if tag_to_id.get(pw["definition"]) in gp_war_ids:
            pw["war"] = True
    return snap

def _extract_powers(data, names, index=None, gp_ids=None, player_id=None, player_tag=None):
    """提取列强名单: prestige 排名前 8 (V3 列强由声望动态决定)。
    player_id/player_tag 用于标注玩家所在国 (is_player=True)。"""
    if index is None or gp_ids is None:
        index, gp_ids, _ = _build_indexes(data)
    powers = []
    ranked = sorted([cid for cid, e in index.items()
                     if e.get("prestige") is not None],
                    key=lambda c: -index[c]["prestige"])
    for cid in ranked[:8]:
        entry = index[cid]
        tag = entry.get("definition")
        if not tag:
            continue
        powers.append({"name": names.get(tag, tag), "definition": tag,
                       "war": False, "prestige": entry.get("prestige"),
                       "is_player": (player_id is not None and cid == player_id)
                                    or bool(player_tag and tag == player_tag)})
    return powers

# 附庸关系类型: pacts.database 中 first=宗主, second=附庸
SUBJECT_ACTIONS = {"colony", "dominion", "protectorate", "puppet", "tributary",
                   "vassal", "crown_land", "chartered_company", "personal_union"}

def _iter_pacts(data):
    """迭代 pacts.database 中的所有 pact 对象 (限制在 pacts manager 范围内)。"""
    pc = data.find(b'"pacts"')
    if pc < 0:
        return
    pact_end = _object_end(data, data.find(b'{', pc))
    pdb = data.find(b'"database"', pc)
    j = data.find(b'{', pdb)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, pact_end - 1)
        if not m:
            return
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("targets"):
            yield obj
        j = end

# ---------------------------------------------------------------------------
# 条约 (treaty_manager.database)
# ---------------------------------------------------------------------------

_TREATY_ZH = None

def _load_treaty_names():
    """加载 treaty_name_* 本地化 → 中文条约名 (游戏+mod, 后加载覆盖)。"""
    global _TREATY_ZH
    if _TREATY_ZH is not None:
        return _TREATY_ZH
    zh = {}
    for base in _loc_dirs():
        if not os.path.isdir(base):
            continue
        for root, _sub, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".yml"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8-sig",
                              errors="replace") as fp:
                        for line in fp:
                            # 允许行尾带注释 (如 "$SIGNING_LOCATION$妥协" # 备注)
                            m = re.match(
                                r"\s*(treaty_name_[a-z_0-9]+):\s*\"([^\"]+)\"\s*(?:#.*)?$",
                                line)
                            if m:
                                zh[m.group(1)] = m.group(2).strip()
                except Exception:
                    continue
    _TREATY_ZH = zh
    return zh

def _v3_num_date(n):
    """V3 内部数字日期(自纪元起小时数) → "Y.M.D" 字符串。
    格式: n = ((Y-1)*365 + (M-1)*30 + (D-1) + 1825365) * 24
    实测: 1372.1.1→55818720, 1554.1.1→57413040, 1604.1.15→57851376。"""
    try:
        days = int(n) // 24 - 1825365
        y = days // 365 + 1
        rem = days % 365
        m = rem // 30 + 1
        d = rem % 30 + 1
        return f"{y}.{m}.{d}"
    except Exception:
        return str(n)

# 条款类型 → 中文 (优先加载本地化 concept_*, 缺的硬编码兜底)
ARTICLE_ZH_FALLBACK = {
    "defensive_pact": "共同防御",
    "military_assistance": "军事援助",
    "foreign_investment_rights": "外国投资权",
    "trade_privilege": "贸易特权",
    "goods_transfer": "货物移交",
    "guarantee_independence": "独立保障",
    "military_access": "军事通行权",
    "transit_rights": "过境权",
    "treaty_port": "条约港",
    "money_transfer": "金钱移交",
    "law_commitment": "法律承诺",
    "support_independence": "支持独立",
    "host_power_bloc_embassy": "东道国集团使馆",
    "no_tolls": "免通行费",
}
ARTICLE_CONCEPT_MAP = {
    "defensive_pact": "concept_defensive_pact",
    "military_assistance": "concept_military_assistance",
    "foreign_investment_rights": "concept_foreign_investment",
    "trade_privilege": "concept_trade_privilege",
    "guarantee_independence": "concept_guarantee_independence",
    "treaty_port": "concept_treaty_port",
    "military_access": "concept_military_access",
}
ARTICLE_GOODS = {
    "grain": "谷物", "fish": "鱼", "fruit": "水果", "livestock": "牲畜",
    "food": "食物", "groceries": "杂货", "sugar": "糖", "tea": "茶叶",
    "coffee": "咖啡", "liquor": "烈酒", "wine": "葡萄酒", "tobacco": "烟草",
    "opium": "鸦片", "silk": "丝绸", "cotton": "棉花", "wool": "羊毛",
    "dye": "染料", "wood": "木材", "cloth": "布料", "fabric": "织物",
    "clothes": "成衣", "furniture": "家具", "iron": "铁", "coal": "煤",
    "steel": "钢", "tools": "工具", "lead": "铅", "sulfur": "硫磺",
    "glass": "玻璃", "porcelain": "瓷器", "paper": "纸张",
    "small_arms": "轻武器", "artillery": "火炮", "ammunition": "弹药",
    "ships": "船舶", "engines": "引擎", "fertilizer": "化肥", "oil": "石油",
    "rubber": "橡胶", "services": "服务业", "transportation": "交通",
}

_CONCEPT_ZH = None

def _concept_zh():
    """加载本地化 concept_* 中文名。"""
    global _CONCEPT_ZH
    if _CONCEPT_ZH is not None:
        return _CONCEPT_ZH
    zh = {}
    loc_dir = GAME_LOCALIZATION
    try:
        for fn in os.listdir(loc_dir):
            if not fn.endswith(".yml"):
                continue
            with open(os.path.join(loc_dir, fn), encoding="utf-8-sig", errors="replace") as fp:
                for line in fp:
                    m = re.match(r"\s*(concept_[a-z_]+):\s*\"([^\"]+)\"\s*$", line)
                    if m and "$" not in m.group(2) and "[" not in m.group(2):
                        zh[m.group(1)] = m.group(2).strip()
    except Exception:
        pass
    _CONCEPT_ZH = zh
    return zh

def _article_zh(article_type):
    """条款类型 → 中文名。
    daoyu_treaty_articles 等修改器强制条款及无法识别本地化的条款, 一律写"下文略"。"""
    concept = ARTICLE_CONCEPT_MAP.get(article_type)
    if concept:
        zh = _concept_zh().get(concept)
        if zh:
            return zh
    return ARTICLE_ZH_FALLBACK.get(article_type) or "下文略"

def _iter_treaty_articles(data):
    """迭代 treaty_article_manager.database 的所有条款对象 (限范围)。"""
    ta = data.find(b'"treaty_article_manager"')
    if ta < 0:
        return
    ta_end = _object_end(data, data.find(b'{', ta))
    tdb = data.find(b'"database"', ta)
    j = data.find(b'{', tdb)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, ta_end - 1)
        if not m:
            return
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("article") is not None:
            yield obj
        j = end

def _article_detail(a):
    """条款附加数据 → 中文描述 (货物/金钱/法律等)。
    inputs 为键值对列表(如 [{"goods": X}, {"quantity": N}]), 成对拼成"轻武器15单位"。"""
    inputs = (a.get("inputs") or [])
    if not inputs:
        return None
    goods = qty = law = state = None
    for it in inputs:
        if not isinstance(it, dict):
            continue
        if "goods" in it:
            goods = ARTICLE_GOODS.get(it["goods"], it["goods"])
        elif "quantity" in it:
            qty = it["quantity"]
        elif "law_type" in it:
            law = it["law_type"].replace("law_", "")
        elif "state" in it:
            state = it["state"]
    if goods is not None:
        return f"{goods}{qty}单位" if qty is not None else goods
    if law is not None:
        return f"施行法律{law}"
    if state is not None:
        return f"州{state}"
    if qty is not None:
        return f"{qty}单位"
    return None


def _region_hub_names(data):
    """扫描 states.database → {州域key: [hub名×5]} (city/port/farm/mine/wood 顺序)。
    同一州域多个州对象时, 优先 hub 名非空者, 同况取较小州 id (确定性)。"""
    out = {}
    sd = data.find(b'"states":{"database"')
    if sd < 0:
        return out
    db = data.find(b'"database"', sd)
    sob = data.find(b'{', db)
    so_end = _object_end(data, sob)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = sob
    while True:
        m = _IDOBJ.search(data, j, so_end - 1)
        if not m:
            break
        sid = int(m.group(1))
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and isinstance(obj.get("region"), str):
            rk = obj["region"]
            names = _hub_names(obj)
            cur = out.get(rk)
            if cur is None:
                out[rk] = [sid, names]
            else:
                cur_sid, cur_names = cur
                cur_ok = any(n for n in cur_names)
                new_ok = any(n for n in names)
                if new_ok and (not cur_ok or sid < cur_sid):
                    out[rk] = [sid, names]
        j = end
    return {rk: names for rk, (_sid, names) in out.items()}


def _signing_location(region_hubs, region, hub):
    """$SIGNING_LOCATION$ → 签约地中文名; 解析不了返回 None。
    优先该州域对应 hub 名 (玩家改名/本地化), 回退州域名 (如 莫斯科)。"""
    if not region:
        return None
    idx = HUB_ORDER.index(hub) if hub in HUB_ORDER else 0
    names = (region_hubs or {}).get(region) or []
    if idx < len(names) and names[idx]:
        loc = names[idx]
        # 个别 hub 名是未解析的本地化键 (如 HUB_NAME_STATE_X_city_southern_bantu), 跳过
        if not loc.startswith(("HUB_NAME_", "STATE_")) \
                and not re.fullmatch(r"[A-Z][A-Z0-9_]*", loc):
            return loc
    return _load_loc_all().get(region)


def _render_treaty_name(data, treaty_obj, fname, sname, get_region_hubs):
    """条约 name 对象 → 中文名 (无则 None)。
    custom 字面直出; scripted/dynamic 查本地化并渲染占位符:
      $SIGNING_LOCATION$ (签约地) / $SIGNING_MONTH$ (签约月)
      [FIRST/SECOND_COUNTRY.GetName/GetAdjectiveNoFormatting] (缔约方中文名)
      [FIRST_COUNTRY.GetRuler.GetPrimaryRoleTitle] (略去)
    地点名每次熔化时按当时州 hub 数据现读, 不做跨存档定格。"""
    nm = treaty_obj.get("name") or {}
    cust = (nm.get("custom") or {}).get("custom_name")
    if cust:
        return cust
    dyn = nm.get("dynamic") or {}
    key = ((nm.get("scripted") or {}).get("scripted_name")
           or dyn.get("dynamic_name") or "")
    if not key:
        return None
    zh = _load_treaty_names().get(key, "")
    if not zh:
        return None
    ctx = dyn.get("context") or {}
    if "$SIGNING_LOCATION$" in zh:
        region_hubs = get_region_hubs()
        loc = _signing_location(region_hubs, ctx.get("region"), ctx.get("hub"))
        if not loc:
            return None
        zh = zh.replace("$SIGNING_LOCATION$", loc)
    if "$SIGNING_MONTH$" in zh:
        parts = str(ctx.get("date", "")).split(".")
        if len(parts) > 1 and parts[1].isdigit():
            zh = zh.replace("$SIGNING_MONTH$", f"{int(parts[1])}月")
        else:
            zh = zh.replace("$SIGNING_MONTH$", "")
    for ph, v in (
            ("[FIRST_COUNTRY.GetNameNoFormatting]", fname),
            ("[SECOND_COUNTRY.GetNameNoFormatting]", sname),
            ("[FIRST_COUNTRY.GetAdjectiveNoFormatting]", fname),
            ("[SECOND_COUNTRY.GetAdjectiveNoFormatting]", sname),
            ("[FIRST_COUNTRY.GetRuler.GetPrimaryRoleTitle]", ""),
            ("[SECOND_COUNTRY.GetRuler.GetPrimaryRoleTitle]", "")):
        zh = zh.replace(ph, v)
    zh = zh.replace("\u2011", "-").strip(" \t-‐")
    if not zh or "$" in zh or "[" in zh or "]" in zh:
        return None
    return zh


def _extract_treaties(data, names, index=None, gp_ids=None, player_id=None):
    """从 treaty_manager.database 提取**与玩家有关**的条约及条款内容。
    返回 [{id, name(中文), first_name, second_name, date, articles:[{zh, from, to, detail}]}]。
    name 由 custom/scripted/dynamic 渲染; 地点类条约 (如"莫斯科公约") 按当时州 hub
    数据现读, 国名/城市名随存档变化不跨存档定格。
    只保留玩家参与(任一方是玩家)的条约; 其余世界条约(中葡/日荷等)不输出。
    条款来自 treaty_article_manager (article类型 + source/target方向 + goods_transfer 等数据)。"""
    if index is None or gp_ids is None:
        index, gp_ids, _ = _build_indexes(data)
    treaties = []
    # 州域→hub名 映射: 仅在遇到 $SIGNING_LOCATION$ 模板时惰性构建一次
    _region_hubs = {}
    _hubs_loaded = [False]

    def get_region_hubs():
        if not _hubs_loaded[0]:
            _region_hubs.update(_region_hub_names(data))
            _hubs_loaded[0] = True
        return _region_hubs

    tm = data.find(b'"treaty_manager"')
    if tm < 0:
        return treaties
    tm_end = _object_end(data, data.find(b'{', tm))
    tdb = data.find(b'"database"', tm)
    j = data.find(b'{', tdb)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    # 先收集玩家条约 id
    player_tids = set()
    while True:
        m = _IDOBJ.search(data, j, tm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and "first_country" in obj:
            f, s = obj.get("first_country"), obj.get("second_country")
            if player_id is not None and player_id in (f, s):
                player_tids.add(int(m.group(1)))
        j = end
    if not player_tids:
        return treaties
    # 收集条款: treaty_id → [articles]
    tarticles = {}
    for a in _iter_treaty_articles(data):
        tid = a.get("treaty")
        if tid in player_tids:
            tarticles.setdefault(tid, []).append(a)
    # 第二次遍历提取玩家条约
    j = data.find(b'{', tdb)
    while True:
        m = _IDOBJ.search(data, j, tm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if not isinstance(obj, dict) or "first_country" not in obj:
            j = end
            continue
        f, s = obj.get("first_country"), obj.get("second_country")
        if player_id is None or player_id not in (f, s):
            j = end
            continue
        fname = names.get((index.get(f) or {}).get("definition"),
                          (index.get(f) or {}).get("definition") or str(f))
        sname = names.get((index.get(s) or {}).get("definition"),
                          (index.get(s) or {}).get("definition") or str(s))
        tname = _render_treaty_name(data, obj, fname, sname, get_region_hubs)
        raw_date = obj.get("entered_into_force_on", "")
        date = _v3_num_date(raw_date) if isinstance(raw_date, (int, float)) else str(raw_date)
        tid = int(m.group(1))
        articles = []
        for a in tarticles.get(tid, []):
            azh = _article_zh(a.get("article"))
            if azh == "下文略":
                # 修改器强制条款/无法识别条款: 无内容无方向, 仅写"下文略"
                articles.append({"zh": azh, "from": None, "to": None, "detail": None})
                continue
            src = a.get("source_country")
            tgt = a.get("target_country")
            detail = _article_detail(a)
            articles.append({
                "zh": azh,
                "from": names.get((index.get(src) or {}).get("definition"),
                                  str(src)) if src and src != 4294967295 else None,
                "to": names.get((index.get(tgt) or {}).get("definition"),
                                str(tgt)) if tgt and tgt != 4294967295 else None,
                "detail": detail,
            })
        treaties.append({
            "id": str(tid),
            "name": tname or f"{fname}与{sname}之条约",
            "first_name": fname, "second_name": sname,
            "date": date,
            "articles": articles,
        })
        j = end
    return treaties


def _extract_subjects(data, player_id, names, index=None):
    """从 pacts.database 提取玩家的附庸国 (first=宗主, second=附庸)。
    返回 [{name, type, country_id}]。"""
    subs = []
    if not player_id:
        return subs
    if index is None:
        index, _, _ = _build_indexes(data)
    for pact in _iter_pacts(data):
        act = pact.get("action")
        if act not in SUBJECT_ACTIONS:
            continue
        tg = pact.get("targets") or {}
        if tg.get("first") != player_id:
            continue
        sub_id = tg.get("second")
        if sub_id is None:
            continue
        entry = index.get(sub_id) or {}
        tag = entry.get("definition")
        subs.append({"name": names.get(tag, tag) if tag else str(sub_id),
                     "type": act, "country_id": sub_id})
    return subs


def _extract_rivals(data, player_id, names, index=None):
    """从 pacts.database 提取玩家的宿敌 (rivalry pact, 任一方是玩家)。
    返回 [{name, definition, country_id}]，按 pact 出现顺序去重。"""
    rivals = []
    if not player_id:
        return rivals
    if index is None:
        index, _, _ = _build_indexes(data)
    seen = set()
    for pact in _iter_pacts(data):
        if pact.get("action") != "rivalry":
            continue
        tg = pact.get("targets") or {}
        f, s = tg.get("first"), tg.get("second")
        if f != player_id and s != player_id:
            continue
        other = s if f == player_id else f
        if other in seen or other is None:
            continue
        seen.add(other)
        entry = index.get(other) or {}
        tag = entry.get("definition")
        rivals.append({
            "name": names.get(tag, tag) if tag else str(other),
            "definition": tag,
            "country_id": other,
        })
    return rivals


def _extract_interest_groups(data, player_id, chars=None):
    """从 interest_groups.database 提取玩家全部利益集团。
    返回按 clout 降序的 [{name, definition, clout_pct, in_government, approval_state,
    leader_name, leader_ideology}]。chars 可由调用方复用 _player_characters 结果,
    避免与统治者解析重复扫描 character_manager。
    in_government=True 的即当前执政(组阁)利益集团。"""
    groups = []
    if not player_id:
        return groups
    if chars is None:
        chars = _player_characters(data, player_id)
    loc = _load_loc_all()
    idx = data.find(b'"interest_groups"')
    if idx < 0:
        return groups
    ig_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return groups
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = data.find(b'{', db)
    while True:
        m = _IDOBJ.search(data, j, ig_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if (isinstance(obj, dict) and obj.get("country") == player_id
                and obj.get("definition")):
            clout = obj.get("clout")
            leader = chars.get(obj.get("leader")) if obj.get("leader") is not None else None
            lideo = (leader or {}).get("ideology")
            groups.append({
                "name": obj.get("name") or obj.get("definition"),
                "definition": obj.get("definition"),
                "clout_pct": round(clout * 100, 1) if isinstance(clout, (int, float)) else None,
                "in_government": bool(obj.get("in_government")),
                "approval_state": obj.get("approval_state"),
                "leader_name": (leader or {}).get("name"),
                "leader_ideology": (_clean_loc_name(loc.get(lideo, lideo), loc)
                                    if lideo else None),
            })
        j = end
    groups.sort(key=lambda g: -(g.get("clout_pct") or 0))
    return groups

def ensure_fresh_melt():
    """强制用最新存档重新熔化, 返回 (melted_bytes, err)。"""
    v3 = find_latest_v3()
    if not v3:
        return None, "未找到存档"
    path, err = melt_with_rakaly(v3, force=True)
    if err:
        return None, err
    try:
        with open(MELT_CACHE, "rb") as fp:
            return fp.read(), None
    except Exception as e:
        return None, f"读取失败: {e}"

def make_newspaper(year=None, force=True, melted=None, snap=None):
    """用存档数据生成报纸 (复用 journal.py)。
    melted/snap 由调用方已熔化/解析时可直接传入, 避免同一年份重复熔化解析。"""
    import journal
    if snap is None:
        if melted is None:
            data = ensure_fresh_melt()
            if data[1]:
                print(data[1])
                return 1
            melted, _ = data
        snap = extract_full_snapshot(melted)
    if year and snap.get("year") != year:
        print(f"存档年份 {snap.get('year')} 与请求 {year} 不符")
    cfg = journal.load_config()
    # 首次确定文件夹: 检查根目录同名文件夹, 有则加数字(大南、大南2...); 同局沿用
    if not journal.SESSION["folder"]:
        with journal._FOLDER_LOCK:
            if not journal.SESSION["folder"]:
                journal.SESSION["folder"] = journal.determine_folder(
                    snap.get("player") or "未知名国家", cfg["journal_dir"])
    # 存档层落盘: 补回上一年存档中的「去年战争」(V3 war_manager 只保留进行中战争)
    _merge_prev_year_wars(snap, cfg["journal_dir"], journal.SESSION["folder"])
    jdata = build_journal_data(snap)
    journal.on_block_complete(jdata, cfg, force=force)
    print("报纸生成完成")
    return 0

def _generate_async(year, snap):
    """后台线程: 生成某年报纸, 不阻塞存档监控循环。"""
    try:
        make_newspaper(year=year, force=True, snap=snap)
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {year} 年报纸生成失败: {e}")

# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def cmd_check():
    v3 = find_latest_v3()
    if not v3:
        print("未找到存档。"); return 1
    print(f"存档: {v3}")
    print(f"  rakaly: {'已就绪 ' + RAKALY if os.path.exists(RAKALY) else '未找到, 请下载到 ' + RAKALY}")
    if os.path.exists(MELT_CACHE):
        print(f"  melt 缓存: {MELT_CACHE} ({os.path.getsize(MELT_CACHE)/1e6:.0f} MB)")
    else:
        print("  melt 缓存: 无 (运行 'melt' 生成)")
    return 0

def cmd_melt():
    v3 = find_latest_v3()
    if not v3: print("未找到存档。"); return 1
    path, err = melt_with_rakaly(v3, force=True)
    if err: print(f"熔化失败: {err}"); return 1
    return 0

def cmd_sniff():
    melted, err = ensure_fresh_melt()
    if err: print(err); return 1
    snap = extract_full_snapshot(melted)
    print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
    return 0

def cmd_watch(continue_mode=False):
    import journal
    cfg = journal.load_config()
    print("监控存档中 (只处理本程序启动后保存的存档)...")
    print("启动时记录基准, 之后检测到存档更新才处理; 玩家变化视为新局。")
    # 启动基准: 忽略已有的旧存档, 只处理之后写入的
    baseline = None
    try:
        v0 = find_latest_v3()
        if v0:
            baseline = os.path.getmtime(v0)
            print(f"  基准存档: {os.path.basename(v0)} ({datetime.fromtimestamp(baseline).strftime('%H:%M:%S')})")
            print("  之后保存的新存档才会被处理(避免读老存档)。")
    except Exception:
        pass
    # continue 模式: 沿用该国家最新会话文件夹; 当前年份报纸缺失则先用当前存档补生成
    if continue_mode:
        melted, err = ensure_fresh_melt()
        if err:
            print(err)
            return 1
        snap = extract_full_snapshot(melted)
        player = snap.get("player") or "未知名国家"
        folder = journal.find_latest_session_folder(player, cfg["journal_dir"])
        if folder:
            journal.SESSION["folder"] = folder
            print(f"续传模式: 沿用最新文件夹 [{folder}]")
        else:
            journal.SESSION["folder"] = journal.determine_folder(player, cfg["journal_dir"])
            print(f"续传模式: 未找到 {player} 的历史文件夹, 将新建 [{journal.SESSION['folder']}]")
        year = snap.get("year")
        if year:
            md_path = os.path.join(cfg["journal_dir"], journal.SESSION["folder"],
                                   f"报纸_{year}.md")
            if not os.path.exists(md_path):
                print(f"续传模式: {year} 年报纸缺失, 先用当前存档补生成")
                make_newspaper(year=year, force=True, melted=melted, snap=snap)
            else:
                print(f"续传模式: {year} 年报纸已存在, 进入监控等待下一年。")
    last_mtime = None
    last_year = None
    last_player = None
    while True:
        try:
            v3 = find_latest_v3()
            if v3:
                mt = os.path.getmtime(v3)
                if mt != last_mtime and (baseline is None or mt > baseline + 3):
                    last_mtime = mt
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到新存档, 重新熔化...")
                    melted = ensure_fresh_melt()
                    if melted[1]:
                        print(f"  熔化失败: {melted[1]}")
                    else:
                        snap = extract_full_snapshot(melted[0])
                        player = snap.get("player")
                        year = snap.get("year")
                        if player and player != last_player:
                            print(f"  玩家: {player} (新局或换国)")
                            last_player = player
                        if year is not None and year != last_year:
                            print(f"  新年份 {year}, 后台生成报纸 (不阻塞监控)")
                            threading.Thread(target=_generate_async,
                                             args=(year, snap), daemon=True).start()
                            last_year = year
                        else:
                            print(f"  年份 {year} 未变, 跳过(避免重复)")
            time.sleep(30)
        except KeyboardInterrupt:
            print("已停止。"); return 0
        except Exception as e:
            print(f"出错: {e}"); time.sleep(30)

def cmd_continue():
    return cmd_watch(continue_mode=True)

def main():
    cmds = {"check": cmd_check, "melt": cmd_melt, "sniff": cmd_sniff,
            "newspaper": make_newspaper, "watch": cmd_watch,
            "continue": cmd_continue}
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    if cmd not in cmds:
        print("可用: check | melt | sniff | newspaper [年份] | watch | continue"); return 1
    kwargs = {}
    if cmd == "newspaper" and args:
        kwargs["year"] = int(args[0]) if args[0].isdigit() else None
    return cmds[cmd](**kwargs)

if __name__ == "__main__":
    sys.exit(main())
