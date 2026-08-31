# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察2: 死人与记忆与战争 (逐段 try/except)。"""
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

    def s_dead():
        # 死人库: 顶层 characters 下? 还是顶层? 检查各候选
        for key in ("dead_unprunable", "dead_prunable"):
            v = data.get(key)
            print(f"顶层 {key}: {type(v).__name__}", end=" ")
            if isinstance(v, dict):
                print(f"键数={len(v)} 前5={list(v.keys())[:5]}")
            else:
                print()
        ch = data.get("characters") or {}
        print("characters 键:", list(ch.keys()))
        for key in ("dead_unprunable", "dead_prunable", "natural_deaths"):
            v = ch.get(key)
            print(f"characters.{key}: {type(v).__name__}", end=" ")
            if isinstance(v, dict):
                print(f"键数={len(v)} 前3={list(v.keys())[:3]}")
            else:
                print()
        # 死人样本
        du = data.get("dead_unprunable") or ch.get("dead_unprunable") or {}
        if isinstance(du, dict) and du:
            k0 = list(du.keys())[0]
            print(f"\n--- dead_unprunable 样本 id={k0} ---")
            print(json.dumps(du[k0], ensure_ascii=False, indent=1)[:4000])

    show("死人库", s_dead)

    def s_mem():
        cmm = data.get("character_memory_manager")
        print("type:", type(cmm).__name__)
        if isinstance(cmm, dict):
            ks = list(cmm.keys())
            print("键数:", len(ks), "前10:", ks[:10])
            for k in ks[:3]:
                v = cmm[k]
                if isinstance(v, dict):
                    sub = list(v.keys())[:8]
                    print(f"  {k}: dict 子键({len(v)}) 前8: {sub}")
                else:
                    print(f"  {k}: {type(v).__name__} {str(v)[:150]}")
        # 玩家角色对象里是否有 memories?
        living = data.get("living") or {}
        pc = living.get("11368") or {}
        print("\n玩家 11368 字段:", list(pc.keys()))
        for f in ("memories", "memory_manager", "historical"):
            if f in pc:
                print(f"  {f}:", json.dumps(pc[f], ensure_ascii=False)[:1500])

    show("记忆", s_mem)

    def s_wars():
        aw = data.get("wars", {}).get("active_wars") or {}
        print("active_wars 数:", len(aw))
        k0 = list(aw.keys())[0]
        print(f"--- war id={k0} ---")
        print(json.dumps(aw[k0], ensure_ascii=False, indent=1)[:3500])

    show("战争", s_wars)

    def s_combats():
        cmb = data.get("combats")
        print("type:", type(cmb).__name__)
        if isinstance(cmb, dict):
            print("键数:", len(cmb), "前10:", list(cmb.keys())[:10])
            k0 = list(cmb.keys())[0]
            print(f"--- combat id={k0} ---")
            print(json.dumps(cmb[k0], ensure_ascii=False, indent=1)[:2500])

    show("战斗", s_combats)

    def s_sieges():
        sg = data.get("sieges")
        print("type:", type(sg).__name__)
        if isinstance(sg, dict):
            print("键数:", len(sg))
            k0 = list(sg.keys())[0]
            print(f"--- siege id={k0} ---")
            print(json.dumps(sg[k0], ensure_ascii=False, indent=1)[:1500])

    show("围城", s_sieges)

if __name__ == "__main__":
    main()
