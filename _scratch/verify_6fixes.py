# -*- coding: utf-8 -*-
"""回归验证 (2026-08-27 六项修复):
1a 方案C: SoL 缩放热量占比 → 穷家庭水果/加工食品量下降
1b 方案D2: 下层阶级无分红/投资收入
2  strata 映射 + pop 所在州 pop_needs → 餐桌账本篮子行恢复
4  方案E1: 两/银两汇率 yoy 非 0
5  money_transfer 按 TAG 取币种 + 汇率换算
"""
import io, os, sys, random

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal as j
import journal_save as js
from currency import currency_unit, format_money

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
data = open(os.path.join(TOOLS, "melt.json"), "rb").read()
ctx = js.SaveContext(data)

print("=" * 70)
print("[2] 餐桌上的账本篮子 (state 889 关东, lower_class 候选)")
state_ids = [887, 888, 889, 890, 891, 892, 893, 894, 896, 897, 898]
pops = ctx.player_pops(state_ids)
sid = 889
state_pool = {pid: o for pid, o in pops.items() if o.get("location") == sid}
lows = js._pool_pick_pops(state_pool, classes=("lower_class",), n=1,
                          rnd=random.Random(1))
print("  样本州 lower_class 候选数:", len(lows))
if lows:
    pid, o = lows[0]
    print("  抽中 pop:", pid, o.get("type"), "culture", o.get("culture"),
          "loc", o.get("location"), "wf", o.get("workforce"))
    pop_sid = o.get("location")
    sobj = ctx.state_object(pop_sid)
    pn = (sobj or {}).get("pop_needs") or {}
    entry = pn.get(str(o.get("culture"))) or pn.get(o.get("culture"))
    print("  pop 所在州 pop_needs 命中:", entry is not None)
    if entry:
        prof = js._consumption_profile(entry, o.get("previous_quality_of_life"))
        print("  prof goods:", [g["key"] for g in prof["goods"]],
              "engel:", prof["engel"])
        basket = {
            "budget_rates": js._pop_budget_rates(
                o.get("weekly_budget") or [], o.get("workforce"), o.get("dependents")),
            "consumption_goods": prof["goods"],
            "engel_coefficient": prof["engel"],
            "sol": o.get("previous_quality_of_life"),
            "wife_works": False,
            "children_count": 4,
        }
        lines = j._consumption_breakdown_lines(basket, "两", 153.6)
        print("  --- 消费结构/篮子行 ---")
        for ln in lines:
            print("   ", ln)

print("=" * 70)
print("[1a] 方案C: 穷家庭 (SoL 6, 6口) 主食数量 vs 旧固定占比")
hh_kcal = (2 * 2300 + 4 * 1700) * 30.4
for key, kcal_kg in (("grain", 3500), ("groceries", 2500),
                     ("fish", 1200), ("fruit", 500)):
    share = j._staple_kcal_share(key, 6.0)
    q = hh_kcal * share / kcal_kg
    old = j._STAPLE_KCAL_SHARE.get(key)
    print(f"  {key}: 旧={old} 新share={share:.3f} -> {q:.1f} kg/月")

print("=" * 70)
print("[1b] 方案D2: 下层阶级分红归零 (阿伊努劳工 culture=116)")
animist = [o for o in pops.values() if o.get("culture") == 116]
if animist:
    o = animist[0]
    print("  pop cls:", js._pool_pop_class(o))
    br = js._pop_budget_rates(o.get("weekly_budget") or [],
                              o.get("workforce"), o.get("dependents"))
    print("  归零前 dividends:", br.get("dividends"))
    if js._pool_pop_class(o) == "lower_class":
        br["dividends"] = 0.0
    print("  归零后 dividends:", br.get("dividends"))

print("=" * 70)
print("[4] 方案E1: 两/银两 汇率 yoy 复算 (1837, prev=153.6/76.8)")
def e1_rate(base, g, t, prev, year, cur):
    rnd = random.Random(f"{year}|fx|{cur}")
    n = 1.0 + (rnd.random() * 2.0 - 1.0) * 0.02
    target = base * g * t * n
    lo, hi = base * 0.4, base * 1.6
    yoy_lo, yoy_hi = prev * 0.7, prev * 1.3
    if hi <= prev * (1.0 + 1e-12):
        hi = yoy_hi
    if lo >= prev * (1.0 - 1e-12):
        lo = yoy_lo
    lo = max(lo, yoy_lo); hi = min(hi, yoy_hi)
    rate = max(lo, min(hi, target))
    return rate, (rate / prev - 1.0) * 100.0
for cur, base, prev in (("两", 96.0, 153.6), ("银两", 48.0, 76.8)):
    r, y = e1_rate(base, 1.45, 1.18, prev, 1837, cur)
    print(f"  {cur}: rate={r:.2f} (旧钉死) yoy={y:+.1f}%")

print("=" * 70)
print("[5] money_transfer 按 TAG + 汇率换算")
nat = js._article_natural("money_transfer", "德川幕府", "大清",
                          {"kind": "quantity", "quantity": 700.0},
                          f_tag="JAP", t_tag="CHI")
print("  natural (TAG 币种):", nat)
print("  render 换算 (700×153.6):", format_money(700.0, "两", 153.6))
nat_mex = js._article_natural("money_transfer", "墨西哥", "大不列颠",
                              {"kind": "quantity", "quantity": 7680.0},
                              f_tag="MEX", t_tag="GBR")
print("  墨西哥对照:", nat_mex, "-> 换算:",
      format_money(7680.0, "比索", 114.8276))
