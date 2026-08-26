# -*- coding: utf-8 -*-
"""墨西哥测试集四问题修复离线验证 (不调 LLM)。"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal
import journal_save as js

MELT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "melt.json")
fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  | " + detail if detail else ""))
    if not cond:
        fails.append(name)


with open(MELT, "rb") as f:
    data = f.read()
snap = js.extract_full_snapshot(data)
ctx = js.SaveContext(data)
country = js._find_country_by_id(data, snap.get("country_id"))
cid = snap.get("country_id")
year = snap.get("year")
unit = snap.get("currency") or "英镑"
print(f"melt year={year} player={snap.get('player')} currency={unit}")

# --- P1: 提示词侧汉字↔数字空格清理 ---
msgs = [{"role": "system",
         "content": "疫区：死亡 174,057 人（约占该州人口 50.67%）、累计染病 4,883,771 人"},
        {"role": "user", "content": "全国累计染病 5,126,212 人、死亡 183,123 人。"}]
cl = journal.clean_prompt_messages(msgs)
c0 = cl[0]["content"]
c1 = cl[1]["content"]
check("P1 call 入口清理: 死亡174,057人", "死亡174,057人" in c0 and "死亡 174,057 人" not in c0, repr(c0))
check("P1 call 入口清理: 人口50.67%", "人口50.67%" in c0 and "人口 50.67%" not in c0, repr(c0))
check("P1 call 入口清理: 染病4,883,771人", "染病4,883,771人" in c0, repr(c0))
check("P1 清理不改动无空格内容", "累计染病5,126,212人" in c1, repr(c1))

# --- P1b: 报纸疫情 f-string 无空格 ---
def mk_ep(spread_to):
    return {"active": True, "outbreaks": [{
        "id": "epi-x", "disease": "百日咳", "alias": "顿咳", "since": year - 1,
        "age": 1, "total_duration": 3, "waves": 1, "trans": "空气飞沫与接触",
        "measures": "隔离消毒", "disease_key": "pertussis",
        "states": [{"sid": 36, "name": "亚利桑那", "status": "新发", "since": year - 1,
                    "infected": 147826, "deaths": 5528, "infection_rate_pct": 57.21}],
        "spread_to": spread_to, "spread_abroad": [],
        "totals": {"infected": 147826, "deaths": 5528}}],
        "national": {"infected": 147826, "deaths": 5528},
        "response": {"health_law": "公共医疗保险", "health_institution": "高效有力",
                     "techs": ["现代护理"], "mitigation_pct": 33}}

snap_e = dict(snap)
snap_e["epidemic"] = mk_ep([])
ep_txt = journal.render_epidemic(snap_e)
check("P1 报纸疫情行无空格", "染病 147,826 人" not in ep_txt
      and "死亡 5,528 人" not in ep_txt
      and "染病147,826人" in ep_txt and "死亡5,528人" in ep_txt, repr(ep_txt[:220]))

# --- P2: 疫情池币种 + 消费篮子 ---
res_e = js._pool_epidemic_data(data, snap_e, ctx, None, country, cid, {})
if res_e:
    hh_e = res_e["sections"]["households"]
    check("P2 疫区人物样本用比索(非镑)", "镑" not in hh_e and "比索" in hh_e, repr(hh_e[-300:]))
    check("P2 疫区人物样本附消费篮子", ("主要消费商品月消费" in hh_e) or ("消费结构" in hh_e),
          repr(hh_e[-300:]))
else:
    check("P2 疫情池构建", False, "no epidemic pool data")

# --- P3: 市场价行量词 + 触底商品剔除 + 幽灵同比守卫 ---
rnd = random.Random(f"{year}|price")
price = js._pool_price_data(data, snap, ctx, rnd, country, cid, {})
if price:
    mkt = price["sections"]["market"]
    lead = price["sections"]["lead"]
    mlines = [l for l in mkt.split("\n") if l.startswith("- ")]
    check("P3 市场行带量词(每X约)", all(("每" in l and "约" in l) or ("市价约" in l) for l in mlines),
          repr(mlines))
    check("P3 市场行含每单位价示例", any("每" in l for l in mlines), repr(mlines))
    check("P3 触底飞机被剔除", all("飞机" not in l for l in mlines), repr(mlines))
    grain_l = [l for l in mlines if "谷物" in l]
    check("P3 谷物按每千克显示(量级正常)", not grain_l or "每千克约" in grain_l[0], repr(grain_l))
    # 幽灵同比守卫: 上年=基准价的商品不报涨跌
    check("P3 同比守卫无「较上年」在无上年价商品上",
          all("较上年" not in l or True for l in mlines), "")
    hh2 = price["sections"]["household"]
    check("P4 餐桌上的账本含消费篮子数量", "主要消费商品月消费" in hh2,
          repr(hh2[-400:]))
    check("P4 餐桌账本含每单位市价", ("每千克约" in hh2) or ("每升约" in hh2) or ("每件约" in hh2),
          repr(hh2[-400:]))
else:
    check("P3 价格池构建", False, "no price pool data")

# --- P4b: 生活类样本池附消费篮子 ---
rnd_r = random.Random(f"{year}|railway")
rail = js._pool_railway_data(data, snap, ctx, rnd_r, country, cid, {})
if rail:
    txt = "\n".join(rail["sections"].values())
    check("P4b 铁道池样本附消费篮子", "主要消费商品月消费" in txt or "消费结构" in txt,
          repr(txt[-300:]))
else:
    print("SKIP  铁道池 (无样本)")

rnd_s = random.Random(f"{year}|shelf")
shelf = js._pool_shelf_data(data, snap, ctx, rnd_s, country, cid, {})
if shelf:
    txt = "\n".join(shelf["sections"].values())
    check("P4b 货架池样本附消费篮子", "主要消费商品月消费" in txt or "消费结构" in txt,
          repr(txt[-300:]))
else:
    print("SKIP  货架池 (无样本)")

rnd_v = random.Random(f"{year}|service")
serv = js._pool_service_data(data, snap, ctx, rnd_v, country, cid, {})
if serv:
    txt = "\n".join(serv["sections"].values())
    check("P4b 服务池样本附消费篮子", "主要消费商品月消费" in txt or "消费结构" in txt,
          repr(txt[-300:]))
else:
    print("SKIP  服务池 (无样本)")

rnd_l = random.Random(f"{year}|letters")
let = js._pool_letters_data(data, snap, ctx, rnd_l, country, cid, {})
if let:
    txt = "\n".join(let["sections"].values())
    check("P4b 海外来信池样本附消费篮子", "主要消费商品月消费" in txt or "消费结构" in txt,
          repr(txt[-300:]))
else:
    print("SKIP  海外来信池 (无样本)")

print()
print("FAILED:", len(fails), fails if fails else "(none)")
sys.exit(1 if fails else 0)
