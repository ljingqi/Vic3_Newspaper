# -*- coding: utf-8 -*-
"""验证本次 14 项修改的关键函数 (实样: 当前 melt.json + 1878 快照)。"""
import io
import sys
import json

sys.path.insert(0, r'D:\Journal')
import journal as J
import journal_save as JS
import style as S
import magazine as M

ok = []
fail = []

def check(name, cond, extra=""):
    if cond:
        ok.append(name)
    else:
        fail.append(f"{name} {extra}")

# ---------- P8: clean_number_spaces ----------
s = J.clean_number_spaces("第三街 7 号，第 18 个年头，约 25.8%，共 5 名 工人")
# 只清数字↔汉字边界; 「名 工人」是汉字↔汉字空格, 不在本项范围
check("P8 clean_number_spaces", s == "第三街7号，第18个年头，约25.8%，共5名 工人", repr(s))
check("P8 不破坏纯数字", J.clean_number_spaces("1234 5678") == "1234 5678")

# ---------- P14: 日期 ----------
check("P14 fmt_cn_date 3段", J.fmt_cn_date("1861.4.11") == "1861年4月11日")
check("P14 fmt_cn_date 4段(带时刻)", J.fmt_cn_date("1861.7.15.6") == "1861年7月15日")
check("P14 fmt_cn_date 1.1.1", J.fmt_cn_date("1.1.1") == "未知")
check("P14 mag _fmt_date", M._fmt_date("1861.7.15.6") == "1861年7月15日")
check("P14 mag _fmt_date 未知", M._fmt_date("1.1.1") == "未知")
check("P14 mag _fmt_date 空", M._fmt_date(None) == "未知")

# ---------- P3: totalitarian_flavor ----------
check("P3 falangist->corporatist",
      S.totalitarian_flavor({"govt_key": "gov_falangist_state"}) == "corporatist")
check("P3 soviet->communist",
      S.totalitarian_flavor({"govt_key": "gov_soviet_dictatorship"}) == "communist")
check("P3 council_single->communist",
      S.totalitarian_flavor({"govt_key": "gov_council_single_party_state"}) == "communist")
check("P3 technocracy->generic",
      S.totalitarian_flavor({"govt_key": "gov_technocracy"}) == "generic")
check("P3 旧字段 govt 兜底",
      S.totalitarian_flavor({"govt": "gov_falangist_state"}) == "corporatist")

# ---------- 载入真实 melt (当前 1882 存档) ----------
print("loading melt...", flush=True)
with io.open(r'D:\Journal\tools\melt.json', 'rb') as fh:
    melted = fh.read()
print("melt loaded:", len(melted), flush=True)

# ---------- P11: 党派解析 ----------
tmap = JS._party_template_map(melted)
check("P11 党派映射非空", len(tmap) > 0, f"len={len(tmap)}")
# 墨西哥 country_id=185, party 1332 -> 块内索引0 -> agrarian_party -> 农业党
pid1332 = tmap.get(1332)
check("P11 party 1332 -> agrarian_party", pid1332 == "agrarian_party", repr(pid1332))
loc = JS._load_loc_all()
check("P11 农业党中文名", JS._party_name_zh(1332, melted, loc) == "农业党",
      repr(JS._party_name_zh(1332, melted, loc)))
check("P11 玩家国合法党", JS._player_legal_party_name(melted, 185, loc) == "农业党",
      repr(JS._player_legal_party_name(melted, 185, loc)))

# IG 提取带 party_zh: 墨西哥小市民 -> 农业党
igs = JS._extract_interest_groups(melted, 185)
pb = next((g for g in igs if g.get("name") == "ig_petty_bourgeoisie"), None)
check("P11 IG 小市民 party_zh", (pb or {}).get("party_zh") == "农业党",
      repr((pb or {}).get("party_zh")) if pb else "IG未找到")

# ---------- P9: 工会法 ----------
lab = JS._labor_union_line(melted, 185, loc)
check("P9 杂志工会法行", lab is not None and "工会法" in lab, repr(lab))
# 报纸侧: 用当前熔解 laws (1878 快照当时未施行工会法, 返回 None 属正确行为)
cur_laws = JS.query_laws(melted, 185)
labj = J._labor_law_line({"laws": cur_laws})
check("P9 报纸工会法行", labj is not None and "工会法" in labj, repr(labj))
check("P9 未施行工会法返回None", J._labor_law_line({"laws": ["law_technocracy"]}) is None)
# P9 工会法介绍主来源: 游戏本地化 desc; 遗留 key (游戏已无 desc) 回退硬编码表
labd = J._labor_law_line({"laws": ["law_corporatized_unions"]})
check("P9 报纸desc主来源", labd is not None
      and "劳工组织被置于国家直接或间接控制之下" in labd, repr(labd))
labd2 = J._labor_law_line({"laws": ["law_rights_of_workers"]})
check("P9 遗留key回退硬编码", labd2 is not None
      and "工人可组织工会维护权益" in labd2, repr(labd2))
print("P9 报纸示例:", labd)
print("P9 杂志示例:", lab)

# ---------- P10+P2: _ownership_lines ----------
own_single = {"summary": "该建筑物完全由国家所有",
              "holders": [{"kind": "state", "zh": "国家", "levels": 24, "pct": 100.0}]}
lines = J._ownership_lines(own_single)
check("P10 单一持有人只出一行", len(lines) == 1 and "所有权明细" not in lines[0], repr(lines))
own_company = {"summary": "该建筑物完全由公司持有（持有者为哈利斯科的达能食品）",
               "holders": [{"kind": "company", "zh": "公司", "levels": 10, "pct": 100.0,
                            "owner": {"state_zh": "哈利斯科", "building_zh": "优质食品",
                                      "company_name": "达能食品"}}]}
lines2 = J._ownership_lines(own_company)
check("P2 公司名优先", "达能食品" in lines2[0], repr(lines2))
own_multi = {"summary": "该建筑物主要由公司持有（持有者为哈利斯科的达能食品）",
             "holders": [{"kind": "company", "zh": "公司", "levels": 7, "pct": 70.0,
                          "owner": {"state_zh": "哈利斯科", "company_name": "达能食品"}},
                         {"kind": "laborer", "zh": "本楼从业者", "levels": 3, "pct": 30.0}]}
lines3 = J._ownership_lines(own_multi)
check("P10 多持有人保留明细", len(lines3) == 3 and "所有权明细" in lines3[1], repr(lines3))

# ---------- P1: 投票场景分支 (直接调 _pool_vote_verdict 逻辑验证文案存在) ----------
src = io.open(r'D:\Journal\journal_save.py', encoding='utf-8').read()
check("P1 已按 ok 分支", "投票资格已确认：写他前往投票站" in src
      and "投票资格已被拒绝：写他在投票日被拦在投票站外" in src)

# ---------- P4: 激进指数已删 ----------
check("P4 激进指数已删", "激进指数" not in src)

# ---------- P5/P6: 杂志刊名 ----------
mag = io.open(r'D:\Journal\magazine.py', encoding='utf-8').read()
check("P6 总编辑用刊名", "你是《{mag_name}》杂志的总编辑" in mag)
check("P5 user_msg 去重", "本期数据框架（以下资料为唯一事实依据）" in mag
      and "抬头中的国名按正式国名" not in mag)

# ---------- P7/P13: FACT_GUIDE 瘦身 / 外交标签 ----------
jp = io.open(r'D:\Journal\journal.py', encoding='utf-8').read()
check("P7 FACT_GUIDE 已瘦身", "（如城邑繁盛" not in jp and "度量衡一律使用公制单位" not in jp)
check("P13 外交标签已清理", "世界前八强战况：" in jp and "其中标注「我国」" not in jp)

print("\n==== 通过:", len(ok), " 失败:", len(fail), "====")
for f in fail:
    print("FAIL:", f)
