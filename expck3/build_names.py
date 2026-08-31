# -*- coding: utf-8 -*-
"""构建全量角色名本地化映射表 → expck3/data/names.json

结构: {"schema": 1, "source": "869.2.22", "names": {"<角色id>": {"first_name": "...", "name_zh": "..."}}}
用途: 传记/其它输出查名时兜底 (缓存只收录主角相关人物, 此表覆盖全档)。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl

HERE = os.path.dirname(os.path.abspath(__file__))
MELT = os.path.join(HERE, "data", "melt_869_02_22.json")
OUT = os.path.join(HERE, "data", "names.json")

def main():
    melt = cl.load_melt(MELT)
    chars = cl.all_characters(melt)
    names = {}
    for cid, c in chars.items():
        fn = c.get("first_name")
        if not fn:
            continue
        names[cid] = {
            "first_name": fn,
            "name_zh": cl.name_zh(c),
        }
    out = {
        "schema": 1,
        "source": melt.get("date"),
        "total": len(names),
        "names": names,
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    print(f"已生成 {OUT}: {len(names)} 个角色")
    for cid in ("11368", "10692", "13386", "39250", "11004", "43741", "38315"):
        print(f"  {cid}: {names.get(cid)}")

if __name__ == "__main__":
    main()
