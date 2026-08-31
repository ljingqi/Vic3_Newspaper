#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界时局电影 (一次性生成): 用 output\\卢卡 的 1859 年缓存数据
(snapshot_1859.json + magazine_1859.json), 从 8 个受承认列强中随机抽取
5 个国家 (不含玩家国意大利), 各生成一部剧本。

数据来源全部限于 1859 年快照给出的世界信息: 列强名单/威望/战争参与方/
条约/宿敌; 资料未给出姓名的人物按 SCREENPLAY_RULE 以身份与职业代称。
输出: output\\卢卡\\电影剧本\\1859世界时局\\电影剧本_1859_<国名>.md
"""
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal
import journal_save as js
import movie

SESSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "output", "卢卡")
YEAR = 1859
OUT_DIR = os.path.join(SESSION, "电影剧本", "1859世界时局")

with open(os.path.join(SESSION, "data", "snapshot_1859.json"),
          encoding="utf-8") as f:
    SNAP = json.load(f)
with open(os.path.join(SESSION, "data", "magazine_1859.json"),
          encoding="utf-8") as f:
    MAG = json.load(f)

cfg = journal.load_config()
wars = [w for w in (SNAP.get("wars") or []) if isinstance(w, dict)]


def _country_wars(defn):
    return [w for w in wars
            if any(str(p.get("definition")) == defn
                   for p in (w.get("participants") or []) if isinstance(p, dict))]


def _war_side(w, defn):
    for p in (w.get("participants") or []):
        if isinstance(p, dict) and str(p.get("definition")) == defn:
            return p.get("side")
    return None


def _side_participants(w, side):
    return [p for p in (w.get("participants") or [])
            if isinstance(p, dict) and p.get("side") == side]


def _primary(parts):
    parts = [p for p in parts if isinstance(p, dict) and p.get("name")]
    if not parts:
        return None
    prim = [p for p in parts if p.get("primary")]
    pool = prim or parts
    return max(pool, key=lambda p: p.get("prestige") or 0)


def _war_line(w, me_defn, me_name):
    side = _war_side(w, me_defn)
    en_side = _side_participants(w, "initiator" if side == "target" else "target")
    en_prim = _primary(en_side)
    en_name = (en_prim or {}).get("name") or "对手"
    status = "仍在进行" if not w.get("ended") else "已结束"
    return (f"{me_name}与{en_name}自{w.get('start_date') or '未知'}起交战，"
            f"战事{status}，双方参战国共{len(w.get('participants') or [])}个")


def _pact_zh(action):
    return {"rivalry": "宿敌", "embargo": "禁运", "protectorate": "保护关系",
            "damage_relations": "交恶",
            "support_separatism": "支持分离主义"}.get(action, action or "邦交")


def _build_foreign_movie(p):
    defn, name = p.get("definition"), p.get("name")
    rnd = random.Random(f"1859|{defn}")
    my_wars = _country_wars(defn)
    at_war = bool(my_wars)
    data = {"player_at_war": at_war}
    snap_s = {}
    genre = js._movie_genre_pick(rnd, data, snap_s, [], YEAR)
    # 背景
    flavor = [_war_line(w, defn, name) for w in my_wars[:3]]
    rank_zh = {"great_power": "列强", "major_power": "一等强国",
               "minor_power": "二等强国"}.get(p.get("rank"), "列强")
    era = f"{YEAR}年，{rank_zh}，威望{p.get('prestige') or '未知'}"
    setting = {"capital": name, "state": None, "flavor": flavor, "era": era}
    # 主角: 身份代称 (资料未给出姓名)
    prot = {"name": None, "role": "统帅" if at_war else "当政者",
            "culture": None, "religion": None, "state": None, "place": None,
            "sol": None, "literacy": None, "income": None, "expense": None,
            "family": None, "source": "世界局势数据",
            "desc": f"{YEAR}年{name}的{'统帅' if at_war else '当政者'}（姓名未给出）"}
    # 反派: 交战对手 (数据给出国名) / 宿敌 (与意大利的宿敌关系, 数据给出)
    ant = None
    if at_war:
        w0 = my_wars[0]
        side = _war_side(w0, defn)
        en_side = _side_participants(w0, "initiator" if side == "target" else "target")
        en_prim = _primary(en_side)
        if en_prim and en_prim.get("name"):
            en_nm = en_prim["name"]
            ant = {"name": en_nm, "role": f"{en_nm}统帅",
                   "culture": None, "religion": None, "state": None, "place": None,
                   "sol": None, "literacy": None, "income": None, "expense": None,
                   "family": None, "source": "世界局势数据",
                   "desc": f"与{name}交战的{en_nm}：{_war_line(w0, defn, name)}"}
    if ant is None:
        for pa in (SNAP.get("pacts") or []):
            if (isinstance(pa, dict) and pa.get("action") in ("rivalry", "embargo")
                    and pa.get("first_name") == name):
                other = pa.get("second_name")
                ant = {"name": other, "role": "宿敌", "culture": None,
                       "religion": None, "state": None, "place": None,
                       "sol": None, "literacy": None, "income": None,
                       "expense": None, "family": None, "source": "世界局势数据",
                       "desc": f"{name}与{other}互为宿敌（{_pact_zh(pa.get('action'))}，"
                               f"自{pa.get('start_date') or '未知'}起）"}
                break
    if ant is None:
        ant = {"name": None, "role": "未知对手", "source": "暂无对手数据"}
    # 配角: 同阵营盟邦 (数据给出国名)
    sup = []
    for w in my_wars:
        if len(sup) >= 2:
            break
        side = _war_side(w, defn)
        allies = [p for p in _side_participants(w, side)
                  if str(p.get("definition")) != defn and p.get("name")]
        allies.sort(key=lambda p: -(p.get("prestige") or 0))
        for al in allies:
            if len(sup) >= 2:
                break
            sup.append({"name": al["name"], "role": "盟邦", "culture": None,
                        "religion": None, "state": None, "place": None,
                        "sol": None, "literacy": None, "income": None,
                        "expense": None, "family": None, "source": "世界局势数据",
                        "desc": f"与{name}同阵营的{al['name']}"})
    # 主题/事件
    themes = [{"kind": "战役", "title": "战役", "facts": _war_line(w, defn, name)}
              for w in my_wars[:2]]
    for pa in (SNAP.get("pacts") or []):
        if len(themes) >= 2:
            break
        if (isinstance(pa, dict) and (pa.get("first_name") == name
                                      or pa.get("second_name") == name)):
            other = (pa.get("second_name") if pa.get("first_name") == name
                     else pa.get("first_name"))
            themes.append({"kind": "邦交", "title": "邦交",
                           "facts": f"{name}与{other}：{_pact_zh(pa.get('action'))}"
                                    f"（自{pa.get('start_date') or '未知'}起）"})
    for tr in (SNAP.get("treaties") or []):
        if len(themes) >= 2:
            break
        if (isinstance(tr, dict) and (tr.get("first_name") == name
                                      or tr.get("second_name") == name)):
            other = (tr.get("second_name") if tr.get("first_name") == name
                     else tr.get("first_name"))
            themes.append({"kind": "条约", "title": "条约",
                           "facts": f"{tr.get('name') or '双边条约'}：{name}与{other}"
                                    f"缔结（{tr.get('date') or '日期未知'}）"})
    if not themes:
        themes.append({"kind": "时局", "title": "时局",
                       "facts": f"{YEAR}年，{name}列强地位稳固，威望"
                                f"{p.get('prestige') or '未知'}，本刊资料无其战事记录"})
    finale = js._movie_finale(rnd, data, snap_s, genre)
    return {"seed": f"1859|{defn}", "term": "新剧", "genre": genre,
            "setting": setting, "protagonist": prot, "antagonist": ant,
            "supporting": sup[:2], "themes": themes, "finale": finale}


def main():
    powers = [p for p in (SNAP.get("powers") or []) if isinstance(p, dict)]
    cands = [p for p in powers if not p.get("is_player")]
    picked = random.sample(cands, min(5, len(cands)))
    print("受承认列强候选:", [p.get("name") for p in cands])
    print("随机抽中 5 国:", [p.get("name") for p in picked])
    os.makedirs(OUT_DIR, exist_ok=True)
    for p in picked:
        name = p.get("name")
        defn = p.get("definition")
        try:
            m = _build_foreign_movie(p)
            data = {"player": name, "year": YEAR, "capital": name,
                    "currency": journal.currency_unit(tag=defn) or None,
                    "output_dir": "卢卡", "date": "1859.1.1"}
            title = movie._generate_title(m, data, cfg)
            m["title"] = title
            acts = movie._generate_full(m, data, cfg, title)
            m["acts"] = acts
            movie._check_names(m, acts)
            text = movie._assemble(m, data, title, acts)
            header = (f"<!-- 数据来源: 维多利亚3 报纸Mod 电影剧本(世界时局) | "
                      f"报告日期: 1859.1.1 | 生成时间: "
                      f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
            path = os.path.join(OUT_DIR, f"电影剧本_{YEAR}_{name}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + text.rstrip() + "\n")
            print(f"[OK] 已生成: {path}  《{title}》  "
                  f"体裁={[g.get('zh') for g in m.get('genre') or []]} "
                  f"结局={(m.get('finale') or {}).get('zh')} "
                  f"反派={(m.get('antagonist') or {}).get('name') or '未知'}")
        except Exception as e:
            print(f"[FAIL] {name} 生成失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
