# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察5: 验证记忆库按键=角色ID, 玩家一生数据汇总。"""
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
    db = data.get("character_memory_manager", {}).get("database") or {}
    living = data.get("living") or {}

    def s_key():
        print("key=11368 存在:", "11368" in db)
        if "11368" in db:
            mems = db["11368"]
            print("类型:", type(mems).__name__)
            if isinstance(mems, list):
                print("记忆条数:", len(mems))
                for m in mems[:12]:
                    print(" ", json.dumps(m, ensure_ascii=False)[:300])
            elif isinstance(mems, dict):
                print("子键:", list(mems.keys())[:10])
                print(json.dumps(mems, ensure_ascii=False)[:1500])

    show("key=11368 记忆", s_key)

    def s_chars():
        for cid in ("9363", "11763", "13386", "39250", "13530"):
            print(f"\n--- 角色 {cid} ---")
            c = living.get(cid)
            if not c:
                print("  不在 living 中")
                continue
            print("  字段:", list(c.keys()))
            print("  first_name:", c.get("first_name"))
            print("  birth:", c.get("birth"))
            print("  dynasty_house:", c.get("dynasty_house"))
            print("  family_data:", json.dumps(c.get("family_data"), ensure_ascii=False)[:200])
            if "11368" in db:
                pass
            # 该角色自己的记忆
            if cid in db:
                mems = db[cid]
                cnt = len(mems) if isinstance(mems, list) else 1
                print(f"  记忆条数(key={cid}): {cnt}")
                if isinstance(mems, list):
                    for m in mems[:6]:
                        print("   ", json.dumps(m, ensure_ascii=False)[:220])

    show("周边角色", s_chars)

    def s_all_key_types():
        # 全库键类型统计
        import re
        keys = list(db.keys())
        print("记忆库键数:", len(keys))
        in_living = sum(1 for k in keys if k in living)
        print("键同时是 living 角色的:", in_living)
        du = data.get("dead_unprunable") or {}
        in_dead = sum(1 for k in keys if k in du)
        print("键同时在 dead_unprunable 的:", in_dead)
        # 玩家的记忆条目数
        mems = db.get("11368")
        print("\n玩家 11368 记忆:", json.dumps(mems, ensure_ascii=False)[:2500] if mems else None)

    show("记忆库键归属", s_all_key_types)

if __name__ == "__main__":
    main()
