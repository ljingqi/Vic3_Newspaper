# -*- coding: utf-8 -*-
"""墨西哥测试集修复综合离线断言 (不调 LLM)。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import journal
import journal_save as js
import style
import magazine

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
unit = snap.get("currency") or "英镑"

# --- 1. 槽位: 墨西哥无消费税, 有人头税 ---
fi = snap.get("family_interview") or {}
br = fi.get("budget_rates") or {}
check("1 家庭消费税率=0 (墨西哥 taxed_goods 为空)",
      br.get("consumption_tax", -1) == 0, f"consumption_tax={br.get('consumption_tax')}")
check("1 家庭人头税率>0", (br.get("poll_tax") or 0) > 0, f"poll_tax={br.get('poll_tax')}")

# --- 2. 刊名派生 + voice 无刊名句 ---
data2 = dict(snap)
data2["tech_keys"] = snap.get("tech_keys") or []
name = style.derive_magazine_name(data2)
check("2 刊名程序化派生", isinstance(name, str) and name, f"name={name}")
voice = style.resolve_magazine_voice(data2)
check("2 voice 不含刊名句", "刊名" not in voice)
msgs = magazine.build_intro_messages(data2)
check("2 导言提示词含【刊名】固定变量", f"《{name}》" in msgs[0]["content"])
check("2 导言不再请模型拟名", "拟定刊名" not in msgs[0]["content"])

# --- 3. 餐桌上的账本含家庭分项账本 ---
rnd = __import__("random").Random("1878|price")
price = js._pool_price_data(data, snap, ctx, rnd, country, cid, {})
if price:
    hh = price["sections"]["household"]
    check("3 餐桌账本含家庭月收入分项", "家庭月收入" in hh and "工资约" in hh)
    check("3 餐桌账本含家庭月支出分项", "家庭月支出" in hh and "商品消费约" in hh)
    check("3 餐桌账本含月度结余", "月度结余" in hh)
else:
    check("3 餐桌账本构建", False, "price data unavailable")

# --- 4. 都城若缺失条件化 ---
m1 = journal.build_masthead_messages({"player": "墨西哥", "capital": "墨西哥城",
                                      "govt": "presidential_republic",
                                      "govt_law": "law_presidential_republic",
                                      "year": 1878}, style=1)
txt = m1[0]["content"] + m1[1]["content"]
check("4 都城存在时不出现补填指引", "都城数据缺失" not in txt and "都城若缺失" not in txt)
m2 = journal.build_masthead_messages({"player": "墨西哥", "capital": "",
                                      "govt": "presidential_republic",
                                      "govt_law": "law_presidential_republic",
                                      "year": 1878}, style=1)
txt2 = m2[0]["content"] + m2[1]["content"]
check("4 都城缺失时出现补填指引", "都城数据缺失" in txt2)

# --- 5. 疫情: 尚无扩散 + 州/省动态 ---
def mk_ep(spread_to):
    return {"active": True, "outbreaks": [{
        "id": "epi-x", "disease": "猩红热", "alias": "烂喉痧", "since": 1875,
        "age": 1, "total_duration": 3, "waves": 1, "trans": "空气飞沫与接触",
        "measures": "隔离消毒", "disease_key": "scarlet_fever",
        "states": [{"sid": 36, "name": "韦拉克鲁斯", "status": "新发", "since": 1875,
                    "infected": 1000, "deaths": 50, "infection_rate_pct": 1.2}],
        "spread_to": spread_to, "spread_abroad": []}],
        "national": {"infected": 1000, "deaths": 50},
        "response": {"health_law": "公共医疗保险", "health_institution": "全面铺开",
                     "techs": ["现代护理"], "mitigation_pct": 33}}

snap_e = dict(snap)
snap_e["epidemic"] = mk_ep([])
res_e = js._pool_epidemic_data(data, snap_e, ctx, None, country, cid, {})
hh_e = res_e["sections"]["households"]
check("5 无新传染州写「尚无扩散」", "本年疫情尚无扩散" in hh_e)
check("5 无新传染州不再写「无新州」", "无新州" not in hh_e)
snap_e2 = dict(snap)
snap_e2["epidemic"] = mk_ep(["瓦哈卡"])
res_e2 = js._pool_epidemic_data(data, snap_e2, ctx, None, country, cid, {})
check("5 有新传染州照列州名", "本年疫情新传至：瓦哈卡" in res_e2["sections"]["households"])
snap_mon = dict(snap)
snap_mon["epidemic"] = mk_ep([])
snap_mon["govt"] = "gov_absolute_monarchy"
res_mon = js._pool_epidemic_data(data, snap_mon, ctx, None, country, cid, {})
check("5 君主国疫情用「省」", "该省人口" in res_mon["sections"]["households"])
check("5 专家国疫情用「州」", "该州人口" in hh_e)
snap_e3 = dict(snap)
snap_e3["epidemic"] = mk_ep([])
ep_txt = journal.render_epidemic(snap_e3)
check("5 报纸疫情专电无硬编码州 (动态)", "个州" in ep_txt or "个省" in ep_txt)

# --- 6. 按病种缓解科技 ---
law = "law_public_health_insurance"
techs = ["modern_sewerage", "modern_nursing", "quinine", "pharmaceuticals"]
m, mi, ts_sf = js._epidemic_mitigation_bits(law, 5, techs, 46, disease_key="scarlet_fever")
check("6 猩红热不含奎宁", "quinine" not in ts_sf, f"techs={ts_sf}")
m, mi, ts_ml = js._epidemic_mitigation_bits(law, 5, techs, 46, disease_key="malaria")
check("6 疟疾含奎宁", "quinine" in ts_ml, f"techs={ts_ml}")
m, mi, ts_ch = js._epidemic_mitigation_bits(law, 5, techs, 46, disease_key="cholera")
check("6 霍乱含下水道", "modern_sewerage" in ts_ch, f"techs={ts_ch}")

# --- 7. 国家机构投入点出具体法律 ---
rnd7 = __import__("random").Random("1878|service")
ser = js._pool_service_data(data, snap, ctx, rnd7, country, cid, {})
lead7 = ser["sections"]["lead"]
check("7 内务法律为秘密警察", "内务法律为秘密警察" in lead7)
check("7 教育法律为公立学校", "教育法律为公立学校" in lead7)
check("7 警务法律点出", "警务法律为专职警察" in lead7)

# --- 8. 生产方式无XX剔除 ---
ABSENT_ZH = ("无冷藏", "无飞艇", "无灯街道", "无效果", "无飞机生产", "无坦克生产")
pm_names = js._pm_names_zh(["pm_trawler_fishing", "pm_unrefrigerated"], drop_raw=True)
check("8 _pm_names_zh 剔除无冷藏", pm_names is None or not any(
    n in ABSENT_ZH for n in pm_names), f"names={pm_names}")
by_state, btype_map, objs = ctx.buildings_index(
    [s.get("id") for s in (snap.get("states") or []) if s.get("id") is not None])
loc = js._load_loc_all()
found_bad = 0
for b, o in objs.items():
    txt = js._pool_building_text(data, ctx, cid, b, o, loc,
                                 js.build_goods_map(), pops=None)
    m = re.search(r"采用([^。]*?)。", txt)
    if m and any(a in m.group(1) for a in ABSENT_ZH):
        found_bad += 1
check("8 杂志池建筑文本无否定态生产方式", found_bad == 0, f"bad={found_bad}")

# --- 补充3: 一党制触发投票文章 ---
elig = js._magazine_pool_eligibility(data, snap, ctx, country)
check("补充3 一党制国家投票文章入池", elig.get("voting") is True)
rnd9 = __import__("random").Random("1878|voting")
vot = js._pool_voting_data(data, snap, ctx, rnd9, country, cid, {})
lead9 = vot["sections"]["lead"]
check("补充3 一党制选举规则文案", "参选政党仅执政党一家" in lead9)
ok, reason = js._pool_vote_verdict({"type": "laborers", "acceptance_data": {
    "acceptance_status": "full_citizenship"}}, "law_single_party_state",
    "law_national_supremacy")
check("补充3 一党制未被歧视者有投票权", ok, reason)

print()
print("FAILED:", len(fails), fails if fails else "(none)")
sys.exit(1 if fails else 0)
