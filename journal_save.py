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
  python journal_save.py magazine <年份>   用存档数据生成一份杂志 (magazine.py)
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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
    n = len(data)
    while True:
        q = data.find(b'"', j, n)
        if q < 0:
            return n
        bs = 0
        k = q - 1
        while k >= j and data[k] == 0x5c:
            bs += 1
            k -= 1
        if bs % 2 == 0:
            return q + 1
        j = q + 1

def extract_json_object(data, open_brace_idx):
    """从 '{' 起匹配完整 JSON 对象, 返回 (bytes, end_idx)。"""
    end = _object_end(data, open_brace_idx)
    if end <= open_brace_idx + 1:
        return None, len(data)
    return data[open_brace_idx:end], end

def _object_end(data, brace_idx):
    """只计算 '{' 起完整 JSON 对象的结束位置 (不复制数据)。"""
    depth = 0
    j = brace_idx
    n = len(data)
    while True:
        lb = data.find(b'{', j, n)
        rb = data.find(b'}', j, n)
        q = data.find(b'"', j, n)
        cand = [x for x in (lb, rb, q) if x >= 0]
        if not cand:
            return n
        nxt = min(cand)
        c = data[nxt]
        if c == 0x22:
            j = _skip_string(data, nxt)
            continue
        if c == 0x7b:
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return nxt + 1
        j = nxt + 1

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
GAME_DIR = os.path.dirname(os.path.dirname(GAME_LOCALIZATION))
MAP_EDITOR_STATUS = os.path.join(GAME_DIR, "tools", "mapeditor",
                                 "map_editor_status.txt")
STATE_REGIONS_DIR = os.path.join(GAME_DIR, "map_data", "state_regions")

_NAME_CACHE = None
_LOC_ALL = None
_LOC_PLACEHOLDER_RE = re.compile(r"\$[A-Za-z_][A-Za-z_0-9-]*\$")
_PROVINCE_ID_BY_COLOR = None
_REGION_HUB_KEYS = None
_PROVINCE_HUB_TYPES = None

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
                            m = re.match(r"\s*([A-Za-z_][A-Za-z_0-9-]*)(?::\d+)?:\s*\"([^\"]+)\"\s*(?:#.*)?$",
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
        if not entry.get("is_main_tag"):
            continue
        if tag and dyn_key and loc.get(dyn_key):
            names[tag] = _resolve_country_dyn_name(tag, dyn_key, loc) or names[tag]
    return names

# ---------------------------------------------------------------------------
# 玩家国家提取
# ---------------------------------------------------------------------------

def _country_adjective_zh(tag, loc):
    if not tag:
        return None
    v = loc.get(f"{tag}_ADJ")
    if not v:
        return None
    return _clean_loc_name(v, loc)


def _resolve_country_dyn_name(tag, dyn_key, loc):
    if not dyn_key:
        return None
    v = loc.get(dyn_key)
    if not v:
        return None
    if "$ADJECTIVE$" in v:
        adj = _country_adjective_zh(tag, loc)
        if adj:
            v = v.replace("$ADJECTIVE$", adj)
        else:
            v = _LOC_PLACEHOLDER_RE.sub("", v)
            v = re.sub(r"\$+", "", v)
            return v.strip() or None
    return _clean_loc_name(v, loc)


def build_country_id_names(data, index=None):
    if index is None:
        index, _, _ = _build_indexes(data)
    tag_names = load_current_country_names(data, index)
    loc = _load_loc_all()
    out = {}
    for cid, e in index.items():
        tag = e.get("definition")
        dyn = e.get("dyn_name")
        nm = None
        if dyn and loc.get(dyn):
            nm = _resolve_country_dyn_name(tag, dyn, loc)
        out[cid] = nm if nm else (tag_names.get(tag) if tag else str(cid))
    return out


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


def _find_country_by_id(data, cid):
    """在 country_manager.database 中按国家 id 找国家对象, 返回 obj 或 None。"""
    if cid is None:
        return None
    cm = data.find(b'"country_manager"')
    if cm < 0:
        return None
    cm_brace = data.find(b'{', cm)
    cm_end = _object_end(data, cm_brace)
    db = data.find(b'"database"', cm)
    if db < 0 or db > cm_end:
        return None
    j = data.find(b'{', db)
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    while True:
        m = _IDOBJ.search(data, j, cm_end - 1)
        if not m:
            return None
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(data, ob2)
        if not raw:
            return None
        if int(m.group(1)) != cid:
            j = end
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None


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
    infamy = country.get("infamy")
    # V3 存档省略值为 0 的字段: 恶名为 0 时 country 对象没有 infamy 键,
    # 缺省按 0 处理, 避免渲染层收到 None
    snap["infamy"] = round(infamy, 1) if isinstance(infamy, (int, float)) else 0.0
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
    # key → 中文名 (本地化; 兼容数字/连字符 key, 并含 mod 覆盖)
    zh = {}
    for loc_dir in _loc_dirs():
        try:
            for fn in os.listdir(loc_dir):
                if not fn.endswith(".yml"):
                    continue
                with open(os.path.join(loc_dir, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    for line in fp:
                        m = re.match(
                            r"\s*([a-z0-9_-]+):\s*\"([^\"]+)\"\s*(?:#.*)?$", line)
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
    """本土定义目录: 原版 + 当前 playset 已启用的 mod (mod 覆盖原版)。
    只读取 content_load.json 的 enabledMods, 避免把已安装但未启用的 mod
    (如 Divergences) 的本土定义混入, 导致与游戏内实际生效不一致。"""
    dirs = [HOMELAND_STATES_DIR]
    for base in _enabled_mod_dirs():
        p = os.path.join(base, "common", "history", "states")
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
    for loc_dir in _loc_dirs():
        try:
            for fn in os.listdir(loc_dir):
                if not fn.endswith(".yml"):
                    continue
                with open(os.path.join(loc_dir, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    for line in fp:
                        m = re.match(
                            r"\s*([a-z0-9_-]+):\s*\"([^\"]+)\"\s*(?:#.*)?$", line)
                        if m and m.group(1) in order:
                            zh[m.group(1)] = m.group(2).strip()
        except Exception:
            pass
    _GOODS_CACHE = {"order": order, "cost": cost, "zh": zh}
    return _GOODS_CACHE


# ---------------------------------------------------------------------------
# 工业品产业链 (游戏 common 数据): 建筑 → PM组 → 生产方法 → 投入/产出商品。
# 供「从货架里长出来的」只选「至少经过两个环节」的加工品,
# 保证有上游原料建筑可写 (如 铁矿→铁→工具 / 谷物→加工食品)。
# ---------------------------------------------------------------------------

BUILDINGS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\buildings"
PM_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\production_methods"
PMG_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\production_method_groups"
INDUSTRIAL_BUILDING_GROUPS = ("bg_manufacturing", "bg_light_industry",
                              "bg_heavy_industry", "bg_military_industry")

_GOODS_CHAIN_CACHE = None
_CONSUMER_GOODS_CACHE = None
_PM_EMPLOYMENT_CACHE = None
POP_NEEDS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\pop_needs"


def _parse_braced_blocks(text):
    """把 paradox 文本里 name = { ... } 顶层块拆成 (name, 块内文本)。"""
    n = len(text)
    i = 0
    while i < n:
        m = re.search(r"^([a-z0-9_]+)\s*=\s*\{", text[i:], re.M)
        if not m:
            break
        name = m.group(1)
        start = i + m.end() - 1
        depth = 0
        j = start
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield name, text[start + 1:j]
        i = j + 1


def _game_dirs(vanilla, sub):
    """解析游戏数据时扫描的目录: 原版 + 已启用 mod 的对应子目录 (mod 覆盖原版)。"""
    dirs = [vanilla]
    for base in _enabled_mod_dirs():
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            dirs.append(p)
    return dirs


def _load_goods_chain():
    """解析建筑/生产方法 → ({good: {producers, inputs}}, industrial_goods)。
    只统计工业分组建筑的生产方法; industrial_goods = 有原料投入的产出品。"""
    global _GOODS_CHAIN_CACHE
    if _GOODS_CHAIN_CACHE is not None:
        return _GOODS_CHAIN_CACHE
    import glob as _glob
    building_groups = {}
    for d in _game_dirs(BUILDINGS_DIR, "common/buildings"):
        for fn in _glob.glob(os.path.join(d, "*.txt")):
            try:
                text = open(fn, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            for name, body in _parse_braced_blocks(text):
                if not name.startswith("building_"):
                    continue
                group = re.search(r"\bbuilding_group\s*=\s*([a-z0-9_]+)", body)
                pmgs = re.search(r"\bproduction_method_groups\s*=\s*\{(.*?)\}",
                                 body, re.S)
                building_groups[name] = {
                    "group": group.group(1) if group else "",
                    "pmgs": re.findall(r"([a-z0-9_]+)", pmgs.group(1))
                            if pmgs else [],
                }
    pmg_to_pms = {}
    for d in _game_dirs(PMG_DIR, "common/production_method_groups"):
        for fn in _glob.glob(os.path.join(d, "*.txt")):
            try:
                text = open(fn, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            for name, body in _parse_braced_blocks(text):
                m = re.search(r"\bproduction_methods\s*=\s*\{(.*?)\}", body, re.S)
                if m:
                    pmg_to_pms[name] = re.findall(r"([a-z0-9_]+)", m.group(1))
    pm_io = {}
    for d in _game_dirs(PM_DIR, "common/production_methods"):
        for fn in _glob.glob(os.path.join(d, "*.txt")):
            try:
                text = open(fn, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            for name, body in _parse_braced_blocks(text):
                ins, outs = set(), set()
                for m in re.finditer(r"goods_input_([a-z0-9_]+)_add\s*=\s*(-?[0-9.]+)",
                                     body):
                    try:
                        if float(m.group(2)) > 0:
                            ins.add(m.group(1))
                    except ValueError:
                        pass
                for m in re.finditer(r"goods_output_([a-z0-9_]+)_add\s*=\s*(-?[0-9.]+)",
                                     body):
                    try:
                        if float(m.group(2)) > 0:
                            outs.add(m.group(1))
                    except ValueError:
                        pass
                if ins or outs:
                    pm_io[name] = {"inputs": ins, "outputs": outs}
    chain = {}
    for bname, b in building_groups.items():
        if b["group"] not in INDUSTRIAL_BUILDING_GROUPS:
            continue
        ins, outs = set(), set()
        for pmg in b["pmgs"]:
            for pm in pmg_to_pms.get(pmg, []):
                io = pm_io.get(pm)
                if io:
                    ins |= io["inputs"]
                    outs |= io["outputs"]
        for g in outs:
            chain.setdefault(g, {"producers": set(), "inputs": set()})
            chain[g]["producers"].add(bname)
            chain[g]["inputs"] |= ins
    industrial = {g for g, info in chain.items() if info["inputs"]}
    _GOODS_CHAIN_CACHE = (chain, industrial)
    return _GOODS_CHAIN_CACHE


def _load_consumer_goods():
    """pop 可直接消费的商品集合 (common/pop_needs 的 goods/default 字段)。"""
    global _CONSUMER_GOODS_CACHE
    if _CONSUMER_GOODS_CACHE is not None:
        return _CONSUMER_GOODS_CACHE
    goods = set()
    import glob as _glob
    for d in _game_dirs(POP_NEEDS_DIR, "common/pop_needs"):
        for fn in _glob.glob(os.path.join(d, "*.txt")):
            try:
                text = open(fn, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            goods |= set(re.findall(r"(?:^|\s)(?:goods|default)\s*=\s*([a-z_]+)",
                                    text))
    _CONSUMER_GOODS_CACHE = goods
    return goods


def _load_pm_employment():
    """生产方法 → {职业: 每级雇佣数}: 解析 building_modifiers.level_scaled 中
    building_employment_<type>_add (每级满编雇佣, 游戏文件口径)。"""
    global _PM_EMPLOYMENT_CACHE
    if _PM_EMPLOYMENT_CACHE is not None:
        return _PM_EMPLOYMENT_CACHE
    out = {}
    import glob as _glob
    for d in _game_dirs(PM_DIR, "common/production_methods"):
        for fn in _glob.glob(os.path.join(d, "*.txt")):
            try:
                text = open(fn, encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            for name, body in _parse_braced_blocks(text):
                m = re.search(r"\blevel_scaled\s*=\s*\{(.*?)\}", body, re.S)
                if not m:
                    continue
                emp = {}
                for e in re.finditer(r"building_employment_([a-z]+)_add\s*=\s*([0-9.]+)",
                                     m.group(1)):
                    emp[e.group(1)] = emp.get(e.group(1), 0.0) + float(e.group(2))
                if emp:
                    out[name] = emp
    _PM_EMPLOYMENT_CACHE = out
    return out


def _pool_building_employment(obj, pm_emp, pops=None, bid=None):
    """建筑 → ({职业: 雇佣数}, 是否满编口径)。
    建筑信息默认统计实际在该建筑工作的 POP (按职业汇总 workforce);
    无 POP 数据时退回按活跃生产方法每级雇佣 × 等级计算满编人数
    (游戏文件口径, 逻辑保留)。"""
    if pops and bid is not None:
        agg = {}
        for _pid, o in pops.items():
            if o.get("workplace") != bid:
                continue
            t = o.get("type")
            wf = o.get("workforce")
            if t and isinstance(wf, (int, float)):
                agg[t] = agg.get(t, 0.0) + wf
        if agg:
            return agg, False
    lv = obj.get("levels")
    if isinstance(lv, (int, float)) and lv > 0:
        out = {}
        for pm in (obj.get("production_methods") or []):
            e = pm_emp.get(pm) or {}
            for t, v in e.items():
                out[t] = out.get(t, 0.0) + v
        if out:
            return {t: v * lv for t, v in out.items()}, True
    return {}, False


def _pool_btype_kind(bts):
    """建筑类型列表 → 上游/生产环节形态 (mine/field/forest/fishing/None)。"""
    for t in bts:
        if "_mine" in (t or ""):
            return "mine"
    for t in bts:
        if any(x in (t or "") for x in ("_plantation", "_farm", "_ranch",
                                        "_orchard", "_pasture")):
            return "field"
    for t in bts:
        if "_logging" in (t or ""):
            return "forest"
    for t in bts:
        if "_fishing" in (t or "") or "_whaling" in (t or ""):
            return "fishing"
    return None


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

def _brace_block(text, open_idx):
    """返回从 '{' 下标开始的配对大括号内容 (含两端); 不配对返回 ""。"""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
    return ""


def _load_province_id_by_color():
    """省份颜色 (十进制, 如 xF080A0 → 15761568) → 存档省份 id。

    数据源: 游戏 tools/mapeditor/map_editor_status.txt 首个 completed 块,
    其条目按省份 id 升序导出, 即条目顺序就是省份 id。
    """
    global _PROVINCE_ID_BY_COLOR
    if _PROVINCE_ID_BY_COLOR is not None:
        return _PROVINCE_ID_BY_COLOR
    mapping = {}
    try:
        with open(MAP_EDITOR_STATUS, encoding="utf-8-sig") as fp:
            txt = fp.read()
        i = txt.find("completed={")
        if i >= 0:
            body = _brace_block(txt, txt.find("{", i))
            for j, n in enumerate(re.findall(r"\b(\d+)\s*=", body)):
                mapping[int(n)] = j
    except Exception:
        pass
    _PROVINCE_ID_BY_COLOR = mapping
    return mapping


def _region_hub_keys():
    """州域 key → hub 省份键: {STATE_XXX: {city/port/farm/mine/wood: 'xHEX'}}。

    解析 map_data/state_regions/*.txt 的 city/port/farm/mine/wood 字段;
    目录缺失/解析失败返回 {}。
    """
    global _REGION_HUB_KEYS
    if _REGION_HUB_KEYS is not None:
        return _REGION_HUB_KEYS
    out = {}
    try:
        if not os.path.isdir(STATE_REGIONS_DIR):
            _REGION_HUB_KEYS = out
            return out
        for fn in sorted(os.path.join(STATE_REGIONS_DIR, n)
                         for n in os.listdir(STATE_REGIONS_DIR)
                         if n.endswith(".txt")):
            with open(fn, encoding="utf-8-sig") as fp:
                txt = fp.read()
            for m in re.finditer(r"\b(STATE_[A-Z0-9_]+)\s*=\s*\{", txt):
                body = _brace_block(txt, m.end() - 1)
                hubs = {}
                for hub in HUB_ORDER:
                    hm = re.search(r"\b" + hub +
                                   r'\s*=\s*"(x[0-9A-Fa-f]{6})"', body)
                    if hm:
                        hubs[hub] = hm.group(1)
                if hubs:
                    out[m.group(1)] = hubs
    except Exception:
        pass
    _REGION_HUB_KEYS = out
    return out


def _province_hub_types():
    """存档省份 id → hub 类型 (city/port/farm/mine/wood); 仅 hub 省份有映射。

    由 state_regions 的 hub 省份键 + 颜色→id 表拼出; 同一省份兼作多类 hub
    (如城市兼农场) 时按 HUB_ORDER 优先取首个 (city)。
    """
    global _PROVINCE_HUB_TYPES
    if _PROVINCE_HUB_TYPES is not None:
        return _PROVINCE_HUB_TYPES
    pid_by_color = _load_province_id_by_color()
    out = {}
    for hubs in _region_hub_keys().values():
        for hub, key in hubs.items():
            try:
                pid = pid_by_color.get(int(key[1:], 16))
            except ValueError:
                pid = None
            if pid is not None and pid not in out:
                out[pid] = hub
    _PROVINCE_HUB_TYPES = out
    return out


def _owned_state_provinces(state_obj):
    """州对象 provinces 字段 → 占有省份 id 列表 (多个 [起点, 额外数] 区间对)。"""
    provs = (state_obj.get("provinces") or {}).get("provinces") or []
    out = []
    for i in range(0, len(provs) - 1, 2):
        first, extra = provs[i], provs[i + 1]
        out.extend(range(first, first + extra + 1))
    return out


def _hub_province_owned(state_obj, hub_type):
    """hub 类型对应的州域 hub 省份是否在本州占有省份内。
    州对象缺失 / hub 键缺失 / 省份映射失败时按 True 处理 (沿用原取名, 不误伤普通州)。"""
    if not state_obj or hub_type not in HUB_ORDER:
        return True
    key = (_region_hub_keys().get(state_obj.get("region") or "") or {}).get(hub_type)
    if not key:
        return True
    try:
        prov = _load_province_id_by_color().get(int(key[1:], 16))
    except ValueError:
        return True
    if prov is None:
        return True
    return prov in _owned_state_provinces(state_obj)


def _hub_name_for(state_obj, hub_type):
    """州内某 hub 类型的显示名 (分治州校正)。

    普通州 (hub 省份归本州): 与原逻辑一致。分治州: 若该 hub 类型的省份
    属别国 (如卢卡的伐木营地 → wood hub 在帕尔马), 回退到本州首都省所在
    hub 名 (该国自己那块地的 hub); 本州不占有任何 hub 省份时返回 None
    (不把别国 hub 名安在别国分治州的建筑上)。
    """
    if not state_obj or hub_type not in HUB_ORDER:
        return None
    hubs = _hub_names(state_obj)
    idx = HUB_ORDER.index(hub_type)
    if not (0 <= idx < len(hubs)) or not hubs[idx]:
        return None
    if _hub_province_owned(state_obj, hub_type):
        return hubs[idx]
    cap = state_obj.get("capital")
    if cap is not None:
        cap_hub = _province_hub_types().get(cap)
    if cap_hub in HUB_ORDER:
        i2 = HUB_ORDER.index(cap_hub)
        if i2 < len(hubs) and hubs[i2]:
            return hubs[i2]
    return None


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
    """建立 gov_key → 中文名 映射 (从游戏+已启用 mod 的 simp_chinese 本地化
    读取 gov_ 开头的 key; 兼容数字 key 如 gov_french_2nd_republic_parliamentary
    与版本后缀如 gov_xxx:0)。"""
    global _GOV_CACHE
    if _GOV_CACHE is not None:
        return _GOV_CACHE
    gov = {}
    for loc_dir in _loc_dirs():
        try:
            for fn in os.listdir(loc_dir):
                if not fn.endswith(".yml"):
                    continue
                with open(os.path.join(loc_dir, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    for line in fp:
                        m = re.match(
                            r"\s*(gov_[a-z0-9_]+)(?::\d+)?:\s*\"([^\"]+)\"\s*(?:#.*)?$",
                            line)
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

def _aggregate_pops(data, state_ids, pops=None):
    """遍历 pops.database, 统计给定州内的民族/宗教/职业占比。
    pop 对象: {type, workforce, dependents, location, culture, religion, ...}
    返回 {cultures, religions, professions, total} 各为 [{"name","count","pct"}]。
    pct 为占总人口的百分比。
    pops 可选: 已解析的 {pid: pop对象} (SaveContext.player_pops), 传入时直接
    复用, 不再扫描 pops.database。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return {"cultures": [], "religions": [], "professions": []}

    def _top3(d):
        out = []
        for k, v in sorted(d.items(), key=lambda x: -x[1])[:3]:
            out.append({"name": str(k), "count": round(v),
                        "pct": round(v / total * 100, 1) if total else 0})
        return out

    if pops is not None:
        cult = {}
        reli = {}
        prof = {}
        for obj in pops.values():
            if not isinstance(obj, dict):
                continue
            wf = obj.get("workforce") or 0
            dep = obj.get("dependents") or 0
            ptotal = wf + dep
            t = obj.get("type")
            if t:
                prof[t] = prof.get(t, 0) + ptotal
            c = obj.get("culture")
            if isinstance(c, int):
                cult[c] = cult.get(c, 0) + ptotal
            r = obj.get("religion")
            if r:
                reli[r] = reli.get(r, 0) + ptotal
        total = sum(cult.values()) or sum(reli.values()) or sum(prof.values()) or 1
        return {"cultures": _top3(cult), "religions": _top3(reli),
                "professions": _top3(prof), "total": round(total)}

    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return {"cultures": [], "religions": [], "professions": []}
    db = data.find(b'"database"', pop_db)
    ob = data.find(b'{', db)
    # 逐个 pop 对象 (头 600 字节快速筛州, 命中才完整解析)
    cult = {}
    reli = {}
    prof = {}
    j = ob
    while True:
        i = data.find(b'":{', j)
        if i < 0:
            break
        ob2 = data.find(b'{', i)
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
    return {"cultures": _top3(cult), "religions": _top3(reli),
            "professions": _top3(prof), "total": round(total)}

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
LAWS_DIR = r"F:\Game\steamapps\common\Victoria 3\game\common\laws"

_BG_CACHE = None
_LAW_GROUP_CACHE = None
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


def _load_law_groups():
    """法律 → 法律组 (lawgroup_*) 映射, 读取 game/common/laws/*.txt。
    用于推断进行中的法律将替代同组的哪条现行法。"""
    global _LAW_GROUP_CACHE
    if _LAW_GROUP_CACHE is None:
        _LAW_GROUP_CACHE = {}
        if os.path.isdir(LAWS_DIR):
            for fn in os.listdir(LAWS_DIR):
                if not fn.endswith(".txt"):
                    continue
                with open(os.path.join(LAWS_DIR, fn), "rb") as f:
                    text = f.read()
                for name, block in _clausewitz_blocks(text):
                    if not name.startswith("law_"):
                        continue
                    m = re.search(rb'group\s*=\s*"?([a-z0-9_]+)"?', block)
                    if m:
                        _LAW_GROUP_CACHE[name] = m.group(1).decode()
    return _LAW_GROUP_CACHE


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


def _pm_names_zh(pms, drop_raw=False):
    """生产方式 key 列表 → 中文名列表 (本地化, 含 $引用$ 解析)。
    drop_raw=True 时丢弃未本地化的 key (与杂志 shelf 口径一致), 否则保留原 key。
    返回 None 表示无有效生产方式。"""
    if not pms:
        return None
    loc = _load_loc_all()
    names = []
    for pm in pms:
        nm = loc.get(pm) or pm
        seen = {pm}
        while isinstance(nm, str) and nm.startswith("$") and nm.endswith("$"):
            ref = nm[1:-1]
            if ref in seen or ref not in loc:
                break
            seen.add(ref)
            nm = loc[ref]
        if drop_raw and (nm == pm or "$" in str(nm)
                         or str(nm).startswith("pm_")):
            continue
        if nm and nm not in names:
            names.append(nm)
    return names or None


def _state_object(data, state_id):
    """州 id → 完整 state 对象 (含 region/incorporation 等字段); 找不到返回 None。

    注意: states.database 内嵌其他数字键对象 (如某州对象 trade.goods 的商品 id
    映射, 键形如 "13":{value, prestige_goods}), 不能直接返回第一个 'N':{ 匹配;
    须解析后校验对象像州 (含 capital/region 字段) 才返回, 否则继续往后找。"""
    sob, so_end = _states_db_bounds(data)
    if so_end <= sob:
        return None
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


_STATES_DB_BOUNDS = {}


def _states_db_bounds(data):
    """states.database 起始/结束字节位 (按 bytes 对象 id 缓存, 每次熔化一份)。"""
    key = id(data)
    m = _STATES_DB_BOUNDS.get(key)
    if m:
        return m
    sd = data.find(b'"states":{"database"')
    if sd < 0:
        _STATES_DB_BOUNDS[key] = (0, 0)
        return (0, 0)
    db = data.find(b'"database"', sd)
    sob = data.find(b'{', db)
    so_end = _object_end(data, sob)
    _STATES_DB_BOUNDS[key] = (sob, so_end)
    return (sob, so_end)


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

def _capital_name(data, country, ctx=None):
    """首都 state → 中文名: 优先首都省所在 hub 名(本地化/玩家改名),
    其次城市 hub 名, 失败回退州域名。

    分治州域 (如艾米利亚被卢卡/帕尔马/摩德纳拆分) 里, 小国首都省可能不是
    city hub (卢卡 = port hub), 故先按州 capital 省份定位 hub 类型再取对应名。
    ctx 可选: SaveContext, 传入时州对象走一次解析缓存, 避免重复扫描 states 库。"""
    cap_id = (country or {}).get("capital")
    if not cap_id:
        return ""
    sobj = ctx.state_object(cap_id) if ctx else _state_object(data, cap_id)
    if sobj:
        hubs = _hub_names(sobj)
        cap_prov = sobj.get("capital")
        if cap_prov is not None:
            hub_type = _province_hub_types().get(cap_prov)
            if hub_type in HUB_ORDER:
                idx = HUB_ORDER.index(hub_type)
                if idx < len(hubs) and hubs[idx]:
                    return hubs[idx]
        if hubs and hubs[0]:
            return hubs[0]
    rk = ctx.state_region_key(cap_id) if ctx else _state_region_key(data, cap_id)
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

# 投票权(Distribution of Power)法律组: 供新文风系统做投票权加权
DOP_LAWS = (
    "law_autocracy", "law_neo_absolutism", "law_bakufu",
    "law_technocracy", "law_oligarchy", "law_organic_regulation",
    "law_elder_council", "law_landed_voting", "law_wealth_voting",
    "law_census_voting", "law_universal_suffrage", "law_anarchy",
    "law_single_party_state",
)

# 治理原则(Governance Principles)法律组: 供新文风系统判定政体类别
GOVT_LAWS = (
    "law_chiefdom", "law_monarchy", "law_social_monarchy",
    "law_presidential_republic", "law_parliamentary_republic",
    "law_theocracy", "law_council_republic", "law_corporate_state",
    "law_colonial_administration",
)

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

# 中文语境下连写(不带分隔符)的姓前名后文化: 汉字名之间不加空格/中点 (如 李昪、伊藤博文)
_CJK_JOIN_CULTURES = {
    "han", "manchu", "zhuang", "shan", "yuanzhumin",
    "japanese", "korean", "vietnamese",
}


def _is_cjk_text(s):
    """是否含 CJK 汉字 (用于决定名/姓之间是否连写)。"""
    return bool(s) and any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _localize_character_name(first, last, loc, culture_key=None):
    """角色名中文化: 存档存英文名, 游戏 names_l 本地化提供英文名→中文表。
    优先整词匹配 (如 Karam_Singh→卡拉姆·辛格、Gyu-ho→奎镐), 否则按空格/下划线
    拆词逐个查表, 查不到保留原文。本地化文件同时存在连字符与下划线两种 key 形式,
    故先试原始 key, 再分别试连字符/下划线归一 (如 d-Oilliamson→德·奥扬松)。
    姓前/名前文化 (东亚/匈牙利等) 按文化键值重排为 姓+名 (李昪、元奎镐);
    汉字文化连写不带分隔符, 其余用「·」连接 (吉塔·巴尔加瓦、文卡特吉·辛迪亚)。"""
    def _one(raw):
        if not raw:
            return None
        if raw in loc:
            return loc[raw]
        cand = raw.replace("-", "_")
        if cand in loc:
            return loc[cand]
        cand2 = raw.replace("_", "-")
        if cand2 in loc:
            return loc[cand2]
        return "".join(loc.get(tok, tok) for tok in re.split(r"[ _]+", raw))

    first_zh = _one(first)
    last_zh = _one(last)
    if culture_key in _SURNAME_FIRST_CULTURES:
        a, b = last_zh, first_zh
    else:
        a, b = first_zh, last_zh
    if not a:
        return b or ""
    if not b:
        return a
    if culture_key in _CJK_JOIN_CULTURES and _is_cjk_text(a) and _is_cjk_text(b):
        return a + b
    return a + "·" + b

def _player_characters(data, country_id):
    """character_manager.database 该国角色 → {id: {"name"(中文), "ideology", "template",
    "culture"(中文), "religion"(中文), "home_region"(中文), 及对应原始 key/id}}。"""
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
                                          str(obj.get("last_name") or ""), loc,
                                          culture_id_to_key(obj.get("culture")))
            culture = obj.get("culture")
            religion = obj.get("religion")
            home_region = obj.get("home_region")
            chars[int(m.group(1))] = {
                "name": nm or None,
                "ideology": obj.get("ideology"),
                "template": obj.get("template"),
                "culture_id": culture,
                "culture": culture_id_to_name(culture) if isinstance(culture, int) else None,
                "religion_key": religion,
                "religion": _clean_loc_name(loc.get(religion, religion), loc) if religion else None,
                "home_region_key": home_region,
                "home_region": _clean_loc_name(loc.get(home_region, home_region), loc) if home_region else None,
            }
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
    """用与利益集团首领相同的方式解析统治者: 姓名 / 意识形态 / 在位状态 / 头衔,
    以及文化 / 宗教 / 家乡(均中文, 供政界动态按非主流背景介绍)。
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
        "culture": ch.get("culture"),
        "religion": ch.get("religion"),
        "home_region": ch.get("home_region"),
    }

def _iter_pops_in_states(data, state_ids):
    """单次扫描 pops.database，产出位于指定州集合内的全部 POP 对象。
    先用对象头 600 字节快速筛州 (与 _pops_by_state 相同), 命中才做完整解析,
    避免对存档里全部 POP 逐个 json.loads 后再丢弃 (政治运动提取的旧热点)。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return
    pop_db = data.find(b'"pops"')
    if pop_db < 0:
        return
    db = data.find(b'"database"', pop_db)
    if db < 0:
        return
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
            yield obj
        j = end

def _extract_political_movements(data, country_id, state_ids, pop_stats, player_tag=None,
                                 pops=None):
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
    pop_iter = (pops.values() if pops is not None
                else _iter_pops_in_states(data, state_ids))
    for obj in pop_iter:
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
    _bs, btype_map, _objs = _buildings_index(data, state_ids)
    return btype_map

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
                     movement_names=None, workplace_ownership=None,
                     state_obj=None, building_ctx=None):
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
    hazard_pms_zh = _pm_names_zh(hazard_pms)
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
    # 利益集团：存档的 interest_group_support_array 存的是每 10 万人的支持人数,
    # 一个 POP 的政治倾向按吸引力分散在多个 IG 上 (其余为无政治阵营)。
    # 取吸引力前三的 IG, 并算出无政治阵营人数 = 劳动力 - 全部 IG 支持人数。
    ig_support = (pop.get("interest_group_support_data") or {}).get("interest_group_support_array") or []
    ig_items = []
    if isinstance(ig_support, list) and len(ig_support) >= 2:
        for d in ig_support[1:]:
            if not isinstance(d, dict):
                continue
            for k, v in d.items():
                if isinstance(k, str) and k.isdigit() and isinstance(v, (int, float)) and v > 0:
                    ig_items.append((int(k), v))
    ig_items.sort(key=lambda kv: -kv[1])
    wf_i = int(round(wf))
    top_igs = []
    for idx, val in ig_items[:3]:
        name = (ig_slots or {}).get(idx)
        if name:
            n = round(val * 100000)
            top_igs.append({"name": name, "supporters": n,
                            "pct_of_workforce": round(n / wf_i * 100, 1) if wf_i else None})
    ig_aligned = sum(round(v * 100000) for _, v in ig_items)
    unaff = max(0, wf_i - ig_aligned) if wf_i else None
    # 兼容旧字段: interest_group 仍为吸引力最高者 (share_pct 为其占全部 IG 支持的比例)
    top_ig = None
    if top_igs:
        top_ig = {"name": top_igs[0]["name"],
                  "share_pct": round(top_igs[0]["supporters"] / ig_aligned * 100, 1)
                  if ig_aligned else None}
    # 工作建筑：POP 有 workplace 时按建筑id查类型并本地化；无 workplace 视为失业
    wp_id = pop.get("workplace")
    btype = (building_map or {}).get(wp_id)
    if wp_id is None:
        workplace, unemployed = None, True
    else:
        unemployed = False
        workplace = (building_ctx or {}).get("workplace")
        if not workplace and btype:
            workplace = _load_loc_all().get(btype, btype)
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
    # 访谈地点: 优先用工作建筑所属 hub 的城市名 (建筑级上下文已按州预取一次)
    hub_name = (building_ctx or {}).get("hub_name")
    if not hub_name:
        hub_cat = _hub_for_building(btype)
        if hub_cat:
            if state_obj is not None:
                hub_name = _hub_name_for(state_obj, hub_cat)
            elif hub_names:
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
        "workplace_pms_zh": ((building_ctx or {}).get("pms_zh")
                             if not unemployed else None),
        "consumption_goods": profile["goods"],
        "engel_coefficient": profile["engel"],
        "sol": pop.get("previous_quality_of_life"),
        "wealth": pop.get("wealth"),
        "literacy_pct": literacy,
        "acceptance_status": acc.get("acceptance_status"),
        "interest_group": top_ig,
        "interest_groups": top_igs,
        "politically_unaffiliated": unaff,
        "unaffiliated_pct": round(unaff / wf_i * 100, 1) if wf_i and unaff is not None else None,
        "job_satisfaction": round(job_sat, 2) if isinstance(job_sat, (int, float)) else None,
        "workplace": workplace,
        "workplace_ownership": workplace_ownership if workplace else None,
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

def _extract_player_states(data, state_ids, ctx=None):
    """提取玩家每个州的 [州id, 州域名(中文), 主要居民文化(中文)]。
    单次扫描 pops 按州聚合各族人口, 取人口最多的文化; 州内完全无人时
    回退州域本土文化(add_homeland)。返回按州 id 升序的
    [{id, name, top_culture, empty}]。
    ctx 可选: SaveContext, 传入时复用其 POP 解析与州对象缓存。"""
    state_ids = set(state_ids or [])
    if not state_ids:
        return []
    cult_by_state = {sid: {} for sid in state_ids}
    if ctx is not None:
        for obj in ctx.player_pops(state_ids).values():
            counts = cult_by_state.get(obj.get("location"))
            if counts is None:
                continue
            c = obj.get("culture")
            if isinstance(c, int):
                wf = obj.get("workforce") or 0
                dep = obj.get("dependents") or 0
                counts[c] = counts.get(c, 0) + wf + dep
    else:
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
    state_zh = (lambda sid: ctx.state_zh(sid)) if ctx else (
        lambda sid: _state_zh(data, sid))
    result = []
    for sid in sorted(state_ids):
        sobj = ctx.state_object(sid) if ctx else _state_object(data, sid)
        if ctx is not None:
            rk = ctx.state_region_key(sid)
        else:
            rk = (sobj or {}).get("region") if sobj else _state_region_key(data, sid)
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
        entry = {"id": sid, "name": name or f"州{sid}",
                 "top_culture": top, "empty": empty}
        if sobj:
            dev = sobj.get("devastation")
            if isinstance(dev, (int, float)):
                entry["devastation"] = round(float(dev), 3)
            pol = sobj.get("pollution")
            if isinstance(pol, (int, float)):
                entry["pollution"] = round(float(pol), 3)
            buckets = _state_migration_buckets(sobj)
            if buckets:
                total = sum(r.get("num") or 0 for r in buckets
                            if isinstance(r.get("num"), (int, float)))
                dest = {}
                for r in buckets:
                    tname = state_zh(r.get("target_state"))
                    key = tname or f"州{r.get('target_state')}"
                    dest[key] = dest.get(key, 0) + (r.get("num") or 0)
                top_dest = sorted(dest.items(), key=lambda kv: -kv[1])[:3]
                entry["migration_out"] = {
                    "bucket_count": len(buckets),
                    "total": round(total, 3),
                    "top_destinations": [{"state": k, "num": round(v, 3)}
                                         for k, v in top_dest],
                }
            em = sobj.get("last_week_pop_migration_statistics")
            if isinstance(em, dict):
                ew = em.get("weekly_emigration")
                if isinstance(ew, (int, float)):
                    entry["emigration"] = {
                        "weekly": round(float(ew), 4),
                        "to_states": [{"state": s, "name": state_zh(s)}
                                      for s in (em.get("emigration_states") or [])
                                      if s is not None],
                    }
        result.append(entry)
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
    by_state, _bt, _objs = _buildings_index(data, state_ids)
    return by_state


def _buildings_index(data, state_ids):
    """单次扫描 building_manager.database → (州→[建筑id], 建筑id→类型, 建筑id→完整对象)。

    合并原 _buildings_by_state 与 _building_type_map 的两次整段扫描, 顺带保留
    levels/owners/production_methods 等字段, 供所有权解析与访谈复用。"""
    state_ids = set(state_ids or [])
    by_state = {s: [] for s in state_ids}
    btype_map = {}
    objs = {}
    if not state_ids:
        return by_state, btype_map, objs
    idx = data.find(b'"building_manager"')
    if idx < 0:
        return by_state, btype_map, objs
    bm_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return by_state, btype_map, objs
    _BUILDING_MANAGER_BOUNDS[id(data)] = (data.find(b'{', db), bm_end)
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
            bid = int(m.group(1))
            by_state[int(obj["state"])].append(bid)
            btype_map[bid] = obj["building"]
            objs[bid] = obj
        j = end
    return by_state, btype_map, objs


# ---------------------------------------------------------------------------
# 建筑物所有权解析 (存档 building_ownership_manager)
# 分类与游戏一致: 国有 / 外国投资(外国政府+外国私人) / 公司所有 / 外国公司持有
# / 私有 / 当地劳动力。混合时只取份额前三生成文案。
# ---------------------------------------------------------------------------

_OWNERSHIP_ZH = {
    "state": "国有",
    "foreign": "外国投资",
    "company": "公司所有",
    "foreign_company": "外国公司持有",
    "private": "私有",
    "laborer": "当地劳动力",
}
_OWNERSHIP_HOLDER = {
    "state": "国家",
    "foreign": "外国投资",
    "company": "公司",
    "foreign_company": "外国公司",
    "private": "私人",
    "laborer": "当地劳动力",
}
_OWNERSHIP_ORDER = ("state", "foreign", "company", "foreign_company",
                    "private", "laborer")

_BUILDING_MANAGER_BOUNDS = {}


def _building_manager_bounds(data):
    """building_manager.database 的起始/结束字节位 (按熔化 bytes id 缓存)。"""
    key = id(data)
    m = _BUILDING_MANAGER_BOUNDS.get(key)
    if m:
        return m
    idx = data.find(b'"building_manager"')
    if idx < 0:
        _BUILDING_MANAGER_BOUNDS[key] = (0, 0)
        return (0, 0)
    ob = data.find(b'{', idx)
    ob_end = _object_end(data, ob)
    db = data.find(b'"database"', idx, ob_end)
    if db < 0:
        _BUILDING_MANAGER_BOUNDS[key] = (0, 0)
        return (0, 0)
    _BUILDING_MANAGER_BOUNDS[key] = (data.find(b'{', db), ob_end)
    return _BUILDING_MANAGER_BOUNDS[key]


_BUILDING_HEAD_CACHE = {}


def _building_head(data, bid):
    """按需读取单栋建筑的 (类型key, 州id) 头部字段, 供所有权解析; 带缓存。"""
    cache = _BUILDING_HEAD_CACHE.get(id(data))
    if cache is None:
        cache = _BUILDING_HEAD_CACHE[id(data)] = {}
    hit = cache.get(bid)
    if hit is not None:
        return hit
    db, db_end = _building_manager_bounds(data)
    if db_end <= db:
        return None, None
    pat = ('"' + str(bid) + '":{').encode()
    i = data.find(pat, db, db_end)
    if i < 0:
        cache[bid] = (None, None)
        return None, None
    ob2 = i + len(pat) - 1
    head = data[ob2:min(ob2 + 400, len(data))]
    m_bt = re.search(rb'"building":"([a-z0-9_]+)"', head)
    m_st = re.search(rb'"state":(\d+)', head)
    bt = m_bt.group(1).decode() if m_bt else None
    st = int(m_st.group(1)) if m_st else None
    cache[bid] = (bt, st)
    return bt, st


def _building_object(data, bid):
    """按需解析单栋建筑的完整对象; 找不到返回 None。"""
    db, db_end = _building_manager_bounds(data)
    if db_end <= db:
        return None
    pat = ('"' + str(bid) + '":{').encode()
    i = data.find(pat, db, db_end)
    if i < 0:
        return None
    ob2 = i + len(pat) - 1
    raw, _end = extract_json_object(data, ob2)
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


_OWNERSHIP_DB_BOUNDS = {}
_OWNERSHIP_DB_CACHE = {}


def _ownership_db_bounds(data):
    """building_ownership_manager.database 的起始/结束字节位 (按熔化 bytes id 缓存)。"""
    key = id(data)
    m = _OWNERSHIP_DB_BOUNDS.get(key)
    if m:
        return m
    idx = data.find(b'"building_ownership_manager"')
    if idx < 0:
        _OWNERSHIP_DB_BOUNDS[key] = (0, 0)
        return (0, 0)
    ob = data.find(b'{', idx)
    # 该管理器后紧跟 "decree_manager" 管理器, 用精确边界 "},"decree_manager"" 快速定位段尾,
    # 避免对整段做逐字节括号匹配; 找不到时回退旧逻辑。
    nxt = data.find(b'"},"decree_manager"', idx)
    ob_end = nxt + 1 if nxt > ob else _object_end(data, ob)
    db = data.find(b'"database"', idx, ob_end)
    if db < 0:
        _OWNERSHIP_DB_BOUNDS[key] = (0, 0)
        return (0, 0)
    _OWNERSHIP_DB_BOUNDS[key] = (data.find(b'{', db), ob_end)
    return _OWNERSHIP_DB_BOUNDS[key]


def _ownership_entry(data, oid):
    """按需读取单条所有权实体 {levels, identity, building}; 带缓存。"""
    cache = _OWNERSHIP_DB_CACHE.get(id(data))
    if cache is None:
        cache = _OWNERSHIP_DB_CACHE[id(data)] = {}
    hit = cache.get(oid)
    if hit is not None:
        return hit
    db, db_end = _ownership_db_bounds(data)
    if db_end <= db:
        return None
    pat = ('"' + str(oid) + '":{').encode()
    i = data.find(pat, db, db_end)
    if i < 0:
        cache[oid] = None
        return None
    ob2 = i + len(pat) - 1
    raw, _end = extract_json_object(data, ob2)
    if not raw:
        cache[oid] = None
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        cache[oid] = None
        return None
    obj = obj if isinstance(obj, dict) else None
    cache[oid] = obj
    return obj


def _building_ownership(data, bid, player_id=None, building_obj=None):
    """返回 ({类别: 等级数}, 总等级数); 类别见 _OWNERSHIP_ORDER。

    规则(与游戏一致):
    - identity.country == 本州所属国 → 国有; 否则 → 外国投资(外国政府);
    - identity.building == 自身 → 当地劳动力;
    - identity.building 为公司建筑 → 公司所有; 公司所在州属外国 → 外国公司持有;
    - 其余 → 私有; 所有者建筑所在州属外国 → 外国投资(外国私人)。
    """
    if building_obj is None:
        building_obj = _building_object(data, bid) or {}
    owners = building_obj.get("owners") or []
    total = building_obj.get("levels") or 0
    dist = {k: 0 for k in _OWNERSHIP_ORDER}
    if not owners:
        return dist, total
    st = building_obj.get("state")
    owner_ctry = None
    if st is not None and player_id is None:
        sobj = _state_object(data, st)
        owner_ctry = (sobj or {}).get("country")
    if owner_ctry is None:
        owner_ctry = player_id
    for oid in owners:
        oe = _ownership_entry(data, oid)
        if not oe:
            continue
        lv = oe.get("levels") or 0
        ident = oe.get("identity") or {}
        if "country" in ident:
            c = ident["country"]
            dist["state" if c == owner_ctry else "foreign"] += lv
            continue
        ob = ident.get("building")
        if ob == bid:
            dist["laborer"] += lv
            continue
        ob_bt, ob_st = _building_head(data, ob)
        octry = None
        if ob_st is not None:
            osb = _state_object(data, ob_st)
            octry = (osb or {}).get("country")
        if ob_bt and ob_bt.startswith("building_company_"):
            if octry is not None and octry != owner_ctry:
                dist["foreign_company"] += lv
            else:
                dist["company"] += lv
        else:
            if octry is not None and octry != owner_ctry:
                dist["foreign"] += lv
            else:
                dist["private"] += lv
    return dist, total


def _ownership_sentence(dist, total):
    """按游戏文本生成一句话; 混合时只列份额前三。无数据返回 None。"""
    if not total or not any(dist.values()):
        return None
    items = [(k, v / total) for k, v in dist.items() if v > 0]
    items.sort(key=lambda kv: (-kv[1], _OWNERSHIP_ORDER.index(kv[0])))
    top, share = items[0]
    holder = _OWNERSHIP_HOLDER[top]
    if share >= 1.0 - 1e-9:
        if top == "foreign_company":
            return f"该建筑物完全由{holder}持有"
        return f"该建筑物完全由{holder}所有"
    if share > 0.5:
        if top == "foreign_company":
            return f"该建筑物主要由{holder}持有"
        return f"该建筑物主要由{holder}所有"
    parts = "、".join(f"{_OWNERSHIP_ZH[k]}约{sh * 100:.0f}%"
                      for k, sh in items[:3])
    return f"该建筑物所有权构成：{parts}"


def _pops_by_state(data, state_ids, pops_index=None):
    """单次扫描 pops → {state_id: [POP对象]} (仅玩家州)。
    供家庭采访随机重试时直接取样, 避免每次尝试都整文件重扫 pops。
    pops_index 可选: 已按州分组的 {state_id: [POP对象]} (SaveContext.pops_by_state),
    传入时直接复用。"""
    out = {s: [] for s in (state_ids or [])}
    if not out:
        return out
    if pops_index is not None:
        for sid, lst in pops_index.items():
            if sid in out:
                out[sid] = lst
        return out
    state_ids = set(out)
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
                        cid=None, player_tag=None,
                        preferred_state=None, ruler_visited=False,
                        pops_index=None, buildings_index=None,
                        forced_family=None, rnd=None, building_objs=None):
    """随机选一个州 → 随机选该州一个建筑 → 取建筑内 SoL 最低与最高两个 POP
    (劳动力>MIN_POP_WORKFORCE, 与杂志各文章池同一门槛)
    分别作为「民生访谈」与「邻里富户」数据块。
    preferred_state: 优先在该州取材 (统治者走访联动); ruler_visited=True 且确实用到
    该州时, 在民生访谈块上打 ruler_visited 标记, 供渲染时让受访者提及统治者到访。
    若该州失业率(失业POP劳动力/该州总人口)>5%, 再附加「失业民生」块:
    该州人口最多的失业 POP + 失业率。建筑内合格 POP 不足 2 个时的兜底逻辑:
    同州内再找两次 (共试 3 栋建筑), 仍不满足则换一个新州再试 3 栋,
    再不行返回兜底 (无采访样本, 渲染层输出兜底文本)。
    forced_family: 指定家庭采访 POP(统治者走访联动时使用), 不再随机选州/建筑。
    返回 {"family_interview", "top_sol_peer", "unemployed_interview"} (缺失为 None)。"""
    state_ids = set(state_ids or [])
    result = {"family_interview": None, "top_sol_peer": None, "unemployed_interview": None}
    if not state_ids:
        return result
    rnd = rnd or random
    # 一次性索引 (单文件扫描), 之后所有随机重试只从内存取样
    if pops_index is None:
        pops_index = _pops_by_state(data, state_ids)
    if buildings_index is None:
        buildings_index = _buildings_by_state(data, state_ids)
    state_order = sorted(state_ids)
    sid = None
    lowest = highest = None
    if forced_family is not None:
        sid = forced_family.get("location")
        bid = forced_family.get("workplace")
        if sid not in state_ids or bid is None:
            return result
        cands = []
        for obj in pops_index.get(sid) or []:
            if obj.get("workplace") != bid:
                continue
            if not _pool_workforce_ok(obj):
                continue
            sz = (obj.get("workforce") or 0) + (obj.get("dependents") or 0)
            sol = obj.get("previous_quality_of_life")
            if sol is None or not isinstance(sol, (int, float)):
                continue
            cands.append((sol, sz, obj))
        if not cands:
            return result
        cands.sort(key=lambda x: (x[0], x[1]))
        lowest = forced_family
        highest = cands[-1][2]
    else:
        # 兜底逻辑: 同州内最多试 3 栋建筑 (初次 + 同州再找两次);
        # 全州不满足则换一个新州再试 3 栋 (换州再找三次);
        # 仍不满足则返回兜底 (无采访样本, 渲染层输出兜底文本)。
        # 走访联动: 统治者走访的州优先作为首个尝试州。

        def _cands_in_building(sid, bid):
            cands = []
            for obj in pops_index.get(sid) or []:
                if obj.get("workplace") != bid:
                    continue
                if not _pool_workforce_ok(obj):
                    continue
                sz = (obj.get("workforce") or 0) + (obj.get("dependents") or 0)
                sol = obj.get("previous_quality_of_life")
                if sol is None or not isinstance(sol, (int, float)):
                    continue
                cands.append((sol, sz, obj))
            return cands

        def _try_state(sid, max_buildings):
            """州内依次试 max_buildings 栋建筑;
            返回 (bid, 最穷POP, 最富POP) 或 None。"""
            buildings = list(buildings_index.get(sid) or [])
            rnd.shuffle(buildings)
            for bid in buildings[:max_buildings]:
                cands = _cands_in_building(sid, bid)
                if len(cands) < 2:
                    continue
                # SoL 升序; 同 SoL 时取人口较少者作最穷、人口较多者作最富
                cands.sort(key=lambda x: (x[0], x[1]))
                return bid, cands[0][2], cands[-1][2]
            return None

        state_pool = list(state_order)
        rnd.shuffle(state_pool)
        if preferred_state is not None and preferred_state in state_ids:
            state_pool = [preferred_state] + [s for s in state_pool
                                              if s != preferred_state]

        sid = lowest = highest = None
        if state_pool:
            hit = _try_state(state_pool[0], 3)      # 首个州: 同州再找两次 (共 3 栋)
            if hit:
                bid, lowest, highest = hit
                sid = state_pool[0]
        if lowest is None and len(state_pool) > 1:
            hit = _try_state(state_pool[1], 3)      # 换州再找三次 (新州试 3 栋)
            if hit:
                bid, lowest, highest = hit
                sid = state_pool[1]
        if lowest is None or highest is None:
            return result
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
    bobj = (building_objs or {}).get(bid)
    if isinstance(bobj, dict) and isinstance(bobj.get("production_methods"), list):
        active_pms = [p for p in bobj["production_methods"] if isinstance(p, str)]
    else:
        active_pms = _building_production_methods(data, bid)
    building_group = (_load_building_groups().get(btype) if btype else None)
    # 建筑级上下文只提取一次: 民生访谈/邻里富户/失业板块共用同一建筑与州,
    # 生产方式中文名、建筑名与 hub 名不在每次 _family_from_pop 里重复计算。
    building_ctx = {}
    if btype:
        building_ctx["workplace"] = _load_loc_all().get(btype, btype)
        hub_cat = _hub_for_building(btype)
        if hub_cat:
            if state_obj is not None:
                building_ctx["hub_name"] = _hub_name_for(state_obj, hub_cat)
            elif hub_names:
                building_ctx["hub_name"] = hub_names[HUB_ORDER.index(hub_cat)]
    building_ctx["pms_zh"] = _pm_names_zh(active_pms, drop_raw=True) if bid is not None else None
    movement_names = _movement_names_zh(data, player_tag)
    own_sentence = None
    if bid is not None and cid is not None:
        own_dist, own_total = _building_ownership(data, bid, cid, building_obj=bobj)
        own_sentence = _ownership_sentence(own_dist, own_total)
    common = dict(region_name=region_name, region_key=region_key, ig_slots=ig_slots,
                  building_map=building_map, incorporation=incorporation,
                  harvest_conditions=harvest_conditions, pop_needs=pop_needs,
                  hub_names=hub_names, price_map=price_map,
                  state_obj=state_obj, building_ctx=building_ctx,
                  vital=dict(pollution_pct=pollution_pct, devastation=devastation,
                             bits=bits, schools_inv=schools_inv,
                             building_group=building_group, active_pms=active_pms,
                             institutions_active=bool(incorporation and incorporation >= 1)),
                  movement_names=movement_names, workplace_ownership=own_sentence)
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
            if _pool_workforce_ok(obj) and sz > unemployed_big_sz:
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
    只累加死亡(不含 wounded)，优先使用 *_by_front 汇总值，避免同一伤亡在
    *_by_culture 与 *_by_front 中重复计算；存档值为浮点，原样保留。"""
    cas = {}
    for c in dp_obj.get("casualties") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("country")
        if cid is None:
            continue
        total = _sum_casualty_fields(c, (
            "casualties_from_battles_by_front",
            "casualties_from_attrition_by_front",
        ))
        if total == 0.0:
            total = _sum_casualty_fields(c, (
                "casualties_from_battles_by_culture",
                "casualties_from_attrition_by_culture",
            ))
        if total:
            cas[cid] = round(cas.get(cid, 0) + total, 6)
    return cas


def _dp_wounded(dp_obj):
    """从 diplomatic_play 对象提取负伤: {cid: 总负伤} (不含死亡)。
    与 _dp_casualties 同口径: 优先 *_by_front 汇总, 避免与 *_by_culture 重复计算。"""
    wnd = {}
    for c in dp_obj.get("casualties") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("country")
        if cid is None:
            continue
        total = _sum_casualty_fields(c, (
            "wounded_from_battles_by_front",
            "wounded_from_attrition_by_front",
        ))
        if total == 0.0:
            total = _sum_casualty_fields(c, (
                "wounded_from_battles_by_culture",
                "wounded_from_attrition_by_culture",
            ))
        if total:
            wnd[cid] = round(wnd.get(cid, 0) + total, 6)
    return wnd


def _sum_casualty_fields(entry, keys):
    """累加某国 casualties 对象中指定字段的数值之和。"""
    total = 0.0
    for key in keys:
        value = entry.get(key)
        if isinstance(value, dict):
            total += sum(x for x in value.values() if isinstance(x, (int, float)))
        elif isinstance(value, (int, float)):
            total += value
    return total


def _country_record_cost(record):
    """计算一个国家 country_record 的战争花费。"""
    if not isinstance(record, dict):
        return 0.0
    cost = 0.0
    goods = ((record.get("materiel_cost_of_war") or {}).get("goods")) or {}
    if isinstance(goods, dict):
        for g in goods.values():
            if isinstance(g, dict) and isinstance(g.get("value"), (int, float)):
                cost += g["value"]
    wage = record.get("wage_cost_of_war")
    if isinstance(wage, (int, float)):
        cost += wage
    return cost


def _dp_costs_by_country(dp_obj):
    """从 diplomatic_play 的 country_records 提取各国战争花费: {cid: cost}。"""
    costs = {}
    for r in dp_obj.get("country_records") or []:
        if not isinstance(r, dict):
            continue
        cid = r.get("country")
        if cid is None:
            continue
        costs[cid] = round(costs.get(cid, 0.0) + _country_record_cost(r), 2)
    return costs


def _dp_costs(dp_obj):
    """总战争花费：各国花费之和。"""
    return round(sum(_dp_costs_by_country(dp_obj).values()), 2)

def parse_wars(data, names, player_id=None, index=None, gp_ids=None, dp_index=None,
               save_date=None):
    """解析 war_manager.database 中的战争, 只保留玩家或列强参与的。
    伤亡/花费从关联的 diplomatic_play 对象读取(war.diplomatic_play → dp)。
    返回 [{start_date, peace_date, participants:[{id,definition,name,side,rank}],
           casualties, casualties_total, total_cost, ended, player_involved,
           dp_initiator, dp_target}]

    ended 判定: peace_date 存在且不晚于存档日期(save_date)才算已结束;
    和平日期晚于存档日期时, 该日期只是 AI 向玩家提出的和约计划,
    玩家未接受前不构成和平, 直接视为不存在和平(peace_date 置空)。"""
    if index is None or gp_ids is None or dp_index is None:
        index, gp_ids, dp_index = _build_indexes(data)
    id_names = build_country_id_names(data, index)
    save_tuple = _v3_date_tuple(save_date) if save_date else None
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
        dp_initiator = None
        dp_target = None
        if player_id is not None:
            primary_ids.add(player_id)
        if dp:
            side_by_cid = {r.get("country"): r.get("side", "")
                           for r in dp.get("country_records") or [] if isinstance(r, dict)}
            dp_initiator = dp.get("initiator")
            dp_target = dp.get("target")
            for v in (dp_initiator, dp_target):
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
                side = side_by_cid.get(cid, p.get("side", ""))
                # 外交博弈主方不在 country_records 时, 用 dp 的 initiator/target 补全阵营
                if not side:
                    if cid == dp_initiator:
                        side = "initiator"
                    elif cid == dp_target:
                        side = "target"
                parts.append({
                    "id": cid, "definition": tag,
                    "name": id_names.get(cid) or (names.get(tag, tag) if tag else str(cid)),
                    "side": side,
                    "rank": "great_power" if is_gp else "minor_power",
                    "prestige": entry.get("prestige"),
                    "war_support": round(ws, 1) if isinstance(ws, (int, float)) else None,
                    "primary": is_gp or cid in primary_ids,
                })
        # 伤亡/花费: 关联的 diplomatic_play (dp id 4294967295 = 无关联)
        cas_by_cid = _dp_casualties(dp) if dp else {}
        wnd_by_cid = _dp_wounded(dp) if dp else {}
        cost_by_cid = _dp_costs_by_country(dp) if dp else {}
        total_cost = round(sum(cost_by_cid.values()), 2) if cost_by_cid else None
        casualties_by_side = {}
        wounded_by_side = {}
        costs_by_side = {}
        for cid, val in cas_by_cid.items():
            side = side_by_cid.get(cid)
            if side:
                casualties_by_side[side] = round(casualties_by_side.get(side, 0.0) + val, 6)
        for cid, val in wnd_by_cid.items():
            side = side_by_cid.get(cid)
            if side:
                wounded_by_side[side] = round(wounded_by_side.get(side, 0.0) + val, 6)
        for cid, val in cost_by_cid.items():
            side = side_by_cid.get(cid)
            if side:
                costs_by_side[side] = round(costs_by_side.get(side, 0.0) + val, 2)
        player_involved = player_id is not None and any(p.get("id") == player_id for p in parts)
        has_great_power = any(p.get("rank") == "great_power" for p in parts)
        # 只保留玩家参与 或 有列强参与的战争
        if not (player_involved or has_great_power):
            j = end
            continue
        # 和平日期判定: 晚于存档日期的和约只是计划, 视作不存在和平
        peace = wobj.get("peace_date")
        ended = False
        if peace and peace != "1.1.1":
            p_tuple = _v3_date_tuple(peace)
            if save_tuple and p_tuple:
                ended = p_tuple <= save_tuple
            else:
                ended = True
            if not ended:
                peace = None
        wars.append({
            "id": wid,
            "start_date": wobj.get("start_date"),
            "peace_date": peace,
            "ended": ended,
            "player_involved": player_involved,
            "casualties": cas_by_cid,
            "casualties_total": round(sum(cas_by_cid.values()), 3) if cas_by_cid else None,
            "casualties_by_side": casualties_by_side,
            "wounded": wnd_by_cid,
            "wounded_total": round(sum(wnd_by_cid.values()), 3) if wnd_by_cid else None,
            "wounded_by_side": wounded_by_side,
            "total_cost": total_cost,
            "costs_by_side": costs_by_side,
            "participants": parts,
            "dp_initiator": dp_initiator,
            "dp_target": dp_target,
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


# ===========================================================================
# 杂志数据层: 战役 / 移民 / 同化改信 / 士兵POP / 跨年指纹比对
# ===========================================================================

POP_FP_TYPES = {
    "peasants", "laborers", "farmers", "aristocrats", "officers",
    "clergymen", "capitalists", "bureaucrats", "clerks", "engineers",
    "machinists", "shopkeepers", "soldiers", "slaves", "academics",
}


def _state_zh(data, state_id):
    """州 id → 中文名 (本地化失败回退 STATE_ key, 再失败 None)。"""
    rk = _state_region_key(data, state_id)
    if not rk:
        return None
    return _load_loc_all().get(rk) or rk


def _state_zh_from_sobj(sobj):
    """已解析州对象 → 中文名。"""
    rk = (sobj or {}).get("region")
    if not rk:
        return None
    return _load_loc_all().get(rk) or rk


def _state_migration_buckets(sobj):
    """从州对象提取迁移桶列表。
    存档结构: migration_buckets = [身份对象{culture,religion,type,is_slave},
    数据对象{num_to_migrate,target_state,pops{pop_id:数量},expiration_date}, ...交替]。"""
    buckets = (sobj or {}).get("migration_buckets") or []
    if not isinstance(buckets, list):
        return []
    out = []
    identity = {}
    for b in buckets:
        if not isinstance(b, dict):
            continue
        if "culture" in b or "religion" in b:
            identity = {
                "culture_id": b.get("culture"),
                "religion": b.get("religion"),
                "type": b.get("type"),
                "is_slave": bool(b.get("is_slave")),
            }
            continue
        if "target_state" not in b:
            continue
        rec = dict(identity)
        rec.update({
            "num": b.get("num_to_migrate"),
            "expiration_date": b.get("expiration_date"),
            "target_state": b.get("target_state"),
            "pops": b.get("pops") or {},
        })
        out.append(rec)
    return out


def _migration_records_zh(data, sobj):
    """迁移桶 → 带中文州名/文化/宗教的完整记录。
    换算后不足 1 人的微量记录直接丢弃, 避免「约0人」进提示词。"""
    out = []
    for r in _state_migration_buckets(sobj):
        rec = dict(r)
        rec["origin_state"] = _state_zh_from_sobj(sobj)
        rec["target_name"] = _state_zh(data, r.get("target_state"))
        cid = r.get("culture_id")
        rec["culture_zh"] = culture_id_to_name(cid) if cid is not None else None
        rec["culture_key"] = culture_id_to_key(cid) if cid is not None else None
        rec["religion_zh"] = _religion_zh(r.get("religion"))
        num = r.get("num")
        rec["num_people"] = (int(round(num * 10000))
                             if isinstance(num, (int, float)) else None)
        if (rec["num_people"] or 0) < 1:
            continue
        rec.pop("pops", None)
        out.append(rec)
    return out


def _character_index(data, ids, ctx=None):
    """批量读取角色 (带可选 SaveContext 缓存)。
    ctx 传入时按 id 集合记忆化结果, 重复扫描 (如陆战/海战将领) 只解析一次。"""
    if ctx is not None:
        idset = tuple(sorted({int(x) for x in ids if x is not None}))
        if idset in ctx.char_cache:
            return ctx.char_cache[idset]
        out = _character_index_scan(data, ids)
        ctx.char_cache[idset] = out
        return out
    return _character_index_scan(data, ids)


def _character_index_scan(data, ids):
    """批量读取角色: 单次扫描 character_manager.database, 返回 {id: 信息}。
    只扫 database 子对象, 不扫同 manager 里的 deaths / previous_deaths;
    无姓名字段的对象(死亡记录/占位符)跳过, 已读到的角色不被后续重复条目覆盖。"""
    ids = {int(x) for x in ids if x is not None}
    ids.discard(4294967295)
    if not ids:
        return {}
    cm = data.find(b'"character_manager"')
    if cm < 0:
        return {}
    ob = data.find(b'{', cm)
    end = _object_end(data, ob)
    db = data.find(b'"database"', cm)
    if db < 0 or db > end:
        return {}
    dob = data.find(b'{', db)
    db_end = _object_end(data, dob)
    pat = re.compile(rb'"(\d+)":\{')
    loc = _load_loc_all()
    out = {}
    j = dob

    while True:
        m = pat.search(data, j, db_end - 1)
        if not m:
            break
        cid = int(m.group(1))
        ob2 = m.start() + len(m.group(0)) - 1
        if cid not in ids:
            j = _object_end(data, ob2)
            continue
        raw, nxt = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = nxt
            continue
        if not isinstance(obj, dict):
            j = nxt
            continue
        # 死亡记录/占位对象没有姓名字段, 跳过
        if not (obj.get("first_name") or obj.get("last_name")
                or obj.get("character_roles")):
            j = nxt
            continue
        if cid in out:
            j = nxt
            continue
        nm = _localize_character_name(str(obj.get("first_name") or ""),
                                      str(obj.get("last_name") or ""), loc,
                                      culture_id_to_key(obj.get("culture")))
        hr = obj.get("home_region")
        ideo = obj.get("ideology")
        out[cid] = {
            "name": nm or None,
            "culture": (culture_id_to_name(obj.get("culture"))
                        if obj.get("culture") is not None else None),
            "home_region": (_clean_loc_name(loc.get(hr, hr), loc) if hr else None),
            "ideology": (_clean_loc_name(loc.get(ideo, ideo), loc) if ideo else None),
            "roles": obj.get("character_roles") or [],
        }
        if len(out) == len(ids):
            break
        j = nxt
    return out


def _country_zh_map(data):
    """国家 id → 中文名 + 列强国 id 集合 (供战役解析复用)。"""
    index, gp_ids, _dp = _build_indexes(data)
    return build_country_id_names(data, index), gp_ids


def parse_battles(data, player_id=None, wars=None, zh=None, gp_ids=None, ctx=None):
    """解析 battle_manager.database 的战役对象。

    战役含: 战争/前线/发生地(州域本地化名)/起止日期/胜负/攻守双方(国家、将领、
    编成、营数、兵力、CE、士气)/占领州。存档无逐营→POP 映射, 营仅为数量字段。
    兵力字段为满编比例(0~1), 此处换算为实际人数: 比例×营数×1000。
    过滤: 只保留玩家参战战役 (杂志只写与玩家有关的战事, 列强互殴不入杂志)。
    返回按日期倒序 ≤12 场。
    """
    bm = data.find(b'"battle_manager"')
    if bm < 0:
        return []
    ob = data.find(b'{', bm)
    end = _object_end(data, ob)
    db = data.find(b'"database"', bm)
    if db < 0 or db > end:
        return []
    dob = data.find(b'{', db)
    if zh is None or gp_ids is None:
        zh, gp_ids = _country_zh_map(data)
    war_by_id = {str(w.get("id")): w for w in (wars or [])}
    loc = _load_loc_all()
    pat = re.compile(rb'"(\d+)":\{')
    battles = []
    commander_ids = []
    pending = []
    j = dob
    while True:
        m = pat.search(data, j, end - 1)
        if not m:
            break
        bid = m.group(1).decode()
        ob2 = m.start() + len(m.group(0)) - 1
        raw, nxt = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = nxt
            continue
        if not isinstance(obj, dict) or "type" not in obj:
            j = nxt
            continue
        bd = obj.get("battle_data") or {}
        atk = bd.get("attacker") or {}
        dfd = bd.get("defender") or {}
        pids = [x for x in (atk.get("country"), dfd.get("country"),
                            obj.get("capturing_country"),
                            obj.get("lost_provinces_country"))
                if x is not None]
        player_involved = player_id is not None and player_id in pids
        has_gp = bool(gp_ids) and any(c in gp_ids for c in pids)
        occ = []
        for o in obj.get("occupation_data") or []:
            if isinstance(o, dict) and o.get("state") is not None:
                occ.append({
                    "state": o["state"],
                    "name": (ctx.state_zh(o["state"]) if ctx
                             else _state_zh(data, o["state"])),
                    "fraction": round(float(o.get("fraction") or 0), 3),
                })
        nv = obj.get("name") or {}
        var = {}
        for v in (nv.get("variables") or []):
            if isinstance(v, dict):
                var[v.get("key")] = v.get("value")
        place_key = var.get("STATE_REGION_NAME")
        place = loc.get(place_key) if place_key else None
        if not place:
            ck = var.get("CITY_NAME")
            if ck:
                place = _clean_loc_name(loc.get(ck, ck), loc)
        if not place and occ:
            place = occ[0].get("name")
        war = war_by_id.get(str(obj.get("war")))
        for d in (atk, dfd):
            if d.get("commander") is not None:
                commander_ids.append(d.get("commander"))
        pending.append((bid, obj, atk, dfd, occ, place, war,
                        player_involved, has_gp, pids))
        j = nxt

    chars = _character_index(data, commander_ids, ctx=ctx)

    def _side(d, prefix):
        if not d:
            return None
        ch = chars.get(d.get("commander"))
        cid = d.get("country")
        b_start = obj.get(prefix + "_start_battalions")
        b_end = obj.get(prefix + "_ending_battalions")
        init_size = (d.get("initial_battle_size") or {}).get("script_value_data_result")

        def _men(fraction, battalions):
            """存档兵力为满编比例(0~1): 实际人数 = 比例 × 参战营数 × 1000。"""
            if not isinstance(fraction, (int, float)) or not isinstance(battalions, (int, float)):
                return None
            if battalions <= 0:
                return None
            return int(round(fraction * battalions * 1000))

        return {
            "country_id": cid,
            "country": zh.get(cid) if cid is not None else None,
            "commander": (ch or {}).get("name"),
            "commander_home": (ch or {}).get("home_region"),
            "formation": d.get("formation"),
            "condition": d.get("battle_condition"),
            "order_type": d.get("order_type"),
            "initial_size": init_size,
            "battalions_start": b_start,
            "battalions_end": b_end,
            "manpower_start": _men(obj.get(prefix + "_starting_manpower"),
                                   b_start if isinstance(b_start, (int, float)) else init_size),
            "manpower_end": _men(obj.get(prefix + "_ending_manpower"),
                                 b_end if isinstance(b_end, (int, float)) else b_start),
            "ce_start": obj.get(prefix + "_start_ce"),
            "ce_end": obj.get(prefix + "_end_ce"),
            "morale_start": obj.get(prefix + "_starting_morale"),
            "morale_end": obj.get(prefix + "_ending_morale"),
        }

    for bid, obj, atk, dfd, occ, place, war, pi, hgp, _pids in pending:
        entry = {
            "id": bid,
            "type": obj.get("type"),
            "war": obj.get("war"),
            "front": obj.get("front"),
            "place": place,
            "start_date": obj.get("start_date"),
            "end_date": obj.get("end_date"),
            "status": obj.get("status"),
            "attacker": _side(atk, "attacker"),
            "defender": _side(dfd, "defender"),
            "occupation": occ,
            "captured_provinces": obj.get("num_captured_provinces"),
            "player_involved": bool(pi),
            "has_gp": bool(hgp),
        }
        if war:
            entry["war_participants"] = [p.get("name")
                                         for p in (war.get("participants") or [])]
            entry["war_start"] = war.get("start_date")
        battles.append(entry)

    # 杂志只写玩家参战的战事; 玩家未参战的列强战役一律不进杂志
    if player_id is not None:
        battles = [b for b in battles if b.get("player_involved")]
    battles.sort(key=lambda b: str(b.get("start_date") or ""), reverse=True)
    return battles[:12]


def parse_naval_battles(data, player_id=None, wars=None, zh=None, gp_ids=None, ctx=None):
    """解析 naval_battle_manager.database 的海战对象。

    海战与陆战结构不同: attacker/defender 位于对象顶层(而非 battle_data),
    起止日期在 battle_record 内; 这里映射成与 parse_battles 相同的 entry 结构,
    并额外标记 naval=True 供下游区分。"""
    nb = data.find(b'"naval_battle_manager"')
    if nb < 0:
        return []
    ob = data.find(b'{', nb)
    end = _object_end(data, ob)
    db = data.find(b'"database"', nb)
    if db < 0 or db > end:
        return []
    dob = data.find(b'{', db)
    if zh is None or gp_ids is None:
        zh, gp_ids = _country_zh_map(data)
    war_by_id = {str(w.get("id")): w for w in (wars or [])}
    loc = _load_loc_all()
    pat = re.compile(rb'"(\d+)":\{')
    battles = []
    commander_ids = []
    pending = []
    j = dob
    while True:
        m = pat.search(data, j, end - 1)
        if not m:
            break
        bid = m.group(1).decode()
        ob2 = m.start() + len(m.group(0)) - 1
        raw, nxt = extract_json_object(data, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = nxt
            continue
        if not isinstance(obj, dict) or "type" not in obj:
            j = nxt
            continue
        atk = obj.get("attacker") or {}
        dfd = obj.get("defender") or {}
        pids = [x for x in (atk.get("country"), dfd.get("country"))
                if x is not None]
        player_involved = player_id is not None and player_id in pids
        has_gp = bool(gp_ids) and any(c in gp_ids for c in pids)
        nv = obj.get("name") or {}
        var = {}
        for v in (nv.get("variables") or []):
            if isinstance(v, dict):
                var[v.get("key")] = v.get("value")
        place_key = var.get("STATE_REGION_NAME")
        place = loc.get(place_key) if place_key else None
        if not place:
            ck = var.get("CITY_NAME")
            if ck:
                place = _clean_loc_name(loc.get(ck, ck), loc)
        war = war_by_id.get(str(obj.get("war")))
        for d in (atk, dfd):
            if d.get("commander") is not None:
                commander_ids.append(d.get("commander"))
        rec = obj.get("battle_record") or {}
        pending.append((bid, obj, atk, dfd, place, war, rec,
                        player_involved, has_gp, pids))
        j = nxt

    chars = _character_index(data, commander_ids, ctx=ctx)

    def _ship_count(rec_side, key):
        # 主力舰(priority)与屏卫舰(screening)合计
        total = 0
        for k in (key, key.replace("priority", "screening")):
            v = (rec_side or {}).get(k) or {}
            if isinstance(v, dict):
                n = v.get("ships")
                if isinstance(n, (int, float)):
                    total += n
        return total if total else None

    def _side(d, rec_side, condition):
        if not d:
            return None
        ch = chars.get(d.get("commander"))
        cid = d.get("country")
        init_size = (d.get("initial_battle_size") or {}).get("script_value_data_result")
        return {
            "country_id": cid,
            "country": zh.get(cid) if cid is not None else None,
            "commander": (ch or {}).get("name"),
            "commander_home": (ch or {}).get("home_region"),
            "formation": d.get("formation"),
            "condition": condition,
            "order_type": None,
            "initial_size": init_size,
            "battalions_start": None,
            "battalions_end": None,
            "manpower_start": None,
            "manpower_end": None,
            "ce_start": None,
            "ce_end": None,
            "morale_start": None,
            "morale_end": None,
            "ships_start": _ship_count(rec_side, "start_priority_stats"),
            "ships_end": _ship_count(rec_side, "end_priority_stats"),
        }

    for bid, obj, atk, dfd, place, war, rec, pi, hgp, _pids in pending:
        ra = (rec.get("attacker") or {}) if isinstance(rec, dict) else {}
        rd = (rec.get("defender") or {}) if isinstance(rec, dict) else {}
        entry = {
            "id": bid,
            "type": obj.get("type"),
            "war": obj.get("war"),
            "front": obj.get("front"),
            "place": place,
            "start_date": rec.get("start_date") if isinstance(rec, dict) else None,
            "end_date": rec.get("end_date") if isinstance(rec, dict) else None,
            "status": obj.get("status"),
            "attacker": _side(atk, ra, obj.get("battle_condition")),
            "defender": _side(dfd, rd, obj.get("battle_condition")),
            "occupation": [],
            "captured_provinces": obj.get("num_captured_provinces"),
            "player_involved": bool(pi),
            "has_gp": bool(hgp),
            "naval": True,
        }
        if war:
            entry["war_participants"] = [p.get("name")
                                         for p in (war.get("participants") or [])]
            entry["war_start"] = war.get("start_date")
        battles.append(entry)

    # 与陆战一致: 只保留玩家参战的海战
    if player_id is not None:
        battles = [b for b in battles if b.get("player_involved")]
    battles.sort(key=lambda b: str(b.get("start_date") or ""), reverse=True)
    return battles[:12]


def _mix_land_naval_battles(land, naval, year):
    """合并陆战/海战: 两池各以 50% 概率被抽取(按年份固定随机种子),
    各自保持日期倒序, 最终整体仍按开始日期倒序, 上限 12 场。"""
    rnd = random.Random(year or 0)
    land = list(land or [])
    naval = list(naval or [])
    out = []
    li = ni = 0
    while li < len(land) and ni < len(naval) and len(out) < 12:
        if rnd.random() < 0.5:
            out.append(land[li])
            li += 1
        else:
            out.append(naval[ni])
            ni += 1
    while li < len(land) and len(out) < 12:
        out.append(land[li])
        li += 1
    while ni < len(naval) and len(out) < 12:
        out.append(naval[ni])
        ni += 1
    out.sort(key=lambda b: str(b.get("start_date") or ""), reverse=True)
    return out


# ===========================================================================
# 战争目的 / 军团 / 营 / 舰船 解析 (供杂志战争上下文)
# ===========================================================================

def parse_war_goals(data, wars=None, player_id=None, zh=None, gp_ids=None,
                    dp_index=None):
    """解析 war_goal_manager.database 的战争目的。
    返回 [{war, diplomatic_play, holder, holder_zh, target, target_zh, type,
           type_zh, state, state_zh, region, region_zh, demand_type,
           demand_type_zh, status, nl, article_zh}]。
    nl 为完整自然语言句 (如「巴西要求大不列颠转让属国大南」)。"""
    if zh is None or gp_ids is None:
        zh, gp_ids = _country_zh_map(data)
    if dp_index is None:
        _i, _g, dp_index = _build_indexes(data)
    dp_to_war = {}
    for dpid, dp in dp_index.items():
        w = dp.get("war") if isinstance(dp, dict) else None
        if w is not None:
            dp_to_war[str(dpid)] = w
    loc = _load_loc_all()
    i = data.find(b'"war_goal_manager"')
    if i < 0:
        return []
    db = data.find(b'"database"', i)
    ob = data.find(b'{', db)
    raw, _end = extract_json_object(data, ob)
    if not raw:
        return []
    try:
        wg = json.loads(raw)
    except Exception:
        return []
    out = []
    for _wid, v in wg.items():
        if not isinstance(v, dict) or v.get("status") != "active":
            continue
        typ = v.get("type")
        if not typ:
            continue
        target = v.get("target") or {}
        tcid = target.get("country")
        other_id = target.get("other")
        state_id = target.get("state")
        region = target.get("region")
        dp = v.get("diplomatic_play")
        war_id = dp_to_war.get(str(dp)) if dp is not None else None
        state_zh = _state_zh(data, state_id) if state_id is not None else None
        region_zh = loc.get(region) if region else None
        target_zh = zh.get(tcid) if tcid is not None else None
        other_zh = zh.get(other_id) if other_id is not None else None
        holder_zh = zh.get(v.get("holder")) if v.get("holder") is not None else None
        type_zh = loc.get(f"war_goal_{typ}_type_name") or str(typ)
        demand = v.get("demand_type") or ""
        demand_zh = ("主战目的" if demand == "primary_demand"
                     else "次生目的" if demand == "secondary_demand" else demand)
        article_zh = None
        opts = target.get("options") or {}
        art = opts.get("article")
        if art:
            article_zh = loc.get(art) or art
        st = state_zh or region_zh
        if typ == "conquer_state":
            demand_nl = (f"征服{target_zh}的{st}"
                         if st and target_zh else (f"征服{st}" if st else "征服该地区"))
        elif typ == "annex_country":
            demand_nl = f"吞并{target_zh or '该国'}"
        elif typ == "humiliation":
            demand_nl = f"羞辱{target_zh or '该国'}"
        elif typ == "return_state":
            demand_nl = (f"归还{target_zh}的{st}"
                         if st and target_zh else (f"归还{st}" if st else "归还地区"))
        elif typ == "transfer_subject":
            demand_nl = (f"{other_zh}转让属国{target_zh}"
                         if other_zh and target_zh else f"转让属国{target_zh or '该国'}")
        elif typ == "liberate_subject":
            demand_nl = f"解放附属国{target_zh or '该国'}"
        elif typ == "liberate_country":
            demand_nl = f"解放{target_zh or '该国'}"
        elif typ == "make_protectorate":
            demand_nl = f"将{target_zh or '该国'}建立为受保护国"
        elif typ == "colonization_rights":
            demand_nl = f"索取{target_zh or '该国'}的殖民权"
        elif typ == "enforce_treaty_article":
            demand_nl = f"在{target_zh or '该国'}强制执行{article_zh or '条约'}"
        elif typ == "independence":
            demand_nl = f"自{other_zh}独立" if other_zh else "独立"
        else:
            demand_nl = f"{type_zh}{target_zh}" if target_zh else type_zh
        nl = f"{holder_zh}要求{demand_nl}" if holder_zh else demand_nl
        out.append({
            "war": war_id, "diplomatic_play": dp, "holder": v.get("holder"),
            "holder_zh": holder_zh, "target": tcid, "target_zh": target_zh,
            "other": other_id, "other_zh": other_zh,
            "state": state_id, "state_zh": state_zh, "region": region,
            "region_zh": region_zh, "type": typ, "type_zh": type_zh,
            "demand_type": demand, "demand_type_zh": demand_zh,
            "status": v.get("status"), "nl": nl, "article_zh": article_zh,
        })
    return out


def parse_formations(data, country_ids=None):
    """解析 military_formation_manager 的军团/舰队对象。
    返回 [{id, type(army/fleet), country, name(自定义或本地化名, 可空),
           ordinal_number, units_name_type, home_hq, supply_hub, origin,
           current_location, flags, creation_date}]。"""
    want = {int(x) for x in country_ids} if country_ids else None
    i = data.find(b'"military_formation_manager"')
    if i < 0:
        return []
    db = data.find(b'"database"', i)
    ob = data.find(b'{', db)
    raw, _end = extract_json_object(data, ob)
    if not raw:
        return []
    try:
        fm = json.loads(raw)
    except Exception:
        return []
    loc = _load_loc_all()
    out = []
    for fid, v in fm.items():
        if not isinstance(v, dict) or v.get("type") not in ("army", "fleet"):
            continue
        cid = v.get("country")
        if want is not None and cid not in want:
            continue
        name = v.get("name") or ""
        if not name and v.get("localizable_name"):
            ln = v["localizable_name"]
            if isinstance(ln, dict):
                ln = ln.get("name")
            if ln:
                name = loc.get(ln, "") or ""
        out.append({
            "id": str(fid),
            "type": v.get("type"),
            "country": cid,
            "name": name,
            "ordinal_number": v.get("ordinal_number"),
            "units_name_type": v.get("units_name_type"),
            "home_hq": v.get("home_hq"),
            "supply_hub": v.get("supply_hub"),
            "origin": v.get("origin"),
            "current_location": v.get("current_location"),
            "flags": v.get("flags") or [],
            "active_mobilization_options": v.get("active_mobilization_options") or [],
            "creation_date": v.get("creation_date"),
        })
    return out


_BUILDING_STATE_CACHE = {}


def _building_state_map(data):
    """building id → state id (按熔化 bytes id 缓存, 单次扫描)。"""
    key = id(data)
    m = _BUILDING_STATE_CACHE.get(key)
    if m is not None:
        return m
    out = {}
    i = data.find(b'"building_manager"')
    if i >= 0:
        db = data.find(b'"database"', i)
        ob = data.find(b'{', db)
        raw, _end = extract_json_object(data, ob)
        if raw:
            try:
                bm = json.loads(raw)
                for bid, v in bm.items():
                    if isinstance(v, dict) and v.get("state") is not None:
                        out[str(bid)] = v["state"]
            except Exception:
                pass
    _BUILDING_STATE_CACHE[key] = out
    return out


def parse_combat_units(data, country_id, formations=None):
    """解析 new_combat_unit_manager 中某国的营。
    营名按游戏命名规则重建: 第{name_number}{文化名}{兵种名}营。
    返回 [{id, name, name_number, type, type_zh, culture, culture_zh,
           formation, formation_name, building, building_state, manpower,
           veterancy, mobilization}]。"""
    i = data.find(b'"new_combat_unit_manager"')
    if i < 0:
        return []
    db = data.find(b'"database"', i)
    ob = data.find(b'{', db)
    raw, _end = extract_json_object(data, ob)
    if not raw:
        return []
    try:
        units = json.loads(raw)
    except Exception:
        return []
    loc = _load_loc_all()
    bmap = _building_state_map(data)
    fm_by_id = {f.get("id"): f for f in (formations or [])}
    out = []
    for uid, v in units.items():
        if not isinstance(v, dict) or v.get("country") != country_id:
            continue
        t = v.get("type")
        cult = v.get("culture")
        cult_zh = culture_id_to_name(cult) if cult is not None else None
        type_zh = loc.get(t, t) if t else None
        fid = v.get("formation")
        formation_name = ""
        if fid is not None:
            formation_name = (fm_by_id.get(str(fid)) or {}).get("name") or ""
        out.append({
            "id": str(uid),
            "name": f"第{v.get('name_number')}{cult_zh or ''}{type_zh or ''}营",
            "name_number": v.get("name_number"),
            "type": t,
            "type_zh": type_zh,
            "culture": cult,
            "culture_zh": cult_zh,
            "formation": fid,
            "formation_name": formation_name,
            "building": v.get("building"),
            "building_state": bmap.get(str(v.get("building"))) if v.get("building") is not None else None,
            "manpower": v.get("current_manpower"),
            "veterancy": v.get("current_veterancy_level"),
            "mobilization": bool(v.get("mobilization")),
        })
    return out


_SHIP_DEFS_CACHE = None


def _ship_name_definitions():
    """解析游戏 common/ship_name_definitions: {def_key: {"prefixes", "name_lists"}}。
    name_lists 为按定义内出现顺序的若干名字数组 (属性顺序与存档 dynamic_name 对齐)。"""
    global _SHIP_DEFS_CACHE
    if _SHIP_DEFS_CACHE is not None:
        return _SHIP_DEFS_CACHE
    base = os.path.join(os.path.dirname(GAME_LOCALIZATION), "..",
                        "common", "ship_name_definitions")
    dirs = [base] if os.path.isdir(base) else []
    defs = {}
    pat = re.compile(rb'ship_names_([a-zA-Z0-9_]+)\s*=\s*\{')
    for d in dirs:
        try:
            files = sorted(os.listdir(d))
        except Exception:
            continue
        for fn in files:
            if not fn.endswith(".txt"):
                continue
            try:
                b = open(os.path.join(d, fn), "rb").read()
            except Exception:
                continue
            for m in pat.finditer(b):
                key = m.group(1).decode()
                start = m.end() - 1  # 定义块的开括号 (正则已含 = {)
                depth = 0
                k = start
                while k < len(b):
                    c = b[k:k + 1]
                    if c == b'{':
                        depth += 1
                    elif c == b'}':
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                block = b[start:k + 1]
                block = re.sub(rb'#[^\r\n]*', b'', block)
                prefixes = [x.decode()
                            for x in re.findall(rb'custom_text\s*=\s*"([^"]+)"', block)]
                name_lists = []
                for nlm in re.finditer(rb'name_list\s*=\s*\{([^}]*)\}', block):
                    names = [x.decode()
                             for x in re.findall(rb'\bsn_[A-Za-z0-9_]+', nlm.group(1))]
                    if names:
                        name_lists.append(names)
                defs[key] = {"prefixes": prefixes, "name_lists": name_lists}
    _SHIP_DEFS_CACHE = defs
    return defs


def _resolve_ship_name(ship, loc, defs):
    """舰船 name 字段 → 中文舰名 (prefix + 舰名), 无法解析返回 None。"""
    nm = ship.get("name") or {}
    if not isinstance(nm, dict):
        return None
    ln = nm.get("localizable_name")
    if isinstance(ln, dict) and ln.get("name"):
        return loc.get(ln["name"], ln["name"])
    dyn = nm.get("dynamic_name")
    if not isinstance(dyn, dict):
        return None
    defkey = dyn.get("definition") or ""
    if not defkey.startswith("ship_names_"):
        return None
    d = defs.get(defkey[len("ship_names_"):])
    if not d:
        return None
    prefix = ""
    name_key = None
    nl_seen = 0
    prefix_done = False
    for pr in (dyn.get("properties") or []):
        if not isinstance(pr, dict):
            continue
        if "text" in pr:
            tv = (pr.get("text") or {}).get("value")
            if tv and not prefix_done:
                prefix = loc.get(tv, "")
                prefix_done = True
        elif "name_list" in pr:
            idx = (pr.get("name_list") or {}).get("name", 0)
            lists = d.get("name_lists") or []
            if not lists:
                return None
            lst = lists[nl_seen] if nl_seen < len(lists) else lists[-1]
            nl_seen += 1
            if isinstance(idx, int) and 0 <= idx < len(lst):
                name_key = lst[idx]
    if not name_key:
        return None
    return prefix + loc.get(name_key, name_key)


def parse_ships(data, country_ids=None, formations=None):
    """解析 ship_manager 的舰船: 舰队→国家、模板版本→舰种、舰名本地化。
    返回 [{id, fleet, country, name(中文), type, type_zh, hit_points,
           veterancy, flags}]。"""
    want = {int(x) for x in country_ids} if country_ids else None
    if formations is None:
        formations = parse_formations(data)
    fleet_country = {str(f.get("id")): f.get("country")
                     for f in formations if f.get("type") == "fleet"}
    i = data.find(b'"ship_manager"')
    if i < 0:
        return []
    db = data.find(b'"database"', i)
    ob = data.find(b'{', db)
    raw, _end = extract_json_object(data, ob)
    if not raw:
        return []
    try:
        ships = json.loads(raw)
        if isinstance(ships, dict) and "database" in ships:
            ships = ships["database"]
    except Exception:
        return []
    ver_type = {}
    ti = data.find(b'"ship_templates_manager"')
    if ti >= 0:
        tdb = data.find(b'"database"', ti)
        tob = data.find(b'{', tdb)
        traw, _ = extract_json_object(data, tob)
        if traw:
            try:
                tmpl = json.loads(traw)
                for v in tmpl.values():
                    if isinstance(v, dict):
                        for ver in (v.get("versions") or []):
                            ver_type[str(ver)] = v.get("type")
            except Exception:
                pass
    defs = _ship_name_definitions()
    loc = _load_loc_all()
    out = []
    for sid, s in ships.items():
        if not isinstance(s, dict):
            continue
        cid = fleet_country.get(str(s.get("fleet")))
        if want is not None and cid not in want:
            continue
        typ = ver_type.get(str(s.get("version")))
        out.append({
            "id": str(sid),
            "fleet": s.get("fleet"),
            "country": cid,
            "name": _resolve_ship_name(s, loc, defs),
            "type": typ,
            "type_zh": loc.get(typ, typ) if typ else None,
            "hit_points": s.get("hit_points"),
            "veterancy": s.get("veterancy_experience"),
            "flags": s.get("flags") or [],
        })
    return out


def build_pop_fingerprint(pops):
    """{pop_id: pop对象} → 紧凑指纹 {id: [type, state, culture, religion, workforce]}。"""
    fp = {}
    for pid, obj in (pops or {}).items():
        t = obj.get("type")
        if t in POP_FP_TYPES:
            fp[pid] = [t, obj.get("location"), obj.get("culture"),
                       obj.get("religion"), obj.get("workforce")]
    return fp


def export_pop_fingerprint(pops, folder, year):
    """把玩家州 POP 指纹写入 <folder>/data/pops_<year>.json。"""
    fp = build_pop_fingerprint(pops)
    rd = os.path.join(folder, "data")
    try:
        os.makedirs(rd, exist_ok=True)
    except Exception:
        pass
    path = os.path.join(rd, f"pops_{year}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fp, f, ensure_ascii=False)
    except Exception as e:
        print(f"写入 POP 指纹失败: {e}")
        return None
    return path


def load_pop_fingerprint(folder, year):
    """读取 <folder>/data/pops_<year>.json, 缺失返回 None。"""
    path = os.path.join(folder, "data", f"pops_{year}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def diff_pop_fingerprints(prev, cur):
    """跨年指纹比对。
    同 id 类型变化 = 升职/降职 (如劳工→技工), 同 id 所在州变化 = 迁移。
    返回 (promotions, migrations) 两个列表, 均含真实职业 POP 信息。"""
    prev = prev or {}
    promotions, migrations = [], []
    for pid, c in (cur or {}).items():
        p = prev.get(pid)
        if (not p or not isinstance(p, list) or len(p) < 5
                or not isinstance(c, list) or len(c) < 5):
            continue
        if p[0] != c[0] and p[0] in POP_FP_TYPES and c[0] in POP_FP_TYPES:
            promotions.append({
                "pop_id": pid,
                "state": c[1],
                "old_state": p[1],
                "old_type": p[0],
                "new_type": c[0],
                "culture": c[2],
                "religion": c[3],
                "workforce": c[4],
            })
        elif p[1] != c[1] and c[0] in POP_FP_TYPES:
            migrations.append({
                "pop_id": pid,
                "old_state": p[1],
                "state": c[1],
                "old_type": p[0],
                "new_type": c[0],
                "culture": c[2],
                "religion": c[3],
                "workforce": c[4],
            })
    return promotions, migrations


def _player_pops_with_id(data, state_ids):
    """单次扫描 pops.database, 返回玩家州内 {pop_id: pop对象}。
    仅收录含 workforce 字段的真实 POP。供指纹与杂志样本共用, 避免重复整文件扫描。"""
    state_set = set(state_ids or [])
    out = {}
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
        if sid not in state_set:
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
        if isinstance(obj, dict) and obj.get("location") == sid and "workforce" in obj:
            q = data.rfind(b'"', max(0, i - 120), i)
            pid = data[q + 1:i].decode("utf-8", "replace")
            out[pid] = obj
        j = end
    return out


class SaveContext:
    """进程内共享的存档读取上下文 (阶段1)。

    把 extract_full_snapshot 与 build_magazine_data 都要用到的整文件扫描
    记忆化, 解析一次、多处复用:
      - 国家索引/列强/dp 只建一次 (旧流程两个函数各建一次);
      - 玩家州 POP 只扫描解析一次, 供占比统计/按州索引/政治运动/杂志样本共用;
      - states.database 只解析一次, 供州对象/州域名/首都名等反复查询。
    调用方 (watch/continue) 创建一次后传给两个生成函数, 即可消除跨函数重复遍历。
    """

    def __init__(self, data):
        self.data = data
        self._index = None
        self._pops = {}            # state_ids_tuple -> {pid: obj}
        self._state_obj_cache = {} # sid -> obj (按州惰性缓存)
        self._state_zh_cache = {}
        self._buildings = {}       # state_ids_tuple -> (by_state, btype_map, objs)
        self.char_cache = {}       # ids_tuple -> {cid: info}
        self._formations = None

    def index(self):
        """(国家index, 列强gp_ids, diplomatic_plays dp_index) 只建一次。"""
        if self._index is None:
            self._index = _build_indexes(self.data)
        return self._index

    def player_pops(self, state_ids):
        """玩家州 {pid: pop对象} 只扫描解析一次。"""
        key = tuple(sorted(state_ids or []))
        if key not in self._pops:
            self._pops[key] = _player_pops_with_id(self.data, list(key))
        return self._pops[key]

    def pops_by_state(self, state_ids):
        """由 player_pops 派生 {state_id: [pop对象]}。"""
        out = {s: [] for s in (state_ids or [])}
        for _pid, obj in self.player_pops(state_ids).items():
            loc = obj.get("location")
            if loc in out:
                out[loc].append(obj)
        return out

    def aggregate_pops(self, state_ids):
        """由 player_pops 派生民族/宗教/职业占比。"""
        return _aggregate_pops(self.data, state_ids,
                               pops=self.player_pops(state_ids))

    def state_object(self, sid):
        """州对象按 id 惰性缓存: 每个州只在首次访问时做一次带边界查找,
        避免整库一次 json.loads (约 5.5s) 以及旧代码的重复线性扫描。"""
        if sid not in self._state_obj_cache:
            self._state_obj_cache[sid] = _state_object(self.data, sid)
        return self._state_obj_cache[sid]

    def state_region_key(self, sid):
        obj = self.state_object(sid)
        return obj.get("region") if obj else None

    def state_zh(self, sid):
        """州 id → 中文名 (按州缓存)。"""
        if sid not in self._state_zh_cache:
            rk = self.state_region_key(sid)
            self._state_zh_cache[sid] = (_load_loc_all().get(rk) or rk
                                         if rk else None)
        return self._state_zh_cache[sid]

    def player_states(self, state_ids):
        """玩家州摘要列表 (复用本上下文的 POP 与州对象缓存)。"""
        return _extract_player_states(self.data, state_ids, ctx=self)

    def capital_name(self, country):
        """首都中文名 (复用州对象缓存)。"""
        return _capital_name(self.data, country, ctx=self)

    def buildings_index(self, state_ids):
        """(by_state, btype_map, objs) 建筑索引只建一次。"""
        key = tuple(sorted(state_ids or []))
        if key not in self._buildings:
            self._buildings[key] = _buildings_index(self.data, list(key))
        return self._buildings[key]

    def formations(self):
        """军团/编成索引只建一次。"""
        if self._formations is None:
            self._formations = parse_formations(self.data)
        return self._formations


# ---------------------------------------------------------------------------
# 杂志文章池 (pool): 每期从候选文章随机抽取 3 篇
# 候选: railway(帝国铁道纪行) / turmoil(在光辉以外的地方) /
#       shelf(从货架里长出来的) / service(为人民服务) /
#       voting(神圣庄严的权利) / price(餐桌上的价格) / letters(海外来信) /
#       crime(罪案与法网)
# 判定「数据可用性」后抽取 (种子=年份, 同年稳定), 只对选中的文章懒构建事实。
# 数据不足时用兜底文章补位 (court/migration/war, 数据永远可用)。
# ---------------------------------------------------------------------------

MAGAZINE_POOL_KEYS = ("railway", "turmoil", "shelf", "service", "voting",
                      "price", "letters", "crime", "war_family",
                      "court_household", "migration_change")

MAGAZINE_POOL_FALLBACK = ("court_household", "migration_change", "war_family")

_POOL_CITIZENSHIP_LAWS = (
    "law_ethnostate", "law_national_supremacy", "law_racial_segregation",
    "law_multiculturalism",
)
_POOL_SECURITY_LAWS = (
    "law_national_guard", "law_secret_police", "law_guaranteed_liberties",
)
_POOL_CHURCH_LAWS = (
    "law_state_religion", "law_freedom_of_conscience", "law_total_separation",
    "law_state_atheism",
)
_POOL_SPEECH_LAWS = (
    "law_outlawed_dissent", "law_censorship", "law_right_of_assembly",
    "law_protected_speech", "law_free_speech",
)
_POOL_EDUCATION_LAWS = (
    "law_public_schools", "law_private_schools", "law_religious_schools",
    "law_no_schools",
)
_POOL_HEALTH_LAWS = (
    "law_charitable_health_system", "law_private_health_insurance",
    "law_public_health_insurance", "law_no_health_system",
)
_POOL_DOP_LAWS = (
    "law_autocracy", "law_neo_absolutism", "law_bakufu", "law_technocracy",
    "law_oligarchy", "law_organic_regulation", "law_elder_council",
    "law_landed_voting", "law_wealth_voting", "law_census_voting",
    "law_universal_suffrage", "law_anarchy", "law_single_party_state",
)
# 不设普选的权力分配/治理法律: 独裁制、寡头制、酋邦(长老会议)
_POOL_VOTE_EXCLUDED_LAWS = (
    "law_autocracy", "law_oligarchy", "law_elder_council", "law_chiefdom",
)

# 罪案与法网: 警察机构(Policing)法律组 / 国内安全(Internal Security)法律组
_POOL_POLICING_LAWS = (
    "law_no_police", "law_local_police", "law_dedicated_police",
    "law_militarized_police",
)
_POOL_INTERNAL_SECURITY_LAWS = (
    "law_no_home_affairs", "law_national_guard", "law_secret_police",
    "law_shinsengumi", "law_guaranteed_liberties",
)

# 机构投资等级(0~5) → 自然语言档位 (提示词不传 1级/2级 这类裸数字)
INSTITUTION_LEVEL_ZH = {
    0: "尚未设立",
    1: "初具雏形",
    2: "有限运转",
    3: "全面铺开",
    4: "高效有力",
    5: "臻于完善",
}


def _institution_level_zh(level):
    """机构投资等级 → 自然语言档位; 非法输入返回「未知」。"""
    if not isinstance(level, (int, float)):
        return "未知"
    return INSTITUTION_LEVEL_ZH.get(int(level), f"第{int(level)}档")


# 游戏文件解析失败时的选品兜底清单: 有生产链条 + pop 可直接消费的制成品
_POOL_SHELF_FALLBACK_GOODS = {
    "groceries", "clothes", "luxury_clothes", "furniture", "luxury_furniture",
    "glass", "paper", "porcelain", "liquor", "silk", "small_arms",
    "aeroplanes", "automobiles", "radios", "telephones",
}


def _pool_state_ids(snap):
    return [s.get("id") for s in (snap.get("states") or [])
            if s.get("id") is not None]


def _pool_goods_text(go, gm):
    """建筑 input/output_goods → 自然语言「商品约数量」串。"""
    goods = (go or {}).get("goods") or {}
    order, zh = gm["order"], gm["zh"]
    items = []
    for gid, gv in goods.items():
        try:
            idx = int(gid)
        except (TypeError, ValueError):
            continue
        key = order[idx] if 0 <= idx < len(order) else None
        v = (gv or {}).get("value")
        if isinstance(v, (int, float)) and abs(v) > 1e-9:
            items.append((abs(v), zh.get(key, key or str(gid)), v))
    return "、".join(f"{name}约{round(v, 1)}" for _a, name, v in
                     sorted(items, reverse=True)[:4])


def _pool_building_text(melted, ctx, cid, bid, obj, loc, gm, pops=None, place=None):
    """一栋建筑 → 自然语言: 类型/州/等级/生产方法/所有权/雇佣/投入产出。
    place 非空时用它替代州名 (如贸易中心改用 Hub 名)。"""
    btype = obj.get("building") or ""
    zh = loc.get(btype) or btype or "未知建筑"
    state = place or ctx.state_zh(obj.get("state")) or "未知州"
    bits = [f"{zh}（位于{state}）"]
    lv = obj.get("levels")
    if isinstance(lv, (int, float)):
        bits.append(f"{int(round(lv))}级")
    pms = obj.get("production_methods") or []
    pms_zh = []
    for p in pms:
        v = loc.get(p)
        if v and "$" not in v and v != p and not str(v).startswith("pm_"):
            pms_zh.append(v)
    if pms_zh:
        bits.append("采用" + "、".join(pms_zh))
    try:
        dist, total = _building_ownership(melted, bid, cid, building_obj=obj)
        own = _ownership_sentence(dist, total)
        if own:
            bits.append(own)
    except Exception:
        pass
    emp, is_full = _pool_building_employment(obj, _load_pm_employment(),
                                             pops=pops, bid=bid)
    if emp:
        try:
            from journal import POP_TYPE_NAMES
        except Exception:
            POP_TYPE_NAMES = {}
        parts = []
        for t, v in sorted(emp.items(), key=lambda kv: -kv[1])[:5]:
            parts.append(f"约{int(round(v))}名{POP_TYPE_NAMES.get(t, t)}")
        if parts:
            bits.append(("满编雇佣" if is_full else "实际雇佣") + "、".join(parts))
    else:
        st = obj.get("staffing")
        if isinstance(st, (int, float)):
            bits.append(f"当前雇佣约{round(st, 1)}单位劳动力")
    outs = _pool_goods_text(obj.get("output_goods"), gm)
    if outs:
        bits.append("产出" + outs)
    ins = _pool_goods_text(obj.get("input_goods"), gm)
    if ins:
        bits.append("消耗" + ins)
    return "，".join(bits) + "。"


def _pool_pop_text(pid, obj, ctx, loc):
    """一个 POP → 自然语言: 身份/州/人数/生活水平/识字/接受度/周预算。"""
    try:
        from journal import POP_TYPE_NAMES, sol_band
    except Exception:
        POP_TYPE_NAMES, sol_band = {}, None
    t = POP_TYPE_NAMES.get(obj.get("type"), obj.get("type") or "未知职业")
    state = ctx.state_zh(obj.get("location")) or "未知州"
    culture = culture_id_to_name(obj.get("culture")) or ""
    rel = _religion_zh(obj.get("religion")) or ""
    if culture and rel:
        who = f"{rel}{culture}的{t}"
    elif culture:
        who = f"{culture}的{t}"
    elif rel:
        who = f"{rel}信徒中的{t}"
    else:
        who = t
    bits = [f"{who}，居住在{state}"]
    wf = obj.get("workforce")
    if isinstance(wf, (int, float)) and wf > 0:
        bits.append(f"劳动力约{format(int(round(wf)), ',')}人")
    sol = obj.get("previous_quality_of_life")
    if isinstance(sol, (int, float)) and sol_band:
        band = sol_band(sol)
        if band:
            bits.append(f"生活水平{band}")
    nl = obj.get("num_literate")
    if isinstance(nl, (int, float)) and isinstance(wf, (int, float)) and wf > 0:
        bits.append(f"识字率约{min(100, int(round(nl / wf * 100)))}%")
    acc = (obj.get("acceptance_data") or {}).get("acceptance_status")
    if acc:
        try:
            from journal import ACCEPTANCE_NAMES
        except Exception:
            ACCEPTANCE_NAMES = {}
        bits.append(f"当地接受度为{ACCEPTANCE_NAMES.get(acc, acc)}")
    wb = obj.get("weekly_budget")
    if isinstance(wb, (int, float)):
        bits.append(f"每周收支约{round(wb, 1)}")
    return "，".join(bits) + "。"


def _pool_pop_class(obj):
    """存档 social_class 为嵌套 dict ({"social_class": "lower_class"})。"""
    v = obj.get("social_class")
    if isinstance(v, dict):
        return v.get("social_class")
    return v


# 所有「抽取 POP 作为文章样本」的统一最小劳动力门槛 (劳动力须 > 该值)。
# 报纸访谈、杂志战争样本与各文章池一律从该常量读取, 避免各模块口径不一。
MIN_POP_WORKFORCE = 10


def _pool_workforce_ok(obj):
    """POP 是否达到统一最小劳动力门槛 (workforce > MIN_POP_WORKFORCE)。"""
    wf = obj.get("workforce")
    return isinstance(wf, (int, float)) and wf > MIN_POP_WORKFORCE


def dominant_acceptance_status(pops, weight_key=None):
    """样本POP → 接受度众数; 可选按 weight_key (如 workforce) 加权。
    无有效样本返回 None。"""
    cnt = {}
    for p in pops or []:
        s = p.get("acceptance_status")
        if not s:
            continue
        w = 1
        if weight_key is not None:
            v = p.get(weight_key)
            if isinstance(v, (int, float)) and v > 0:
                w = v
        cnt[s] = cnt.get(s, 0) + w
    if not cnt:
        return None
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def _pool_pick_pops(pops, bid=None, classes=None, n=1, rnd=None,
                    min_workforce=None):
    """按建筑/阶层过滤 POP 并随机抽 n 个; classes 为 social_class 值集合。
    min_workforce 缺省取全局常量 MIN_POP_WORKFORCE (劳动力须 > 该值)。"""
    if min_workforce is None:
        min_workforce = MIN_POP_WORKFORCE
    cand = []
    for pid, obj in pops.items():
        if bid is not None and obj.get("workplace") != bid:
            continue
        if classes and _pool_pop_class(obj) not in classes:
            continue
        wf = obj.get("workforce")
        if not isinstance(wf, (int, float)) or wf <= min_workforce:
            continue
        cand.append((pid, obj))
    if not cand:
        return []
    if rnd is None:
        return cand[:n]
    idxs = rnd.sample(range(len(cand)), min(n, len(cand)))
    return [cand[i] for i in idxs]


def _pool_railway_data(melted, snap, ctx, rnd, country, cid, data):
    """帝国铁道纪行: 铁路州/城市Hub + 两个乡村Hub建筑 + 中上层/下层 POP。"""
    loc = _load_loc_all()
    gm = build_goods_map()
    state_ids = _pool_state_ids(snap)
    by_state, btype_map, objs = ctx.buildings_index(state_ids)
    railways = [(b, objs[b]) for b, t in btype_map.items()
                if t == "building_railway" and (objs[b].get("staffing") or 0) > 0]
    if not railways:
        return None
    rb, robj = rnd.choice(railways)
    sid = robj.get("state")
    hub_names = _hub_names(ctx.state_object(sid))
    city_hub = hub_names[0] if hub_names else None
    st_name = ctx.state_zh(sid) or "未知州"
    div = _pool_division_label(snap)
    if div and city_hub:
        main = f"本期铁道主线：{st_name}{div}{city_hub}。"
    else:
        main = f"本期铁道主线：{st_name}（城市名：{city_hub or '未知'}）。"
    pops = ctx.player_pops(state_ids)
    lead = [
        main,
        _pool_building_text(melted, ctx, cid, rb, robj, loc, gm, pops=pops),
        "这条铁路连接城镇与乡村，运送旅客与货物，并拉动沿线农矿产品外运；"
        "行文以给定数据为准，不得虚构车站名与里程。",
    ]
    rural = []
    for hub_cat in ("farm", "mine", "wood", "port"):
        cand = [(b, o) for b, o in objs.items()
                if (o.get("staffing") or 0) > 0
                and o.get("building") != "building_railway"
                and _hub_for_building(o.get("building")) == hub_cat]
        if cand:
            rural.append(rnd.choice(cand))
    rural = rural[:2]
    rural_lines = []
    if rural:
        rural_lines.append("本期随线走访两座乡村聚落：")
        for b, o in rural:
            hub_cat = _hub_for_building(o.get("building"))
            hub_n = _hub_name_for(ctx.state_object(o.get("state")), hub_cat) \
                if hub_cat in HUB_ORDER else None
            rural_lines.append(
                f"【{hub_n or '乡村聚落'}】"
                + _pool_building_text(melted, ctx, cid, b, o, loc, gm, pops=pops))
    ups = _pool_pick_pops(pops, bid=rb, classes=("middle_class", "upper_class"),
                          n=1, rnd=rnd)
    low_rail = _pool_pick_pops(pops, bid=rb, classes=("lower_class",),
                               n=1, rnd=rnd)
    workers_lines = ["铁路车站与机车库里的人物样本："]
    ups_ck = (
        (culture_id_to_key(ups[0][1].get("culture"))
         if ups and ups[0][1].get("culture") is not None
         else (culture_id_to_key(low_rail[0][1].get("culture"))
               if low_rail and low_rail[0][1].get("culture") is not None
               else None)))
    if ups:
        workers_lines.append("- " + _pool_pop_text(ups[0][0], ups[0][1], ctx, loc))
    if low_rail:
        workers_lines.append("- " + _pool_pop_text(low_rail[0][0], low_rail[0][1], ctx, loc))
    if not ups and not low_rail:
        workers_lines.append("（该铁路建筑当前无足量人群样本，请据雇佣与产出情况含蓄写作。）")
    _blk = person_names_block(f"{snap.get('year')}|{cid}|railway",
                              [("站台人物代表", ups_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        workers_lines.append(_blk)
    _blk = person_names_block(f"{snap.get('year')}|{cid}|railway",
                              [("旅途人物代表", ups_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        lead.append(_blk)
    life_lines = []
    life_ck = None
    if rural:
        rb2, robj2 = rural[0]
        lows = _pool_pick_pops(pops, bid=rb2, classes=("lower_class",),
                               n=2, rnd=rnd)
        life_lines.append("乡村建筑里的劳动者样本：")
        for pid, o in lows:
            life_lines.append("- " + _pool_pop_text(pid, o, ctx, loc))
        if lows and lows[0][1].get("culture") is not None:
            life_ck = culture_id_to_key(lows[0][1].get("culture"))
        if not lows:
            life_lines.append("（该乡村建筑当前无足量人群样本，请据雇佣与产出情况含蓄写作。）")
    _blk = person_names_block(f"{snap.get('year')}|{cid}|railway",
                              [("乡村劳动者代表", life_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        life_lines.append(_blk)
    return {"sections": {
        "lead": "\n".join(lead),
        "rural": ("\n".join(rural_lines) if rural_lines
                  else "（本期无足量乡村聚落样本，请据铁路沿线含蓄写作。）"),
        "workers": "\n".join(workers_lines),
        "life": ("\n".join(life_lines) if life_lines
                 else "（无乡村人群样本，请含蓄收束。）"),
    }}


def _pool_turmoil_data(melted, snap, ctx, rnd, country, cid, data):
    """在光辉以外的地方: 动乱州(激进派占比≥25%) + 政治运动 + 机构法律。"""
    loc = _load_loc_all()
    states = snap.get("states") or []
    rows = []
    for s in states:
        sid = s.get("id")
        sobj = ctx.state_object(sid) if sid is not None else None
        ps = (sobj or {}).get("pop_statistics") or {}
        tot = sum(ps.get(k) or 0 for k in (
            "population_lower_strata", "population_middle_strata",
            "population_upper_strata"))
        rad = ps.get("population_radicals") or 0
        if tot > 0 and rad / tot * 100 >= 25:
            rows.append({"sid": sid, "pct": rad / tot * 100, "tot": tot,
                         "rad": rad, "ps": ps})
    if not rows:
        return None
    pick = rnd.choice(rows)
    sid, pct, tot, rad, ps = (pick["sid"], pick["pct"], pick["tot"],
                              pick["rad"], pick["ps"])
    st = next((s for s in states if s.get("id") == sid), {})
    state_zh = ctx.state_zh(sid) or st.get("name") or "未知州"
    lead = [
        f"本期焦点州：{state_zh}（激进派占比约{pct:.1f}%，"
        f"州总人口约{format(int(round(tot)), ',')}人，"
        f"其中激进派约{format(int(round(rad)), ',')}人）。",
    ]
    nat_rad = snap.get("population_radicals")
    nat_tot = snap.get("total_population")
    if nat_rad and nat_tot:
        lead.append(f"全国激进派占比约{round(nat_rad / nat_tot * 100, 1)}%，"
                    "该州明显高于全国水平。")
    lower, middle, upper = (ps.get("population_lower_strata"),
                            ps.get("population_middle_strata"),
                            ps.get("population_upper_strata"))
    if lower is not None:
        lead.append(f"阶层构成：下层约{format(int(round(lower)), ',')}人、"
                    f"中层约{format(int(round(middle or 0)), ',')}人、"
                    f"上层约{format(int(round(upper or 0)), ',')}人。")
    pops = ctx.player_pops(_pool_state_ids(snap))
    mov_sum = {}
    for obj in pops.values():
        if obj.get("location") != sid:
            continue
        for mid, ratio in (obj.get("political_movement_support") or {}).items():
            try:
                mid_i = int(mid)
            except (TypeError, ValueError):
                continue
            if isinstance(ratio, (int, float)):
                mov_sum[mid_i] = mov_sum.get(mid_i, 0.0) + ratio
    mov_info = {mv.get("id"): mv for mv in (snap.get("political_movements") or [])}
    top = None
    if mov_sum:
        top = mov_info.get(max(mov_sum, key=mov_sum.get))
    movement_lines = []
    if top:
        movement_lines.append(
            f"该州支持度最高的政治运动：{top.get('name') or '未知'}（"
            f"{top.get('ideology') or '未知思潮'}）。")
        if top.get("activism"):
            movement_lines.append(
                f"运动当前处于「{top.get('activism')}」状态，"
                f"激进指数{round(top.get('radicalism') or 0, 2)}。")
        if top.get("supporters"):
            movement_lines.append(
                f"全国支持者约{format(int(round(top['supporters'])), ',')}人，"
                f"大众支持率{round(top.get('popular_pct') or 0, 1)}%、"
                f"军人支持率{round(top.get('military_pct') or 0, 1)}%、"
                f"财富支持率{round(top.get('wealth_pct') or 0, 1)}%。")
        if top.get("civil_war"):
            movement_lines.append("该运动已出现内战/分离倾向。")
    else:
        movement_lines.append("（该州暂无显著政治运动样本。）")
    laws = query_laws(melted, cid)
    law_lines = []
    sel = {}
    for grp, keys in (("公民权", _POOL_CITIZENSHIP_LAWS),
                      ("内部安全", _POOL_SECURITY_LAWS),
                      ("教会与国家", _POOL_CHURCH_LAWS),
                      ("言论", _POOL_SPEECH_LAWS)):
        hit = next((l for l in keys if l in laws), None)
        if hit:
            sel[grp] = hit
    if sel:
        law_lines.append("与冲突相关的现行法律：" + "；".join(
            f"{g}法为{loc.get(k, k)}" for g, k in sel.items()) + "。")
    else:
        law_lines.append("（相关法律数据不足。）")
    insts = _country_institution_levels(melted, cid)
    if insts:
        law_lines.append("全国机构投入：" + "；".join(
            f"{loc.get(k, k)}：{_institution_level_zh(v)}"
            for k, v in sorted(insts.items())) + "。")
    else:
        law_lines.append("（该国暂无机构投入记录，机构均按未设立处理。）")
    incorp = (ctx.state_object(sid) or {}).get("incorporation")
    if incorp is not None and incorp < 1:
        law_lines.append(f"该州尚未完全并入本土（并入进度约{round(incorp * 100)}%），机构覆盖有限。")
    rep = next((obj for pid, obj in sorted(pops.items())
                if obj.get("location") == sid
                and obj.get("culture") is not None), None)
    rep_ck = culture_id_to_key(rep.get("culture")) if rep is not None else None
    _blk = person_names_block(f"{snap.get('year')}|{cid}|turmoil",
                              [("运动支持者代表", rep_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        movement_lines.append(_blk)
    clash_lines = [
        f"政府立场素材：本刊按现行政体（{snap.get('govt_zh') or '未知'}）"
        f"与言论法报道；该州激进派占比约{pct:.1f}%，"
        "执政集团需直面街头与议会的压力，冲突的尺度以给定运动与法律数据为限。"
    ]
    _blk = person_names_block(f"{snap.get('year')}|{cid}|turmoil",
                              [("街垒边的人", rep_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        clash_lines.append(_blk)
    return {"sections": {
        "lead": "\n".join(lead),
        "movement": "\n".join(movement_lines),
        "institutions": "\n".join(law_lines),
        "clash": "\n".join(clash_lines),
    }}


def _pool_shelf_hub_zh(tsid, ctx):
    """贸易中心所在州的 Hub 名: 有 port 优先取 port, 内陆省份取 city;
    解析失败返回 None (调用方回退州名)。"""
    sobj = ctx.state_object(tsid) if tsid is not None else None
    if not sobj:
        return None
    for hub_type in ("port", "city"):
        name = _hub_name_for(sobj, hub_type)
        if name:
            return name
    return None


def _pool_shelf_data(melted, snap, ctx, rnd, country, cid, data):
    """从货架里长出来的: 贸易中心最大交易商品 → 生产链 POP → 顾客。"""
    if country is None:
        return None
    loc = _load_loc_all()
    gm = build_goods_map()
    order, zh, cost = gm["order"], gm["zh"], gm["cost"]
    state_ids = _pool_state_ids(snap)
    by_state, btype_map, objs = ctx.buildings_index(state_ids)
    tcs = [(b, objs[b]) for b, t in btype_map.items()
           if t == "building_trade_center" and (objs[b].get("staffing") or 0) > 0]
    if not tcs:
        return None
    prices = _market_price_map(melted, country) or {}
    chain, industrial = _load_goods_chain()
    if not industrial:
        industrial = set(_POOL_SHELF_FALLBACK_GOODS)
    consumer = _load_consumer_goods()
    world_prices = _pool_world_prices(melted)

    def _supply_ok(gk):
        """世界市场供应代理: 有世界市场价格通道且 价/基准价 < 1.6。
        存档无逐商品供应量; 价格贴顶 (1.75×) 表示卖单远小于买单、供应近乎为零,
        这类后期商品 (电话机/无线电/汽车/飞机) 直接排除。"""
        gid2 = order.index(gk) if gk in order else None
        p = world_prices.get(gid2) if gid2 is not None else None
        c = cost.get(gk)
        if not world_prices:
            return True  # 世界价格解析失败时不误杀
        if gid2 is None or gid2 not in world_prices:
            return False
        if not isinstance(p, (int, float)) or not isinstance(c, (int, float)) or c <= 0:
            return False
        return p / c < _POOL_SUPPLY_PRICE_RATIO

    eligible_goods = {g for g in industrial
                      if g in consumer and _supply_ok(g)}

    def _local_producers(gid):
        """本地 (玩家各州) 产出该商品的生产建筑; 无则返回空列表。"""
        if gid is None:
            return []
        return [(b, o) for b, o in objs.items()
                if str(gid) in ((o.get("output_goods") or {}).get("goods") or {})]

    def _rank(gk):
        if gk not in zh:
            return None
        gid = order.index(gk) if gk in order else None
        p = prices.get(gid) if gid is not None else None
        return {"key": gk, "zh": zh[gk], "gid": gid, "price": p,
                "cost": cost.get(gk)}

    def _pick_qualified(cands):
        """逐个检定「本地有生产建筑」: 不合格换下一种, 返回 (商品, 生产建筑列表)。"""
        for c in cands:
            prod = _local_producers(c["gid"])
            if prod:
                return c, prod
        return None, []

    # 贸易中心按年份种子打乱顺序逐个检定: 优先该州交易记录里的合格制成品
    # (市价降序, 无本地生产建筑就换下一种), 全部不合格再换下一个贸易中心。
    tc_order = list(tcs)
    rnd.shuffle(tc_order)
    good = None
    producers = []
    tb = tobj = None
    tsid = tstate_zh = None
    source = None
    for tb, tobj in tc_order:
        tsid = tobj.get("state")
        tstate_zh = ctx.state_zh(tsid) or "未知州"
        traded = (ctx.state_object(tsid) or {}).get("traded_goods") or []
        ranked = [r for r in (_rank(gk) for gk in traded if gk in eligible_goods) if r]
        ranked.sort(key=lambda r: -(r["price"] if isinstance(r["price"], (int, float))
                                    else 0))
        good, producers = _pick_qualified(ranked)
        if good:
            source = "traded"
            break
    if good is None and tc_order:
        # 所有贸易中心都没有本地可产的交易商品 → 放宽到市场有价的制成品;
        # 按商品名排序迭代, 避免 set 顺序跨进程随机导致同种子选出不同商品。
        tb, tobj = tc_order[0]
        tsid = tobj.get("state")
        tstate_zh = ctx.state_zh(tsid) or "未知州"
        ranked = [r for r in (_rank(gk) for gk in sorted(eligible_goods)) if r]
        good, producers = _pick_qualified(ranked)
        if good:
            source = "fallback"
    if good is None:
        # 本地确实没有任何可产出的合格制成品 → 数据不足, 交文章池兜底。
        return None
    gid = good["gid"]
    chain_info = chain.get(good["key"]) or {}
    producers_zh = [loc.get(b, b) for b in sorted(chain_info.get("producers") or [])]
    inputs_zh = [zh.get(i, i) for i in sorted(chain_info.get("inputs") or [])]
    # 导读「主要原料」优先取本地生产建筑的实际投入 (与作坊段口径一致, 反映在用 PM);
    # 本地无生产建筑时才回落静态产业链 (该建筑所有 PM 的并集, 含未启用的电力等)。
    lead_inputs_zh = inputs_zh
    if producers:
        _real_input_keys = []
        for _b, o in producers:
            for kg in ((o.get("input_goods") or {}).get("goods") or {}):
                try:
                    kid = int(kg)
                except (TypeError, ValueError):
                    continue
                kkey = order[kid] if 0 <= kid < len(order) else None
                if kkey is not None and kkey not in _real_input_keys:
                    _real_input_keys.append(kkey)
        if _real_input_keys:
            lead_inputs_zh = [zh.get(k, k) for k in sorted(_real_input_keys)]
    pops = ctx.player_pops(state_ids)

    # 出口去向必须在 lead 之前算好: lead 直接写真实进口国, 不写「世界市场」。
    importer = None
    market_prices = {}
    laws_by_cid = {}
    try:
        laws_by_cid = _pool_all_laws(melted)
        countries, market_prices = _pool_country_objects(melted)
        importer = _pool_shelf_importer(melted, ctx, snap, rnd, countries,
                                        market_prices, world_prices, gid, cid,
                                        data.get("player") or "", good["key"],
                                        laws_by_cid=laws_by_cid)
    except Exception:
        importer = None

    hub_zh = _pool_shelf_hub_zh(tsid, ctx)
    focus_zh = hub_zh or tstate_zh
    if source == "traded":
        active_line = (
            f"该州交易的大宗商品中，最活跃商品为「{good['zh']}」"
            + (f"，市价约{round(good['price'], 2)}"
               if isinstance(good["price"], (int, float)) else "") + "。")
    else:
        active_line = (
            f"本期从我国可自产的制成品中选取市价居前的「{good['zh']}」"
            + (f"（市价约{round(good['price'], 2)}）"
               if isinstance(good["price"], (int, float)) else "")
            + "作为货架焦点。")
    if importer:
        dest = f"经我国贸易中心出口至{importer['country']}"
        extra = []
        if importer.get("state_zh"):
            extra.append(f"该国商埠：{importer['state_zh']}")
        if isinstance(importer.get("market_price"), (int, float)):
            extra.append(f"当地市价约{round(importer['market_price'], 2)}")
        export_line = dest + (f"（{'，'.join(extra)}）" if extra else "") + "。"
    else:
        export_line = "（出口去向资料不足，本期按本地市场情况写作。）"
    lead = [
        f"本期货架焦点：{focus_zh}的贸易中心。",
        _pool_building_text(melted, ctx, cid, tb, tobj, loc, gm, pops=pops,
                            place=hub_zh),
        active_line,
        (f"「{good['zh']}」为可直接被居民消费的制成品，"
         "产业链至少经过原料→加工两个环节"
         + (f"（主要原料：{'、'.join(lead_inputs_zh[:4])}）"
            if lead_inputs_zh else "")
         + (f"；通常由{'、'.join(producers_zh[:3])}加工"
            if producers_zh else "") + "。"),
        export_line,
    ]
    workshop_lines = [f"生产「{good['zh']}」的本地建筑："]
    wk_ck = None
    if producers:
        for b, o in producers[:2]:
            workshop_lines.append("- " + _pool_building_text(
                melted, ctx, cid, b, o, loc, gm, pops=pops))
            picked = _pool_pick_pops(pops, bid=b,
                                     classes=("lower_class", "middle_class"),
                                     n=1, rnd=rnd)
            for pid, po in picked:
                workshop_lines.append("  工人样本：" + _pool_pop_text(pid, po, ctx, loc))
                if wk_ck is None and po.get("culture") is not None:
                    wk_ck = culture_id_to_key(po.get("culture"))
    else:
        workshop_lines.append(
            "（该商品本地无生产建筑样本；按产业链，此类商品通常由"
            + ("、".join(producers_zh[:3]) if producers_zh else "工业建筑")
            + (f"以{'、'.join(inputs_zh[:4])}为原料加工"
               if inputs_zh else "") + "，请据此写外地输入与商路。）")
    _blk = person_names_block(f"{snap.get('year')}|{cid}|shelf",
                              [("车间工人代表", wk_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        workshop_lines.append(_blk)
    mine_lines = ["原材料链条："]
    up_chain = []
    mn_ck = None
    for b, o in producers[:2]:
        ig = (o.get("input_goods") or {}).get("goods") or {}
        for kg, _kv in ig.items():
            try:
                kid = int(kg)
            except (TypeError, ValueError):
                continue
            kkey = order[kid] if 0 <= kid < len(order) else None
            if kkey is None:
                continue
            upb = [(b2, o2) for b2, o2 in objs.items()
                   if str(kid) in ((o2.get("output_goods") or {}).get("goods") or {})]
            for b2, o2 in upb[:1]:
                up_chain.append((zh.get(kkey, kkey), b2, o2))
    if up_chain:
        for name, b2, o2 in up_chain[:2]:
            mine_lines.append(f"- 上游「{name}」：" + _pool_building_text(
                melted, ctx, cid, b2, o2, loc, gm, pops=pops))
            up_kind = _pool_btype_kind([o2.get("building")])
            up_label = {"mine": "矿工样本", "field": "农工样本",
                        "forest": "林工样本", "fishing": "渔工样本"}.get(
                up_kind, "工人样本")
            picked = _pool_pick_pops(pops, bid=b2, classes=("lower_class",),
                                     n=1, rnd=rnd)
            for pid, po in picked:
                mine_lines.append(f"  {up_label}：" + _pool_pop_text(pid, po, ctx, loc))
                if mn_ck is None and po.get("culture") is not None:
                    mn_ck = culture_id_to_key(po.get("culture"))
    else:
        mine_lines.append(
            ("（本地无上游生产建筑样本；该商品的主要原料为"
             + "、".join(inputs_zh[:4])
             + "，多依赖外地输入，行文须含蓄。）" if inputs_zh
             else "（本地无上游生产建筑样本，原料多依赖外地输入，行文须含蓄。）"))
    _blk = person_names_block(f"{snap.get('year')}|{cid}|shelf",
                              [("上游工人代表", mn_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        mine_lines.append(_blk)
    cust_lines = ["目的地顾客样本："]
    cu_ck = None
    if importer:
        cu_ck = importer.get("pop_culture")
        tariff_txt = ""
        if importer.get("tariff"):
            if importer["tariff"] < 0:
                tariff_txt = f"，进口补贴约{-importer['tariff']}%"
            else:
                tariff_txt = f"，进口关税约{importer['tariff']}%"
        policy_txt = (f"，贸易政策为{loc.get(importer['policy'], importer['policy'])}"
                      if importer.get("policy") else "")
        cust_lines.append(
            f"该商品被出口到{importer['country']}"
            f"{tariff_txt}{policy_txt}。")
        if importer.get("state_zh"):
            cust_lines.append(f"该国商埠：{importer['state_zh']}。")
        if importer.get("pop"):
            cust_lines.append("终端顾客样本：" + importer["pop"])
        else:
            cust_lines.append("（该国商埠无足量人群样本，请含蓄写作。）")
        # 终端花费 = 出厂价 + 出口关税 + 进口关税 (关税按出厂价计)。
        # 出厂价取贸易中心所在市场的当地市价, 与 render_unemployed 同源:
        # _market_price_map 读国家预算价格报告 (缺失回退市场拥有者报告);
        # 该市场在存档中无价格报告时 (AI 市场常见), 回落世界市场参考价。
        wp = importer.get("world_price")
        gate = prices.get(gid) if isinstance(prices.get(gid), (int, float)) else wp
        exporter_laws = laws_by_cid.get(cid) or []
        exporter_policy = next((l for l in _POOL_TRADE_POLICY_MULT
                                if l in exporter_laws), None)
        er = _pool_tariff_rate((country or {}).get("export_tariffs"), gid,
                               "export", exporter_policy)
        ir = importer.get("tariff") or 0.0
        if isinstance(gate, (int, float)) and gate > 0:
            # 现实口径: 出口关税/补贴按出厂价计税; 进口关税按
            # 「出厂价 + 出口关税/补贴金额」(到岸价值) 计税。
            export_duty = gate * er / 100.0
            import_base = gate + export_duty
            import_duty = import_base * ir / 100.0
            total = gate + export_duty + import_duty
            bits = [f"出厂价约{round(gate, 2)}"]
            if abs(er) >= 1e-9:
                bits.append(
                    f"出口补贴{-er}%×出厂价{round(gate, 2)}" if er < 0
                    else f"出口关税{er}%×出厂价{round(gate, 2)}")
            if abs(ir) >= 1e-9:
                bits.append(
                    f"进口补贴{-ir}%×（到岸价{round(import_base, 2)}）" if ir < 0
                    else f"进口关税{ir}%×（到岸价{round(import_base, 2)}）")
        cust_lines.append(
            f"该消费者购买时共花费约{round(total, 2)}英镑（" + "＋".join(bits) + "）。")
    else:
        picked = _pool_pick_pops(pops, classes=("lower_class", "middle_class"),
                                 n=2, rnd=rnd)
        for pid, po in picked:
            cust_lines.append("- " + _pool_pop_text(pid, po, ctx, loc))
            if cu_ck is None and po.get("culture") is not None:
                cu_ck = culture_id_to_key(po.get("culture"))
        cust_lines.append("（出口去向资料不足，按本地市场情况写目的地顾客。）")
    _blk = person_names_block(f"{snap.get('year')}|{cid}|shelf",
                              [("顾客家庭代表", cu_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        cust_lines.append(_blk)
    if not importer and isinstance(good["price"], (int, float)):
        cust_lines.append(
            f"「{good['zh']}」当前市价约{round(good['price'], 2)}，"
            "可作为家庭账本的一笔支出参照。")

    # 动态板块标题: 按生产/上游环节实际形态命名,
    # 避免「生产染料却写矿井」之类的错位 (生产→田垄/作坊, 上游→田垄/矿脉/林场)
    prod_bts = [objs[b].get("building") for b, _ in producers]
    if not prod_bts:
        prod_bts = list(chain_info.get("producers") or [])
    wk = _pool_btype_kind(prod_bts)
    up_bts = [o2.get("building") for _n, _b2, o2 in up_chain]
    mk = _pool_btype_kind(up_bts)
    if mk is None:
        raw_keys = set(chain_info.get("inputs") or [])
        if raw_keys & {"iron", "coal", "sulfur", "lead", "gold", "oil",
                       "stone", "clay", "graphite", "salt", "copper", "zinc"}:
            mk = "mine"
        elif raw_keys & {"grain", "fish", "meat", "sugar", "fruit", "milk",
                         "rice", "cotton", "dye", "silk", "tobacco"}:
            mk = "field"
        elif raw_keys & {"wood", "hardwood", "rubber"}:
            mk = "forest"
    section_titles = {
        "workshop": {"mine": "矿场里的手", "field": "田垄上的手",
                     "forest": "林场里的手", "fishing": "渔场里的手"}.get(
            wk, "工场里的手"),
        "mine": {"mine": "矿脉的尽头", "field": "田垄的尽头",
                 "forest": "林场的尽头", "fishing": "渔场的尽头"}.get(
            mk, "原料的来处"),
    }
    return {"sections": {
        "lead": "\n".join(lead),
        "workshop": "\n".join(workshop_lines),
        "mine": "\n".join(mine_lines),
        "customer": "\n".join(cust_lines),
    }, "section_titles": section_titles}


def _pool_service_data(melted, snap, ctx, rnd, country, cid, data):
    """为人民服务: 教育/医疗/执法机构 + 随机州随机 POP。"""
    loc = _load_loc_all()
    insts = _country_institution_levels(melted, cid) or {}
    laws = query_laws(melted, cid)
    edu = next((l for l in _POOL_EDUCATION_LAWS if l in laws), None)
    health = next((l for l in _POOL_HEALTH_LAWS if l in laws), None)
    state_ids = _pool_state_ids(snap)
    states = snap.get("states") or []
    if insts:
        lead = ["国家机构投入：" + "；".join(
            f"{loc.get(k, k)}：{_institution_level_zh(v)}"
            for k, v in sorted(insts.items())) + "。"]
    else:
        lead = ["（该国暂无机构投入记录，机构均按未设立处理。）"]
    if edu:
        lead.append(f"教育法律为{loc.get(edu, edu)}。")
    if health:
        lead.append(f"卫生法律为{loc.get(health, health)}。")
    if not insts:
        lead.append("（机构数据不足，请据法律与民情含蓄写作。）")
    pops = ctx.player_pops(state_ids)
    state_pops = {}
    for pid, obj in pops.items():
        state_pops.setdefault(obj.get("location"), []).append((pid, obj))
    cand_states = [s for s in states if state_pops.get(s.get("id"))]
    st = rnd.choice(cand_states) if cand_states else (states[0] if states else {})
    sid = st.get("id")
    st_zh = ctx.state_zh(sid) or st.get("name") or "未知州"
    sps = state_pops.get(sid) or []
    wf_tot = sum((o.get("workforce") or 0) for _p, o in sps)
    lit_tot = sum((o.get("num_literate") or 0) for _p, o in sps)
    classroom = [f"样本州：{st_zh}。"]
    if wf_tot > 0:
        classroom.append(f"该州识字率约{min(100, int(round(lit_tot / wf_tot * 100)))}%"
                         "（按人口统计）。")
    gov_wf = (ctx.state_object(sid) or {}).get("pop_statistics") or {}
    g = gov_wf.get("population_government_workforce")
    if g is not None:
        classroom.append(f"该州政府雇员约{format(int(round(g)), ',')}人。")
    staff = _pool_pick_pops(pops, classes=("middle_class", "upper_class"),
                            n=2, rnd=rnd)
    state_pool = {pid: o for pid, o in sps}
    staff = (_pool_pick_pops(state_pool, classes=("middle_class", "upper_class"),
                             n=2, rnd=rnd)
             or staff)
    if staff:
        classroom.append("基层公职/教员样本：")
        for pid, o in staff:
            classroom.append("- " + _pool_pop_text(pid, o, ctx, loc))
    st_ck = (culture_id_to_key(staff[0][1].get("culture"))
             if staff and staff[0][1].get("culture") is not None else None)
    _blk = person_names_block(f"{snap.get('year')}|{cid}|service",
                              [("基层公职/教员代表", st_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        classroom.append(_blk)
    grassroots_pop = (_pool_pick_pops(state_pool, classes=("lower_class",),
                                      n=1, rnd=rnd)
                      or _pool_pick_pops(pops, classes=("lower_class",),
                                         n=1, rnd=rnd))
    grassroots = ["最基层样本："]
    if grassroots_pop:
        pid, o = grassroots_pop[0]
        grassroots.append(_pool_pop_text(pid, o, ctx, loc))
    else:
        grassroots.append("（无足量基层人群样本，请含蓄写作。）")
    gr_ck = (culture_id_to_key(grassroots_pop[0][1].get("culture"))
             if grassroots_pop and grassroots_pop[0][1].get("culture") is not None
             else None)
    _blk = person_names_block(f"{snap.get('year')}|{cid}|service",
                              [("基层民众代表", gr_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        grassroots.append(_blk)
    lights = []
    if snap.get("literacy"):
        lights.append(f"全国识字率约{snap.get('literacy')}。")
    if snap.get("population_radicals") and snap.get("total_population"):
        lights.append(f"全国激进派占比约"
                      f"{round(snap['population_radicals'] / snap['total_population'] * 100, 1)}%。")
    if not lights:
        lights.append("（收束数据不足，请据机构与法律含蓄展望。）")
    return {"sections": {
        "lead": "\n".join(lead),
        "classroom": "\n".join(classroom),
        "grassroots": "\n".join(grassroots),
        "lights": "\n".join(lights),
    }}


_POOL_VOTE_RULES = {
    "law_universal_suffrage": ("普选制", "全体成年公民均可投票"),
    "law_census_voting": ("资格性选举制", "有产与识字者投票，下层劳动者多数被排除"),
    "law_wealth_voting": ("财产投票", "达到财产门槛者投票，无产者被排除"),
    "law_landed_voting": ("地产投票", "贵族、军官、教士与资本家等显贵投票"),
    "law_oligarchy": ("寡头制", "普通民众不参与选举"),
    "law_technocracy": ("技术官僚制", "普通民众不参与选举"),
    "law_organic_regulation": ("有机体规制", "普通民众不参与选举"),
    "law_elder_council": ("长老会议", "普通民众不参与选举"),
    "law_autocracy": ("独裁制", "不设选举"),
    "law_neo_absolutism": ("新专制", "不设选举"),
    "law_bakufu": ("幕府制", "不设选举"),
    "law_single_party_state": ("一党制", "无自由选举"),
    "law_anarchy": ("无政府", "无正式选举程序"),
}


def _pool_discrimination_reason(pop, citizenship, church, state_religion):
    """接受度低于二等公民时, 按现行公民权法/教会法推断排除维度。
    公民权法决定文化维度 (族裔/民族), 教会法决定宗教维度;
    两者同时成立时文化优先 (公民权是政治参与的主要门槛)。"""
    culture_cause = citizenship in ("law_ethnostate", "law_national_supremacy",
                                    "law_racial_segregation")
    rel = pop.get("religion")
    religion_cause = bool(church == "law_state_religion" and rel and state_religion
                          and rel != state_religion)
    if culture_cause:
        return "文化"
    if religion_cause:
        return "宗教"
    return "文化"


def _pool_vote_verdict(pop, dop, citizenship, church=None, state_religion=None):
    """按权力分配法/公民权法近似检定 POP 是否拥有投票权。

    存档无逐 POP 选民标记, 此为程序口径: 文化宗教接纳性 (acceptance) +
    社会阶层 (social_class) + 职业类型。接受度在二等公民以下
    (公开歧视/暴力敌视/文化抹除) 一律无投票权, 二等公民及以上保留资格。
    拒绝理由直接给出具体维度, 优先级: 文化/宗教(受歧视) > 财富(财产/资格) >
    职业(地产阶层)。"""
    acc = (pop.get("acceptance_data") or {}).get("acceptance_status") or ""
    if acc in ("open_prejudice", "violent_hostility", "cultural_erasure"):
        reason = _pool_discrimination_reason(pop, citizenship, church,
                                             state_religion)
        return False, f"该人群因为{reason}不拥有投票权"
    if dop == "law_universal_suffrage":
        return True, "该人群拥有投票权——普选制下全体成年公民均可投票"
    if dop in ("law_census_voting", "law_wealth_voting"):
        ok = _pool_pop_class(pop) in ("middle_class", "upper_class")
        if ok:
            return True, "该人群拥有投票权——达到财产/资格门槛"
        return False, "该人群因为财富不拥有投票权"
    if dop == "law_landed_voting":
        ok = pop.get("type") in ("aristocrats", "capitalists", "clergymen",
                                 "officers")
        if ok:
            return True, "该人群拥有投票权——属于地产投票认可的显贵阶层"
        return False, "该人群因为职业不拥有投票权"
    rule = _POOL_VOTE_RULES.get(dop)
    if rule:
        return False, f"该人群不拥有投票权——{rule[1]}"
    return False, "该人群不拥有投票权——现行权力分配法未提供普选程序"


def _pool_voting_data(melted, snap, ctx, rnd, country, cid, data):
    """神圣庄严的权利: 选举法律 + 随机州随机 POP 的投票权检定。"""
    loc = _load_loc_all()
    laws = query_laws(melted, cid)
    dop = next((l for l in _POOL_DOP_LAWS if l in laws), None)
    citizenship = next((l for l in _POOL_CITIZENSHIP_LAWS if l in laws), None)
    church = next((l for l in _POOL_CHURCH_LAWS if l in laws), None)
    state_ids = _pool_state_ids(snap)
    states = snap.get("states") or []
    pops = ctx.player_pops(state_ids)
    state_pops = {}
    for pid, obj in pops.items():
        if not _pool_workforce_ok(obj):
            continue
        state_pops.setdefault(obj.get("location"), []).append((pid, obj))
    cand = [s for s in states if state_pops.get(s.get("id"))]
    st = rnd.choice(cand) if cand else (states[0] if states else {})
    sid = st.get("id")
    st_zh = ctx.state_zh(sid) or st.get("name") or "未知州"
    ps = (ctx.state_object(sid) or {}).get("pop_statistics") or {}
    ev = ps.get("population_eligible_voters")
    parts = ps.get("population_political_participants")
    rule = _POOL_VOTE_RULES.get(dop)
    lead = [f"现行权力分配法：{loc.get(dop, dop) if dop else '未知'}。"]
    if rule:
        lead.append(rule[1] + "。")
    if citizenship:
        lead.append(f"公民权法律为{loc.get(citizenship, citizenship)}。")
    if church:
        lead.append(f"教会与国家关系法律为{loc.get(church, church)}。")
    gate = [f"样本州：{st_zh}。"]
    if isinstance(ev, (int, float)):
        gate.append(f"该州合格选民约{round(ev * 100, 1)}%（按政治活跃人口计）。")
    if isinstance(parts, (int, float)):
        gate.append(f"政治参与人口约{format(int(round(parts)), ',')}人。")
    sps = state_pops.get(sid) or []
    ballot = []
    if sps:
        pid, pop = rnd.choice(sps)
        ballot.append(_pool_pop_text(pid, pop, ctx, loc))
        bl_ck = (culture_id_to_key(pop.get("culture"))
                 if pop.get("culture") is not None else None)
        # 投票文章例外: 未施行妇女选举权时, 合格选民必然为男性
        women_suffrage = snap.get("women_law") == "law_womens_suffrage"
        _blk = person_names_block(f"{snap.get('year')}|{cid}|voting",
                                  [("选民（主角）", bl_ck)],
                                  female_pct=women_law_female_pct(snap.get("women_law")),
                                  genders=({"选民（主角）": "male"}
                                           if not women_suffrage else None))
        if _blk:
            ballot.append(_blk)
        ok, reason = _pool_vote_verdict(pop, dop, citizenship, church=church,
                                        state_religion=snap.get("religion"))
        ballot.append(f"判定结果：{reason}。")
        ballot.append("请严格按判定结果描写投票日场景：拥有则写他履行权利的过程；"
                      "不拥有则写他被拦在门外的情景，不得反转。")
    else:
        ballot.append("（该州无人群样本。）")
    future = []
    movs = snap.get("political_movements") or []
    if movs:
        m0 = movs[0]
        future.append(f"当前最有影响力的政治运动：{m0.get('name') or '未知'}（"
                      f"{m0.get('ideology') or '未知思潮'}），大众支持率"
                      f"{round(m0.get('popular_pct') or 0, 1)}%。")
    if snap.get("laws_in_progress"):
        future.append("立法进行中：" + "、".join(
            str(loc.get(x.get("law"), x.get("law")))
            for x in snap["laws_in_progress"][:3]) + "。")
    if not future:
        future.append("（展望数据不足。）")
    return {"sections": {
        "lead": "\n".join(lead),
        "gate": "\n".join(gate),
        "ballot": "\n".join(ballot),
        "future": "\n".join(future),
    }}


def _pool_price_data(melted, snap, ctx, rnd, country, cid, data):
    """餐桌上的价格: 市价涨落 + 一户人家的餐桌账本。"""
    if country is None:
        return None
    loc = _load_loc_all()
    gm = build_goods_map()
    order, zh, cost = gm["order"], gm["zh"], gm["cost"]
    prices = _market_price_map(melted, country) or {}
    rows = []
    for gid, p in prices.items():
        key = order[gid] if 0 <= gid < len(order) else None
        if not key or key not in zh:
            continue
        c = cost.get(key)
        if not isinstance(c, (int, float)) or c <= 0:
            continue
        rows.append({"key": key, "zh": zh[key], "gid": gid, "price": p,
                     "cost": c, "ratio": p / c})
    if not rows:
        return None
    # 只保留市价与基准价有实际差异的商品, 避免默认价(未交易)混入榜单
    rows_dev = [r for r in rows if abs(r["ratio"] - 1) > 1e-6]
    if rows_dev:
        rows = rows_dev
    up = sorted(rows, key=lambda r: -(r["ratio"]))[:3]
    down = sorted(rows, key=lambda r: r["ratio"])[:3]
    lead = ["本年度市场物价（以基准价为参照）："]
    lead.append("上涨最明显：" + "、".join(
        f"{r['zh']}（约为基准价的{round(r['ratio'], 2)}倍）" for r in up) + "。")
    lead.append("下跌最明显：" + "、".join(
        f"{r['zh']}（约为基准价的{round(r['ratio'], 2)}倍）" for r in down) + "。")
    state_ids = _pool_state_ids(snap)
    pops = ctx.player_pops(state_ids)
    states = snap.get("states") or []
    locs = {p.get("location") for p in pops.values()}
    cand = [s for s in states if s.get("id") in locs]
    st = rnd.choice(cand) if cand else (states[0] if states else {})
    sid = st.get("id")
    st_zh = ctx.state_zh(sid) or st.get("name") or "未知州"
    household = [f"样本家庭所在地：{st_zh}。"]
    ps = (ctx.state_object(sid) or {}).get("pop_statistics") or {}
    wage = ps.get("wage")
    if isinstance(wage, (int, float)):
        household.append(f"该州平均周薪约{round(wage, 1)}。")
    state_pool = {pid: o for pid, o in pops.items()
                  if o.get("location") == sid}
    lows = (_pool_pick_pops(state_pool, classes=("lower_class",), n=1, rnd=rnd)
            or _pool_pick_pops(pops, classes=("lower_class",), n=1, rnd=rnd))
    if lows:
        pid, o = lows[0]
        household.append("餐桌上的主妇/劳工样本：" + _pool_pop_text(pid, o, ctx, loc))
        hh_ck = (culture_id_to_key(o.get("culture"))
                 if o.get("culture") is not None else None)
        _blk = person_names_block(f"{snap.get('year')}|{cid}|price",
                                  [("餐桌主妇（家庭主妇/劳工）", hh_ck)],
                                  female_pct=women_law_female_pct(snap.get("women_law")),
                                  genders={"餐桌主妇（家庭主妇/劳工）": "female"})
        if _blk:
            household.append(_blk)
        sobj = ctx.state_object(sid)
        pn = (sobj or {}).get("pop_needs") or {}
        entry = None
        if isinstance(pn, dict):
            entry = pn.get(str(o.get("culture"))) or pn.get(o.get("culture"))
        if entry:
            try:
                prof = _consumption_profile(entry, o.get("previous_quality_of_life"))
                if prof and prof.get("goods"):
                    household.append("家庭消费画像（按消费轻重排列）：" + "、".join(
                        g.get("name") for g in prof["goods"][:4]) + "。")
                if prof and prof.get("engel") is not None:
                    household.append(f"恩格尔系数约{prof['engel']}%。")
            except Exception:
                pass
    market = ["本刊关注的几件商品与市价："]
    for r in rows[:5]:
        market.append(f"- {r['zh']}：市价约{round(r['price'], 2)}（基准价{r['cost']}）")
    street = ["街市与生计收束素材："]
    if isinstance(wage, (int, float)):
        street.append(f"{st_zh}平均周薪约{round(wage, 1)}，可作家庭支出参照。")
    street.append("物价涨落与工资、识字率、阶层结构共同构成百姓餐桌的底色，"
                  "行文以给定数字为准，不得编造。")
    hh_ck = (culture_id_to_key(lows[0][1].get("culture"))
             if lows and lows[0][1].get("culture") is not None else None)
    _blk = person_names_block(f"{snap.get('year')}|{cid}|price",
                              [("街市百姓代表", hh_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        street.append(_blk)
    return {"sections": {
        "lead": "\n".join(lead),
        "household": "\n".join(household),
        "market": "\n".join(market),
        "street": "\n".join(street),
    }}


def _pool_letters_data(melted, snap, ctx, rnd, country, cid, data):
    """海外来信: 未并入本土的海外属地 + 本土首都对照。"""
    loc = _load_loc_all()
    state_ids = _pool_state_ids(snap)
    states = snap.get("states") or []
    pops = ctx.player_pops(state_ids)
    state_pops = {}
    for pid, obj in pops.items():
        if not _pool_workforce_ok(obj):
            continue
        state_pops.setdefault(obj.get("location"), []).append((pid, obj))
    colonies = []
    for s in states:
        sid = s.get("id")
        sobj = ctx.state_object(sid) if sid is not None else None
        incorp = (sobj or {}).get("incorporation")
        if incorp is not None and incorp < 1 and state_pops.get(sid):
            colonies.append(s)
    if not colonies:
        return None
    st = rnd.choice(colonies)
    sid = st.get("id")
    st_zh = ctx.state_zh(sid) or st.get("name") or "未知州"
    sobj = ctx.state_object(sid)
    hs = _hub_names(sobj)
    lead = [
        f"海外属地：{st_zh}（尚未完全并入本土，"
        f"并入进度约{round(((sobj or {}).get('incorporation') or 0) * 100)}%）。",
    ]
    cap_hub = (_province_hub_types().get(sobj.get("capital"))
               if sobj and sobj.get("capital") is not None else None)
    local_cap = (_hub_name_for(sobj, cap_hub)
                 if cap_hub in HUB_ORDER
                 else (hs[0] if hs else None))
    if local_cap:
        lead.append(f"当地首府：{local_cap}。")
    if st.get("top_culture"):
        lead.append(f"当地主要文化：{st.get('top_culture')}。")
    harbor = []
    by_state, btype_map, objs = ctx.buildings_index(state_ids)
    gm = build_goods_map()
    in_state = [objs[b] for b in by_state.get(sid, []) if b in objs]
    port = next((o for o in in_state
                 if _hub_for_building(o.get("building")) == "port"), None)
    if port:
        bid = next(b for b, o in objs.items() if o is port)
        harbor.append("港口建筑：" + _pool_building_text(
            melted, ctx, cid, bid, port, loc, gm, pops=pops))
    traded = (sobj or {}).get("traded_goods") or []
    if traded:
        harbor.append("该州交易商品：" + "、".join(
            str(gm["zh"].get(k, k)) for k in traded[:8]) + "。")
    island = ["属地居民样本："]
    sps = state_pops.get(sid) or []
    isl_ck = None
    if sps:
        sampled = rnd.sample(sps, min(2, len(sps)))
        for pid, o in sampled:
            island.append("- " + _pool_pop_text(pid, o, ctx, loc))
        if sampled and sampled[0][1].get("culture") is not None:
            isl_ck = culture_id_to_key(sampled[0][1].get("culture"))
    else:
        island.append("（无人群样本。）")
    _blk = person_names_block(f"{snap.get('year')}|{cid}|letters",
                              [("海外写信人", isl_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        island.append(_blk)
    home = [f"本土对照：首都{snap.get('capital') or '未知'}。"]
    cap_pops = [(pid, o) for pid, o in pops.items()
                if o.get("location") == snap.get("capital_id")
                and _pool_workforce_ok(o)]
    home_ck = None
    if cap_pops:
        home.append("本土家庭样本：" + _pool_pop_text(cap_pops[0][0], cap_pops[0][1], ctx, loc))
        if cap_pops[0][1].get("culture") is not None:
            home_ck = culture_id_to_key(cap_pops[0][1].get("culture"))
    _blk = person_names_block(f"{snap.get('year')}|{cid}|letters",
                              [("故乡回信人", home_ck)],
                              female_pct=women_law_female_pct(snap.get("women_law")))
    if _blk:
        home.append(_blk)
    return {"sections": {
        "lead": "\n".join(lead),
        "harbor": "\n".join(harbor) if harbor else "（该属地港口数据不足。）",
        "island": "\n".join(island),
        "home": "\n".join(home),
    }}


# ---------------------------------------------------------------------------
# 罪案与法网: 每期一桩案件 (受害者/凶手/证人 3 POP) + 法律与机构
# ---------------------------------------------------------------------------

CRIME_TYPES = (
    "murder", "arson", "assault", "blackmail", "robbery", "theft",
    "terrorism",
)
CRIME_TYPE_ZH = {
    "murder": "凶杀",
    "arson": "纵火",
    "assault": "故意伤害",
    "blackmail": "勒索",
    "robbery": "抢劫",
    "theft": "盗窃",
    "terrorism": "恐怖主义（激进派）",
}
CRIME_SCENES_ZH = ("受害者工作建筑内", "路上", "受害者家中")

# Hub 类别 → 中文语境用词 (提示词不出现 Hub 这类元词汇)
_HUB_CATEGORY_ZH = {
    "city": "城邑",
    "port": "港埠",
    "farm": "村落",
    "mine": "矿镇",
    "wood": "林场",
}

# 姓在前、名在后的文化 (按文化键值判定; 东亚/匈牙利等传统姓氏在前)
_SURNAME_FIRST_CULTURES = {
    "han", "manchu", "zhuang", "shan", "yuanzhumin",
    "japanese", "korean", "vietnamese", "hungarian",
}

# 政治动机的「政府直属建筑」: 存档中无所有权记录、由国家直接拥有 (政府行政/大学/艺术学院等)
_GOVERNMENT_BUILDING_TYPES = (
    "building_government_administration",
    "building_university",
    "building_skyscraper",
    "building_art_academy",
    "building_arts_academy",
)

# 接受度状态 → 等级 (数值越大越差): 完全接纳 < 公开歧视 < 二等公民 < 文化抹除 < 暴力敌视
_CRIME_ACCEPTANCE_RANK = {
    "full_acceptance": 0,
    "open_prejudice": 1,
    "second_rate_citizen": 2,
    "cultural_erasure": 3,
    "violent_hostility": 4,
}


def _crime_acceptance_rank(pop):
    """接受度状态 → 等级(越大越差); 缺失返回 None。"""
    acc = (pop.get("acceptance_data") or {}).get("acceptance_status")
    return _CRIME_ACCEPTANCE_RANK.get(acc)


# ---------------------------------------------------------------------------
# 女权法律 → 女性人物概率: 依据现行 lawgroup_rights_of_women 法律, 调整报纸/杂志
# 随机人名的男女名池抽取概率 (士兵文章除外, 军人/军官角色强制男名池)。
# 档位仅作默认值, 可在 config.json 用 female_pct_by_women_law 覆盖。
# ---------------------------------------------------------------------------
WOMEN_LAW_ORDER = (
    "law_no_womens_rights",        # 法定监护
    "law_women_in_the_fields",     # 女性耕作 (黑山专属)
    "law_women_own_property",      # 有产妇女
    "law_women_in_the_workplace",  # 女性工作
    "law_womens_suffrage",         # 妇女选举权
)
DEFAULT_WOMEN_LAW_FEMALE_PCT = {
    "law_no_womens_rights": 0.05,
    "law_women_in_the_fields": 0.05,
    "law_women_own_property": 0.15,
    "law_women_in_the_workplace": 0.30,
    "law_womens_suffrage": 0.45,
}
_WOMEN_PCT_OVERRIDE = None


def _women_pct_override():
    """config.json 的 female_pct_by_women_law 覆盖表 (一次性读取并缓存)。"""
    global _WOMEN_PCT_OVERRIDE
    if _WOMEN_PCT_OVERRIDE is None:
        override = {}
        try:
            path = os.path.join(SCRIPT_DIR, "config.json")
            with open(path, encoding="utf-8") as fp:
                cfg = json.load(fp)
            override = dict(cfg.get("female_pct_by_women_law") or {})
        except Exception:
            override = {}
        _WOMEN_PCT_OVERRIDE = override
    return _WOMEN_PCT_OVERRIDE


def women_law_female_pct(law_key):
    """女权法律 key → 女性人物概率 (0~1); 法律未知/缺失返回 None (维持合并池现行为)。"""
    if not law_key:
        return None
    pct = _women_pct_override().get(law_key)
    if pct is None:
        pct = DEFAULT_WOMEN_LAW_FEMALE_PCT.get(law_key)
    if pct is None:
        return None
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, pct))


_CULTURE_NAMES = None


def build_culture_names():
    """culture key → {first: [合并名池], male: [男名池], female: [女名池], last: [姓池]}。
    解析 game/common/cultures/*.txt 中每个文化内联的
    male/female_common_first_names 与 common/noble_last_names (一次性缓存)。
    token 保留原始下划线/连字符形式 (如 Hari_Singh、Ch_ok), 供本地化整词查表;
    解析失败返回空 dict (调用方不命名)。"""
    global _CULTURE_NAMES
    if _CULTURE_NAMES is not None:
        return _CULTURE_NAMES
    out = {}
    try:
        import glob
        for fn in sorted(glob.glob(os.path.join(CULTURE_FILES, "*.txt"))):
            with open(fn, encoding="utf-8-sig", errors="replace") as fp:
                text = fp.read()
            for m in re.finditer(r"(?m)^([a-z_]+)\s*=\s*\{", text):
                key = m.group(1)
                body = text[m.end():]
                nxt = re.search(r"(?m)^[a-z_]+\s*=\s*\{", body)
                block = body[:nxt.start()] if nxt else body
                male_first = []
                female_first = []
                for lm in re.finditer(
                        r"\bmale_common_first_names\s*=\s*\{(.*?)\}",
                        block, re.S):
                    male_first += [t for t in lm.group(1).split()
                                   if re.fullmatch(r"[A-Za-z][A-Za-z'\-_]*", t)]
                for lm in re.finditer(
                        r"female_common_first_names\s*=\s*\{(.*?)\}",
                        block, re.S):
                    female_first += [t for t in lm.group(1).split()
                                     if re.fullmatch(r"[A-Za-z][A-Za-z'\-_]*", t)]
                male_first = list(dict.fromkeys(male_first))
                female_first = list(dict.fromkeys(female_first))
                # 合并池保持 男→女 的原文顺序, 未指定性别时行为与旧版完全一致
                first = list(dict.fromkeys(male_first + female_first))
                last = []
                for lm in re.finditer(
                        r"(?:common|noble)_last_names\s*=\s*\{(.*?)\}",
                        block, re.S):
                    last += [t for t in lm.group(1).split()
                             if re.fullmatch(r"[A-Za-z][A-Za-z'\-_]*", t)]
                first = list(dict.fromkeys(first))
                last = list(dict.fromkeys(last))
                if first and last:
                    out[key] = {
                        "first": first,
                        "last": last,
                        "male": male_first or first,
                        "female": female_first or first,
                    }
    except Exception:
        out = {}
    _CULTURE_NAMES = out
    return out


def _crime_make_name(culture_key, rnd, gender=None):
    """按文化随机组合 姓+名 → (拉丁原名, 中译名); 姓前/名前由文化键值判定;
    gender 为 "male"/"female" 时从对应名池取, None 用合并池 (现行为);
    无该文化姓名数据返回 (None, None)。拉丁名仅用于内部身份/唯一性判断,
    对外一律用中译名 (经 names_l 本地化查表)。"""
    if not culture_key:
        return None, None
    data = build_culture_names().get(culture_key)
    if not data:
        return None, None
    if gender in ("male", "female"):
        first = rnd.choice(data.get(gender) or data["first"])
    else:
        first = rnd.choice(data["first"])
    last = rnd.choice(data["last"])
    if culture_key in _SURNAME_FIRST_CULTURES:
        latin = f"{last} {first}"
    else:
        latin = f"{first} {last}"
    # 展示用拉丁名把下划线还原为空格 (如 Ch_ok→Ch ok)
    latin = " ".join(p.replace("_", " ") for p in latin.split())
    zh = _localize_character_name(first, last, _load_loc_all(), culture_key)
    return latin, (zh or None)


def _crime_role_names(case, rnd, female_pct=None):
    """受害者/凶手/证人三人姓名 → {role: (拉丁名, 中译名)}。
    按各自文化生成; 三人拉丁名、中译名与「名」均互不相同。
    female_pct 给出时三人各自按该概率先掷性别再取名; 性别在重试循环外一次性
    掷定, 保证同一角色重试时性别不变。"""
    roles = (("受害者", case["victim"][1]),
             ("凶手", case["murderer"][1]),
             ("证人", case["witness"][1]))
    genders = {}
    if female_pct is not None:
        for role, _pop in roles:
            genders[role] = "female" if rnd.random() < female_pct else "male"

    def _given_part(culture_key, name):
        if not name:
            return None
        parts = name.split()
        if culture_key in _SURNAME_FIRST_CULTURES:
            return parts[-1]
        return parts[0]

    names = {}
    for _ in range(20):
        names = {role: _crime_make_name(
                     culture_id_to_key(pop.get("culture")), rnd,
                     gender=genders.get(role))
                 for role, pop in roles}
        latins = [n[0] for n in names.values() if n[0]]
        zhs = [n[1] for n in names.values() if n[1]]
        givens = [_given_part(culture_id_to_key(case[k][1].get("culture")), n[0])
                  for k, n in (("victim", names["受害者"]),
                               ("murderer", names["凶手"]),
                               ("witness", names["证人"]))]
        givens = [g for g in givens if g]
        if (len(set(latins)) == len(latins)
                and len(set(zhs)) == len(zhs)
                and len(set(givens)) == len(givens)):
            break
    return names


def culture_person_name(culture_key, seed=None, gender=None, female_pct=None):
    """按文化生成一个确定性中文人名 (经 names_l 本地化查表)。
    seed 推荐用 f"{year}|{country}|{article}|{section}|{role}" 保证同年稳定;
    gender 显式指定男/女名池; 未指定且 female_pct 给出时, 先按该概率掷性别再
    取名 (同一 seed 结果稳定); 两者皆无时维持合并池现行为。
    无该文化姓名池或查不到译名时返回 None (调用方不得自行命名)。"""
    if not culture_key:
        return None
    rnd = random.Random(seed) if seed is not None else random.Random()
    if gender is None and female_pct is not None:
        gender = "female" if rnd.random() < female_pct else "male"
    _latin, zh = _crime_make_name(culture_key, rnd, gender=gender)
    return zh or None


def person_names(seed, roles, female_pct=None, genders=None):
    """roles: [(角色名, culture_key|None), ...] → {角色: 中文名}。
    各角色姓名互不相同; 文化无名池的角色不出现在结果里。
    genders: {角色: "male"/"female"} 显式强制性别; 其余角色在 female_pct 给出时
    按该概率各自掷性别, 否则维持合并池现行为。"""
    out = {}
    used = set()
    genders = genders or {}
    for i, (role, ck) in enumerate(roles):
        nm = None
        if ck:
            for _ in range(20):
                g = genders.get(role)
                nm = culture_person_name(
                    ck, seed=f"{seed}|{i}|{role}|{_}",
                    gender=g,
                    female_pct=None if g else female_pct)
                if nm and nm not in used:
                    break
        if nm:
            out[role] = nm
            used.add(nm)
    return out


def person_names_block(seed, roles, female_pct=None, genders=None):
    """人名名单提示块: 姓名已由数据给定, 全文必须原样使用。无姓名返回空串。"""
    names = person_names(seed, roles, female_pct=female_pct, genders=genders)
    if not names:
        return ""
    lines = ["人物名单（姓名已由数据给定，全文必须原样使用，不得自行取名或改名）："]
    for role, _ck in roles:
        if role in names:
            lines.append(f"- {role}：{names[role]}")
    return "\n".join(lines)


_ZH_CULTURE_INDEX = None


def culture_key_from_zh(zh_name):
    """中文文化名 → culture key (本地化反向查表); 找不到返回 None。"""
    global _ZH_CULTURE_INDEX
    if not zh_name:
        return None
    if _ZH_CULTURE_INDEX is None:
        idx = {}
        for k, v in (build_culture_map().get("_zh") or {}).items():
            idx.setdefault(v, k)
        _ZH_CULTURE_INDEX = idx
    return _ZH_CULTURE_INDEX.get(zh_name)


def _crime_hub_label(cat):
    """Hub 类别 → 中文语境用词; 未知类别回退「聚落」。"""
    return _HUB_CATEGORY_ZH.get(cat, "聚落")


def _crime_state_owned(melted, cid, bid, obj):
    """建筑是否由国家(政府)直接拥有:
    1) 所有权记录中份额最大者为国有 (identity.country == 本国);
    2) 政府直属建筑无所有权记录 (政府行政机构/大学/艺术学院等) 直接视为国有。"""
    owners = obj.get("owners") or []
    if not owners:
        return (obj.get("building") or "") in _GOVERNMENT_BUILDING_TYPES
    try:
        dist, total = _building_ownership(melted, bid, cid, building_obj=obj)
    except Exception:
        return False
    if not total or not dist.get("state"):
        return False
    top = max(dist, key=lambda k: (dist[k], _OWNERSHIP_ORDER.index(k)))
    return top == "state"


def _crime_workplace_ctx(ctx, obj):
    """工作建筑对象 → (建筑中文名, 聚落名, 州中文名, 聚落类别)。"""
    loc = _load_loc_all()
    btype = obj.get("building") or ""
    bzh = loc.get(btype, btype) or "未知建筑"
    state = ctx.state_zh(obj.get("state")) or "未知州"
    hub = None
    cat = _hub_for_building(btype)
    if cat:
        sobj = ctx.state_object(obj.get("state")) if obj.get("state") is not None else None
        if sobj:
            hub = _hub_name_for(sobj, cat)
    return bzh, hub, state, cat


def _crime_candidates(pops, objs, require_workplace=False, classes=None):
    """可作案件角色的 POP: 劳动力超过统一最小门槛、阶层可识别、
    (可选)工作建筑在本国州内。"""
    out = []
    for pid, obj in pops.items():
        if not _pool_workforce_ok(obj):
            continue
        cls = _pool_pop_class(obj)
        if cls not in ("lower_class", "middle_class", "upper_class"):
            continue
        if classes and cls not in classes:
            continue
        if require_workplace and obj.get("workplace") not in objs:
            continue
        out.append((pid, obj))
    return out


def _crime_motive(melted, cid, victim, murderer, objs):
    """按数据判定动机: 经济(受害者SoL更高) > 文化(受害者接受度更差) > 政治(政府建筑)。
    返回 (key, 自然语言说明) 或 None。"""
    from journal import sol_band
    v_sol = victim.get("previous_quality_of_life")
    m_sol = murderer.get("previous_quality_of_life")
    if isinstance(v_sol, (int, float)) and isinstance(m_sol, (int, float)) and v_sol > m_sol:
        vb = sol_band(v_sol) or f"约{v_sol}"
        mb = sol_band(m_sol) or f"约{m_sol}"
        return "economic", f"经济动机：受害者生活水平（{vb}）高于凶手（{mb}）。"
    v_acc = _crime_acceptance_rank(victim)
    m_acc = _crime_acceptance_rank(murderer)
    if v_acc is not None and m_acc is not None and v_acc > m_acc:
        return "cultural", "文化动机：受害者在当地受到的接受度低于凶手（更受歧视）。"
    bid = victim.get("workplace")
    if bid in objs and _crime_state_owned(melted, cid, bid, objs[bid]):
        return "political", "政治动机：受害者工作于国家（政府）所有的建筑。"
    return None


def _crime_pick_case(melted, snap, ctx, rnd, cid, pops, objs):
    """抽取一桩案件: 随机案件类型 → 按类型约束选受害者/凶手 → 判定动机 → 补证人。
    返回 dict 或 None (数据不足以成案时让兜底文章补位)。"""
    mov_info = {mv.get("id"): mv for mv in (snap.get("political_movements") or [])}
    protest_mids = {mid for mid, mv in mov_info.items()
                    if mv.get("activism") in ("抗议", "武斗")}
    all_cand = _crime_candidates(pops, objs)
    victims = _crime_candidates(pops, objs, require_workplace=True)
    if len(all_cand) < 3 or not victims:
        return None
    cls_of = {"lower_class": 0, "middle_class": 1, "upper_class": 2}
    for _ in range(40):
        crime_type = rnd.choice(CRIME_TYPES)
        if crime_type in ("robbery", "theft"):
            # 抢劫/盗窃: 受害者阶层恰好比凶手高一级
            mrank = rnd.choice((0, 1))
            mcls = ("lower_class", "middle_class")[mrank]
            vcls = ("middle_class", "upper_class")[mrank]
            mpool = [x for x in all_cand if _pool_pop_class(x[1]) == mcls]
            vpool = [x for x in victims if _pool_pop_class(x[1]) == vcls]
            if not mpool or not vpool:
                continue
            murderer = rnd.choice(mpool)
            vpool = [x for x in vpool if x[0] != murderer[0]]
            if not vpool:
                continue
            victim = rnd.choice(vpool)
        elif crime_type == "terrorism":
            # 恐怖主义: 凶手参与某个人已进入抗议(抗议/武斗)的政治运动
            mpool = [
                x for x in all_cand
                if any(v > 0 and _safe_int(mid) in protest_mids
                       for mid, v in (x[1].get("political_movement_support") or {}).items())
            ]
            if not mpool:
                continue
            murderer = rnd.choice(mpool)
            vpool = [x for x in victims if x[0] != murderer[0]]
            if not vpool:
                continue
            victim = rnd.choice(vpool)
        else:
            victim = rnd.choice(victims)
            mpool = [x for x in all_cand if x[0] != victim[0]]
            if not mpool:
                continue
            murderer = rnd.choice(mpool)
        motive = _crime_motive(melted, cid, victim[1], murderer[1], objs)
        if not motive:
            continue
        rest = [x for x in all_cand if x[0] not in (victim[0], murderer[0])]
        same_state = [x for x in rest
                      if x[1].get("location") == victim[1].get("location")]
        same_bld = [x for x in rest
                    if x[1].get("workplace") == victim[1].get("workplace")]
        if same_state:
            witness = rnd.choice(same_state)
        elif same_bld:
            witness = rnd.choice(same_bld)
        elif rest:
            witness = rnd.choice(rest)
        else:
            continue
        movement = None
        if crime_type == "terrorism":
            for mid, v in (murderer[1].get("political_movement_support") or {}).items():
                mv = mov_info.get(_safe_int(mid))
                if mv and mv.get("activism") in ("抗议", "武斗") and v > 0:
                    movement = mv
                    break
        return {"victim": victim, "murderer": murderer, "witness": witness,
                "crime_type": crime_type, "scene": rnd.choice(CRIME_SCENES_ZH),
                "motive": motive[0], "motive_text": motive[1],
                "movement": movement}
    return None


def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pool_crime_data(melted, snap, ctx, rnd, country, cid, data):
    """罪案与法网: 每期一桩案件 + 3个居民(受害者/凶手/证人) + 法律机构。
    案件类型: 凶杀/纵火/故意伤害/勒索/抢劫/盗窃/恐怖主义(激进派);
    案发地为受害者工作建筑所在聚落; 法律与机构等级一律自然语言。"""
    if not cid:
        return None
    from journal import law_zh
    # 案件类型与角色按 (年|crime|国家) 播种: 同年稳定, 且不同国家案件各不相同
    rnd = random.Random(f"{snap.get('year') or 0}|crime|{cid}")
    loc = _load_loc_all()
    state_ids = _pool_state_ids(snap)
    pops = ctx.player_pops(state_ids)
    _bs, _bmap, objs = ctx.buildings_index(state_ids)
    case = _crime_pick_case(melted, snap, ctx, rnd, cid, pops, objs)
    if not case:
        return None
    victim, murderer, witness = (case["victim"], case["murderer"],
                                 case["witness"])
    vbid = victim[1].get("workplace")
    vobj = objs.get(vbid) or {}
    bzh, vhub, vstate, vcat = (_crime_workplace_ctx(ctx, vobj) if vbid in objs
                               else ("未知建筑", None,
                                     ctx.state_zh(victim[1].get("location")),
                                     None))
    place = vhub or vstate or "未知地点"
    hub_label = _crime_hub_label(vcat)
    crime_zh = CRIME_TYPE_ZH.get(case["crime_type"], case["crime_type"])
    scene = case["scene"]
    names = _crime_role_names(
        case, rnd,
        female_pct=women_law_female_pct(snap.get("women_law")))
    mov_line = ""
    mv = case.get("movement")
    if mv:
        mov_line = (
            f"凶手参与的抗议政治运动：{mv.get('name') or '未知'}（"
            f"{mv.get('ideology') or '未知思潮'}），当前处于「{mv.get('activism')}」"
            f"状态，激进指数{round(mv.get('radicalism') or 0, 2)}。"
        )
    # 法律与机构 (需求: Policing / Internal Security 法律 + 两机构自然语言等级)
    laws = query_laws(melted, cid)
    policing = next((l for l in _POOL_POLICING_LAWS if l in laws), None)
    internal = next((l for l in _POOL_INTERNAL_SECURITY_LAWS if l in laws), None)
    insts = _country_institution_levels(melted, cid) or {}
    # 存档无该机构条目即未投入, 按 0 级「尚未设立」处理
    police_lv = _institution_level_zh(insts.get("institution_police", 0))
    home_lv = _institution_level_zh(insts.get("institution_home_affairs", 0))

    def _role_line(pop, role):
        txt = _pool_pop_text(pop[0], pop[1], ctx, loc)
        nm = (names.get(role) or (None, None))[1]
        return f"- 【{role}】{nm}，{txt}" if nm else f"- 【{role}】{txt}"

    # 案件概要: 每个板块都重述案件类型/案发地/场景, 避免后续板块只看摘要而写串
    case_head = (
        f"本期罪案特稿：一桩{crime_zh}案。"
        f"案发地：{place}（受害者工作建筑所在的{hub_label}）；案发现场为{scene}。"
        "案件类型、案发地与案发现场全篇不得改变，非暴力案件不得写成杀伤。"
    )
    if all((names.get(r) or (None, None))[1]
           for r in ("受害者", "凶手", "证人")):
        name_rule = ("三人中文姓名已由资料给定，全篇必须原样使用（译法固定），"
                     "不得另行取名、改名或回写拉丁原名。")
    else:
        name_rule = ("不得虚构人物姓名，一律以「受害者」「凶手」「证人」"
                     "及职业身份代称。")
    # 三角色全表: 每个板块都原样附带, 防止模型在分板块写作时互换角色
    role_table = (
        "全篇三角色身份固定，不得互换、合并或改写（身份/职业/文化/宗教/人数/"
        f"生活水平一律以资料为准；{name_rule}）：\n"
        + _role_line(victim, "受害者") + "\n"
        + _role_line(murderer, "凶手") + "\n"
        + _role_line(witness, "证人")
    )
    case_lines = [
        case_head,
        f"受害者工作建筑：{bzh}（位于{place}）。",
        role_table,
        f"动机：{case['motive_text']}",
    ]
    if mov_line:
        case_lines.append(mov_line)
    case_lines.append(
        f"开篇请立起案发地（{hub_label}）的场景与人物，可按案件类型还原案发经过，"
        "但不得虚构资料之外的具体伤亡数字与日期。"
    )
    victim_lines = [
        case_head,
        role_table,
        f"受害者工作建筑：{bzh}（位于{place}）。",
        "本板块只写【受害者】与【证人】两位（凶手不得在此出场或换角）："
        "从他们的视角写案发前后的生活、现场与听闻，"
        "以资料中的职业/文化/宗教/生活水平塑造人物。",
    ]
    perp_lines = [
        case_head,
        role_table,
        f"动机：{case['motive_text']}",
    ]
    if mov_line:
        perp_lines.append(mov_line)
    perp_lines.append(
        "本板块只写【凶手】一位（受害者与证人不得换角）："
        "写凶手的处境与动机如何从资料中生长出来：经济落差/文化隔阂/"
        "政治怨愤以给定动机为准；恐怖主义案件须写其政治运动背景，"
        "不得虚构运动领袖姓名与具体行动细节。"
    )
    justice_lines = [
        case_head,
        role_table,
        "现行警察机构法律（Policing）："
        + (law_zh(policing) if policing else "（资料缺失）") + "。",
        "现行国内安全法律（Internal Security）："
        + (law_zh(internal) if internal else "（资料缺失）") + "。",
        f"执法机构（Policing）投入：{police_lv}。",
        f"内务机构（Internal Security）投入：{home_lv}。",
        "本板块请写案件进入法网后的后续——侦办、缉凶、庭审或悬案收束，"
        "尺度以给定法律与机构为限，不得虚构具体判决与刑期。",
    ]
    return {"sections": {
        "case": "\n".join(case_lines),
        "victim": "\n".join(victim_lines),
        "perpetrator": "\n".join(perp_lines),
        "justice": "\n".join(justice_lines),
    }}


# ---------------------------------------------------------------------------
# 货架文章: 世界市场出口去向模拟 (按 Victoria 3 Wiki 贸易优势口径近似)
# 存档不保存逐国贸易路线, 用可得的国家级数据模拟:
#   出口 → 世界市场 (world_market 每商品价格) → 按「贸易优势代理权重」
#   (价格差 + 市场准入 + 贸易能力 − 进口关税, 再乘贸易政策修正) 加权抽取进口国
#   → 进口国市场中心州 (market_capital/首都) 随机 POP 作为终端顾客。
# ---------------------------------------------------------------------------

# 关税/补贴率(%) = 贸易政策法案的基础税率(按进出口方向) × 档位系数。
# 法案 modifier 见 common/laws/01_trade_policy.txt; 档位系数见 00_defines.txt
# TARIFF_LEVEL_EFFECT_LOW/HIGH/MAXIMUM = 0.25/0.5/1.0。
# 存档 tariffs 字典只保存显式设置的档位, 未设置的走游戏默认档位
# DEFAULT_EXPORT_TARIFFS / DEFAULT_IMPORT_TARIFFS = low_tariffs。
_POOL_TARIFF_LAW_BASE = {
    "law_mercantilism": {"import": 0.50, "export": 0.20,
                         "import_sub": 0.20, "export_sub": 0.50},
    "law_protectionism": {"import": 0.50, "export": 0.50,
                          "import_sub": 0.50, "export_sub": 0.50},
    "law_canton_system": {"import": 0.50, "export": 0.50,
                          "import_sub": 0.20, "export_sub": 0.20},
    "law_sakoku": {"import": 0.50, "export": 0.50,
                   "import_sub": 0.20, "export_sub": 0.20},
    "law_free_trade": {"import": 0.0, "export": 0.0,
                       "import_sub": 0.50, "export_sub": 0.50},
    "law_isolationism": {"import": 0.0, "export": 0.0,
                         "import_sub": 0.0, "export_sub": 0.0},
}
_POOL_TARIFF_LEVEL_FRACTION = {
    "no_tariffs_or_subventions": 0.0,
    "low_tariffs": 0.25,
    "high_tariffs": 0.5,
    "max_tariffs": 1.0,
    "low_subventions": -0.25,
    "high_subventions": -0.5,
    "max_subventions": -1.0,
}
_POOL_TRADE_POLICY_MULT = {
    "law_free_trade": 1.25,
    "law_protectionism": 1.0,
    "law_mercantilism": 0.75,
    "law_isolationism": 0.0,
    "law_canton_system": 0.0,
}

# 世界市场供应代理阈值: 存档无逐商品供应量字段, 用「世界市场价/基准价」代替。
# 价格贴顶 (1.75×基准价) 表示卖单远小于买单、供应近乎为零 —— 这类后期商品
# (电话机/无线电/汽车/飞机) 直接排除; 实际有供应的商品通常 ≤1.5×。
_POOL_SUPPLY_PRICE_RATIO = 1.6

# 商品 → (需求类别, 最低消费 SoL)
# 按 Needs Wiki (1.13) 需求档位表: 需求类别首次被消费的财富档位下界;
# 商品跨多类别时取最小阈值 (如 groceries 属基本食物, SoL 1 即可消费)。
_POOL_NEED_INFO = {
    "groceries": ("基本食物", 1),
    "clothes": ("简朴衣物", 1),
    "liquor": ("酒类饮品", 1),
    "furniture": ("粗制品", 5),
    "glass": ("家用物品", 10),
    "paper": ("家用物品", 10),
    "luxury_clothes": ("奢侈品", 15),
    "luxury_furniture": ("奢侈品", 15),
    "porcelain": ("奢侈品", 15),
    "silk": ("奢侈品", 15),
    "radios": ("奢侈品", 15),
    "automobiles": ("自由出行", 10),
    "small_arms": ("休闲", 20),
    "telephones": ("通讯", 20),
    "aeroplanes": ("休闲", 20),
}


def _pool_tariff_rate(tariffs, gid, direction="import", law=None):
    """某商品关税/补贴率(%): 贸易政策法案基础税率 × 档位系数。
    tariffs 为存档国家 tariffs 字典 (商品id字符串键 → {level}); 该商品未显式
    设置时回落游戏默认档位 low_tariffs (00_defines DEFAULT_*_TARIFFS)。
    direction 为 "import"/"export", law 为该国现行贸易政策法案。"""
    if gid is None:
        return 0.0
    entry = (tariffs or {}).get(str(gid)) or {}
    level = entry.get("level") or "low_tariffs"
    frac = _POOL_TARIFF_LEVEL_FRACTION.get(level, 0.0)
    bases = _POOL_TARIFF_LAW_BASE.get(law) or {}
    key = ("import_sub" if direction == "import" else "export_sub") \
        if "subvention" in level else direction
    return bases.get(key, 0.0) * frac * 100.0


def _pool_division_label(snap):
    """政体 → 行政区划后缀 (省/州), 与报纸口径一致 (journal._division_label)。"""
    try:
        from journal import _division_label
    except Exception:
        return None
    return _division_label(snap.get("govt") or snap.get("govt_key") or "")


def _pool_series_last(obj, key):
    """国家对象里 gdp/prestige 等时序字段的当前值 (最后一个通道最后一个值)。"""
    ch = ((obj or {}).get(key) or {}).get("channels") or {}
    last = None
    for v in ch.values():
        vals = v.get("values") or []
        if vals:
            last = vals[-1]
    return last


def _pool_country_objects(melted):
    """单次扫描 country_manager → ({cid: 国家对象}, {市场id: {商品id: 价格}})。"""
    out = {}
    prices_by_market = {}
    cm = melted.find(b'"country_manager"')
    if cm < 0:
        return out, prices_by_market
    cm_end = _object_end(melted, melted.find(b'{', cm))
    db = melted.find(b'"database"', cm)
    if db < 0:
        return out, prices_by_market
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = melted.find(b'{', db)
    while True:
        m = _IDOBJ.search(melted, j, cm_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(melted, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if isinstance(obj, dict) and obj.get("definition") and obj.get("states"):
            cid = int(m.group(1))
            out[cid] = obj
            pm = _price_report_to_map((obj.get("budget") or {}).get("current_price_report"))
            if not pm:
                pm = _price_report_to_map((obj.get("budget") or {}).get("previous_price_report"))
            mid = obj.get("market")
            if pm and mid is not None and mid not in prices_by_market:
                prices_by_market[mid] = pm
        j = end
    return out, prices_by_market


def _pool_world_prices(melted):
    """世界市场每商品价格: world_market.price_trend.channels[商品id].values[-1]。"""
    i = melted.find(b'"world_market":{')
    if i < 0:
        return {}
    ob = melted.find(b'{', i)
    end = _object_end(melted, ob)
    seg = melted[ob:min(end, ob + 600000)]
    out = {}
    for m in re.finditer(rb'"(\d+)":\{.*?"values":\[(.*?)\]', seg, re.S):
        vals = m.group(2).decode("utf-8", "replace").split(",")
        if not vals:
            continue
        try:
            out[int(m.group(1))] = float(vals[-1].strip())
        except ValueError:
            pass
    return out


def _pool_world_market_hubs(melted, ctx):
    """世界市场中心 (每个有港口的市场区域一个): [{state, country, trade_centers}]。"""
    i = melted.find(b'"active_world_market_hubs":[')
    if i < 0:
        return []
    start = melted.find(b'[', i)
    depth, end, n = 0, start, len(melted)
    while end < n:
        c = melted[end]
        if c == 91:
            depth += 1
        elif c == 93:
            depth -= 1
            if depth == 0:
                break
        end += 1
    try:
        arr = json.loads(melted[start:end + 1])
    except Exception:
        return []
    out = []
    for e in arr:
        sid = e.get("state")
        if sid is None:
            continue
        sobj = ctx.state_object(sid)
        out.append({"state": sid, "country": (sobj or {}).get("country"),
                    "trade_centers": e.get("trade_centers") or []})
    return out


def _pool_all_laws(melted):
    """单次扫描 laws.database → {cid: [法律key]}。"""
    out = {}
    idx = melted.find(b'"laws"')
    if idx < 0:
        return out
    laws_end = _object_end(melted, melted.find(b'{', idx))
    db = melted.find(b'"database"', idx)
    if db < 0:
        return out
    _IDOBJ = re.compile(rb'"(\d+)":\{')
    j = melted.find(b'{', db)
    while True:
        m = _IDOBJ.search(melted, j, laws_end - 1)
        if not m:
            break
        ob2 = m.start() + len(m.group(0)) - 1
        raw, end = extract_json_object(melted, ob2)
        if not raw:
            break
        try:
            obj = json.loads(raw)
        except Exception:
            j = end
            continue
        if (isinstance(obj, dict) and obj.get("law") and obj.get("active")
                and obj.get("country") is not None):
            out.setdefault(obj["country"], []).append(obj["law"])
        j = end
    return out


def _pool_shelf_importer(melted, ctx, snap, rnd, countries, market_prices,
                         world_prices, gid, player_cid, player_name, good_key,
                         laws_by_cid=None):
    """按贸易优势代理权重抽取进口国, 返回事实 dict; 无候选返回 None。"""
    if gid is None:
        return None
    hubs = _pool_world_market_hubs(melted, ctx)
    cand = {}
    for h in hubs:
        cid = h.get("country")
        if cid is None or cid == player_cid:
            continue
        cand.setdefault(cid, {"state": h["state"],
                              "tcs": len(h.get("trade_centers") or [])})
    if not cand:
        return None
    at_war = set()
    for w in (snap.get("wars") or []):
        if w.get("player_involved"):
            for p in (w.get("participants") or []):
                c = p.get("country_id") or p.get("id")
                if c is not None:
                    at_war.add(c)
    if laws_by_cid is None:
        laws_by_cid = _pool_all_laws(melted)
    world_p = world_prices.get(gid)
    if not isinstance(world_p, (int, float)) or world_p <= 0:
        return None
    rows = []
    for cid, info in cand.items():
        c = countries.get(cid)
        if not c or cid in at_war:
            continue
        laws = laws_by_cid.get(cid) or []
        policy = next((l for l in _POOL_TRADE_POLICY_MULT if l in laws), None)
        mult = _POOL_TRADE_POLICY_MULT.get(policy, 0.0)
        if mult <= 0:
            continue
        mid = c.get("market")
        local_p = (market_prices.get(mid) or {}).get(gid) if mid is not None else None
        if not isinstance(local_p, (int, float)):
            local_p = world_p
        price_bonus = max(0.0, (local_p - world_p) / world_p) * 200
        tariff = _pool_tariff_rate(c.get("import_tariffs"), gid, "import", policy)
        capacity = min(info["tcs"], 10) * 8
        sobj = ctx.state_object(info["state"])
        incorp = (sobj or {}).get("incorporation")
        access = 100.0 if (incorp is None or incorp >= 1) else max(0.0, incorp * 100)
        gdp = _pool_series_last(c, "gdp")
        gdp_w = 1.0
        if isinstance(gdp, (int, float)) and gdp > 0:
            gdp_w = min(2.0, 1.0 + 0.05 * (gdp / 1000000.0))
        w = (100 + price_bonus + access + capacity - tariff) * mult * gdp_w
        if w <= 0:
            continue
        rows.append({"cid": cid, "obj": c, "state": info["state"],
                     "market_price": local_p, "world_price": world_p,
                     "tariff": tariff, "policy": policy,
                     "tcs": info["tcs"], "weight": w})
    if not rows:
        return None
    pick = rnd.choices(rows, weights=[r["weight"] for r in rows], k=1)[0]
    index, _, _ = ctx.index()
    try:
        names = build_country_id_names(melted, index)
    except Exception:
        names = {}
    cname = names.get(pick["cid"]) or str(pick["cid"])
    tsid = pick["obj"].get("market_capital") or pick["obj"].get("capital")
    tsid = tsid if isinstance(tsid, int) and tsid > 0 else None
    need = _POOL_NEED_INFO.get(good_key)
    need_name = need[0] if need else None
    need_sol = need[1] if need else None
    pop_text = None
    sol_note = None
    pop_culture = None
    if tsid is not None:
        pops = ctx.player_pops([tsid])
        loc = _load_loc_all()
        if need_sol:
            qualified = [(pid, o) for pid, o in pops.items()
                         if isinstance(o.get("previous_quality_of_life"), (int, float))
                         and o["previous_quality_of_life"] >= need_sol
                         and _pool_workforce_ok(o)]
            if qualified:
                pid, o = rnd.choice(qualified)
                pop_text = _pool_pop_text(pid, o, ctx, loc)
                pop_culture = (culture_id_to_key(o.get("culture"))
                               if o.get("culture") is not None else None)
                sol_note = (f"该商品属{need_name}需求，通常由生活水平{need_sol}及以上"
                            "的家庭消费，本样本满足门槛。")
            else:
                best = None
                for _pid, o in pops.items():
                    v = o.get("previous_quality_of_life")
                    if isinstance(v, (int, float)) and (best is None or v > best):
                        best = v
                top = [(pid, o) for pid, o in pops.items()
                       if isinstance(o.get("previous_quality_of_life"), (int, float))
                       and o["previous_quality_of_life"] == best
                       and _pool_workforce_ok(o)]
                if top:
                    pid, o = rnd.choice(top)
                    pop_text = _pool_pop_text(pid, o, ctx, loc)
                    pop_culture = (culture_id_to_key(o.get("culture"))
                                   if o.get("culture") is not None else None)
                sol_note = (
                    f"该商品属{need_name}需求，通常由生活水平{need_sol}及以上的家庭消费；"
                    + (f"该州生活水平最高的样本约{best}，略低于门槛，请据样本含蓄写作。"
                       if best is not None else "该州无足量样本。"))
        else:
            picked = _pool_pick_pops(pops, classes=("lower_class", "middle_class"),
                                     n=1, rnd=rnd)
            if picked:
                pop_text = _pool_pop_text(picked[0][0], picked[0][1], ctx, loc)
                pop_culture = (culture_id_to_key(picked[0][1].get("culture"))
                               if picked[0][1].get("culture") is not None else None)
    total_w = sum(r["weight"] for r in rows)
    return {
        "country": cname,
        "state": tsid,
        "state_zh": ctx.state_zh(tsid) if tsid else None,
        "market_price": pick["market_price"],
        "world_price": pick["world_price"],
        "tariff": pick["tariff"],
        "policy": pick["policy"],
        "pop": pop_text,
        "pop_culture": pop_culture,
        "need": need_name,
        "need_sol": need_sol,
        "sol_note": sol_note,
        "weight_share": round(pick["weight"] / total_w * 100, 1),
    }


def _magazine_pool_eligibility(melted, snap, ctx, country):
    """便宜判定 8 篇文章的数据可用性 (复用 ctx 缓存, 不新增整文件扫描)。"""
    state_ids = _pool_state_ids(snap)
    states = snap.get("states") or []
    by_state, btype_map, objs = ctx.buildings_index(state_ids)
    railway = any(t == "building_railway" and (objs.get(b) or {}).get("staffing", 0) > 0
                  for b, t in btype_map.items())
    shelf = any(t == "building_trade_center" and (objs.get(b) or {}).get("staffing", 0) > 0
                for b, t in btype_map.items())
    turmoil = False
    for s in states:
        sid = s.get("id")
        sobj = ctx.state_object(sid) if sid is not None else None
        ps = (sobj or {}).get("pop_statistics") or {}
        tot = sum(ps.get(k) or 0 for k in (
            "population_lower_strata", "population_middle_strata",
            "population_upper_strata"))
        rad = ps.get("population_radicals") or 0
        if tot > 0 and rad / tot * 100 >= 25:
            turmoil = True
            break
    pops = ctx.player_pops(state_ids)
    letters = False
    for s in states:
        sid = s.get("id")
        if sid is None:
            continue
        sobj = ctx.state_object(sid)
        incorp = (sobj or {}).get("incorporation")
        if (incorp is not None and incorp < 1
                and any(p.get("location") == sid for p in pops.values())):
            letters = True
            break
    prices = False
    if country is not None:
        prices = bool(_market_price_map(melted, country))
    # 罪案与法网: 有 POP 在国家建筑中工作即可 (成案细节构建期再判定, 失败走兜底)
    crime = any(obj.get("workplace") in objs
                for obj in pops.values())
    # 独裁 / 寡头 / 酋邦(长老会议) 不设普选, 神圣庄严的权利不得入池
    laws = query_laws(melted, snap.get("country_id"))
    voting = not any(l in _POOL_VOTE_EXCLUDED_LAWS for l in laws)
    return {
        "railway": railway,
        "turmoil": turmoil,
        "shelf": shelf,
        "service": True,
        "voting": voting,
        "price": prices,
        "letters": letters,
        "crime": crime,
        "war_family": True,
        "court_household": True,
        "migration_change": True,
    }


def _select_magazine_pool(melted, snap, ctx, country, pool_override=None, size=3):
    """抽取本期文章: 种子=年份 (同年稳定); pool_override 可固定组合调试。"""
    elig = _magazine_pool_eligibility(melted, snap, ctx, country)
    year = snap.get("year") or 0
    candidates = [k for k in MAGAZINE_POOL_KEYS if elig.get(k)]
    if pool_override:
        picked = [k for k in pool_override if k in MAGAZINE_POOL_KEYS and elig.get(k)]
        picked = list(dict.fromkeys(picked))
    else:
        rnd = random.Random(f"pool|{year}")
        picked = (rnd.sample(candidates, min(size, len(candidates)))
                  if candidates else [])
    fallback = []
    for k in MAGAZINE_POOL_FALLBACK:
        if len(picked) + len(fallback) >= size:
            break
        if k not in picked and k not in fallback:
            fallback.append(k)
    return {
        "seed": year,
        "size": size,
        "candidates": candidates,
        "eligibility": elig,
        "picked": picked,
        "fallback": fallback,
    }


_POOL_BUILDERS = {
    "railway": _pool_railway_data,
    "turmoil": _pool_turmoil_data,
    "shelf": _pool_shelf_data,
    "service": _pool_service_data,
    "voting": _pool_voting_data,
    "price": _pool_price_data,
    "letters": _pool_letters_data,
    "crime": _pool_crime_data,
}


def build_magazine_data(melted, snap, folder, year, ctx=None,
                        pool_override=None, pool_size=3):
    """汇总杂志数据 (全部来自真实存档, 采样由 year 播种保证同年稳定)。
    返回 dict: battles / migrations / promotions / pop_migrations / conversions /
    soldiers / families / elites / civilians / war_states / cabinet / ruler。
    ctx 可选: SaveContext, 传入时复用快照提取已建好的索引/POP/州对象 (阶段1),
    不再重复整文件扫描。"""
    if ctx is None:
        ctx = SaveContext(melted)
    rnd = random.Random(year or 0)
    state_ids = [s.get("id") for s in (snap.get("states") or [])
                 if s.get("id") is not None]
    data = {}

    # 国家名/列强/外交博弈索引: 战役、战争目的共用一份
    index0, gp_ids0, dp_index0 = ctx.index()
    zh = build_country_id_names(melted, index0)

    # 战役 (仅玩家参战, ≤12 场; 玩家未参战的列强战役不进杂志)
    # 陆战与海战各自独立解析, 合并时两池各以 50% 概率被抽取
    data["battles"] = _mix_land_naval_battles(
        parse_battles(melted, player_id=snap.get("country_id"),
                      wars=snap.get("wars"), zh=zh, gp_ids=gp_ids0, ctx=ctx),
        parse_naval_battles(melted, player_id=snap.get("country_id"),
                            wars=snap.get("wars"), zh=zh, gp_ids=gp_ids0, ctx=ctx),
        snap.get("year"))
    # 报告年度: 存档在年初(1月)时报道上一历年, 否则报道本年度至今。
    # 战役州只取报告年度内的战役, 避免把前几年的战场/遗留荒废度误报为当前战乱。
    save_date = str(snap.get("date") or "")
    try:
        save_month = int(save_date.split(".")[1]) if "." in save_date else 1
    except (ValueError, IndexError):
        save_month = 1
    report_year = (year - 1) if save_month <= 1 else year

    def _battle_year(b):
        try:
            return int(str(b.get("start_date") or "").split(".")[0])
        except (ValueError, TypeError):
            return None

    recent_battles = [b for b in data["battles"] if _battle_year(b) == report_year]
    battle_state_ids = set()
    battle_place_names = set()
    for b in recent_battles:
        for o in b.get("occupation") or []:
            battle_state_ids.add(o.get("state"))
        if b.get("place"):
            battle_place_names.add(b.get("place"))
    # 战役发生地(州名)同样计入战场州, 供士兵/平民样本排序与 in_battle_state 标记
    state_name_to_id = {str(s.get("name")): s.get("id")
                        for s in (snap.get("states") or [])
                        if s.get("name") and s.get("id") is not None}
    for name in battle_place_names:
        sid = state_name_to_id.get(str(name))
        if sid is not None:
            battle_state_ids.add(sid)

    # 玩家相关战争: 去年/前年玩家参战 + 当前仍在进行的玩家战争。
    # player_at_war 供杂志第一篇文章切换「战地报道 / 和平年驻地训练」结构。
    player_wars = []
    seen_war_ids = set()
    for w in (snap.get("last_year_wars") or []) + \
             (snap.get("prev_year_wars") or []) + \
             (snap.get("wars") or []):
        if not w.get("player_involved"):
            continue
        wid = w.get("id")
        if wid is not None and wid in seen_war_ids:
            continue
        if wid is not None:
            seen_war_ids.add(wid)
        player_wars.append(w)
    data["player_wars"] = player_wars
    # 只有「进行中」的玩家战争才算战争年; 已结束的战争(含跨年合并回填的
    # 旧战事)不再触发战地报道结构, 避免模型对着陈年战事编造战斗细节。
    data["player_at_war"] = bool(data["battles"]) or any(
        not w.get("ended") for w in player_wars)

    # 战争目的 (主战+次生, 自然语言, 不含地区 ID)
    # 优先复用快照中已解析的一次性结果 (extract_full_snapshot 已解析),
    # 旧快照/直接传入的 snap 无该字段时才各自补解析
    if snap.get("war_goals") is not None:
        data["war_goals"] = snap["war_goals"]
    else:
        data["war_goals"] = parse_war_goals(
            melted, wars=snap.get("wars"), player_id=snap.get("country_id"),
            zh=zh, gp_ids=gp_ids0, dp_index=dp_index0)

    # 军团 / 营 / 舰船
    cid = snap.get("country_id")
    formations = ctx.formations()
    data["formations"] = [f for f in formations if f.get("country") == cid]
    data["units"] = parse_combat_units(melted, cid, formations=formations)
    naval_cids = set()
    for b in data["battles"]:
        if b.get("naval"):
            for side in ("attacker", "defender"):
                scid = (b.get(side) or {}).get("country_id")
                if scid is not None:
                    naval_cids.add(scid)
    data["ships"] = (parse_ships(melted, country_ids=naval_cids,
                                 formations=formations) if naval_cids else [])

    # 玩家州迁移记录 (migration_buckets)
    mig = []
    for sid in state_ids:
        sobj = ctx.state_object(sid)
        if not sobj:
            continue
        mig.extend(_migration_records_zh(melted, sobj))
    data["migrations"] = mig

    # POP 单次扫描: 指纹导出 + 跨年比对 + 分类样本
    pops = ctx.player_pops(state_ids)
    export_pop_fingerprint(pops, folder, year)

    # 新家园接受度: 按 (目标州, 文化id) 汇总同文化POP的接受状态,
    # 供移民板块以区间文字描述「在新家园的接受度」; 目标州无同文化样本时保持未知。
    acc_by_state_culture = {}
    for _pid, obj in pops.items():
        st = obj.get("location")
        cul = obj.get("culture")
        acc = (obj.get("acceptance_data") or {}).get("acceptance_status")
        if st is None or cul is None or not acc:
            continue
        acc_by_state_culture.setdefault((st, cul), []).append(acc)
    target_acc = {}
    for key, accs in acc_by_state_culture.items():
        target_acc[key] = Counter(accs).most_common(1)[0][0]
    for r in data["migrations"]:
        key = (r.get("target_state"), r.get("culture_id"))
        r["target_acceptance_status"] = target_acc.get(key)
    cur_fp = build_pop_fingerprint(pops)
    prev_fp = load_pop_fingerprint(folder, year - 1) if year else None
    promotions, pop_migrations = diff_pop_fingerprints(prev_fp, cur_fp)
    for p in promotions:
        p["state_name"] = ctx.state_zh(p.get("state"))
        p["old_state_name"] = ctx.state_zh(p.get("old_state"))
        p["culture_zh"] = (culture_id_to_name(p.get("culture"))
                           if p.get("culture") is not None else None)
        p["culture_key"] = (culture_id_to_key(p.get("culture"))
                            if p.get("culture") is not None else None)
        p["religion_zh"] = _religion_zh(p.get("religion"))
        p["type_zh"] = p.get("new_type")
        p["old_type_zh"] = p.get("old_type")
    for p in pop_migrations:
        p["state_name"] = ctx.state_zh(p.get("state"))
        p["old_state_name"] = ctx.state_zh(p.get("old_state"))
        p["culture_zh"] = (culture_id_to_name(p.get("culture"))
                           if p.get("culture") is not None else None)
        p["culture_key"] = (culture_id_to_key(p.get("culture"))
                            if p.get("culture") is not None else None)
        p["religion_zh"] = _religion_zh(p.get("religion"))
    data["promotions"] = promotions
    data["pop_migrations"] = pop_migrations

    soldiers, elites, civilians, convs = [], [], [], []
    civ_by_state = {}
    for pid, obj in pops.items():
        if not _pool_workforce_ok(obj):
            continue
        t = obj.get("type")
        if t in ("soldiers", "officers"):
            soldiers.append((pid, obj))
        if t in ("aristocrats", "capitalists", "bureaucrats"):
            elites.append((pid, obj))
        if t in ("laborers", "farmers", "peasants", "clerks", "machinists",
                 "shopkeepers", "slaves"):
            civilians.append((pid, obj))
            civ_by_state.setdefault(obj.get("location"), []).append((pid, obj))
        if obj.get("conversion_religion") or obj.get("assimilation_culture"):
            convs.append((pid, obj))
    # 战役州 POP 优先: 士兵/平民样本贴近真实战场与前线后方
    soldiers.sort(key=lambda x: x[1].get("location") in battle_state_ids, reverse=True)
    civilians.sort(key=lambda x: x[1].get("location") in battle_state_ids, reverse=True)

    # 驻军州: 军团/舰队当前驻地 (current_location); 无则回退士兵样本所在州。
    # 不采用单位 building_state——那是兵营/驻地建筑所在州, 可能是本土征兵点而非现驻地。
    garrison_state_ids = set()
    for f in data.get("formations") or []:
        loc = f.get("current_location") or {}
        if isinstance(loc, dict) and loc.get("type") == "state":
            ident = loc.get("identity")
            if ident is not None:
                garrison_state_ids.add(ident)
    if not garrison_state_ids:
        garrison_state_ids = {obj.get("location") for _pid, obj in soldiers
                              if obj.get("location") is not None}

    # 驻地军民关系基调: 逐驻军州直接读取游戏文件定义的本土文化
    # (common/history/states/*.txt 的 add_homeland), 取这些文化在该州的
    # POP 按劳动力加权的接受度众数; 州内无本土文化样本时回退该州全体平民
    # 加权众数; 跨州再取「最差」档——本土大州人口不会淹没殖民地驻地的
    # 敌意, 也不美化任何存在暴力敌视的驻军州 (士兵自身不参与)。
    # 供 magazine.py 的驻地板块提示词使用。
    def _tone_flat(obj):
        acc = obj.get("acceptance_data") or {}
        return {"acceptance_status": acc.get("acceptance_status"),
                "workforce": obj.get("workforce")}

    hm = build_homeland_map()
    state_statuses = []
    for sid in garrison_state_ids:
        rk = ctx.state_region_key(sid)
        home_cults = (hm.get(rk) or set()) if rk else set()
        pool = []
        if home_cults:
            pool = [_tone_flat(obj) for _pid, obj in pops.items()
                    if (obj.get("location") == sid
                        and _pool_workforce_ok(obj)
                        and culture_id_to_key(obj.get("culture")) in home_cults)]
        if not pool:
            pool = [_tone_flat(obj) for _pid, obj in civilians
                    if obj.get("location") == sid and _pool_workforce_ok(obj)]
        st = dominant_acceptance_status(pool, weight_key="workforce")
        if st:
            state_statuses.append(st)
    if state_statuses:
        # 档位顺序与罪案接受度一致: 完全接纳 < 公开歧视 < 二等公民 < 文化抹除 < 暴力敌视
        data["garrison_tone_status"] = max(
            state_statuses,
            key=lambda s: _CRIME_ACCEPTANCE_RANK.get(s, 0))
    else:
        data["garrison_tone_status"] = dominant_acceptance_status(
            [_tone_flat(obj) for _pid, obj in civilians
             if _pool_workforce_ok(obj)],
            weight_key="workforce")

    def _pick(lst, n):
        if not lst:
            return []
        return [lst[i] for i in sorted(rnd.sample(range(len(lst)), min(n, len(lst))))]

    def _info(pid, obj, extra=None):
        acc = obj.get("acceptance_data") or {}
        d = {
            "pop_id": pid,
            "state": obj.get("location"),
            "state_name": ctx.state_zh(obj.get("location")),
            "type": obj.get("type"),
            "culture": (culture_id_to_name(obj.get("culture"))
                        if obj.get("culture") is not None else None),
            "culture_key": (culture_id_to_key(obj.get("culture"))
                            if obj.get("culture") is not None else None),
            "religion": _religion_zh(obj.get("religion")),
            "workforce": obj.get("workforce"),
            "sol": obj.get("previous_quality_of_life"),
            "wealth": obj.get("wealth"),
            "in_battle_state": obj.get("location") in battle_state_ids,
            "acceptance_status": acc.get("acceptance_status"),
            "acceptance_value": acc.get("acceptance_value"),
        }
        if extra:
            d.update(extra)
        return d

    soldier_samples = _pick(soldiers, 6)
    data["soldiers"] = [_info(pid, obj) for pid, obj in soldier_samples]
    data["elites"] = [_info(pid, obj) for pid, obj in _pick(elites, 6)]
    # 当地平民样本优先驻军州, 保证「驻军所在州居民」名副其实
    civ_pool = [x for x in civilians if x[1].get("location") in garrison_state_ids]
    data["civilians"] = [_info(pid, obj) for pid, obj
                         in _pick(civ_pool or civilians, 6)]

    fam = []
    for pid, obj in soldier_samples:
        cand = civ_by_state.get(obj.get("location")) or []
        if cand:
            fam.append(_info(*_pick(cand, 1)[0], extra={
                "soldier_state": obj.get("location"),
                "soldier_state_name": ctx.state_zh(obj.get("location")),
            }))
    data["families"] = fam

    conv_out = []
    for pid, obj in _pick(convs, 8):
        extra = {}
        cr = obj.get("conversion_religion")
        if cr:
            extra["converting_to_religion"] = _religion_zh(cr)
        ac = obj.get("assimilation_culture")
        if ac is not None:
            extra["assimilating_to_culture"] = culture_id_to_name(ac)
        conv_out.append(_info(pid, obj, extra))
    data["conversions"] = conv_out

    # 迁移/升职样本: 保持记录本身完整, 仅截取前若干条供提示词
    data["migrations"] = _pick(data["migrations"], 6)
    data["promotions"] = _pick(promotions, 6)
    data["pop_migrations"] = _pick(pop_migrations, 6)

    # 战乱州民生: 仅报告年度内有战役的玩家州 (战役发生地或占领州)。
    # 荒废度为历史战争遗留, 不作为入选条件, 避免停战多年后仍被误报。
    war_states = []
    for s in (snap.get("states") or []):
        if s.get("id") in battle_state_ids or s.get("name") in battle_place_names:
            war_states.append(s)
    data["war_states"] = war_states

    # 大臣 (执政利益集团) 与统治者
    igs = snap.get("interest_groups") or []
    data["cabinet"] = [g for g in igs if g.get("in_government")]
    ri = snap.get("ruler_info") or {}
    data["ruler"] = {
        "name": ri.get("name"),
        "title": ri.get("title"),
        "ideology": ri.get("ideology"),
        "status": ri.get("status"),
        "culture": ri.get("culture"),
        "religion": ri.get("religion"),
        "home_region": ri.get("home_region"),
        "activity": snap.get("ruler_activity"),
    }

    # 文章池: 抽取本期 3 篇, 只对选中的文章懒构建事实
    try:
        country_obj = _find_country_by_id(melted, cid)
    except Exception:
        country_obj = None
    pool = _select_magazine_pool(melted, snap, ctx, country_obj,
                                 pool_override=pool_override, size=pool_size)
    for key in list(pool["picked"]):
        fn = _POOL_BUILDERS.get(key)
        if not fn:
            continue
        try:
            facts = fn(melted, snap, ctx, random.Random(f"{year or 0}|{key}"),
                       country_obj, cid, data)
        except Exception as e:
            print(f"[magazine-pool] {key} 数据构建失败: {e}")
            facts = None
        if facts:
            data[key] = facts
        else:
            # 构建期才发现不可用: 从本期剔除, 用兜底文章补位
            pool["picked"].remove(key)
            for k in MAGAZINE_POOL_FALLBACK:
                if len(pool["picked"]) + len(pool["fallback"]) >= pool["size"]:
                    break
                if k not in pool["picked"] and k not in pool["fallback"]:
                    pool["fallback"].append(k)
    data["pool"] = pool
    return data


def _merge_prev_year_wars(snap, journal_dir, folder):
    """存档层落盘: 生成本年快照时, 把上一年存档中仍在进行的战争并入
    last_year_wars / prev_year_wars, 补回 V3 war_manager 只保留进行中战争
    而丢失的「去年战争」。仅并入报告字段, 不改 wars, 避免影响基于进行中
    战争的列强交战状态等判定。
    上一年存档中仍在进行的战争若已不在本年 war_manager, 说明在本年初已结束,
    并入时标记 ended=True (和约日期未知), 避免战事专电误报「仍在进行」。"""
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
    # 本年仍在进行的战争 (war_manager 只保留进行中战争)
    ongoing_ids = {w.get("id") for w in (snap.get("wars") or [])
                   if w.get("id") is not None and not w.get("ended")}
    def _as_merged(w):
        w2 = dict(w)
        wid = w2.get("id")
        if (wid is not None and wid not in ongoing_ids
                and not w2.get("ended")):
            w2["ended"] = True
            w2["peace_date"] = None
        return w2
    lyw = list(snap.get("last_year_wars") or [])
    lyw_seen = {w.get("id") for w in lyw if w.get("id") is not None}
    for w in prev_wars:
        wid = w.get("id")
        if wid is not None and wid in lyw_seen:
            continue
        ps = [p for p in (w.get("participants") or []) if p.get("primary")]
        if not ps:
            continue
        w2 = _as_merged(w)
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
        pyw.append(_as_merged(w))
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


def _enactment_phase_suffix(laws):
    """按游戏 common/customizable_localization/03_misc.txt 的触发链, 由现行
    治理法律决定立法阶段名的后缀 (tec/courep/autocracy/demrep/conmon/mon/generic)。
    has_law_or_variant 以基础 law key 近似判断 (相关法律变体极少)。"""
    laws = set(laws or [])
    if "law_technocracy" in laws:
        return "tec"
    if "law_council_republic" in laws:
        return "courep"
    if "law_autocracy" in laws:
        return "autocracy"
    if ({"law_parliamentary_republic", "law_presidential_republic"} & laws
            and {"law_landed_voting", "law_census_voting", "law_wealth_voting",
                 "law_universal_suffrage"} & laws):
        return "demrep"
    if ({"law_monarchy", "law_social_monarchy"} & laws
            and {"law_census_voting", "law_wealth_voting",
                 "law_universal_suffrage"} & laws):
        return "conmon"
    if ({"law_monarchy", "law_social_monarchy"} & laws
            and {"law_landed_voting", "law_oligarchy",
                 "law_single_party_state"} & laws):
        return "mon"
    return "generic"


def _enactment_phase_names_zh(suffix):
    """阶段名后缀 → 三个立法阶段的中文名列表; 缺失时回退 generic。"""
    loc = _load_loc_all()
    names = []
    for i in range(3):
        nm = (loc.get(f"enactment_phase_{i}_{suffix}")
              or loc.get(f"enactment_phase_{i}_generic"))
        names.append(nm or f"阶段{i}")
    return names


def query_laws_in_progress(data, country_id):
    """从 laws.database 提取该国**正在制定**的法律。

    进行中: 带 enactment_start_date 且未生效 (无 active) 的条目。
    返回 [{law, phase, progress, start_date, last_checkpoint_result,
    last_checkpoint_date}], 按 phase/progress 语义: phase 0~2 对应政体专属的
    三个立法阶段 (存档在 phase=0 时不写该字段, 缺省按 0 处理),
    progress 为当前阶段立法周期 (检查点间隔) 内的 0~1 进度。"""
    out = []
    if not country_id:
        return out
    idx = data.find(b'"laws"')
    if idx < 0:
        return out
    laws_end = _object_end(data, data.find(b'{', idx))
    db = data.find(b'"database"', idx)
    if db < 0:
        return out
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
        if (isinstance(obj, dict) and obj.get("law")
                and obj.get("country") == country_id
                and obj.get("enactment_start_date") and not obj.get("active")):
            out.append({
                "law": obj["law"],
                "phase": obj.get("phase") or 0,
                "progress": obj.get("progress"),
                "start_date": obj.get("enactment_start_date"),
                "last_checkpoint_result": obj.get("enactment_last_checkpoint_result"),
                "last_checkpoint_date": obj.get("enactment_last_checkpoint_or_stop_date"),
            })
        j = end
    return out


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


def _pick_building(melted, state_id, rnd=None, buildings_index=None, building_type_map=None,
                   building_objs=None):
    """随机挑一个该州建筑, 返回 (本地化中文名, 建筑id); 挑不到返回 (None, None)。"""
    if state_id is None:
        return None, None
    rnd = rnd or random
    if buildings_index is None:
        bids = list(_buildings_in_state(melted, state_id))
    else:
        bids = buildings_index.get(state_id) or []
    loc = _load_loc_all()
    pairs = []
    for b in bids:
        if building_objs is not None:
            obj = building_objs.get(b)
            t = (obj or {}).get("building") if isinstance(obj, dict) else None
        else:
            if building_type_map is None:
                building_type_map = _building_type_map(melted, [state_id])
            t = building_type_map.get(b)
        if t and (loc.get(t) or "") not in ("", t) \
                and not t.startswith("building_company_") \
                and not t.startswith("building_port"):
            pairs.append((b, t))
    if not pairs:
        return None, None
    bid, t = rnd.choice(pairs)
    return loc.get(t), bid


def _religion_zh(key):
    """宗教 key → 中文名 (复用 journal.py 的映射表)。"""
    if not key:
        return ""
    try:
        from journal import RELIGION_NAMES
        return RELIGION_NAMES.get(key, key)
    except Exception:
        return key


def _pick_envoy_country(snap, rnd):
    """选「接见外国使节」的对象国:
    优先有外交关系(非附庸、非宿敌、非玩家)的国家, 在候选中随机取一个;
    没有则回退为随机非玩家列强; 再不行从条约里取非玩家对方国。
    """
    player = snap.get("player") or ""
    subs = {s.get("name") for s in (snap.get("subjects") or []) if s.get("name")}

    def partner_of(first, second):
        if not first or not second:
            return None
        if first == player:
            return second
        if second == player:
            return first
        return None

    rels = []
    for t in snap.get("treaties") or []:
        p = partner_of(t.get("first_name"), t.get("second_name"))
        if p and p != player and p not in subs and p not in rels:
            rels.append(p)
    for p in snap.get("pacts") or []:
        if p.get("action") in SUBJECT_ACTIONS or p.get("action") == "rivalry":
            continue
        pn = partner_of(p.get("first_name"), p.get("second_name"))
        if pn and pn != player and pn not in subs and pn not in rels:
            rels.append(pn)
    if rels:
        return rnd.choice(rels)
    others = [p.get("name") for p in (snap.get("powers") or [])
              if not p.get("is_player") and p.get("name")]
    others = [o for o in dict.fromkeys(others) if o != player]
    if others:
        return rnd.choice(others)
    for t in snap.get("treaties") or []:
        if t.get("first_name") and t.get("first_name") != player:
            return t["first_name"]
        if t.get("second_name") and t.get("second_name") != player:
            return t["second_name"]
    return ""


def _pick_visit_pop(snap, capital_id, pops_index=None):
    """为「统治者走访居民家中」挑选首都州内的实际 POP。

    优先 top_culture + 国教、职业为 farmers/peasants，且同一工作建筑还有合格
    对照 POP 的人群；没有时退回同文化同宗教、就业且非奴隶的人群。"""
    states = snap.get("states") or []
    cap_state = next((s for s in states if s.get("id") == capital_id), None)
    if not cap_state:
        return None
    top_culture = cap_state.get("top_culture")
    state_religion = snap.get("religion")
    pops = pops_index.get(capital_id) if pops_index else []
    if not pops:
        return None

    def _culture_name(obj):
        cid = obj.get("culture")
        return culture_id_to_name(cid) if cid is not None else None

    def _size(obj):
        return (obj.get("workforce") or 0) + (obj.get("dependents") or 0)

    def _has_peer_in_building(obj):
        bid = obj.get("workplace")
        if bid is None:
            return False
        for other in pops:
            if other is obj or other.get("workplace") != bid:
                continue
            if (not _pool_workforce_ok(other)
                    or not isinstance(other.get("previous_quality_of_life"), (int, float))):
                continue
            return True
        return False

    def _is_poorest_in_building(obj):
        bid = obj.get("workplace")
        if bid is None:
            return False
        sols = [
            o.get("previous_quality_of_life")
            for o in pops
            if o.get("workplace") == bid
            and _pool_workforce_ok(o)
            and isinstance(o.get("previous_quality_of_life"), (int, float))
        ]
        if not sols:
            return False
        return obj.get("previous_quality_of_life") == min(sols)

    valid = [
        o for o in pops
        if o.get("workplace") is not None
        and o.get("type") != "slaves"
        and _pool_workforce_ok(o)
        and _culture_name(o) == top_culture
        and o.get("religion") == state_religion
    ]
    if not valid:
        return None
    type_rank = {"farmers": 0, "peasants": 1}
    with_peer = [o for o in valid if _has_peer_in_building(o)]
    building_min = [o for o in with_peer if _is_poorest_in_building(o)]
    candidates = building_min or with_peer or valid
    candidates.sort(key=lambda o: (
        o.get("previous_quality_of_life")
        if isinstance(o.get("previous_quality_of_life"), (int, float)) else 1e18,
        type_rank.get(o.get("type"), 2),
        -_size(o),
    ))
    return candidates[0]


def _assemble_ruler_activity(melted, snap, country_id, buildings_index=None,
                             building_type_map=None, visit_pop_obj=None,
                             building_objs=None):
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
            bld, bid = _pick_building(melted, st.get("id"), rnd=rnd,
                                      buildings_index=buildings_index,
                                      building_type_map=building_type_map,
                                      building_objs=building_objs)
            if bld:
                where = st.get("name") or capital or "某地"
                own = ""
                if bid is not None:
                    bobj = (building_objs or {}).get(bid)
                    own_dist, own_total = _building_ownership(
                        melted, bid, country_id, building_obj=bobj)
                    own_sentence = _ownership_sentence(own_dist, own_total)
                    if own_sentence:
                        own = f"（{own_sentence}）"
                return f"{ruler}视察了位于{where}的{bld}{own}", kind, None
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
            if not visit_pop_obj:
                continue
            sid = visit_pop_obj.get("location")
            st = next((s for s in states if s.get("id") == sid), {})
            stname = st.get("name") or capital or "某地"
            culture = culture_id_to_name(visit_pop_obj.get("culture")) or ""
            rel_zh = _religion_zh(visit_pop_obj.get("religion"))
            try:
                from journal import POP_TYPE_NAMES
            except Exception:
                POP_TYPE_NAMES = {}
            pop_type = visit_pop_obj.get("type")
            profession = POP_TYPE_NAMES.get(pop_type, pop_type or "")
            if stname and culture and profession and rel_zh:
                return (f"{ruler}走访了{stname}的{culture}人{profession}家庭，"
                        f"在信奉{rel_zh}的居民家中体察民情", kind, sid)
            if stname and culture:
                return f"{ruler}走访了{stname}的{culture}人家，体察民情", kind, sid
        elif kind == "receive_envoys":
            foreign = _pick_envoy_country(snap, rnd)
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
    # 政体原始键 (如 gov_constitutional_empire), 供采访地点按政体标注"省/州"
    data["govt_key"] = snap.get("govt")
    # 首都: 由首都 state 的 hub 名(城市)解析, 失败回退州域名; 不再让模型凭空猜测
    data["capital"] = snap.get("capital") or ""
    data["gdp"] = snap.get("gdp", "未知")
    data["pop"] = snap.get("total_population", "未知")
    data["sol"] = snap.get("avgsoltrend", "未知")
    data["literacy"] = snap.get("literacy", "未知")
    data["prestige"] = snap.get("prestige", "未知")
    data["infamy"] = snap.get("infamy")
    data["religion"] = snap.get("religion", "未知")
    # 国教中文名: 供政界动态判断领袖宗教是否非国教
    data["state_religion"] = _religion_zh(snap.get("religion")) or None
    # 首都州(区域)中文名/key: 供判断领袖家乡是否非首都州
    data["capital_region"] = snap.get("capital_region")
    data["capital_region_key"] = snap.get("capital_region_key")
    # 统治者: 姓名/头衔/意识形态/在位状态来自 character_manager 解析(见 ruler_info);
    # 首都名已由存档 state hub 解析(见 data["capital"])
    ri = snap.get("ruler_info") or {}
    data["ruler"] = ri.get("name") or ""
    data["ruler_title"] = ri.get("title") or ""
    data["ruler_ideology"] = ri.get("ideology")
    data["ruler_status"] = ri.get("status")
    data["ruler_activity"] = snap.get("ruler_activity")
    data["ruler_culture"] = ri.get("culture")
    data["ruler_religion"] = ri.get("religion")
    data["ruler_home_region"] = ri.get("home_region")
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
    data["laws_in_progress"] = snap.get("laws_in_progress") or []
    data["free_speech_law"] = snap.get("free_speech_law")
    data["dop_law"] = snap.get("dop_law")
    data["govt_law"] = snap.get("govt_law")
    data["women_law"] = snap.get("women_law")
    data["techs"] = snap.get("techs") or []
    data["tech_keys"] = snap.get("tech_keys") or []
    data["powers"] = snap.get("powers") or []
    data["treaties"] = snap.get("treaties") or []
    data["subjects"] = snap.get("subjects") or []
    data["rivals"] = snap.get("rivals") or []
    data["pacts"] = snap.get("pacts") or []
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
    # 战争目的: 随快照解析一次, 供报纸战事专电与杂志共用
    data["war_goals"] = snap.get("war_goals") or []
    return data

def extract_full_snapshot(melted, cid=None, ctx=None):
    """从熔化数据提取完整快照 (精确数值 + 本年度法律变化 + pop占比 + 战争 + 政体中文)。
    cid 为 None 时取玩家国; 指定 cid 时可提取任意国家 (供 test 等批量生成复用)。
    ctx 可选: SaveContext, 传入时复用已建索引/已解析 POP 与州对象 (阶段1),
    否则内部新建一个, 保证无上下文调用 (test 脚本等) 行为不变。"""
    if ctx is None:
        ctx = SaveContext(melted)
    if cid is None:
        country, meta, tag, cid = find_player_country(melted)
    else:
        country = _find_country_by_id(melted, cid)
        meta = _parse_meta(melted)
        tag = (country or {}).get("definition")
    snap = snapshot_from_country(country, meta)
    if not country:
        return snap
    snap["tag"] = tag
    snap["country_id"] = cid
    player_tag = tag or (country or {}).get("definition")
    snap["govt_zh"] = gov_to_name(snap.get("govt"))
    snap["capital"] = ctx.capital_name(country)
    # 首都州(区域)键与中文名: 供领袖/统治者「家乡非首都州」判定
    cap_rk = ctx.state_region_key((country or {}).get("capital"))
    snap["capital_region_key"] = cap_rk
    snap["capital_region"] = _load_loc_all().get(cap_rk) if cap_rk else None
    # 法律: 只保留本年度内发生变化的法律 (新施行 + 废除), 不再输出全部现行法
    enacted, repealed = query_laws_changed(melted, cid, snap.get("date"))
    snap["laws_enacted"] = enacted
    snap["laws_repealed"] = repealed
    snap["laws"] = list(dict.fromkeys(enacted + repealed))
    active_laws = query_laws(melted, cid)
    snap["free_speech_law"] = next(
        (l for l in active_laws if l in FREE_SPEECH_LAWS), None)
    snap["dop_law"] = next(
        (l for l in active_laws if l in DOP_LAWS), None)
    snap["govt_law"] = next(
        (l for l in active_laws if l in GOVT_LAWS), None)
    snap["women_law"] = next(
        (l for l in WOMEN_LAW_ORDER if l in active_laws), None)
    # 立法进行中: 法律 + 当前阶段(政体专属本地化) + 提交日期
    laws_ip = query_laws_in_progress(melted, cid)
    phase_names = _enactment_phase_names_zh(_enactment_phase_suffix(active_laws))
    law_groups = _load_law_groups()
    active_by_group = {}
    for l in active_laws:
        g = law_groups.get(l)
        if g:
            active_by_group.setdefault(g, []).append(l)
    for item in laws_ip:
        ph = item.get("phase")
        if isinstance(ph, int) and 0 <= ph < len(phase_names):
            item["phase_zh"] = phase_names[ph]
        else:
            item["phase_zh"] = f"阶段{ph}"
        # 被替代的现行法: 同一法律组中当前生效的那条
        g = law_groups.get(item["law"])
        cands = active_by_group.get(g) or []
        if len(cands) == 1:
            item["replace_law"] = cands[0]
    snap["laws_in_progress"] = laws_ip
    snap["player_country_id"] = cid
    index, gp_ids, dp_index = ctx.index()
    names = load_current_country_names(melted, index)
    if cid is not None and tag:
        # 非玩家国: 用国家名覆盖 meta.name(玩家名), 供杂志/报纸以该国名义写作
        snap["player"] = (build_country_id_names(melted, index).get(cid)
                          or names.get(tag, tag))
    state_ids = (country or {}).get("states") or []
    pops = ctx.aggregate_pops(state_ids)
    prim_cultures = _get_primary_cultures(melted, state_ids)
    snap["states"] = ctx.player_states(state_ids)
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
    snap["wars"] = parse_wars(melted, names, cid, index=index, gp_ids=gp_ids,
                              dp_index=dp_index, save_date=snap.get("date"))
    # 前一年玩家国家发生的战争及结果
    snap["prev_year_wars"] = _prev_year_player_wars(snap.get("wars") or [], snap.get("year"))
    # 去年发生的战争(玩家/列强参战, 仅主要参加者), 供战事专电
    snap["last_year_wars"] = _last_year_wars(snap.get("wars") or [], snap.get("year"))
    # 战争目的: 与报纸/杂志共用的快照字段, 只在提取快照时解析一次,
    # 杂志不再各自重扫 war_goal_manager (见 build_magazine_data)
    snap["war_goals"] = parse_war_goals(
        melted, wars=snap.get("wars"), player_id=cid,
        zh=build_country_id_names(melted, index), gp_ids=gp_ids,
        dp_index=dp_index)
    # 单文件扫描一次建索引: 角色 / 建筑 / POP, 供首领、统治者与家庭采访复用
    chars = _player_characters(melted, cid)
    buildings_index, building_map, building_objs = ctx.buildings_index(state_ids)
    pops_index = ctx.pops_by_state(state_ids)
    ig_slots = _country_ig_slots(melted, cid)
    price_map = _market_price_map(melted, country)
    snap["interest_groups"] = _extract_interest_groups(melted, cid, chars=chars)
    snap["powers"] = _extract_powers(melted, names, index=index, gp_ids=gp_ids,
                                     player_id=cid, player_tag=player_tag)
    # 统治者: 用与利益集团首领相同的方式解析姓名/意识形态, 再据政体键读游戏头衔;
    # 程序侧拼装统治者活动；走访类先从首都州选真实 POP，供家庭采访复用同一 POP。
    snap["ruler_info"] = _ruler_info(melted, cid, (country or {}).get("ruler"),
                                     snap.get("govt"), chars=chars)
    capital_id = (country or {}).get("capital")
    visit_pop_obj = _pick_visit_pop(snap, capital_id, pops_index=pops_index)
    ruler_act, act_kind, visit_state = _assemble_ruler_activity(
        melted, snap, cid, buildings_index=buildings_index,
        building_type_map=building_map, visit_pop_obj=visit_pop_obj,
        building_objs=building_objs)
    snap["ruler_activity"] = ruler_act
    # 家庭采访样本: 走访活动必须与统治者访问的家庭完全一致;
    # 其它活动按年份确定性随机，避免同年重生成结果漂移。
    forced_family = visit_pop_obj if (act_kind == "visit_pop" and visit_pop_obj is not None) else None
    interview_rnd = random.Random(snap.get("year") or 0)
    interview = _pick_interview_set(melted, state_ids, ig_slots, building_map, price_map,
                                    cid=cid, player_tag=player_tag,
                                    preferred_state=(forced_family.get("location")
                                                     if forced_family is not None else None),
                                    ruler_visited=forced_family is not None,
                                    pops_index=pops_index, buildings_index=buildings_index,
                                    forced_family=forced_family, rnd=interview_rnd,
                                    building_objs=building_objs)
    snap["family_interview"] = interview.get("family_interview")
    snap["top_sol_peer"] = interview.get("top_sol_peer")
    snap["unemployed_interview"] = interview.get("unemployed_interview")
    # 已研发科技 (单份存档无完成日期, 无法识别去年新研发; 上层用逐年 raw JSON 对比
    # 得出本年新增, 无新增时随机抽取; 本地化后供广告板块使用; 原始 key 供新文风系统计分)
    loc = _load_loc_all()
    tech_keys = _country_technologies(melted, cid)
    snap["tech_keys"] = tech_keys
    snap["techs"] = [loc.get(t, t) for t in tech_keys]
    # 激进派/效忠派占全国人口比例
    tot = snap.get("total_population") or 0
    ps = (country.get("pop_statistics") or {})
    if tot:
        snap["radicals_pct"] = round((ps.get("population_radicals") or 0) / tot * 100, 2)
        snap["loyalists_pct"] = round((ps.get("population_loyalists") or 0) / tot * 100, 2)
    snap["treaties"] = _extract_treaties(melted, names, index=index, gp_ids=gp_ids, player_id=cid)
    # pacts.database 只扫描一次, 附庸/宿敌/其他外交行动共用同一份结果
    pact_list = _extract_pacts(melted, cid, names, index=index)
    snap["pacts"] = pact_list
    snap["subjects"] = _extract_subjects(melted, cid, names, index=index, pacts=pact_list)
    snap["rivals"] = _extract_rivals(melted, cid, names, index=index, pacts=pact_list)
    snap["political_movements"] = _extract_political_movements(
        melted, cid, state_ids, (country.get("pop_statistics") or {}),
        player_tag=player_tag, pops=ctx.player_pops(state_ids))
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

# 条款类型 → 中文 (优先加载本地化 concept_*, 缺的硬编码兜底; 覆盖原版全部条款)
ARTICLE_ZH_FALLBACK = {
    "alliance": "同盟",
    "defensive_pact": "共同防御条约",
    "military_assistance": "军事援助",
    "foreign_investment_rights": "外国投资权",
    "trade_privilege": "贸易特权",
    "goods_transfer": "货物移交",
    "guarantee_independence": "保证独立",
    "military_access": "军事通行权",
    "transit_rights": "过境权",
    "treaty_port": "条约港",
    "money_transfer": "金钱移交",
    "law_commitment": "法律承诺",
    "support_independence": "支持独立",
    "host_power_bloc_embassy": "东道国集团使馆",
    "no_tolls": "免通行费",
    "free_text": "备注",
    "take_on_debt": "承担债务",
    "state_transfer": "领土移交",
    "join_power_bloc": "加入势力集团",
    "offer_embassy": "设立大使馆",
    "non_colonization_agreement": "不殖民协议",
    "prohibit_trade_with_global_market": "禁止与世界市场贸易",
    "acquire_monopoly_for_company": "公司垄断",
    "no_tariffs": "禁止关税",
    "no_subventions": "禁止补助金",
    "amend_succession": "修改继承",
    "recognize_independence": "承认独立",
    "transfer_subject": "转让附庸",
    "ship_transfer": "舰船移交",
    "toll_exemption": "免除通行费",
    "strait_access": "海峡通行权",
    "no_strait_closure": "不封闭海峡",
    "non_piracy_agreement": "禁止海盗协议",
    "abandon_piracy": "放弃海盗行为",
    "enforce_embargo": "强制禁运",
    "daoyu_treaty_articles": "强制条约",
}

# 条款类型 → 官方自然语言模板本地化键 (diplomacy_l_simp_chinese.yml 的 *_article_short_desc)
ARTICLE_TEMPLATE_KEYS = {
    "alliance": "alliance_article_short_desc",
    "defensive_pact": "defensive_pact_article_short_desc",
    "military_assistance": "military_assistance_article_short_desc",
    "foreign_investment_rights": "foreign_investment_rights_article_short_desc",
    "trade_privilege": "trade_privilege_article_short_desc",
    "goods_transfer": "goods_transfer_article_short_desc",
    "guarantee_independence": "guarantee_independence_article_short_desc",
    "military_access": "military_access_article_short_desc",
    "transit_rights": "transit_rights_article_short_desc",
    "treaty_port": "treaty_port_article_short_desc",
    "money_transfer": "money_transfer_article_short_desc",
    "law_commitment": "law_commitment_article_short_desc",
    "support_independence": "support_independence_article_short_desc",
    "host_power_bloc_embassy": "host_power_bloc_embassy_article_short_desc",
    "no_tolls": "no_tolls_article_short_desc",
    "take_on_debt": "take_on_debt_article_short_desc",
    "state_transfer": "state_transfer_article_short_desc",
    "join_power_bloc": "join_power_bloc_article_short_desc",
    "offer_embassy": "offer_embassy_article_short_desc",
    "non_colonization_agreement": "non_colonization_agreement_article_short_desc",
    "prohibit_trade_with_global_market": "prohibit_trade_with_global_market_article_short_desc",
    "acquire_monopoly_for_company": "acquire_monopoly_for_company_article_short_desc",
    "no_tariffs": "no_tariffs_article_short_desc",
    "no_subventions": "no_subventions_article_short_desc",
    "amend_succession": "amend_succession_article_short_desc",
    "recognize_independence": "recognize_independence_article_short_desc",
    "transfer_subject": "transfer_subject_article_short_desc",
    "ship_transfer": "ship_transfer_article_short_desc",
    "toll_exemption": "toll_exemption_article_short_desc",
    "strait_access": "strait_access_article_short_desc",
    "no_strait_closure": "no_strait_closure_article_short_desc",
    "non_piracy_agreement": "non_piracy_agreement_article_short_desc",
    "abandon_piracy": "abandon_piracy_article_short_desc",
    "enforce_embargo": "enforce_embargo_article_short_desc",
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
    # 原版 53 商品 (官方简体中文译名, 与游戏内一致)
    "ammunition": "弹药", "small_arms": "轻武器", "artillery": "火炮",
    "tanks": "坦克", "aeroplanes": "飞机", "manowars": "风帆战舰",
    "ironclads": "铁甲舰",
    "grain": "谷物", "fish": "鱼类", "fabric": "织物", "wood": "木材",
    "groceries": "加工食品", "clothes": "衣物", "furniture": "家具",
    "paper": "纸张", "services": "服务", "transportation": "运力",
    "electricity": "电力", "merchant_marine": "商船", "clippers": "帆船",
    "steamers": "蒸汽船", "silk": "丝绸", "dye": "染料", "sulfur": "硫磺",
    "coal": "煤炭", "iron": "铁", "lead": "铅", "hardwood": "硬木",
    "rubber": "橡胶", "oil": "油", "engines": "发动机", "steel": "钢",
    "glass": "玻璃", "fertilizer": "肥料", "tools": "工具",
    "explosives": "炸药", "porcelain": "瓷器", "meat": "肉类",
    "fruit": "水果", "liquor": "烈酒", "wine": "葡萄酒", "tea": "茶叶",
    "coffee": "咖啡", "sugar": "糖", "tobacco": "烟草", "opium": "鸦片",
    "automobiles": "汽车", "telephones": "电话机", "radios": "无线电",
    "luxury_clothes": "高档衣物", "luxury_furniture": "高档家具",
    "gold": "黄金", "fine_art": "艺术品",
    # mod/旧版商品 (journal mod 清单, 保留以免译名空缺)
    "livestock": "牲畜", "food": "食物", "cotton": "棉花", "wool": "羊毛",
    "cloth": "布料", "ships": "船舶",
}

_CONCEPT_ZH = None

# $concept_xxx$ 占位符兜底: 本地化缺失时保证模板仍可读
_CONCEPT_FALLBACK = {
    "concept_money": "金钱", "concept_goods": "商品", "concept_good": "商品",
    "concept_state": "州", "concept_tariffs": "关税", "concept_subventions": "补助金",
    "concept_trade_privilege": "贸易特权", "concept_trade_privileges": "贸易特权",
    "concept_military_access": "军事通行权", "concept_military_assistance": "军事援助",
    "military_assistance": "军事援助",
    "concept_world_market": "国际市场", "concept_company_monopoly": "公司垄断",
    "concept_strait": "海峡", "concept_straits": "海峡", "concept_tolls": "通行费",
    "concept_loans": "贷款", "concept_power_bloc": "势力集团", "concept_armies": "陆军",
    "concept_law": "法律", "concept_colonize": "殖民", "concept_strategic_region": "战略区域",
    "concept_ship": "舰船", "concept_treaty_port": "条约港", "concept_subject": "附庸国",
    "concept_article": "条款", "concept_treaty": "条约", "concept_alliance": "同盟",
    "concept_defensive_pact": "共同防御条约", "host_power_bloc_embassy": "东道国集团使馆",
}

def _goods_zh(key):
    """商品 key → 中文名 (硬编码表优先, 回退游戏本地化, 再回退原 key 保证非空)。"""
    zh = ARTICLE_GOODS.get(key)
    if zh:
        return zh
    try:
        return build_goods_map()["zh"].get(key, key)
    except Exception:
        return key

def _concept_zh():
    """加载本地化 concept_* 中文名 (游戏+已启用 mod)。"""
    global _CONCEPT_ZH
    if _CONCEPT_ZH is not None:
        return _CONCEPT_ZH
    zh = {}
    for loc_dir in _loc_dirs():
        try:
            for fn in os.listdir(loc_dir):
                if not fn.endswith(".yml"):
                    continue
                with open(os.path.join(loc_dir, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    for line in fp:
                        m = re.match(
                            r"\s*(concept_[a-z0-9_-]+):\s*\"([^\"]+)\"\s*$", line)
                        if m and "$" not in m.group(2) and "[" not in m.group(2):
                            zh[m.group(1)] = m.group(2).strip()
        except Exception:
            pass
    _CONCEPT_ZH = zh
    return zh


def _article_concept_zh(key):
    """$concept_xxx$ → 中文名; 本地化缺失时用兜底表, 再回退原 key。"""
    zh = _concept_zh().get(key)
    if zh:
        return zh
    return _CONCEPT_FALLBACK.get(key, key)


_ARTICLE_TEMPLATE_CACHE = None


def _article_templates():
    """加载本地化 *_article_short_desc → 自然语言模板 (游戏原版+mod, 后者覆盖)。"""
    global _ARTICLE_TEMPLATE_CACHE
    if _ARTICLE_TEMPLATE_CACHE is not None:
        return _ARTICLE_TEMPLATE_CACHE
    loc = _load_loc_all()
    out = {}
    for key in ARTICLE_TEMPLATE_KEYS.values():
        v = loc.get(key)
        if v:
            out[key] = v
    _ARTICLE_TEMPLATE_CACHE = out
    return out


_ARTICLE_LOC_RE = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)\$")


def _clean_loc_markup(s):
    """去掉本地化富文本标记 (#bold_black ... #! / @icon) 并归一空白。"""
    s = re.sub(r"#bold_black\s*", "", s)
    s = re.sub(r"#[A-Za-z_][A-Za-z_0-9]*", "", s)
    s = re.sub(r"#!", "", s)
    s = re.sub(r"@[A-Za-z_][A-Za-z_0-9]*", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" \t-–—")


def _render_article_template(tmpl, fname, sname):
    """模板占位符 → 国名, $concept_xxx$ → 中文, 去标记。"""
    s = tmpl
    for ph, v in (
            ("[SOURCE_COUNTRY.GetNameNoFormatting]", fname),
            ("[TARGET_COUNTRY.GetNameNoFormatting]", sname),
            ("[SOURCE_COUNTRY.GetAdjectiveNoFormatting]", fname),
            ("[TARGET_COUNTRY.GetAdjectiveNoFormatting]", sname),
            ("[FIRST_COUNTRY.GetNameNoFormatting]", fname),
            ("[SECOND_COUNTRY.GetNameNoFormatting]", sname),
            ("[FIRST_COUNTRY.GetAdjectiveNoFormatting]", fname),
            ("[SECOND_COUNTRY.GetAdjectiveNoFormatting]", sname)):
        s = s.replace(ph, v)
    s = _ARTICLE_LOC_RE.sub(lambda m: _article_concept_zh(m.group(1)), s)
    return _clean_loc_markup(s)


def _article_zh(article_type):
    """条款类型 → 中文名; 未知类型回退原 key, 不再输出"下文略"。"""
    concept = ARTICLE_CONCEPT_MAP.get(article_type)
    if concept:
        zh = _concept_zh().get(concept)
        if zh:
            return zh
    return ARTICLE_ZH_FALLBACK.get(article_type) or article_type

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
    """条款附加数据 → (展示文本, 结构化信息)。
    inputs 为键值对列表(如 [{"goods": X}, {"quantity": N}]), 成对拼成"轻武器15单位";
    结构化信息供渲染层拼自然语句 (如"巴西向奥地利移交27单位的咖啡")。
    free_text 条款的 inputs 为 [{"text": "..."}], 原文直出。"""
    inputs = (a.get("inputs") or [])
    if not inputs:
        return None, None
    goods = qty = law = state = text = None
    for it in inputs:
        if not isinstance(it, dict):
            continue
        if "goods" in it:
            goods = it["goods"]
        elif "quantity" in it:
            qty = it["quantity"]
        elif "law_type" in it:
            law = it["law_type"]
        elif "state" in it:
            state = it["state"]
        elif "text" in it:
            text = it["text"]
    if goods is not None:
        gz = _goods_zh(goods)
        return (f"{gz}{qty}单位" if qty is not None else gz), \
               {"kind": "goods", "goods": gz, "quantity": qty}
    if text is not None:
        return text, {"kind": "free_text", "text": text}
    if law is not None:
        law_zh = _load_loc_all().get(law, law.replace("law_", ""))
        return f"施行法律{law_zh}", {"kind": "law", "law": law_zh, "law_key": law}
    if state is not None:
        if isinstance(state, str):
            state_zh = _load_loc_all().get(state, state.replace("STATE_", ""))
        else:
            state_zh = str(state)
        return f"州{state_zh}", {"kind": "state", "state": state_zh, "state_key": state}
    if qty is not None:
        return f"{qty}单位", {"kind": "quantity", "quantity": qty}
    return None, None


def _article_natural(article_type, fname, sname, meta):
    """条款 → 一句自然语言描述 (方向=source→target, 均为中文国名)。
    优先用游戏官方 *_article_short_desc 模板填国名/商品/数量/州/法律;
    无法识别时兜底为"{from}对{to}实施{条款名}", 保证永不出现"下文略"。"""
    fname = fname or "？"
    sname = sname or "？"
    if article_type == "free_text":
        return None
    if article_type == "daoyu_treaty_articles":
        # 刀鱼作弊条款: 含义为"强制对方接受该条约"
        return f"{fname}强制{sname}接受该条约"
    meta = meta or {}
    kind = meta.get("kind")
    if article_type == "money_transfer" and kind == "quantity":
        # 游戏内实际逻辑: 每周转移固定数额的英镑
        qty = meta.get("quantity")
        if qty is not None:
            return f"{fname}每周向{sname}转移{qty}英镑"
    tmpl_key = ARTICLE_TEMPLATE_KEYS.get(article_type)
    tmpl = _article_templates().get(tmpl_key) if tmpl_key else None
    if tmpl:
        s = tmpl
        if kind == "goods":
            gz = meta.get("goods") or "货物"
            if article_type == "goods_transfer":
                qty = meta.get("quantity")
                s = s.replace("$concept_goods$",
                              f"{qty}单位的{gz}" if qty is not None else gz)
            elif article_type in ("no_tariffs", "no_subventions",
                                  "prohibit_trade_with_global_market"):
                s = s.replace("$concept_good$", gz)
            elif article_type == "acquire_monopoly_for_company":
                s = s.replace("$concept_company_monopoly$", f"{gz}的垄断权")
            elif article_type == "ship_transfer":
                s = s.replace("$concept_ship$", gz)
        elif kind == "state" and article_type == "treaty_port":
            st = meta.get("state") or "该州"
            s = s.replace("$concept_treaty_port$", f"位于{st}的条约港")
        elif kind == "state" and article_type == "state_transfer":
            s = s.replace("将一个$concept_state$", f"将{meta.get('state') or '一个州'}")
        elif kind == "law" and article_type == "law_commitment":
            lw = meta.get("law") or "该法律"
            s = s.replace("$concept_law$", f"{lw}法律")
        return _render_article_template(s, fname, sname)
    if kind == "state" and article_type == "state_transfer":
        return f"{fname}将{meta.get('state') or '该州'}转让给{sname}"
    zh = ARTICLE_ZH_FALLBACK.get(article_type) or article_type
    return f"{fname}对{sname}实施{zh}"


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
    返回 [{id, name(中文), first_name, second_name, date,
           articles:[{zh, from, to, detail, meta, natural(自然语言句)}]}]。
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
        # 草拟条约 (未进入生效期, 如谈判遗留/draft_treaties) 一律不输出,
        # 避免模型把未生效条约当成真实条约报道。
        if not obj.get("entered_into_force_on"):
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
            article_type = a.get("article")
            azh = _article_zh(article_type)
            src = a.get("source_country")
            tgt = a.get("target_country")
            detail, meta = _article_detail(a)
            f_a = (names.get((index.get(src) or {}).get("definition"), str(src))
                   if src and src != 4294967295 else None)
            t_a = (names.get((index.get(tgt) or {}).get("definition"), str(tgt))
                   if tgt and tgt != 4294967295 else None)
            articles.append({
                "zh": azh,
                "from": f_a,
                "to": t_a,
                "detail": detail,
                "meta": meta,
                "natural": _article_natural(article_type, f_a, t_a, meta),
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


def _pact_country_name(cid, names, index):
    """pact 中国家 id → 中文名 (经 definition 查本地化, 失败回退 id)。"""
    entry = index.get(cid) or {}
    tag = entry.get("definition")
    return names.get(tag, tag) if tag else str(cid)


def _extract_pacts(data, player_id, names, index=None):
    """从 pacts.database 一次性提取与玩家相关的全部 pact (任一方是玩家)。
    返回 [{action, first, second, first_name, second_name, start_date}],
    first=发起方/宗主, second=对象/附庸 (与存档 targets 字段一致)。"""
    pacts = []
    if not player_id:
        return pacts
    if index is None:
        index, _, _ = _build_indexes(data)
    for pact in _iter_pacts(data):
        tg = pact.get("targets") or {}
        f, s = tg.get("first"), tg.get("second")
        if f != player_id and s != player_id:
            continue
        if f is None or s is None:
            continue
        pacts.append({
            "action": pact.get("action"),
            "first": f, "second": s,
            "first_name": _pact_country_name(f, names, index),
            "second_name": _pact_country_name(s, names, index),
            "start_date": pact.get("start_date"),
        })
    return pacts


def _extract_subjects(data, player_id, names, index=None, pacts=None):
    """从 pacts.database 提取玩家的附庸国 (first=宗主, second=附庸)。
    返回 [{name, type, country_id}]。pacts 为 _extract_pacts 的结果时可复用, 避免重复扫描。"""
    subs = []
    if not player_id:
        return subs
    if index is None:
        index, _, _ = _build_indexes(data)
    for pact in (pacts if pacts is not None else _extract_pacts(data, player_id, names, index)):
        act = pact.get("action")
        if act not in SUBJECT_ACTIONS or pact.get("first") != player_id:
            continue
        sub_id = pact.get("second")
        if sub_id is None:
            continue
        subs.append({"name": pact.get("second_name") or str(sub_id),
                     "type": act, "country_id": sub_id})
    return subs


def _extract_rivals(data, player_id, names, index=None, pacts=None):
    """从 pacts.database 提取玩家的宿敌 (rivalry pact, 任一方是玩家)。
    返回 [{name, definition, country_id}]，按 pact 出现顺序去重。
    pacts 为 _extract_pacts 的结果时可复用, 避免重复扫描。"""
    rivals = []
    if not player_id:
        return rivals
    if index is None:
        index, _, _ = _build_indexes(data)
    seen = set()
    for pact in (pacts if pacts is not None else _extract_pacts(data, player_id, names, index)):
        if pact.get("action") != "rivalry":
            continue
        f, s = pact.get("first"), pact.get("second")
        other = s if f == player_id else f
        if other in seen or other is None:
            continue
        seen.add(other)
        entry = index.get(other) or {}
        tag = entry.get("definition")
        rivals.append({
            "name": pact.get("second_name" if f == player_id else "first_name")
                    or str(other),
            "definition": tag,
            "country_id": other,
        })
    return rivals


def _ig_approval_band(approval):
    """利益集团对政府的支持度档位 (游戏官方中文名)。
    阈值同 common/defines/00_defines.txt: <=-10 愤怒, <=-5 不满, <5 中立,
    >=5 满意, >=10 忠诚。存档 approval_state 在中立时不写, 故一律按数值推算。"""
    if not isinstance(approval, (int, float)):
        return None
    if approval <= -10:
        return "愤怒"
    if approval <= -5:
        return "不满"
    if approval < 5:
        return "中立"
    if approval < 10:
        return "满意"
    return "忠诚"


def _extract_interest_groups(data, player_id, chars=None):
    """从 interest_groups.database 提取玩家全部利益集团。
    返回按 clout 降序的 [{name, definition, clout_pct, in_government, approval_state,
    approval_band, leader_name, leader_ideology, leader_culture, leader_religion,
    leader_home_region}]。chars 可由调用方复用 _player_characters 结果,
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
            approval = obj.get("approval")
            groups.append({
                "name": obj.get("name") or obj.get("definition"),
                "definition": obj.get("definition"),
                "clout_pct": round(clout * 100, 1) if isinstance(clout, (int, float)) else None,
                "in_government": bool(obj.get("in_government")),
                "approval_state": obj.get("approval_state"),
                "approval_band": _ig_approval_band(approval),
                "leader_name": (leader or {}).get("name"),
                "leader_ideology": (_clean_loc_name(loc.get(lideo, lideo), loc)
                                    if lideo else None),
                "leader_culture": (leader or {}).get("culture"),
                "leader_religion": (leader or {}).get("religion"),
                "leader_home_region": (leader or {}).get("home_region"),
            })
        j = end
    groups.sort(key=lambda g: -(g.get("clout_pct") or 0))
    return groups

# ---------------------------------------------------------------------------
# 快照缓存 (阶段2: 落盘缓存, 重复生成报纸/杂志时跳过熔化+提取)
# ---------------------------------------------------------------------------

SNAPSHOT_CACHE_VERSION = 4
# 快照缓存写入锁: 报纸/杂志并行生成时两者会各自落盘同一 snapshot_<year>.json
# (内容相同), 加锁避免并发写同一文件交错。
_SNAP_CACHE_LOCK = threading.Lock()


def _current_save_stamp():
    """当前最新存档的 (文件名, mtime), 用于校验快照缓存; 无存档返回 (None, None)。"""
    v3 = find_latest_v3()
    if not v3:
        return None, None
    try:
        return os.path.basename(v3), os.path.getmtime(v3)
    except OSError:
        return None, None


def _snapshot_cache_path(journal_dir, folder, year):
    """快照缓存路径: <journal_dir>/<folder>/data/snapshot_<year>.json。"""
    return os.path.join(journal_dir, folder, "data", f"snapshot_{year}.json")


def _save_snapshot_cache(snap, journal_dir, folder, year):
    """把完整快照落盘, 附带 _meta 存档校验信息 (存档名+mtime+玩家+会话文件夹)。
    只缓存 extract_full_snapshot 的纯提取结果, 不含 _merge_prev_year_wars
    补回的跨年战争, 使缓存与上一年 raw JSON 解耦, 读取后每次重新合并结果一致。"""
    if not folder or not year:
        return
    save_name, save_mtime = _current_save_stamp()
    snap2 = dict(snap)
    snap2["_meta"] = {
        "version": SNAPSHOT_CACHE_VERSION,
        "year": year,
        "player": snap.get("player"),
        "save_name": save_name,
        "save_mtime": save_mtime,
        "session_folder": folder,
    }
    path = _snapshot_cache_path(journal_dir, folder, year)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _SNAP_CACHE_LOCK:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(snap2, fp, ensure_ascii=False)
    except Exception as e:
        print(f"写入快照缓存失败: {e}")


def _load_snapshot_cache(journal_dir, year):
    """按年份在一级会话文件夹中查找快照缓存。
    校验: 缓存必须来自当前最新存档 (save_name + mtime 一致) 且年份匹配,
    否则视为失效返回 (None, None), 由调用方重新熔化提取。
    只扫描 <journal_dir>/<folder>/data/snapshot_<year>.json 一级深度,
    不会误取 test*/ 等子目录下的测试缓存。"""
    if not year:
        return None, None
    save_name, save_mtime = _current_save_stamp()
    if not save_name:
        return None, None
    try:
        entries = sorted(os.listdir(journal_dir))
    except OSError:
        return None, None
    matches = []
    for folder in entries:
        path = _snapshot_cache_path(journal_dir, folder, year)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fp:
                snap = json.load(fp)
        except Exception:
            continue
        meta = snap.get("_meta") or {}
        if not isinstance(meta, dict):
            continue
        mt = meta.get("save_mtime")
        mt_ok = isinstance(mt, (int, float)) and abs(mt - save_mtime) < 1e-6
        if (meta.get("version") == SNAPSHOT_CACHE_VERSION
                and meta.get("year") == year
                and meta.get("save_name") == save_name
                and mt_ok):
            matches.append((snap, meta.get("session_folder")))
    if not matches:
        return None, None
    # 多个有效缓存(极少见)时优先取最新会话: 文件夹名为 玩家名 或 玩家名N, N 大者最新
    def _session_key(item):
        folder = str(item[1] or "")
        m = re.match(r"^(.*?)(\d+)$", folder)
        return (m.group(1), int(m.group(2))) if m else (folder, 0)
    matches.sort(key=_session_key, reverse=True)
    return matches[0][0], matches[0][1]


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

def make_newspaper(year=None, force=True, melted=None, snap=None, ctx=None):
    """用存档数据生成报纸 (复用 journal.py)。
    melted/snap 由调用方已熔化/解析时可直接传入, 避免同一年份重复熔化解析。
    未传入 snap 时优先读取当年快照缓存 (snapshot_<year>.json); 缓存命中则
    跳过熔化与完整提取, 只读 JSON (~30KB), 大幅加快重复生成。
    ctx 可选: SaveContext, 由 watch/continue 创建一次并传给报纸与杂志,
    使两个生成函数共享索引/POP/州对象解析 (阶段1)。"""
    import journal
    cfg = journal.load_config()
    snap_from_cache = False
    cache_folder = None
    if snap is None:
        if melted is None:
            cached = _load_snapshot_cache(cfg["journal_dir"], year)
            if cached[0] is not None:
                snap, cache_folder = cached
                snap_from_cache = True
                print(f"使用快照缓存: "
                      f"{_snapshot_cache_path(cfg['journal_dir'], cache_folder, year)}")
            else:
                data = ensure_fresh_melt()
                if data[1]:
                    print(data[1])
                    return 1
                melted, _ = data
                if ctx is None:
                    ctx = SaveContext(melted)
                snap = extract_full_snapshot(melted, ctx=ctx)
        else:
            if ctx is None:
                ctx = SaveContext(melted)
            snap = extract_full_snapshot(melted, ctx=ctx)
    if year and snap.get("year") != year:
        print(f"存档年份 {snap.get('year')} 与请求 {year} 不符")
    # 首次确定文件夹: 检查根目录同名文件夹, 有则加数字(大南、大南2...); 同局沿用
    if not journal.SESSION["folder"]:
        with journal._FOLDER_LOCK:
            if not journal.SESSION["folder"]:
                if snap_from_cache and cache_folder:
                    journal.SESSION["folder"] = cache_folder
                else:
                    journal.SESSION["folder"] = journal.determine_folder(
                        snap.get("player") or "未知名国家", cfg["journal_dir"])
    # 快照落盘缓存: 只缓存纯提取结果, 跨年战争由 _merge_prev_year_wars 每次重算
    if not snap_from_cache:
        _save_snapshot_cache(snap, cfg["journal_dir"], journal.SESSION["folder"],
                             snap.get("year"))
    # 存档层落盘: 补回上一年存档中的「去年战争」(V3 war_manager 只保留进行中战争)
    _merge_prev_year_wars(snap, cfg["journal_dir"], journal.SESSION["folder"])
    jdata = build_journal_data(snap)
    journal.on_block_complete(jdata, cfg, force=force)
    print("报纸生成完成")
    return 0


def make_magazine(year=None, force=True, melted=None, snap=None, cfg=None, ctx=None):
    """用存档数据生成杂志 (magazine.py), 复用 make_newspaper 的熔化/快照/
    会话文件夹逻辑, 避免同一年份重复熔化解析。
    cfg 可传入覆盖(如 test 目录), 缺省重新读取 config.json。
    未传入 snap 时优先读取当年快照缓存; 命中后只需读 melt 缓存即可构建杂志数据
    (跳过约 41s 的完整提取, 保留约 10s 的杂志数据构建)。
    ctx 可选: SaveContext, 与 make_newspaper 共享索引/POP/州对象解析 (阶段1)。"""
    import journal
    cfg = cfg or journal.load_config()
    snap_from_cache = False
    cache_folder = None
    if snap is None:
        if melted is None:
            cached = _load_snapshot_cache(cfg["journal_dir"], year)
            if cached[0] is not None:
                snap, cache_folder = cached
                snap_from_cache = True
                print(f"使用快照缓存: "
                      f"{_snapshot_cache_path(cfg['journal_dir'], cache_folder, year)}")
            else:
                data = ensure_fresh_melt()
                if data[1]:
                    print(data[1])
                    return 1
                melted, _ = data
                if ctx is None:
                    ctx = SaveContext(melted)
                snap = extract_full_snapshot(melted, ctx=ctx)
        else:
            if ctx is None:
                ctx = SaveContext(melted)
            snap = extract_full_snapshot(melted, ctx=ctx)
    if year and snap.get("year") != year:
        print(f"存档年份 {snap.get('year')} 与请求 {year} 不符")
    if not journal.SESSION["folder"]:
        with journal._FOLDER_LOCK:
            if not journal.SESSION["folder"]:
                if snap_from_cache and cache_folder:
                    journal.SESSION["folder"] = cache_folder
                else:
                    journal.SESSION["folder"] = journal.determine_folder(
                        snap.get("player") or "未知名国家", cfg["journal_dir"])
    if not snap_from_cache:
        _save_snapshot_cache(snap, cfg["journal_dir"], journal.SESSION["folder"],
                             snap.get("year"))
    # 杂志数据需要 melted 字节: 缓存命中时读 melt 缓存即可 (约 0.5s), 缺缓存再熔化
    if snap_from_cache and melted is None:
        melted, err = load_melted()
        if err:
            melted, err = ensure_fresh_melt()
            if err:
                print(err)
                return 1
        if ctx is None:
            ctx = SaveContext(melted)
    _merge_prev_year_wars(snap, cfg["journal_dir"], journal.SESSION["folder"])
    jdata = build_journal_data(snap)
    jdata["output_dir"] = journal.SESSION["folder"]
    session_dir = os.path.join(cfg["journal_dir"], journal.SESSION["folder"])
    jdata["magazine"] = build_magazine_data(
        melted, snap, session_dir, snap.get("year"), ctx=ctx,
        pool_override=cfg.get("magazine_pool_override"),
        pool_size=cfg.get("magazine_pool_size", 3))
    import magazine
    magazine.generate_magazine(jdata, cfg, force=force)
    print("杂志生成完成")
    return 0


def _generate_async(year, snap, melted=None):
    """后台线程: 并行生成某年报纸与杂志(同一快照 + 同一 SaveContext,
    不重复熔化解析, 也不重复扫描索引/POP/州对象), 不阻塞监控。

    报纸与杂志的 LLM 请求相互独立: 报纸只消费 snap+往年 raw JSON, 杂志只消费
    melted+snap, 两边不读对方输出, 因此顶层并行使总耗时约等于两者较长者,
    而非顺序相加。DeepSeek 官方对 deepseek-v4-flash 的账号级并发上限为 2500,
    本项目两边同时打满也仅约 23 个并发请求, 远低于限流, 并行安全。
    前置步骤(定会话文件夹/落快照缓存/合并去年战争)在线程启动前只做一次:
    - 避免两线程并发写同一 snapshot_<year>.json (已另加 _SNAP_CACHE_LOCK 兜底);
    - 避免两线程并发改写 snap 的 last_year_wars/prev_year_wars (幂等但应只算一次)。"""
    import journal
    cfg = journal.load_config()
    ctx = SaveContext(melted) if melted is not None else None
    # 前置步骤只做一次 (与 make_newspaper/make_magazine 内部的重复步骤幂等)
    if not journal.SESSION["folder"]:
        with journal._FOLDER_LOCK:
            if not journal.SESSION["folder"]:
                journal.SESSION["folder"] = journal.determine_folder(
                    snap.get("player") or "未知名国家", cfg["journal_dir"])
    _save_snapshot_cache(snap, cfg["journal_dir"],
                         journal.SESSION["folder"], snap.get("year"))
    _merge_prev_year_wars(snap, cfg["journal_dir"], journal.SESSION["folder"])

    def _run(name, enabled_key, fn):
        try:
            if cfg.get(enabled_key, True):
                fn()
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {year} 年{name}已在配置中禁用 "
                      f"({enabled_key}=false), 跳过")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {year} 年{name}生成失败: {e}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(_run, "报纸", "newspaper_enabled",
                      lambda: make_newspaper(year=year, force=True,
                                             snap=snap, ctx=ctx)),
            ex.submit(_run, "杂志", "magazine_enabled",
                      lambda: make_magazine(year=year, force=True,
                                            melted=melted, snap=snap, ctx=ctx)),
        ]
        for f in futures:
            f.result()

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
        ctx = SaveContext(melted)
        snap = extract_full_snapshot(melted, ctx=ctx)
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
            mg_path = os.path.join(cfg["journal_dir"], journal.SESSION["folder"],
                                   f"杂志_{year}.md")
            if not os.path.exists(md_path) and cfg.get("newspaper_enabled", True):
                print(f"续传模式: {year} 年报纸缺失, 先用当前存档补生成")
                make_newspaper(year=year, force=True, melted=melted, snap=snap, ctx=ctx)
            if cfg.get("magazine_enabled", True) and not os.path.exists(mg_path):
                print(f"续传模式: {year} 年杂志缺失, 先用当前存档补生成")
                make_magazine(year=year, force=True, melted=melted, snap=snap, ctx=ctx)
            if os.path.exists(md_path) and os.path.exists(mg_path):
                print(f"续传模式: {year} 年报纸与杂志均存在, 进入监控等待下一年。")
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
                            print(f"  新年份 {year}, 后台生成报纸+杂志 (不阻塞监控)")
                            threading.Thread(target=_generate_async,
                                             args=(year, snap, melted[0]),
                                             daemon=True).start()
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
            "newspaper": make_newspaper, "magazine": make_magazine,
            "watch": cmd_watch,
            "continue": cmd_continue}
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    if cmd not in cmds:
        print("可用: check | melt | sniff | newspaper [年份] | magazine [年份] | watch | continue"); return 1
    kwargs = {}
    if cmd in ("newspaper", "magazine") and args:
        kwargs["year"] = int(args[0]) if args[0].isdigit() else None
    return cmds[cmd](**kwargs)

if __name__ == "__main__":
    sys.exit(main())
