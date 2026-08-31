# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察3: 记忆条目结构、玩家记忆、死亡/仇人、履历。"""
import json, traceback

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

    def s_mem_entry():
        db = data.get("character_memory_manager", {}).get("database") or {}
        ks = list(db.keys())
        print("记忆库键数:", len(ks))
        k0 = ks[0]
        v = db[k0]
        print(f"--- 记忆条目 {k0} ---")
        print(json.dumps(v, ensure_ascii=False, indent=1)[:2000])
        # 统计 memory 的 type 字段值
        from collections import Counter
        c = Counter()
        for k in ks[:3000]:
            e = db[k]
            t = e.get("type") if isinstance(e, dict) else None
            c[t] += 1
        print("\n记忆类型分布(前3000):", c.most_common(20))

    show("记忆条目结构", s_mem_entry)

    def s_player_mem():
        db = data.get("character_memory_manager", {}).get("database") or {}
        # 找属于玩家 11368 的记忆
        mine = []
        for k, e in db.items():
            if isinstance(e, dict) and e.get("character") == 11368:
                mine.append((k, e))
        print(f"玩家 11368 的记忆条数: {len(mine)}")
        for k, e in mine[:8]:
            print(f"\n--- {k} ---")
            print(json.dumps(e, ensure_ascii=False)[:800])

    show("玩家记忆", s_player_mem)

    def s_death():
        # 死亡相关标记扫描
        blob = json.dumps(data, ensure_ascii=False)
        for s in ("killer", "murder", "death_reason", "cause_of_death",
                  "death_date", "died_of", "executed", "suicide"):
            print(f"  {s!r}: {blob.count(s)}")
        # dead_unprunable 中带 killer 的样本
        du = data.get("dead_unprunable") or {}
        found = 0
        for k, e in du.items():
            s = json.dumps(e, ensure_ascii=False)
            if "killer" in s or "murder" in s:
                print(f"\n--- 死人 {k} 含 killer/murder ---")
                print(s[:1200])
                found += 1
                if found >= 3:
                    break
        if not found:
            print("  dead_unprunable 中未见 killer/murder 字段")

    show("死亡与仇人", s_death)

    def s_secrets():
        sc = data.get("secrets")
        print("type:", type(sc).__name__)
        if isinstance(sc, dict):
            ks = list(sc.keys())
            print("键数:", len(ks), "前10:", ks[:10])
            for k in ks[:3]:
                v = sc[k]
                print(f"--- secret {k} ---")
                print(json.dumps(v, ensure_ascii=False, indent=1)[:800])

    show("秘密库", s_secrets)

    def s_landed():
        living = data.get("living") or {}
        pc = living.get("11368") or {}
        ld = pc.get("landed_data")
        print("玩家 landed_data:")
        print(json.dumps(ld, ensure_ascii=False, indent=1)[:3000])
        cd = pc.get("court_data")
        print("\n玩家 court_data:")
        print(json.dumps(cd, ensure_ascii=False, indent=1)[:1200])
        pd = pc.get("playable_data")
        print("\n玩家 playable_data:")
        print(json.dumps(pd, ensure_ascii=False, indent=1)[:1500])

    show("玩家履历", s_landed)

    def s_relations():
        for key in ("opinions", "relations", "house_relations"):
            v = data.get(key)
            print(f"\n{key}: type={type(v).__name__}")
            if isinstance(v, dict):
                ks = list(v.keys())[:5]
                print("  键数:", len(v), "前5:", ks)
                for k in ks[:2]:
                    print(f"  {k}:", json.dumps(v[k], ensure_ascii=False)[:400])

    show("关系库", s_relations)

    def s_stories():
        st = data.get("stories")
        print("type:", type(st).__name__)
        if isinstance(st, dict):
            ks = list(st.keys())[:5]
            print("键数:", len(st), "前5:", ks)
            for k in ks[:2]:
                print(f"--- story {k} ---")
                print(json.dumps(st[k], ensure_ascii=False, indent=1)[:1200])

    show("故事库", s_stories)

if __name__ == "__main__":
    main()
