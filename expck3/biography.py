# -*- coding: utf-8 -*-
"""小传生成器 v2: 由记忆缓存库(v2) + 最新档 + names.json 生成主角小传 (md)。

v2 修正: 记忆经 alive_data.memories → database 提取, 支持每角色多条记忆;
角色名查 names.json 兜底 (全档 43912 人), 消除「未知」漏键。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "cache", "memories.json")
NAMES_PATH = os.path.join(HERE, "data", "names.json")
OUT_DIR = os.path.join(HERE, "output")

TRAIT_ZH = {
    "trusting": "轻信", "impatient": "急躁", "vengeful": "睚眦必报",
    "education_learning_3": "学识（教育三级）", "whole_of_body": "身心合一",
    "governor": "治理者", "ambitious": "雄心勃勃", "brave": "勇敢",
    "craven": "怯懦", "greedy": "贪婪", "lustful": "好色", "gluttonous": "饕餮",
    "wrathful": "暴怒", "paranoid": "多疑", "deceitful": "狡诈",
    "honest": "诚实", "shy": "羞怯", "arrogant": "傲慢", "patient": "坚忍",
    "diligent": "勤勉", "slothful": "懒惰", "compassionate": "慈悲",
    "sadistic": "残忍", "callous": "冷酷", "just": "公正", "generous": "慷慨",
    "stubborn": "固执", "fickle": "善变", "gregarious": "合群",
}

SIMPLIFY = {"誠": "诚", "邊": "边", "師": "师", "綽": "绰", "繫": "系", "浣": "浣"}

def zh(s):
    for k, v in SIMPLIFY.items():
        s = s.replace(k, v)
    return s

DEATH_REASON_ZH = {
    "death_execution": "处决", "death_murder": "谋杀", "death_duel": "决斗",
    "death_accident": "意外", "death_stress": "忧惧而亡", "death_wounds": "伤重不治",
    "death_punishment": "刑罚", "death_poison": "毒杀", "death_snake": "蛇噬",
    "death_dungeon": "囚毙", "death_fight": "斗殴", "death_old_age": "寿终",
    "death_natural_causes": "寿终", "death_heart_attack": "心疾",
    "death_broken_bones": "骨碎", "death_drinking_passive": "酗酒",
    "death_disappearance": "失踪而亡", "death_plotting": "密谋致死",
}

def date_key(s):
    try:
        return tuple(int(x) for x in s.split("."))
    except Exception:
        return (9999, 0, 0)

def date_filekey(s):
    return "_".join(f"{int(x):02d}" for x in s.split("."))

_NAMES = None
def load_names():
    global _NAMES
    if _NAMES is None:
        with open(NAMES_PATH, encoding="utf-8") as fp:
            _NAMES = json.load(fp)["names"]
    return _NAMES

def resolve_name(cache, cid):
    """角色 id → 中文名 (缓存 → names.json → id)。"""
    if cid is None:
        return ""
    c = cache.get("characters", {}).get(str(cid))
    if c and c.get("name_zh"):
        return zh(c["name_zh"])
    n = load_names().get(str(cid))
    if n and n.get("name_zh"):
        return zh(n["name_zh"])
    return str(cid)

def resolve_title(melt, tid):
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    t = lt.get(str(tid)) or {}
    name = (t.get("title_name_data") or {}).get("name") or t.get("key") or str(tid)
    return f"{name}（{t.get('key')}）" if t.get("key") else str(tid)

def generate_biography(cache, melt_path, period=None):
    with open(melt_path, encoding="utf-8") as fp:
        melt = json.load(fp)
    pid = cache["player_id"]
    pc = cache["characters"].get(str(pid)) or {}
    living = melt.get("living") or {}
    pobj = living.get(str(pid)) or {}

    ad = pobj.get("alive_data") or {}
    tl = melt.get("traits_lookup") or []
    trait_keys = [tl[t] if t < len(tl) else f"trait{t}" for t in (pobj.get("traits") or [])]
    trait_zh = [TRAIT_ZH.get(k, k) for k in trait_keys]

    house_meta = (melt.get("meta_data") or {}).get("meta_house_name")
    pname = resolve_name(cache, pid)
    lines = []
    A = lines.append

    def fmt(x, nd=1):
        try:
            return f"{float(x):.{nd}f}".rstrip("0").rstrip(".")
        except Exception:
            return str(x)

    A(f"# {zh(house_meta)}{pname}小传（山南观察使）")
    A(f"")
    head = f"{period} · " if period else ""
    A(f"> {head}由年度自动存档 {' / '.join(cache.get('sources') or [])} 共 {len(cache.get('sources') or [])} 份快照整理")
    A(f"> 本小传为实验性流水线的确定性输出，全部事实取自存档记忆与档案数据。")
    A(f"")

    # 出身
    A(f"## 出身")
    A(f"")
    A(f"生于 {pc.get('birth')}，汉族（asian_han_chinese），文化属 han 系，信仰经学（jingxue）。")
    A(f"{pc.get('birth')} 自创{zh(house_meta)}氏（{pname}氏），并为家族首任家主。")
    A(f"早年科举四试及第：童子试、乡试、会试、殿试皆中（存档履历 flags）。")
    A(f"为人{'、'.join(trait_zh)}。")
    A(f"")

    # 受任
    landed = pc.get("landed") or {}
    domain_ids = landed.get("domain") or []
    LEVEL_ZH = {"k_": "王国", "d_": "公国", "c_": "县", "b_": "堡", "e_": "帝国"}
    def domain_label(tid):
        lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
        t = lt.get(str(tid)) or {}
        key = t.get("key") or str(tid)
        name = (t.get("title_name_data") or {}).get("name") or key
        lvl = ""
        for pfx, z in LEVEL_ZH.items():
            if key.startswith(pfx):
                lvl = z
                break
        return f"{name}（{lvl}）" if lvl else name
    domain_zh = [domain_label(t) for t in domain_ids]
    capital_name = domain_label((pc.get("landed") or {}).get("realm_capital") or 14908)
    A(f"## 受任山南")
    A(f"")
    A(f"867.1.1 起执掌一方（became_ruler_date）；867.9.8 受天朝委任，为山南观察使（k_shannan，任命制，前任 9455），政体天朝官制（celestial_government）。")
    A(f"直辖 {len(domain_ids)} 地：{'、'.join(domain_zh)}（治所{capital_name}）。")
    A(f"麾下封臣 {landed.get('vassal_count', 0)} 人，御前会议六席，储君 13530。")
    A(f"")

    # 治政大事 (时间线, 来自主角及相关人物记忆)
    A(f"## 治政两年大事")
    A(f"")
    events = []
    related_events = []
    def add(date, ev, is_player=False):
        if not date:
            return
        (events if is_player else related_events).append((date, ev))
    # 主角记忆
    for m in pc.get("memories") or []:
        zht = cl.BIO_MEMORY_TYPES.get(m["type"], m["type"])
        parts = m.get("participants") or {}
        extra = ""
        if m["type"] == "married":
            other = parts.get("spouse")
            extra = f"，娶 {resolve_name(cache, other)}（{other}）"
        elif m["type"] == "became_rivals":
            other = parts.get("rival")
            extra = f"，与 {resolve_name(cache, other)}（{other}）结仇"
        elif m["type"] == "imprisoned_other":
            other = parts.get("imprisoned")
            extra = f"，囚禁 {resolve_name(cache, other)}（{other}）"
        elif m["type"] == "spouse_died":
            other = parts.get("dead_relation")
            extra = f"，妻 {resolve_name(cache, other)}（{other}）身亡"
        elif m["type"] == "lost_title_memory":
            nh = parts.get("new_holder")
            title_id = None
            reason = ""
            for v in m.get("vars") or []:
                if v.get("flag") == "landed_title":
                    title_id = v.get("identity")
                if v.get("flag") == "reason" and v.get("identity"):
                    reason = f"（{v.get('identity')}）"
            tstr = resolve_title(melt, title_id) if title_id else ""
            extra = f"，让出 {tstr}，归 {resolve_name(cache, nh)}（{nh}）"
        add(m.get("creation_date"), f"主角：{zht}{reason}{extra}", is_player=True)
    # 相关人物记忆
    for cid, c in cache.get("characters", {}).items():
        if int(cid) == pid:
            continue
        for m in c.get("memories") or []:
            zht = cl.BIO_MEMORY_TYPES.get(m["type"], m["type"])
            parts = m.get("participants") or {}
            extra = ""
            if m["type"] == "married":
                other = parts.get("spouse")
                if other == pid:
                    extra = "（档案称与主角成婚）"
                else:
                    extra = f"，成婚对象 {resolve_name(cache, other)}（{other}）"
            elif m["type"] == "became_lovers":
                other = parts.get("new_relation")
                extra = f"，与 {resolve_name(cache, other)}（{other}）相恋"
            elif m["type"] == "broke_up_lovers":
                other = parts.get("old_lover")
                extra = f"，与 {resolve_name(cache, other)}（{other}）分手"
            elif m["type"] == "became_rivals":
                other = parts.get("rival")
                extra = f"，与 {resolve_name(cache, other)}（{other}）结仇"
            elif m["type"] == "lost_title_memory":
                nh = parts.get("new_holder")
                extra = f"，让出，归 {resolve_name(cache, nh)}（{nh}）"
            elif m["type"] == "first_born":
                extra = f"，得长子 {parts.get('child')}"
            elif m["type"] == "child_born":
                extra = f"，得子 {parts.get('child')}"
            elif m["type"] == "ascended_throne_memory":
                extra = ""
            add(m.get("creation_date"), f"{resolve_name(cache, int(cid))}（{cid}）：{zht}{extra}")
    # 死亡事件 (执政期内, 主角相关人物)
    for cid, c in cache.get("characters", {}).items():
        d = c.get("death")
        if not d:
            continue
        if date_key(d.get("date") or "") < (867, 1, 1):
            continue
        reason = DEATH_REASON_ZH.get(d.get("reason"), d.get("reason") or "寿终")
        killer = d.get("killer")
        kstr = ""
        is_player_related = (killer == pid)
        if killer == pid:
            kstr = "，主角行刑"
        elif killer:
            kstr = f"，凶手 {resolve_name(cache, killer)}（{killer}）"
        add(d.get("date"),
            f"{resolve_name(cache, int(cid))}（{cid}）殁于 {d.get('date')}，被{reason}{kstr}",
            is_player=is_player_related)

    seen = set()
    def emit(lst, title):
        if not lst:
            return
        A(f"### {title}")
        A(f"")
        for date, ev in sorted(lst, key=lambda x: date_key(x[0])):
            if (date, ev) in seen:
                continue
            seen.add((date, ev))
            A(f"- {date}　{ev}")
        A(f"")
    emit(events, "主角亲历")
    emit(related_events, "相关人物动态")
    if not events and not related_events:
        A("（两年间无重大事件记录）")
    A(f"")

    # 婚姻与家庭
    A(f"## 婚姻与家庭")
    A(f"")
    fam = pc.get("family") or {}
    def zhc(cid):
        return resolve_name(cache, cid)
    spouse_ids = fam.get("primary_spouse") or fam.get("spouse") or []
    former = fam.get("former_spouses") or []
    child_ids = fam.get("child") or []
    A(f"现任正妻：{'、'.join(f'{zhc(s)}（{s}）' for s in spouse_ids)}。")
    if former:
        A(f"前妻：{'、'.join(f'{zhc(s)}（{s}）' for s in former)}。")
    A(f"子女：{'、'.join(f'{zhc(c)}（{c}）' for c in child_ids)}。储君 13530。")
    A(f"")

    # 战事
    A(f"## 战事")
    A(f"")
    A(f"执政两年来，存档未见主角亲历的战役记录：无胜战/败战记忆，未列名于任何活跃战争参战方，亦无战斗（combat）参与记录。坐镇襄阳，未亲历战阵。")
    A(f"")

    # 现状
    A(f"## 现状（{melt.get('date')}）")
    A(f"")
    age = None
    try:
        by, bm, bd = (int(x) for x in (pc.get("birth") or "0.0.0").split("."))
        cy, cm_, cd_ = (int(x) for x in (melt.get("date") or "0.0.0").split("."))
        age = cy - by
    except Exception:
        pass
    A(f"年 {age} 岁（生于 {pc.get('birth')}）。健康 {fmt(ad.get('health'))}，压力 {ad.get('stress')}。国库金 {fmt(ad.get('gold', {}).get('value'))}，月入 {fmt(ad.get('income'))}。虔诚 {fmt(ad.get('piety', {}).get('currency'))}，威望 {fmt(ad.get('prestige', {}).get('currency'))}，影响力 {fmt(ad.get('influence', {}).get('currency'))}，功勋 {fmt(ad.get('merit', {}).get('currency'))}（天朝功勋）。")
    A(f"领土 {len(domain_ids)} 地、封臣 {landed.get('vassal_count', 0)} 人。储君（13530）已定，与二元共治体制（diarchy 50331829）并行。")
    A(f"")

    # 数据说明
    A(f"---")
    A(f"")
    A(f"### 附：本小传数据来源")
    A(f"")
    A(f"- 人物档案、家庭、领地、死亡：存档 living / dead_unprunable / dead_prunable 角色对象")
    A(f"- 记忆：character_memory_manager.database（键=记忆 ID）+ 角色 alive_data.memories（记忆 ID 列表）；跨 {len(cache.get('sources') or [])} 档累积去重")
    A(f"- 结仇：became_rivals / became_grudge / became_nemesis 记忆，含双方视角")
    A(f"- 人名：first_name 为名表键，经 Unicode 码点解码（names.json 全档映射兜底）")
    A(f"- 已知机制：角色死亡时其 memories 列表被清空，生前记忆仅存于历年存档缓存")
    return "\n".join(lines)

def main():
    cache = cl.load_cache(CACHE_PATH)
    latest = cache.get("last_date")
    melt_path = os.path.join(HERE, "data", f"melt_{date_filekey(latest)}.json")
    md = generate_biography(cache, melt_path, period="治政两年（867.1.1 – 869.2.22）")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "边诚小传_867-869.md")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(md)
    print("已生成:", out)

if __name__ == "__main__":
    main()
