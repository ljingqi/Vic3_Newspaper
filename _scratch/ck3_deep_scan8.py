# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察8: 名称解析路径 (traits/culture/faith/dynasty)。"""
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

    def s_traits():
        tl = data.get("traits_lookup")
        print("type:", type(tl).__name__)
        if isinstance(tl, dict):
            ks = list(tl.keys())[:15]
            print("键数:", len(ks), "前15:", ks)
            # 玩家 traits 74,58,81,22,40,285
            for t in ("74", "58", "81", "22", "40", "285"):
                print(f"  trait {t}:", tl.get(t))

    show("traits_lookup", s_traits)

    def s_dyn():
        dh = (data.get("dynasties") or {}).get("dynasty_house") or {}
        for hid in ("5756", "3874", "9387"):
            v = dh.get(hid)
            if v is not None:
                print(f"house {hid}:", json.dumps(v, ensure_ascii=False)[:400])
        dyn = (data.get("dynasties") or {}).get("dynasties") or {}
        d0 = list(dyn.keys())[0]
        print(f"dynasty 样本 {d0}:", json.dumps(dyn[d0], ensure_ascii=False)[:300])

    show("dynasty_house", s_dyn)

    def s_culture_faith():
        blob = json.dumps(data, ensure_ascii=False)
        for s in ("culture_lookup", "faith_lookup", "culture_manager", "\"cultures\"", "\"faiths\""):
            print(f"  {s!r}: {blob.count(s)}")
        cm = data.get("culture_manager")
        print("culture_manager:", type(cm).__name__)
        if isinstance(cm, dict):
            print("  键:", list(cm.keys())[:10])
            for k in list(cm.keys())[:2]:
                v = cm[k]
                print(f"  {k}:", json.dumps(v, ensure_ascii=False)[:400])
        rel = data.get("religion")
        print("religion:", type(rel).__name__)
        if isinstance(rel, dict):
            print("  键:", list(rel.keys())[:10])

    show("culture/faith 解析", s_culture_faith)

    def s_prov_title_map():
        # 省份→领地: 通过 landed_titles.capital / holdings 关联
        lt = (data.get("landed_titles") or {}).get("landed_titles") or {}
        # 襄阳 title 14908 → capital barony 14909 → 省份? 看看 county_manager
        cm = data.get("county_manager")
        print("county_manager:", type(cm).__name__)
        if isinstance(cm, dict):
            ks = list(cm.keys())[:8]
            print("  键数:", len(cm), "前8:", ks)
            k0 = ks[0]
            print("  样本:", json.dumps(cm[k0], ensure_ascii=False)[:500])

    show("省份-领地映射", s_prov_title_map)

    def s_important2():
        im = data.get("important_action_manager") or {}
        act = im.get("active") or {}
        print("important actions:", len(act))
        for k, v in act.items():
            if isinstance(v, dict) and v.get("character") == 11368:
                print(f"  {k}: {v.get('important_action_type')}")

    show("玩家重要行动", s_important2)

if __name__ == "__main__":
    main()
