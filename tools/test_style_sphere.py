#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态文风「文化圈轴」离线单测 (不调 API)。

覆盖:
  1. style_sphere_from_data 的 TAG 主表 / 国教 / 文化名兜底判定;
  2. sinic 输出与 MODERNITY_TIERS 逐档一致 (不回归);
  3. west/islam/other 1~2 档: 公历纪年规则、阿拉伯数字、13 个板块标题齐备、
     中式语域锚点 (伏惟/谨按/朝廷/户部/本馆/岁次/邸报/奏报) 不出现;
  4. 全部生成提示词无负向措辞;
  5. 杂志基调/拟题指南与文化圈一致;
  6. 州情速写按文化圈去中国化。

用法: python tools/test_style_sphere.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import journal  # noqa: E402
import style  # noqa: E402

NEG_RE = re.compile(r"不要|请勿|禁止|避免|切勿|不得|严禁|不可|不再|勿")
CN_ANCHORS = ("伏惟", "谨按", "朝廷", "户部", "本馆", "岁次", "邸报", "奏报")
SECTION_KEYS = ("headline", "war", "diplo", "econ", "politics", "society",
                "epidemic", "family", "peer", "unemployed", "comment", "ads",
                "stock")
FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
        print(f"  FAIL  {msg}")
    return cond


def mk(tag=None, religion=None, cat_law="law_monarchy",
       dop="law_autocracy", tech=None, cultures=None):
    d = {"govt_key": "gov_test", "govt": "测试政体",
         "govt_law": cat_law, "dop_law": dop, "tech_keys": list(tech or [])}
    if tag:
        d["player_tag"] = tag
    if religion:
        d["religion"] = religion
    if cultures:
        d["primary_cultures"] = list(cultures)
    return d


# 构造各档位: 议会制共和国 (+1) + 投票权修正, 基础分取对应区间
_TIER_CASES = {
    1: (["rationalism", "democracy"], "law_autocracy"),
    2: (["rationalism", "democracy"], "law_landed_voting"),
    3: (["rationalism", "democracy"], "law_wealth_voting"),
    4: (["rationalism", "democracy", "mass_communication", "egalitarianism",
         "nationalism", "labor_movement", "organized_sports", "human_rights"],
        "law_landed_voting"),
    5: (list(style.RATIONALISM_BRANCH), "law_landed_voting"),
}


def test_sphere_detection():
    print("[1] 文化圈判定")
    cases = [
        (("PRU", "protestant"), style.SPHERE_WEST),
        (("CHI", "confucian"), style.SPHERE_SINIC),
        (("TUR", "sunni"), style.SPHERE_ISLAM),
        (("KZH", "sunni"), style.SPHERE_ISLAM),
        (("ZUL", "animist"), style.SPHERE_OTHER),
        (("BAL", "hindu"), style.SPHERE_OTHER),
        (("GBR", "protestant"), style.SPHERE_WEST),
        (("JAP", "shinto"), style.SPHERE_SINIC),
        ((None, "sunni"), style.SPHERE_ISLAM),
        ((None, "catholic"), style.SPHERE_WEST),
        ((None, "confucian"), style.SPHERE_SINIC),
        ((None, "animist"), style.SPHERE_OTHER),
        (("ZZZ", "animist", ["哈萨克"]), style.SPHERE_ISLAM),
        (("ZZZ", "animist", ["法兰西"]), style.SPHERE_WEST),
        (("ZZZ", "animist", ["汉"]), style.SPHERE_SINIC),
    ]
    for case, want in cases:
        tag, rel = case[0], case[1]
        cultures = case[2] if len(case) > 2 else None
        got = style.style_sphere_from_data(
            mk(tag=tag, religion=rel, cultures=cultures))
        check(got == want, f"{tag}/{rel}/{cultures} -> {got}, 期望 {want}")


def test_sinic_identity():
    print("[2] sinic 与 MODERNITY_TIERS 逐档一致")
    for tier, (tech, dop) in _TIER_CASES.items():
        st = style.resolve_newspaper_style(
            mk(tag="CHI", religion="confucian",
               cat_law="law_parliamentary_republic", dop=dop, tech=tech))
        base = style.MODERNITY_TIERS[tier]
        check(st["sphere"] == style.SPHERE_SINIC,
              f"tier{tier} sinic sphere={st['sphere']}")
        check(st["tier"] == tier, f"tier{tier} 解析为 {st['tier']}")
        check(st["name"] == base["name"], f"tier{tier} name 被改写")
        check(st["number_format"] == base["number_format"],
              f"tier{tier} number_format 被改写")
        check(st["section_titles"] == base["section_titles"],
              f"tier{tier} section_titles 被改写")
        check(style._CALENDAR_MARK not in st["voice"],
              f"tier{tier} sinic voice 被追加公历规则")


def _prompt_fields(st):
    out = [st.get("name") or "", st.get("voice") or "",
           st.get("masthead") or "", st.get("econ_guide") or "",
           st.get("ads_guide") or "", st.get("number_guide") or ""]
    out += list((st.get("section_titles") or {}).values())
    return out


def test_sphere_tiers():
    print("[3] west/islam/other 1~2 档语域与字段完整性")
    probes = [("PRU", "protestant"), ("KZH", "sunni"), ("ZUL", "animist")]
    for tag, rel in probes:
        for tier in (1, 2):
            tech, dop = _TIER_CASES[tier]
            st = style.resolve_newspaper_style(
                mk(tag=tag, religion=rel,
                   cat_law="law_parliamentary_republic", dop=dop, tech=tech))
            label = f"{tag}/tier{tier}"
            check(st["sphere"] != style.SPHERE_SINIC,
                  f"{label} sphere 仍为 sinic")
            check(style._CALENDAR_MARK in st["voice"],
                  f"{label} voice 缺公历纪年规则")
            check(st["number_format"] == "arabic",
                  f"{label} 数字格式非阿拉伯")
            check(set(SECTION_KEYS) <= set(st["section_titles"]),
                  f"{label} 板块标题缺项")
            blob = "".join(_prompt_fields(st))
            for a in CN_ANCHORS:
                check(a not in blob, f"{label} 出现中式锚点「{a}」")
            m = NEG_RE.search(blob)
            check(not m, f"{label} 提示词含负向词「{m.group(0) if m else ''}」")


def test_sphere_titles():
    print("[3b] 共和/君主称谓分流")
    tech, dop = _TIER_CASES[1]
    rep = style.resolve_newspaper_style(
        mk(tag="HAI", religion="catholic",
           cat_law="law_presidential_republic", dop=dop, tech=tech))
    check("总统" in rep["voice"], "共和政体 west/tier1 未用「总统」称谓")
    check("陛下" not in rep["voice"], "共和政体 west/tier1 出现「陛下」")
    check("朝廷" not in rep["voice"], "共和政体 west/tier1 出现「朝廷」")
    check(rep["section_titles"]["politics"] == "政府与内阁",
          f"共和政体 west/tier1 政界栏名仍为 {rep['section_titles']['politics']}")
    mon = style.resolve_newspaper_style(
        mk(tag="PRU", religion="protestant",
           cat_law="law_monarchy", dop=dop, tech=tech))
    check("陛下" in mon["voice"], "君主政体 west/tier1 缺「陛下」称谓")
    check("总统" not in mon["voice"], "君主政体 west/tier1 出现「总统」")
    check(mon["section_titles"]["politics"] == "宫廷与内阁",
          "君主政体 west/tier1 政界栏名被改写")
    islam = style.resolve_newspaper_style(
        mk(tag="KZH", religion="sunni",
           cat_law="law_monarchy", dop=dop, tech=tech))
    check("苏丹" in islam["voice"] and "维齐尔" in islam["voice"],
          "伊斯兰君主政体称谓缺失")
    check(islam["section_titles"]["politics"] == "王廷与迪万",
          f"伊斯兰君主政体政界栏名异常: {islam['section_titles']['politics']}")


def test_all_tiers_clean():
    print("[4] 全档位提示词负向措辞检查 (sphere × tier)")
    for tag, rel in (("PRU", "protestant"), ("KZH", "sunni"),
                     ("ZUL", "animist"), ("CHI", "confucian")):
        for tier in range(1, 6):
            tech, dop = _TIER_CASES[tier]
            st = style.resolve_newspaper_style(
                mk(tag=tag, religion=rel,
                   cat_law="law_parliamentary_republic", dop=dop, tech=tech))
            blob = "".join(_prompt_fields(st))
            m = NEG_RE.search(blob)
            check(not m,
                  f"{tag}/tier{tier} 含负向词「{m.group(0) if m else ''}」")
            if st["sphere"] != style.SPHERE_SINIC:
                check(style._CALENDAR_MARK in st["voice"],
                      f"{tag}/tier{tier} 非 sinic 却无公历规则")


def test_magazine():
    print("[5] 杂志基调与拟题指南")
    for tag, rel, tier in (("PRU", "protestant", 1), ("PRU", "protestant", 2),
                           ("PRU", "protestant", 3), ("KZH", "sunni", 1),
                           ("KZH", "sunni", 3), ("ZUL", "animist", 1),
                           ("CHI", "confucian", 1)):
        tech, dop = _TIER_CASES[tier]
        d = mk(tag=tag, religion=rel,
               cat_law="law_parliamentary_republic", dop=dop, tech=tech)
        voice = style.resolve_magazine_voice(d)
        sphere = style.style_sphere_from_data(d)
        label = f"{tag}/mag/tier{tier}"
        if sphere != style.SPHERE_SINIC:
            check(style._CALENDAR_MARK in voice, f"{label} 杂志基调缺公历规则")
            for a in ("朝廷", "户部", "伏惟", "谨按", "御驾亲征", "天命"):
                check(a not in voice, f"{label} 杂志基调出现「{a}」")
        m = NEG_RE.search(voice)
        check(not m, f"{label} 杂志基调含负向词「{m.group(0) if m else ''}」")
        guide = style.resolve_magazine_title_guide(d)
        check(bool(guide), f"{label} 拟题指南为空")
        m2 = NEG_RE.search(guide)
        check(not m2, f"{label} 拟题指南含负向词")
    # 西方 1 档标题体例应为论说体
    d = mk(tag="PRU", religion="protestant",
           cat_law="law_parliamentary_republic", dop="law_autocracy",
           tech=["rationalism", "democracy"])
    check("论" in style.resolve_magazine_title_guide(d),
          "west/tier1 拟题指南缺论说体体例")


def test_state_flavor():
    print("[6] 州情速写文化圈替换")
    lines = ["基层由士绅宗族把持，衙门只管催科与刑名", "蒙学初开",
             "政令不出都门，市廛栉比、商贾辐辏"]
    tech, dop = _TIER_CASES[1]
    west = journal._state_flavor_lines_for_tier(
        lines, mk(tag="PRU", religion="protestant",
                  cat_law="law_parliamentary_republic", dop=dop, tech=tech))
    sinic = journal._state_flavor_lines_for_tier(
        lines, mk(tag="CHI", religion="confucian",
                  cat_law="law_parliamentary_republic", dop=dop, tech=tech))
    blob = "".join(west)
    for bad in ("衙门", "士绅", "都门", "市廛", "蒙学"):
        check(bad not in blob, f"west 州情速写仍含「{bad}」: {blob}")
    check("官署" in blob and "地主乡绅" in blob, f"west 州情速写替换缺失: {blob}")
    check(sinic == lines, "sinic 州情速写被改写")


def test_prompt_assembly():
    print("[7] 抬头/板块/杂志导言提示词注入公历纪年")
    import magazine
    magazine._set_style_system("dynamic")
    tech, dop = _TIER_CASES[1]
    for tag, rel, want in (("PRU", "protestant", True),
                           ("CHI", "confucian", False)):
        d = mk(tag=tag, religion=rel, cat_law="law_monarchy", dop=dop, tech=tech)
        d.update({"player": "测试国", "capital": "测试城", "year": 1836,
                  "govt": "君主制", "govt_zh": "君主制", "currency": "卢布"})
        st = style.resolve_newspaper_style(d)
        blob = "".join(m["content"]
                       for m in journal.build_masthead_messages(d, st))
        check(("纪年一律用公历" in blob) == want,
              f"{tag} 抬头提示词公历纪年注入不符 (want={want})")
        smsg = journal.build_section_messages("headline", d, {}, [], "# 《X》",
                                              style=st)
        sblob = "".join(m["content"] for m in smsg)
        check(("纪年一律用公历" in sblob) == want,
              f"{tag} 板块提示词公历纪年注入不符 (want={want})")
        iblob = "".join(m["content"] for m in magazine.build_intro_messages(d))
        check(("纪年一律用公历" in iblob) == want,
              f"{tag} 杂志导言提示词公历纪年注入不符 (want={want})")


def test_desinicize():
    print("[6b] 输出兜底去中式制度词")
    src = ("据户部奏报，朝廷已令各州县衙门照章办事；伏惟陛下圣明，"
           "本馆谨按：士绅设蒙馆义学，都门邸报亦载其事。")
    tech, dop = _TIER_CASES[1]
    west = journal._desinicize_text(
        src, mk(tag="HAI", religion="catholic",
                cat_law="law_presidential_republic", dop=dop, tech=tech))
    for bad in ("户部", "朝廷", "州县", "衙门", "伏惟", "陛下", "本馆",
                "士绅", "蒙馆", "义学", "都门", "邸报", "奏报"):
        check(bad not in west, f"west 兜底未清「{bad}」: {west}")
    check("财政部" in west and "政府" in west and "总统" in west,
          f"west 兜底替换缺失: {west}")
    sinic = journal._desinicize_text(
        src, mk(tag="CHI", religion="confucian",
                cat_law="law_monarchy", dop=dop, tech=tech))
    check(sinic == src, "sinic 文本被兜底替换改写")


def main():
    test_sphere_detection()
    test_sinic_identity()
    test_sphere_tiers()
    test_sphere_titles()
    test_all_tiers_clean()
    test_magazine()
    test_state_flavor()
    test_desinicize()
    test_prompt_assembly()
    print()
    if FAIL:
        print(f"共 {len(FAIL)} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
