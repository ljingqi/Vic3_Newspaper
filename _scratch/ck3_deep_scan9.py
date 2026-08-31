# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察9: 玩家传记素材汇总。"""
import json

MELT = r"D:\Journal\_scratch\ck3_melt.json"
PID = 11368

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    living = data.get("living") or {}
    du = data.get("dead_unprunable") or {}
    db = data.get("character_memory_manager", {}).get("database") or {}

    tl = data.get("traits_lookup") or []
    print("traits_lookup 长度:", len(tl))
    pc = living.get(str(PID)) or {}
    for t in pc.get("traits") or []:
        key = tl[t] if t < len(tl) else "?"
        print(f"  trait {t}: {key}")

    cm = (data.get("culture_manager") or {}).get("cultures") or {}
    c47 = cm.get("47") or {}
    print("\nculture 47:", json.dumps(c47, ensure_ascii=False)[:200])
    rel = (data.get("religion") or {}).get("faiths") or {}
    if isinstance(rel, dict):
        f41 = rel.get("41")
        print("faith 41:", json.dumps(f41, ensure_ascii=False)[:200])

    # 前妻 13386
    print("\n--- 前妻 13386 ---")
    c = living.get("13386") or du.get("13386")
    if c:
        print(json.dumps(c, ensure_ascii=False)[:600])
    else:
        print("  不在 living/dead_unprunable")
        dp = (data.get("characters") or {}).get("dead_prunable") or {}
        c2 = dp.get("13386")
        if c2:
            print("  在 dead_prunable:", json.dumps(c2, ensure_ascii=False)[:600])

    # 现任妻子 39250 记忆 & 死亡相关
    print("\n--- 现任妻子 39250 记忆 ---")
    print(json.dumps(db.get("39250"), ensure_ascii=False)[:400])

    # 子女
    print("\n--- 玩家子女 ---")
    for cid in ("13136", "13251", "13252", "13530"):
        c = living.get(cid)
        if not c:
            print(f"  {cid}: 不在 living")
            continue
        nm = c.get("first_name")
        birth = c.get("birth")
        fam = c.get("family_data") or {}
        print(f"  {cid}: name={nm} birth={birth} spouse={fam.get('primary_spouse')}")

    # 玩家父亲/母亲
    print("\n玩家 family 全量:", json.dumps(pc.get("family_data"), ensure_ascii=False))

    # 玩家的 k_shannan 头衔历史
    lt = (data.get("landed_titles") or {}).get("landed_titles") or {}
    t14906 = lt.get("14906") or {}
    print("\nk_shannan(14906):")
    print("  key:", t14906.get("key"))
    print("  holder:", t14906.get("holder"), "date:", t14906.get("date"))
    print("  history:", json.dumps(t14906.get("history"), ensure_ascii=False))
    print("  capital:", t14906.get("capital"))
    print("  title_name_data:", json.dumps(t14906.get("title_name_data"), ensure_ascii=False)[:300])
    # 头衔名的 localizations: 查找 k_shannan 本地化
    print("  name keys:", [k for k in t14906.keys() if 'name' in k])

    # 玩家 realm 的 vassal 列表 (vassal_contracts)
    vc = pc.get("landed_data", {}).get("vassal_contracts") or []
    print("\nvassal_contracts:", vc[:6])

if __name__ == "__main__":
    main()
