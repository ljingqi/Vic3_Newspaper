# -*- coding: utf-8 -*-
"""离线全管线冒烟: 报纸全板块 + 杂志全板块消息构建 (不调 API)。"""
import io
import json
import sys

sys.path.insert(0, r'D:\Journal')
import journal as J
import magazine as M

for year in (1836, 1838):
    print(f"===== {year} =====")
    data = json.load(io.open(
        rf'D:\Journal\output\德川幕府2\data\raw_{year}.json', encoding='utf-8'))
    cfg = J.load_config()
    st = J.resolve_style(cfg, data)

    # 报纸: masthead + 板块列表 (与 generate_newspaper 同逻辑)
    mm = J.build_masthead_messages(data, st)
    assert len(mm) == 2 and mm[0]["role"] == "system" and mm[1]["role"] == "user"
    sections = [(k, t) for k, t, _d in J.SECTION_DEFS
                if not (k == "unemployed" and not data.get("unemployed_interview"))
                and not (k == "stock" and not data.get("stock_market"))
                and not (k == "epidemic" and not (data.get("epidemic") or {}).get("active"))
                and not (k == "war" and not J._has_war_report(data, None))]
    print("  sections:", [k for k, _ in sections])
    assert not any(k == "war" for k, _ in sections) or J._has_war_report(data, None), \
        "war 板块在无战事时不应出现"
    mh = "# 《京都邸报》\n\n国名：德川幕府｜都城：京都｜年份：%d" % year
    for k, _t in sections:
        msgs = J.build_section_messages(k, data, cfg, None, mh, style=st)
        assert len(msgs) == 2, k
        assert msgs[0]["content"].strip() and msgs[1]["content"].strip(), k
    print("  报纸板块消息构建 OK (%d 个板块)" % len(sections))

    # 杂志: 文章列表 → 标题 → 导言 → 首板块 → 后续板块
    arts = M._build_article_list(data)
    themes = []
    for a in arts:
        t = a.get("theme") or a.get("default_title") or a["key"]
        assert not t.startswith("court_") and not t.startswith("war_") \
            and not t.startswith("migration_"), f"theme 漏键值: {t}"
        themes.append(t)
    mi = M.build_intro_messages(data)
    assert len(mi) == 2, "intro"
    intro = "（导言占位）" * 20
    for a in arts:
        ml = M.build_lead_messages(a, data, intro)
        assert len(ml) == 2, a["key"]
        for sec in a["sections"][1:]:
            ms = M.build_section_messages(a, sec, data, intro, "（开篇占位）" * 20)
            assert len(ms) == 2, (a["key"], sec["key"])
    print(f"  杂志 {len(arts)} 篇: 标题/导言/首板块/后续板块 消息构建 OK")
    print("  themes:", themes)

print("ALL OK")
