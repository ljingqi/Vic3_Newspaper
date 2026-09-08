#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 V3 游戏本体 map_data/state_regions 生成州级「食物画像」data/state_food_palette.json。

用途: 食物风味层(区域×时令)的权威数据源:
  - 生计类型 subsistence (farm/rice_farm/pasture/fishing_village/orchard)
  - 可建农场/种植园 arable_resources → 简化标签 (rice/rye/maize/millet/wheat/
    livestock/banana/sugar/tea/coffee/tobacco/cotton/silk/dye/vineyard/opium…)
  - 封顶资源含 fishing_wharf → 本州有渔获
  - 州 traits
  - 州中心纬度/半球/纬度带 (state_geojson.json 的 point.y; V3 等距投影,
    y=2048 为赤道, y 越大越靠南): 供「报告月×半球」时令机制使用。

用法: python tools/build_state_food_palette.py
输出: data/state_food_palette.json (UTF-8, {STATE_KEY: {...}})

只读游戏本体与项目 JSON; 可重复执行 (幂等覆盖)。
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 简化标签: building_* → palette 标签
_FARM_TAG = {
    "building_wheat_farm": "wheat",
    "building_rye_farm": "rye",
    "building_maize_farm": "maize",
    "building_millet_farm": "millet",
    "building_rice_farm": "rice",
    "building_livestock_ranch": "livestock",
    "building_banana_plantation": "banana",
    "building_sugar_plantation": "sugar",
    "building_tea_plantation": "tea",
    "building_coffee_plantation": "coffee",
    "building_tobacco_plantation": "tobacco",
    "building_cotton_plantation": "cotton",
    "building_silk_plantation": "silk",
    "building_dye_plantation": "dye",
    "building_vineyard": "vineyard",
    "building_opium_plantation": "opium",
}

_SUBSISTENCE_TAG = {
    "building_subsistence_farm": "farm",
    "building_subsistence_rice_farm": "rice_farm",
    "building_subsistence_pasture": "pasture",
    "building_subsistence_fishing_village": "fishing_village",
    "building_subsistence_orchard": "orchard",
}


def _lat_band(lat):
    """粗纬度带: 供果菜/季相词表选取。"""
    a = abs(lat)
    if a <= 23.5:
        return "tropical"
    if a <= 35:
        return "subtropical"
    if a <= 55:
        return "temperate"
    if a <= 66.5:
        return "cold"
    return "arctic"


def parse_state_regions(state_regions_dir):
    """解析 18 个州定义 txt → {STATE_KEY: {subsistence, farms[], fish, traits[]}}。"""
    out = {}
    re_block = re.compile(r'^\s*(STATE_[A-Z0-9_]+)\s*=\s*\{', re.M)
    re_subs = re.compile(r'subsistence_building\s*=\s*"(building_subsistence_[a-z_]+)"')
    re_arable = re.compile(r'arable_resources\s*=\s*\{([^}]*)\}')
    re_capped = re.compile(r'capped_resources\s*=\s*\{([^}]*)\}')
    re_traits = re.compile(r'traits\s*=\s*\{([^}]*)\}')
    re_build = re.compile(r'"(building_[a-z_]+)"')
    re_trait_key = re.compile(r'"(state_trait_[a-z0-9_]+)"')

    for fn in sorted(os.listdir(state_regions_dir)):
        if not fn.endswith(".txt"):
            continue
        text = open(os.path.join(state_regions_dir, fn), encoding="utf-8-sig").read()
        # 切出每个 STATE 块
        matches = list(re_block.finditer(text))
        for i, m in enumerate(matches):
            key = m.group(1)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[m.end():end]
            entry = {}
            sm = re_subs.search(block)
            if sm:
                entry["subsistence"] = _SUBSISTENCE_TAG.get(sm.group(1), sm.group(1))
            am = re_arable.search(block)
            farms = []
            if am:
                for b in re_build.findall(am.group(1)):
                    t = _FARM_TAG.get(b)
                    if t and t not in farms:
                        farms.append(t)
            entry["farms"] = farms
            cm = re_capped.search(block)
            entry["fish"] = bool(cm and 'building_fishing_wharf' in cm.group(1))
            tm = re_traits.search(block)
            entry["traits"] = (re_trait_key.findall(tm.group(1))
                               if tm else [])  # state_trait_xxx 键
            out[key] = entry
    return out


def _load_geojson_points(path):
    """{STATE_KEY: (point.y, equator_y)} (state_geojson.json GeoJSON 风格:
    {"width","height","features":[{id, polys, point:[x,y]}, ...]})。"""
    if not os.path.exists(path):
        return {}, 2048.0
    data = json.load(open(path, encoding="utf-8"))
    equator = float(data.get("height", 4096)) / 2.0
    pts = {}
    for v in data.get("features") or []:
        if not isinstance(v, dict):
            continue
        k = v.get("id")
        p = v.get("point")
        if k and isinstance(p, (list, tuple)) and len(p) >= 2:
            pts[k] = (p[1], equator)
    return pts, equator


def main():
    cfg = json.load(open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8"))
    game_dir = cfg.get("game_dir") or ""
    state_regions_dir = os.path.join(game_dir, "map_data", "state_regions")
    if not os.path.isdir(state_regions_dir):
        state_regions_dir = os.path.join(game_dir, "game", "map_data", "state_regions")
    if not os.path.isdir(state_regions_dir):
        print(f"找不到游戏州定义目录: {state_regions_dir}")
        return 1
    states = parse_state_regions(state_regions_dir)
    print(f"解析到 {len(states)} 个州")
    pts, equator = _load_geojson_points(os.path.join(SCRIPT_DIR, "state_geojson.json"))
    print(f"state_geojson 点数据 {len(pts)} 条 (赤道 y={equator})")
    out = {}
    for key, e in states.items():
        rec = dict(e)
        py = pts.get(key)
        if py is not None:
            y, eq = py
            lat = (eq - y) * 90.0 / eq  # y 越小越北; y=赤道处为 0
            rec["lat"] = round(lat, 1)
            rec["hemisphere"] = "north" if lat >= 0 else "south"
            rec["lat_band"] = _lat_band(lat)
        out[key] = rec
    dst = os.path.join(SCRIPT_DIR, "data", "state_food_palette.json")
    with open(dst, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1, sort_keys=True)
    n_lat = sum(1 for v in out.values() if "lat" in v)
    print(f"写入 {dst}: {len(out)} 州 (含纬度 {n_lat})")
    for k in ("STATE_URALSK", "STATE_SAMARA", "STATE_KHIVA"):
        if k in out:
            print(f"  样例 {k}:", json.dumps(out[k], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
