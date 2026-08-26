# -*- coding: utf-8 -*-
"""端到端验证: 用 1878 快照跑真实提示词构建函数。"""
import io
import sys
import json

sys.path.insert(0, r'D:\Journal')
import journal as J
import journal_save as JS
import magazine as M
import style as S

snap = json.load(io.open(r'D:\Journal\_scratch\mexico_1878_backup\data\snapshot_1878.json',
                         encoding='utf-8'))
data = JS.build_journal_data(snap)
data["magazine"] = JS.build_magazine_data.__wrapped__ if False else None
print("build_journal_data OK; player:", data.get("player"), "| govt_key:",
      data.get("govt_key"))

# ---------- P5/P6: 杂志导言提示词 ----------
data["magazine"] = snap.get("magazine") or {}
msgs = M.build_intro_messages(data)
sys_msg, user_msg = msgs[0]["content"], msgs[1]["content"]
print("\n--- sys_msg 前 3 行 ---")
print("\n".join(sys_msg.splitlines()[:3]))
print("\n--- user_msg ---")
print(user_msg)
assert f"你是《{S.derive_magazine_name(data)}》杂志的总编辑" in sys_msg, "P6 刊名未生效"
assert "抬头中的国名按正式国名" not in user_msg, "P5 去重未生效"

# ---------- P12: 政论板块条件化 ----------
cfg = J.load_config()
masthead = "# 《测试报》\n国名：墨西哥｜都城：墨西哥城｜年份：1878"
# 有 ruler_activity: 不应出现「该行缺失时」
data["ruler_activity"] = "何塞·马里亚·普雷西亚多检阅了驻防墨西哥城的禁卫部队"
msgs2 = J.build_section_messages("politics", data, cfg, None, masthead)
pol = msgs2[0]["content"]
print("\n--- 政论 sys_msg (有 ruler_activity) 是否含缺失分支:",
      "该行缺失时" in pol or "统治者活动数据缺失" in pol)
assert "统治者活动数据缺失" not in pol, "P12 有数据时不应传缺失分支"
# 无 ruler_activity: 应出现
data.pop("ruler_activity", None)
msgs3 = J.build_section_messages("politics", data, cfg, None, masthead)
pol3 = msgs3[0]["content"]
print("--- 政论 sys_msg (无 ruler_activity) 是否含缺失分支:",
      "统治者活动数据缺失" in pol3)
assert "统治者活动数据缺失" in pol3, "P12 无数据时应传缺失分支"

# ---------- P11: 政论利益集团行带党派 ----------
# 1878 快照是旧代码产物 (无 party_zh); 用当前熔解新提取的 IG 覆盖, 模拟新版快照
with io.open(r'D:\Journal\tools\melt.json', 'rb') as fh:
    _melted = fh.read()
data["interest_groups"] = JS._extract_interest_groups(_melted, 185)
data["ruler_activity"] = None
msgs3 = J.build_section_messages("politics", data, cfg, None, masthead)
pol3 = msgs3[0]["content"]
pol3_facts = msgs3[1]["content"]
lines = [ln for ln in pol3_facts.splitlines() if "隶属" in ln]
print("\n--- 政论事实 (含党派) ---")
for ln in lines[:4]:
    print(ln)
assert any("隶属农业党" in ln for ln in lines), "P11 政论未带党派"
assert "统治者活动数据缺失" in pol3, "P12 无数据时应传缺失分支"

# ---------- P3: 杂志 voice 分流 ----------
print("\n--- 杂志 voice (falangist->corporatist) ---")
voice = M._voice(data)
print(voice[:120], "...")
assert "统合运动" in voice, "P3 falangist 应为统合文风"
data2 = dict(data)
data2["govt_key"] = "gov_soviet_dictatorship"
voice2 = M._voice(data2)
print("\n--- 杂志 voice (soviet->communist) ---")
print(voice2[:120], "...")
assert "统合运动" not in voice2 and "先锋" not in voice2, "P3 soviet 应非统合文风"

# ---------- P7: FACT_GUIDE 瘦身后政论提示词内容 ----------
print("\n--- 政论 sys_msg 全文 (前 700 字) ---")
print(pol3[:700])
print("\n全部端到端断言通过")
