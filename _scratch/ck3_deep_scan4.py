# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察4: 记忆归属、结仇/战役记忆、头衔历史。"""
import json, traceback
from collections import Counter

MELT = r"D:\Journal\_scratch\ck3_melt.json"

def show(label, fn):
    try:
        print(f"\n{'='*20} {label} {'='*20}")
        fn()
    except Exception:
        print("!! 段错误:")
        traceback.print_exc()

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)

    def s_mem_full():
        db = data.get("character_memory_manager", {}).get("database") or {}
        for k in ("0", "1", "2", "16777220", "16777221"):
            if k in db:
                print(f"--- key={k} ---")
                print(json.dumps(db[k], ensure_ascii=False))
        # 全部键的数值分布
        keys = [int(k) for k in db.keys()]
        print("\n键 min/max:", min(keys), max(keys))
        print("键 > 16777216 的数量:", sum(1 for k in keys if k > 16777216))
        print("键 0..10000 的数量:", sum(1 for k in keys if k < 10000))
        # 有 character/owner 字段的条目?
        has_char = sum(1 for e in db.values() if isinstance(e, dict) and ("character" in e or "owner" in e))
        print("含 character/owner 字段的条目:", has_char)

    show("记忆条目全貌", s_mem_full)

    def s_mem_types():
        db = data.get("character_memory_manager", {}).get("database") or {}
        types = Counter()
        for e in db.values():
            if isinstance(e, dict):
                types[e.get("type")] += 1
        print("全部记忆类型分布:")
        for t, c in types.most_common(60):
            print(f"  {t}: {c}")
        # 打印关键类型样本
        for want in ("became_rivals", "battle_won_memory", "battle_lost_memory",
                     "offensive_war", "defensive_war", "imprisoned", "became_nemesis",
                     "became_grudge", "lost_title_memory", "ascended_throne_memory"):
            for k, e in db.items():
                if isinstance(e, dict) and e.get("type") == want:
                    print(f"\n--- {want} key={k} ---")
                    print(json.dumps(e, ensure_ascii=False)[:600])
                    break

    show("记忆类型与样本", s_mem_types)

    def s_player_mem2():
        # 玩家参与的参与者查找: 任何参与者字段含 11368
        db = data.get("character_memory_manager", {}).get("database") or {}
        mine = []
        for k, e in db.items():
            if not isinstance(e, dict):
                continue
            s = json.dumps(e, ensure_ascii=False)
            if "11368" in s:
                mine.append((k, e))
        print(f"参与者含 11368 的记忆: {len(mine)}")
        for k, e in mine[:15]:
            print(f"--- {k} {e.get('type')} ---")
            print(json.dumps(e, ensure_ascii=False)[:400])

    show("玩家记忆(参与者检索)", s_player_mem2)

    def s_title_change():
        tv = data.get("title_and_vassal_change_manager")
        print("type:", type(tv).__name__)
        if isinstance(tv, dict):
            print("键:", list(tv.keys()))
            for k in list(tv.keys())[:3]:
                v = tv[k]
                print(f"--- {k} ---")
                print(json.dumps(v, ensure_ascii=False, indent=1)[:1000])

    show("头衔变更管理", s_title_change)

    def s_important():
        im = data.get("important_action_manager")
        print("type:", type(im).__name__)
        if isinstance(im, dict):
            print("键:", list(im.keys())[:10])
            for k in list(im.keys())[:2]:
                print(f"--- {k} ---")
                print(json.dumps(im[k], ensure_ascii=False)[:600])

    show("重要事件管理", s_important)

if __name__ == "__main__":
    main()
