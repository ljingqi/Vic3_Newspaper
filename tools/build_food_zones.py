#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 data/food_zones.json: 州 → 食物圈 zone + 半球/纬度带 + 农产画像。

数据源 (一次性, 升级游戏版本后重跑):
  1. map_data/state_regions/*.txt        → 生计类型/可建农场/渔获/特质
  2. common/geographic_regions/*.txt     → 官方地理分组 (人类聚落尺度 = 食物圈)
  3. state_geojson.json point            → 州中心像素 y → 纬度/半球/纬度带

zone 归属链:
  1) 关键词匹配地理分组 (turkestan/japan/caribbean/mexico/…) → 食物圈 zone;
  2) 州级手工覆盖 (STATE_OVERRIDES, 分组覆盖不到的州/测试集州);
  3) 纬度带兜底 → generic_temperate / generic_tropical / generic_boreal
     (宁平勿奇: 未精修的州一律落泛型带, 绝不写奇异菜)。

输出 (UTF-8, 运行时零游戏依赖):
{
  "zones": {"STATE_X": zone_id},           # 州 → 食物圈 (food_cuisine.json 键)
  "states": {"STATE_X": {"lat","hemisphere","band","subsistence","farms",
                          "fish","traits"}},
  "fallback_zone": "generic_temperate"
}
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "tools"))

from build_state_food_palette import (  # noqa: E402
    _SUBSISTENCE_TAG, parse_state_regions, _lat_band)

# 地理分组名关键词 → 食物圈 zone (键在 data/food_cuisine.json "zones")
_GEO_KEYWORD_ZONE = [
    ("turkestan", "steppe_central_asia"),
    ("japan", "east_asia_rice"),
    ("home_islands", "east_asia_rice"),
    ("mexico", "mesoamerica_maize"),
    ("caribbean", "caribbean_tropical"),
    ("antilles", "caribbean_tropical"),
    ("west_indies", "caribbean_tropical"),
]

# 州级覆盖: 地理分组未覆盖的测试集州 / 需要精修的州 → zone
_STATE_OVERRIDES = {
    "STATE_SAMARA": "volga_rye_wheat",
    "STATE_SYRDARYA": "steppe_central_asia",
    "STATE_CHELYABINSK": "generic_temperate",
}

_BAND_ZONE = {
    "tropical": "generic_tropical",
    "subtropical": "generic_temperate",
    "temperate": "generic_temperate",
    "cold": "generic_boreal",
    "arctic": "generic_boreal",
}


def parse_geographic_regions(geo_dir):
    """{geographic_region_name: [STATE_*]} (仅含直接列 state_regions 的分组)。"""
    out = {}
    re_block = re.compile(r'^\s*(geographic_region_[A-Za-z0-9_]+)\s*=\s*\{', re.M)
    re_state = re.compile(r'\b(STATE_[A-Z0-9_]+)\b')
    for fn in sorted(os.listdir(geo_dir)):
        if not fn.endswith(".txt"):
            continue
        text = open(os.path.join(geo_dir, fn), encoding="utf-8-sig").read()
        matches = list(re_block.finditer(text))
        for i, m in enumerate(matches):
            key = m.group(1)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[m.end():end]
            states = re_state.findall(block)
            if states:
                out.setdefault(key, [])
                for s in states:
                    if s not in out[key]:
                        out[key].append(s)
    return out


def assign_zones(states, geo_groups):
    """state → zone (关键词分组 → 州覆盖 → 纬度带兜底)。"""
    zones = {}
    # 1) 关键词分组: 每个州可命中多个组, 取顺序最靠前的 zone
    for state in states:
        for kw, zone in _GEO_KEYWORD_ZONE:
            if any(kw in g for g, sts in geo_groups.items() if state in sts):
                zones[state] = zone
                break
    # 2) 州级覆盖 (覆盖关键词分组结果, 供精修)
    for state, zone in _STATE_OVERRIDES.items():
        zones[state] = zone
    # 3) 纬度带兜底
    for state, rec in states.items():
        if state not in zones:
            band = rec.get("lat_band") or "temperate"
            zones[state] = _BAND_ZONE.get(band, "generic_temperate")
    return zones


def main():
    cfg = json.load(open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8"))
    game_dir = cfg.get("game_dir") or ""
    state_regions_dir = os.path.join(game_dir, "game", "map_data", "state_regions")
    geo_dir = os.path.join(game_dir, "game", "common", "geographic_regions")
    if not os.path.isdir(state_regions_dir):
        print(f"找不到州定义目录: {state_regions_dir}")
        return 1
    states = parse_state_regions(state_regions_dir)

    # 纬度/半球: 复用 build_state_food_palette 的 geojson 换算
    geojson = os.path.join(SCRIPT_DIR, "state_geojson.json")
    equator = 2048.0
    pts = {}
    if os.path.exists(geojson):
        data = json.load(open(geojson, encoding="utf-8"))
        equator = float(data.get("height", 4096)) / 2.0
        for v in data.get("features") or []:
            p = v.get("point") if isinstance(v, dict) else None
            if v.get("id") and isinstance(p, (list, tuple)) and len(p) >= 2:
                pts[v["id"]] = p[1]
    for key, rec in states.items():
        y = pts.get(key)
        if y is not None:
            lat = (equator - y) * 90.0 / equator
            rec["lat"] = round(lat, 1)
            rec["hemisphere"] = "north" if lat >= 0 else "south"
            rec["lat_band"] = _lat_band(lat)

    geo_groups = {}
    if os.path.isdir(geo_dir):
        geo_groups = parse_geographic_regions(geo_dir)
        print(f"地理分组 {len(geo_groups)} 个 (含州列表)")
    zones = assign_zones(states, geo_groups)

    doc = {
        "zones": dict(sorted(zones.items())),
        "states": dict(sorted(states.items())),
        "fallback_zone": "generic_temperate",
        "_meta": {"geo_groups": len(geo_groups),
                  "state_count": len(states)},
    }
    dst = os.path.join(SCRIPT_DIR, "data", "food_zones.json")
    with open(dst, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1, sort_keys=True)
    # 抽查
    for k in ("STATE_URALSK", "STATE_SAMARA", "STATE_KHIVA",
              "STATE_AKTOBE", "STATE_SYRDARYA", "STATE_CHELYABINSK"):
        if k in zones:
            print(f"  {k} -> {zones[k]}  ",
                  {kk: states[k].get(kk) for kk in
                   ("lat", "hemisphere", "lat_band", "subsistence") if kk in states[k]})
    cnt = {}
    for z in zones.values():
        cnt[z] = cnt.get(z, 0) + 1
    print(f"写入 {dst} ({len(states)} 州; zone 分布: " +
          ", ".join(f"{z}={n}" for z, n in sorted(cnt.items())) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
