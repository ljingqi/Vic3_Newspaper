# -*- coding: utf-8 -*-
"""临时检查: 疫情「无新州→尚无扩散」与州/省动态 (合成疫情数据)。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal_save as js
import journal

with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tools", "melt.json"), "rb") as f:
    data = f.read()
snap = js.extract_full_snapshot(data)
ctx = js.SaveContext(data)
country = js._find_country_by_id(data, snap.get("country_id"))


def mk(spread_to):
    return {
        "active": True,
        "outbreaks": [{
            "id": "epi-x", "disease": "猩红热", "alias": "烂喉痧", "since": 1875,
            "age": 1, "total_duration": 3, "waves": 1, "trans": "空气飞沫与接触",
            "measures": "隔离消毒", "disease_key": "scarlet_fever",
            "states": [{"sid": 1, "name": "韦拉克鲁斯", "status": "新发", "since": 1875,
                        "infected": 1000, "deaths": 50, "infection_rate_pct": 1.2}],
            "spread_to": spread_to, "spread_abroad": [],
        }],
        "national": {"infected": 1000, "deaths": 50},
        "response": {"health_law": "公共医疗保险", "health_institution": "全面铺开",
                     "techs": ["现代护理"], "mitigation_pct": 33},
    }


for st in ([], ["瓦哈卡"]):
    snap2 = dict(snap)
    snap2["epidemic"] = mk(st)
    res = js._pool_epidemic_data(data, snap2, ctx, None, country,
                                 snap.get("country_id"), {})
    hh = res["sections"]["households"]
    line = [l for l in hh.split("\n") if "本年疫情新传至" in l]
    print("spread_to=%s -> %s" % (st or "[]", line[0] if line else "MISSING"))
    out = res["sections"]["outbreak"]
    print("    outbreak:", [l for l in out.split("\n") if "波及" in l][0])
    print("    state row:", [l for l in out.split("\n") if "人口" in l][0])

print("--- newspaper ---")
snap3 = dict(snap)
snap3["epidemic"] = mk([])
print(journal.render_epidemic(snap3))
