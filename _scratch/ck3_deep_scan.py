# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察: 人物对象字段、玩家角色、记忆、战争、死亡。"""
import json

MELT = r"D:\Journal\_scratch\ck3_melt.json"

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)

    print("=== living: type/规模 ===")
    living = data.get("living")
    print("  type:", type(living).__name__)
    if isinstance(living, dict):
        keys = list(living.keys())
        print("  键数:", len(keys), "前20:", keys[:20])

    print("\n=== played_character / currently_played_characters ===")
    print("  played_character:", data.get("played_character"))
    print("  currently_played_characters:", data.get("currently_played_characters"))

    print("\n=== character_lookup ===")
    cl = data.get("character_lookup")
    print("  type:", type(cl).__name__)
    if isinstance(cl, dict):
        keys = list(cl.keys())[:20]
        print("  键数:", len(cl), "前20:", keys)
        k0 = list(cl.keys())[0]
        print(f"  样本 {k0}:", json.dumps(cl[k0], ensure_ascii=False)[:300])

    # 取一个活人样本: 玩家角色
    pid = None
    try:
        pid = data.get("currently_played_characters") or data.get("played_character")
        if isinstance(pid, list):
            pid = pid[0]
    except Exception:
        pid = None
    print("\n=== 玩家角色 id:", pid, "===")

    # living 可能是 {id: obj} 或 manager
    sample_char = None
    sample_id = None
    if isinstance(living, dict):
        if pid is not None and str(pid) in living:
            sample_id, sample_char = str(pid), living[str(pid)]
        elif keys:
            sample_id = keys[0]
            sample_char = living[sample_id]
    if sample_char is not None:
        print(f"--- 活人样本 id={sample_id} 字段 ---")
        print(json.dumps(sample_char, ensure_ascii=False, indent=1)[:6000])

    # 死人样本 (dead_unprunable / dead_prunable)
    for db_key in ("dead_unprunable", "dead_prunable"):
        db = data.get("characters", {}).get(db_key) if isinstance(data.get("characters"), dict) else None
        if not db:
            db = data.get(db_key)
        if isinstance(db, dict) and db:
            k0 = list(db.keys())[0]
            print(f"\n=== 死人样本 characters.{db_key} id={k0} ===")
            print(json.dumps(db[k0], ensure_ascii=False, indent=1)[:3000])

    print("\n=== character_memory_manager ===")
    cmm = data.get("character_memory_manager")
    print("  type:", type(cmm).__name__)
    if isinstance(cmm, dict):
        print("  键:", list(cmm.keys())[:10])
        for k in list(cmm.keys())[:2]:
            v = cmm[k]
            print(f"  {k}: {type(v).__name__}", (list(v.keys())[:10] if isinstance(v, dict) else str(v)[:200]))

    print("\n=== wars.active_wars 样本 ===")
    aw = data.get("wars", {}).get("active_wars") or {}
    k0 = list(aw.keys())[0] if aw else None
    if k0:
        print(f"--- war id={k0} ---")
        print(json.dumps(aw[k0], ensure_ascii=False, indent=1)[:4000])

    print("\n=== combats 样本 ===")
    cmb = data.get("combats")
    print("  type:", type(cmb).__name__)
    if isinstance(cmb, dict):
        print("  键数:", len(cmb), "前10:", list(cmb.keys())[:10])
        k0 = list(cmb.keys())[0]
        print(f"--- combat id={k0} ---")
        print(json.dumps(cmb[k0], ensure_ascii=False, indent=1)[:2500])

if __name__ == "__main__":
    main()
