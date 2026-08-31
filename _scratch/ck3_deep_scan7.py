# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察7: 记忆键编码验证、多记忆格式、头衔名、省份名、diarchy。"""
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
    living = data.get("living") or {}
    du = data.get("dead_unprunable") or {}
    dp = (data.get("characters") or {}).get("dead_prunable") or {}
    allchars = {**living, **du, **dp}
    db = data.get("character_memory_manager", {}).get("database") or {}

    def s_encoding():
        ok_low = ok_high = tot_low = tot_high = 0
        for k in db.keys():
            try:
                ki = int(k)
            except ValueError:
                continue
            if ki < 0x1000000:
                tot_low += 1
                if k in allchars:
                    ok_low += 1
            else:
                tot_high += 1
                if str(ki & 0xFFFFFF) in allchars:
                    ok_high += 1
        print(f"键 < 0x1000000: {tot_low} 个, 其中是角色ID: {ok_low}")
        print(f"键 >= 0x1000000: {tot_high} 个, 其中 (键&0xFFFFFF) 是角色ID: {ok_high}")
        # 9363 / 11368 归属
        for k in ("9363", "11368", "4", "738"):
            print(f"  key={k}: living={k in living} dead_unprunable={k in du} dead_prunable={k in dp}")

    show("记忆键编码验证", s_encoding)

    def s_multimem():
        # 找值是 list 的键
        nlist = sum(1 for v in db.values() if isinstance(v, list))
        ndict = sum(1 for v in db.values() if isinstance(v, dict))
        print(f"记忆条目: list 值 {nlist}, dict 值 {ndict}")
        for k, v in db.items():
            if isinstance(v, list) and v:
                print(f"\n--- key={k} 是 list, 长度 {len(v)} ---")
                for m in v[:5]:
                    print("  ", json.dumps(m, ensure_ascii=False)[:280])
                break

    show("多记忆格式", s_multimem)

    def s_titles2():
        lt = (data.get("landed_titles") or {}).get("landed_titles") or {}
        print("landed_titles.landed_titles 键数:", len(lt))
        for tid in ("14906", "14907", "14908", "14909", "14910", "14911", "16108", "17459", "2101", "5790"):
            v = lt.get(tid)
            if v is None:
                print(f"  {tid}: 无")
                continue
            s = json.dumps(v, ensure_ascii=False)
            print(f"  {tid}: {s[:400]}")

    show("头衔(二级)", s_titles2)

    def s_prov():
        prov = data.get("provinces") or {}
        for pid in ("14909", "1593", "8745", "2633", "2638", "8203"):
            v = prov.get(pid)
            if v is not None:
                print(f"  province {pid}:", json.dumps(v, ensure_ascii=False)[:200])

    show("省份", s_prov)

    def s_war_names():
        wn = (data.get("wars") or {}).get("names") or {}
        print("wars.names:", json.dumps(wn, ensure_ascii=False)[:800])

    show("战争名", s_war_names)

    def s_diarchy():
        d = data.get("diarchies")
        print("type:", type(d).__name__)
        if isinstance(d, dict):
            ks = list(d.keys())[:8]
            print("键数:", len(d), "前8:", ks)
            v = d.get("50331829")
            if v is not None:
                print("diarchy 50331829:", json.dumps(v, ensure_ascii=False)[:1200])

    show("Diarchy", s_diarchy)

    def s_player_full_keys():
        pc = living.get("11368") or {}
        print("玩家字段全列表:")
        for k, v in pc.items():
            s = json.dumps(v, ensure_ascii=False)
            print(f"  {k}: {s[:180]}")

    show("玩家全字段", s_player_full_keys)

if __name__ == "__main__":
    main()
