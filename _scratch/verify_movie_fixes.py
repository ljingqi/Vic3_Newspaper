#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电影模块两处修复的合成验证 (不依赖存档/LLM):
1. 选角互斥: 主角 pop_key 与各配角两两不同, 支持配角内部去重;
2. 渲染自然语言: 生活水平/识字率用档名, 月收支按币种主辅币格式化。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal_save as js
import movie

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        fails.append(name)


# ---------------------------------------------------------------- 选角互斥
pool = [
    {"pop_id": 101, "state": 1, "type": "laborers", "culture": "汉人",
     "culture_key": "han", "religion": "buddhism", "sol": 6.2,
     "state_name": "江南"},
    {"pop_id": 202, "state": 2, "type": "aristocrats", "culture": "汉人",
     "culture_key": "han", "religion": "buddhism", "sol": 18.0,
     "state_name": "直隶"},
    {"pop_id": 303, "state": 3, "type": "soldiers", "culture": "汉人",
     "culture_key": "han", "religion": "buddhism", "sol": 11.5,
     "state_name": "山东"},
    {"pop_id": 404, "state": 4, "type": "shopkeepers", "culture": "汉人",
     "culture_key": "han", "religion": "buddhism", "sol": 14.2,
     "state_name": "广东"},
]
data = {
    "civilians": [pool[0], pool[3]],
    "families": [pool[1]],
    "elites": [pool[1]],
    "soldiers": [pool[2]],
}
snap = {"player": "测试国", "family_interview": None}

# 主角 = pool[0] (civilians 劳工) → 配角应避开它, 且配角两两不同
prot = js._movie_pop_card(pool[0], "平民样本")
check("主角卡带 pop_key", prot.get("pop_key") is not None,
      f"pop_key={prot.get('pop_key')}")
prot["name"] = "测试主角"
sup = js._movie_supporting(random.Random(1), data, snap, prot, 1836)
pkeys = [c.get("pop_key") for c in sup]
pids = [c.get("pop_id") for c in sup]
check("配角数量 0~2", 0 <= len(sup) <= 2, f"got {len(sup)}")
check("配角不含主角 pop_key",
      all(k is None or k != prot.get("pop_key") for k in pkeys),
      f"prot={prot.get('pop_key')} sup={pkeys}")
check("配角内部无重复 pop_id", len(pids) == len(set(pids)), f"pids={pids}")
check("配角来自不同样本组(职业不同)",
      len({c.get("role") for c in sup}) == len(sup), f"roles={[c.get('role') for c in sup]}")
print(f"  样本: 主角={prot.get('role')} pop_key={prot.get('pop_key')} "
      f"| 配角={[(c.get('role'), c.get('pop_id'), c.get('pop_key')) for c in sup]}")

# 主角是民生访谈家庭 → 配角不再出现"配偶/长子"家人
fi = {"location": 9, "workplace_id": 55, "pop_type": "laborers",
      "culture": "汉人", "religion": "buddhism", "sol": 5.1,
      "region_name": "江南", "hub_name": "苏州城", "wife_works": True,
      "children_count": 2, "literacy_pct": 12.0}
prot_fam = {"name": "阿福", "role": "劳工", "culture": "汉人",
            "religion": "佛教", "state": "江南", "sol": 5.1,
            "income": 0.5, "expense": 0.42,
            "source": "民生访谈家庭", "pop_key": js._movie_pop_key(fi)}
sup2 = js._movie_supporting(random.Random(2), data, snap, prot_fam, 1836)
roles2 = [c.get("role") for c in sup2]
check("访谈家庭主角的配角无家人(配偶/长子)",
      not any("配偶" in r or "长子" in r for r in roles2), f"roles={roles2}")
check("访谈家庭主角的配角仍避开其 pop_key",
      all(c.get("pop_key") != prot_fam.get("pop_key") for c in sup2),
      f"prot_fam_key={prot_fam.get('pop_key')} sup={[c.get('pop_key') for c in sup2]}")

# ---------------------------------------------------------------- 渲染自然语言
card = {"name": "阿福", "role": "劳工", "culture": "汉人", "religion": "佛教",
        "state": "江南", "place": "苏州城", "sol": 13.0, "literacy": 23.5,
        "income": 0.5, "expense": 0.42}
d = {"currency": "比索", "exchange_rates": {"rates": {"比索": {"rate": 114.8}}}}
fact = movie._char_fact(card, d)
check("生活水平用档名", "生活水平温饱尚可" in fact and "生活水平13" not in fact, fact)
check("识字率用档名", "识字率目不识丁" in fact and "23.5" not in fact, fact)
check("月收支按币种格式化", "月收入约" in fact and "比索" in fact
      and "月收入0.5" not in fact, fact)
print(f"  样本渲染: {fact}")

# 无 data 时 (片名预生成等路径) 不崩溃, 金额退化为币种缺省仍可读
fact2 = movie._char_fact(card, None)
check("无 data 兜底可读", "月收入约" in fact2, fact2)

# _slots_block 全量渲染不含裸数值
movie_obj = {"term": "新剧", "genre": [{"id": "drama", "zh": "正剧", "percent": 100}],
             "setting": {"capital": "北京", "state": "直隶", "era": "1836年"},
             "protagonist": card, "antagonist": {"name": None, "role": "宿敌"},
             "supporting": [], "themes": [], "finale": {"zh": "凯旋", "desc": "x"}}
block = movie._slots_block(movie_obj, data=d)
check("slots 块无裸生活水平", "生活水平13" not in block, block)
check("slots 块无裸月收入", "月收入0.5" not in block, block)

# 登场人物行 (读者可见) 生活水平档名
line = movie._char_line("主角", card)
check("登场人物行生活水平档名", "生活水平温饱尚可" in line and "生活水平13" not in line, line)
print(f"  登场人物行: {line}")

print()
if fails:
    print("存在失败项:", fails)
    sys.exit(1)
print("全部通过")
