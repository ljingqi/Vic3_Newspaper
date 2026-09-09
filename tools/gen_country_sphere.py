#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「国家 TAG / 文化 → 文风文化圈」静态表 (data/country_sphere.json)。

背景 (2026): 动态文风原先只有「档位」一条轴, 非中华文化圈国家在 1~2 档被写成
中式邸报体 (伏惟/谨按/岁次丙申)。本表给文风系统补一条「文化圈」轴:

  sinic  中华文化圈 (汉/满/蒙古/藏/苗/彝/朝鲜/日本/越南…)
  west   西方 (欧洲/美洲/大洋洲/殖民定居社会)
  islam  伊斯兰世界 (阿拉伯/波斯/突厥/柏柏尔/萨赫勒穆斯林政权…)
  other  其余 (南亚/东南亚/非洲/美洲原住民/太平洋; 中性王廷公报体)

数据源:
  game/common/cultures/*.txt                文化 → heritage / religion
  game/localization/simp_chinese/cultures_l_simp_chinese.yml  文化键 → 中文名
  tools/countries_table.json                国家 TAG → 主要文化键

判定: heritage 先定圈; 落在 other 且文化宗教属伊斯兰 (sunni/shiite/ibadi) 时
升为 islam (萨赫勒、高加索、马来群岛等穆斯林政权由此归位)。

用法:
  python tools/gen_country_sphere.py          重新生成 data/country_sphere.json
  python tools/gen_country_sphere.py --stats  只看统计, 不写文件
"""

import json
import os
import re
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "country_sphere.json")
COUNTRIES_TABLE = os.path.join(ROOT, "tools", "countries_table.json")
CONFIG = os.path.join(ROOT, "config.json")

SPHERES = ("sinic", "west", "islam", "other")
ISLAMIC_RELIGIONS = {"sunni", "shiite", "ibadi"}

# heritage → 文化圈。heritage 取 game/common/cultures/*.txt。
HERITAGE_SPHERE = {
    # ---- 西方 (欧洲/美洲定居社会/大洋洲/加勒比) ----
    "heritage_british": "west",
    "heritage_gallic": "west",
    "heritage_germanic": "west",
    "heritage_iberian": "west",
    "heritage_italic": "west",
    "heritage_netherlandish": "west",
    "heritage_nordic": "west",
    "heritage_east_slavic": "west",
    "heritage_west_slavic": "west",
    "heritage_south_slavic": "west",
    "heritage_baltic": "west",
    "heritage_magyar": "west",
    "heritage_romanian": "west",
    "heritage_greek": "west",
    "heritage_albanian": "west",
    "heritage_armenian": "west",
    "heritage_georgian": "west",
    "heritage_ashkenazi": "west",
    "heritage_sephardic": "west",
    "heritage_latin_american_settler": "west",
    "heritage_north_american_settler": "west",
    "heritage_african_settler": "west",
    "heritage_african_diaspora": "west",
    "heritage_caribbean": "west",
    "heritage_atlantic": "west",
    "heritage_australian": "west",
    # ---- 中华文化圈 ----
    "heritage_han": "sinic",
    "heritage_manchu": "sinic",
    "heritage_mongolian": "sinic",
    "heritage_tibetan": "sinic",
    "heritage_miao": "sinic",
    "heritage_yi": "sinic",
    "heritage_korean": "sinic",
    "heritage_japanese": "sinic",
    "heritage_vietnamese": "sinic",
    # ---- 伊斯兰世界 ----
    "heritage_arab": "islam",
    "heritage_iranian": "islam",
    "heritage_turkmen": "islam",
    "heritage_uzbek": "islam",
    "heritage_kipchak": "islam",
    "heritage_tatar": "islam",
    "heritage_hazaran": "islam",
    "heritage_uighur": "islam",
    "heritage_berber": "islam",
    "heritage_afro_arab": "islam",
    "heritage_somali": "islam",
    "heritage_anatolian": "islam",
    "heritage_syriac": "islam",
    # ---- 其余 (先落 other, 穆斯林政权由 religion 升为 islam) ----
    "heritage_sahelian": "other",
    "heritage_north_caucasian": "other",
    "heritage_insulindian": "other",
    "heritage_darfurian": "other",
    "heritage_abyssinian": "other",
    "heritage_kordofanian": "other",
    "heritage_east_african": "other",
    "heritage_central": "other",
    "heritage_volga_uralic": "other",
    "heritage_sami": "other",
    "heritage_circumpolar": "other",
    "heritage_siberian": "other",
    "heritage_formosan": "other",
    "heritage_ainu": "other",
    "heritage_insular": "other",
    "heritage_promethean": "other",
    "heritage_tai": "other",
    "heritage_burmese": "other",
    "heritage_khmer": "other",
    "heritage_assamese": "other",
    "heritage_himalayan": "other",
    "heritage_gangetic": "other",
    "heritage_deccani": "other",
    "heritage_carnatic": "other",
    "heritage_indusine": "other",
    "heritage_gujarati": "other",
    "heritage_rajasthani": "other",
    "heritage_kashmiri": "other",
    "heritage_southwest_indian": "other",
    "heritage_eastern_woodlands_indian": "other",
    "heritage_northwest_coast_indian": "other",
    "heritage_plains_indian": "other",
    "heritage_plateau_indian": "other",
    "heritage_great_basin_indian": "other",
    "heritage_californian_indian": "other",
    "heritage_subarctic_indian": "other",
    "heritage_mesoamerican": "other",
    "heritage_andean": "other",
    "heritage_amazonian": "other",
    "heritage_guarani": "other",
    "heritage_patagonian": "other",
    "heritage_polynesian": "other",
    "heritage_melanesian": "other",
    "heritage_micronesian": "other",
    "heritage_congolese": "other",
    "heritage_guinean": "other",
    "heritage_eastern_bantu": "other",
    "heritage_southern_bantu": "other",
    "heritage_southwest_bantu": "other",
    "heritage_khoisan": "other",
    "heritage_nilotic": "other",
    "heritage_eastern_highlands": "other",
}

CULTURE_BLOCK_RE = re.compile(r"(?m)^([a-z_0-9]+)\s*=\s*\{")
HERITAGE_RE = re.compile(r"\bheritage\s*=\s*(\S+)")
RELIGION_RE = re.compile(r"\breligion\s*=\s*(\S+)")


def _game_dir():
    """config.json 的 game_dir; 缺失时尝试常见路径。"""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            gd = (json.load(f) or {}).get("game_dir")
    except Exception:
        gd = None
    cands = [gd,
             r"F:\SteamLibrary\steamapps\common\Victoria 3",
             r"F:\Game\steamapps\common\Victoria 3",
             r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "game", "common", "cultures")):
            return c
    return None


def parse_cultures(game_dir):
    """game/common/cultures/*.txt → {culture_key: (heritage, religion)}。"""
    import glob
    out = {}
    pat = os.path.join(game_dir, "game", "common", "cultures", "*.txt")
    for fn in sorted(glob.glob(pat)):
        with open(fn, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        for m in CULTURE_BLOCK_RE.finditer(text):
            key = m.group(1)
            if key.startswith("heritage_") or key in ("religion",):
                continue
            body = text[m.end():]
            nxt = CULTURE_BLOCK_RE.search(body)
            block = body[:nxt.start()] if nxt else body
            h = HERITAGE_RE.search(block)
            r = RELIGION_RE.search(block)
            out[key] = (h.group(1) if h else None, r.group(1) if r else None)
    return out


def parse_culture_names(game_dir):
    """cultures_l_simp_chinese.yml → {culture_key: 中文名}。"""
    path = os.path.join(game_dir, "game", "localization", "simp_chinese",
                        "cultures_l_simp_chinese.yml")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([a-z_0-9]+):\s*"(.*)"\s*$', line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def culture_sphere(heritage, religion):
    """heritage 定圈 + 穆斯林宗教升圈。"""
    sp = HERITAGE_SPHERE.get(heritage or "", "other")
    if sp == "other" and (religion or "").lower() in ISLAMIC_RELIGIONS:
        return "islam"
    return sp


def build():
    game_dir = _game_dir()
    if not game_dir:
        return None, "未找到 Victoria 3 游戏目录 (config.json 的 game_dir)"
    cultures = parse_cultures(game_dir)
    names = parse_culture_names(game_dir)
    with open(COUNTRIES_TABLE, encoding="utf-8") as f:
        rows = json.load(f)

    culture_spheres = {}
    for key, (heritage, religion) in cultures.items():
        zh = names.get(key)
        if zh:
            culture_spheres[zh] = culture_sphere(heritage, religion)

    tags = OrderedDict()
    for row in rows:
        tag = row.get("tag")
        if not tag:
            continue
        cs = [c for c in (row.get("cultures") or []) if c in cultures]
        if not cs:
            continue
        sp = culture_sphere(*cultures[cs[0]])
        # 主体文化非穆斯林、但国族文化全为穆斯林时升为 islam (萨科托/摩洛哥/阿富汗…);
        # 首文化为印度教、次文化为穆斯林的复合政权 (如巴厘) 留 other,
        # 由运行时按存档国教 (data["religion"]) 再判。
        if sp == "other" and all(
                culture_sphere(*cultures[c]) == "islam" for c in cs):
            sp = "islam"
        tags[tag] = sp

    data = {
        "version": 1,
        "source": "Victoria 3 common/cultures heritage + countries_table.json",
        "spheres": list(SPHERES),
        "tags": dict(sorted(tags.items())),
        "cultures": dict(sorted(culture_spheres.items())),
    }
    return data, None


def main():
    data, err = build()
    if err:
        print(err)
        return 1
    stats = Counter(data["tags"].values())
    cstats = Counter(data["cultures"].values())
    print("国家 TAG:", len(data["tags"]),
          " ".join(f"{k}={stats.get(k, 0)}" for k in SPHERES))
    print("文化(中文名):", len(data["cultures"]),
          " ".join(f"{k}={cstats.get(k, 0)}" for k in SPHERES))
    for probe in ("PRU", "AUS", "RUS", "FRA", "GBR", "USA", "HAI",
                  "CHI", "JAP", "KOR", "DAI", "TUR", "PER", "BUK", "KZH",
                  "ZUL", "HAW", "SIA", "BAL", "SOK"):
        if probe in data["tags"]:
            print(f"  {probe} -> {data['tags'][probe]}")
    if "--stats" in sys.argv:
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=False)
    print("已写出:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
