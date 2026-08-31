# -*- coding: utf-8 -*-
"""expck3 记忆缓存库核心库 (v2, 修正记忆归属机制)。

记忆系统真实结构 (经 exp6/exp7/exp8 实测验证):
  - character_memory_manager.database : 键 = **记忆 ID** (与角色共享 id 池,
    所以大量记忆 ID 恰好落在角色 id 范围内 — 之前 v1 误判为「键=角色 id」)。
  - 每个角色的 alive_data.memories = { 记忆ID列表 } : 角色 → 记忆的多对多映射。
  - 角色**死亡时 memories 列表被清空**, 记忆对象也从 database 移除
    (实测: 868 活有记忆→869 已死 141 人全部清空; 对照活人 6792/6793 保留)。
  - 因此必须在角色死前的年度存档里抓取记忆 → 缓存库是唯一可靠方案。

用法: pipeline.py / exp4_build_cache.py 调用 extract_snapshot 并入年度快照。
"""
import json
import os
import re

# ---------------------------------------------------------------------------
# 名称解码
# ---------------------------------------------------------------------------

_CP_RE = re.compile(r"_([0-9A-Fa-f]{3,5})(?=_|$)")

def decode_codepoints(key):
    """'Cheng_8AA0' → '诚'; 'Shanzhi_5584_81F3' → '善知' (码点拼接)。"""
    if not key:
        return key
    parts = _CP_RE.findall(key)
    if not parts:
        return key
    zh = "".join(chr(int(h, 16)) for h in parts)
    return zh if any("\u3400" <= ch <= "\u9fff" for ch in zh) else key

def name_zh(char_obj):
    fn = (char_obj or {}).get("first_name") or ""
    return decode_codepoints(fn)

# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def load_melt(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)

def _db(melt):
    """记忆对象库: {记忆ID(str): {type, participants, creation_date, ...}}"""
    return melt.get("character_memory_manager", {}).get("database") or {}

def _living(melt):
    return melt.get("living") or {}

def _dead_unprunable(melt):
    return melt.get("dead_unprunable") or {}

def _dead_prunable(melt):
    return (melt.get("characters") or {}).get("dead_prunable") or {}

def all_characters(melt):
    out = {}
    out.update(_living(melt))
    out.update(_dead_unprunable(melt))
    out.update(_dead_prunable(melt))
    return out

def mem_ids_of(char_obj):
    """角色 alive_data.memories (记忆ID列表)。"""
    return (char_obj or {}).get("alive_data", {}).get("memories") or []

def find_player(melt):
    cpc = melt.get("currently_played_characters") or []
    if cpc:
        return int(cpc[0])
    pc = melt.get("played_character")
    if isinstance(pc, dict) and pc.get("character"):
        return int(pc["character"])
    return None

def family_of(char_obj):
    fd = (char_obj or {}).get("family_data") or {}
    out = {}
    for key in ("primary_spouse", "spouse", "former_spouses", "child",
                "father", "mother", "siblings"):
        v = fd.get(key)
        if v is None:
            continue
        ids = [int(x) for x in (v if isinstance(v, list) else [v])]
        out[key] = ids
    return out

# ---------------------------------------------------------------------------
# 记忆条目
# ---------------------------------------------------------------------------

def memory_brief(mem_id, e):
    """记忆对象 → 精简条目 (附记忆ID; vars 带 {flag,type,identity} 以便取关联对象)。"""
    vars_out = []
    for f in (e.get("variables") or {}).get("data") or []:
        d = f.get("data") or {}
        vars_out.append({
            "flag": f.get("flag"),
            "type": d.get("type"),
            "identity": d.get("identity"),
        })
    return {
        "id": mem_id,
        "type": e.get("type"),
        "participants": e.get("participants"),
        "creation_date": e.get("creation_date"),
        "end_date": e.get("end_date"),
        "vars": vars_out,
    }

BIO_MEMORY_TYPES = {
    "became_rivals": "结仇",
    "became_grudge": "结怨",
    "became_nemesis": "结为死敌",
    "stopped_being_rivals": "化解仇怨",
    "rival_died": "仇人身亡",
    "battle_won_memory": "胜战",
    "battle_lost_memory": "败战",
    "offensive_war": "主动开战",
    "defensive_war": "被迫应战",
    "war_won": "战胜",
    "war_lost": "战败",
    "joined_allys_war": "助战",
    "ascended_throne_memory": "登位",
    "lost_title_memory": "失土",
    "imprisoned": "被囚",
    "imprisoned_other": "囚禁他人",
    "released_from_prison_memory": "获释",
    "relative_died": "亲属亡故",
    "spouse_died": "丧偶",
    "friend_died": "友人亡故",
    "married": "成婚",
    "broke_up_lovers": "分手",
    "became_lovers": "结为情侣",
    "child_born": "添丁",
    "first_born": "得长子",
    "child_premature": "幼子夭折",
    "child_stillborn": "婴儿夭折",
    "twins_born": "孪生",
    "passed_child_exam_memory": "童子试及第",
    "failed_child_exam_memory": "童子试落第",
    "passed_provincial_exam_memory": "乡试及第",
    "failed_provincial_exam_memory": "乡试落第",
    "passed_metropolitan_exam_memory": "会试及第",
    "passed_palace_exam_memory": "殿试及第",
    "tortured_memory": "受刑",
    "torturer_memory": "施刑",
    "witnessed_death_battle": "目击战殁",
    "became_incapable_due_to_battle_concussion": "战伤致残",
    "became_friends": "结友",
    "became_soulmates": "结为灵魂伴侣",
    "became_blood_brother": "结为血盟兄弟",
    "completed_hajj_memory": "朝觐归来",
    "hostage_created_hostage": "为人质",
    "hostage_created_warden": "看守人质",
    "hostage_created_home_court": "交出人质",
    "picked_serenity_aspect_memory": "皈依安详之道",
    "picked_creation_aspect_memory": "皈依创世之道",
    "ward_education_completed": "教化完成",
    "childhood_education_guardian": "受业于",
    "childhood_education_no_guardian": "独自求学",
    "completed_rites_of_passage": "完成成人礼",
    "completed_adult_education": "完成成人学业",
    "became_acclaimed": "获拥戴",
    "witnessed_a_coronation_memory": "见证加冕",
    "grand_wedding_completed_guest": "出席大婚",
    "ignored_assault_memory": "受辱未报",
    "had_sex": "私通",
}

# ---------------------------------------------------------------------------
# 缓存库
# ---------------------------------------------------------------------------

EMPTY_CACHE = {
    "schema": 2,
    "player_id": None,
    "player_name": None,
    "game_version": None,
    "sources": [],
    "last_date": None,
    "player_death": None,
    "characters": {},
    "relations": {},
}

def load_cache(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    return dict(EMPTY_CACHE)

def save_cache(cache, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False, indent=1)

def char_record(cache, cid):
    key = str(cid)
    if key not in cache["characters"]:
        cache["characters"][key] = {
            "id": cid,
            "first_name": None,
            "name_zh": None,
            "birth": None,
            "death": None,
            "dynasty_house": None,
            "culture": None,
            "faith": None,
            "traits": [],
            "family": {},
            "landed": {},
            "memories": [],
        }
    return cache["characters"][key]

# ---------------------------------------------------------------------------
# 单档提取 (v2: 记忆经 alive_data.memories → database)
# ---------------------------------------------------------------------------

def extract_snapshot(cache, melt, date_label):
    """把一个存档快照并入缓存。返回 False 表示玩家不一致被拒绝。"""
    player_id = find_player(melt)
    if cache["player_id"] is not None and player_id is not None \
            and cache["player_id"] != player_id:
        print(f"  [跳过] 档期 {date_label} 玩家 {player_id} 与缓存玩家 "
              f"{cache['player_id']} 不一致")
        return False
    if cache["player_id"] is None:
        cache["player_id"] = player_id
    cache["player_id"] = player_id or cache["player_id"]
    meta = melt.get("meta_data") or {}
    if meta.get("meta_player_name") and not cache.get("player_name"):
        cache["player_name"] = meta["meta_player_name"]
    cache["game_version"] = meta.get("version") or cache["game_version"]
    if date_label not in cache["sources"]:
        cache["sources"].append(date_label)
    cache["last_date"] = date_label

    chars = all_characters(melt)
    db = _db(melt)

    # 玩家死亡检测
    if player_id is not None:
        pdead = (chars.get(str(player_id)) or {}).get("dead_data")
        if pdead and cache["player_death"] is None:
            cache["player_death"] = {
                "date": pdead.get("date"),
                "reason": pdead.get("reason"),
                "killer": pdead.get("killer"),
            }

    # 目标角色集: 玩家 + 家族/家庭 + 记忆参与者 (两轮)
    targets = set()
    if player_id is not None:
        targets.add(player_id)
        p = chars.get(str(player_id))
        if p:
            for ids in family_of(p).values():
                targets.update(ids)
            house = p.get("dynasty_house")
            if house is not None:
                for cid, c in chars.items():
                    if c.get("dynasty_house") == house:
                        targets.add(int(cid))
    # 第一轮: 玩家记忆参与者
    def add_participants(owner_id):
        c = chars.get(str(owner_id))
        if not c:
            return
        for mid in mem_ids_of(c):
            e = db.get(str(mid))
            if not e:
                continue
            for v in (e.get("participants") or {}).values():
                if isinstance(v, int):
                    targets.add(v)
    if player_id is not None:
        add_participants(player_id)
    # 第二轮: 目标集角色的记忆参与者
    second = list(targets)
    for cid in second:
        add_participants(cid)
    # 全库: 记忆参与者含玩家的记忆拥有者 (交叉读取)
    if player_id is not None:
        for cid, c in chars.items():
            for mid in mem_ids_of(c):
                e = db.get(str(mid))
                if not e:
                    continue
                if player_id in (e.get("participants") or {}).values():
                    targets.add(int(cid))
                    for v in (e.get("participants") or {}).values():
                        if isinstance(v, int):
                            targets.add(v)

    for cid in sorted(targets):
        c = chars.get(str(cid))
        if c is None:
            continue
        rec = char_record(cache, cid)
        if rec["first_name"] is None:
            rec["first_name"] = c.get("first_name")
            rec["name_zh"] = name_zh(c)
            rec["birth"] = c.get("birth")
            rec["dynasty_house"] = c.get("dynasty_house")
            rec["culture"] = c.get("culture")
            rec["faith"] = c.get("faith")
            rec["traits"] = c.get("traits") or []
        rec["family"] = family_of(c)
        if cid == player_id:
            ld = c.get("landed_data") or {}
            rec["landed"] = {
                "domain": ld.get("domain"),
                "became_ruler_date": ld.get("became_ruler_date"),
                "government": ld.get("government"),
                "realm_capital": ld.get("realm_capital"),
                "vassal_count": len(ld.get("vassal_contracts") or []),
                "council": ld.get("council"),
                "laws": ld.get("laws"),
                "succession": ld.get("succession"),
            }
        dd = c.get("dead_data")
        if dd and rec["death"] is None:
            rec["death"] = {
                "date": dd.get("date"),
                "reason": dd.get("reason"),
                "killer": dd.get("killer"),
                "liege": dd.get("liege"),
                "liege_title": dd.get("liege_title"),
                "named_title": dd.get("named_title"),
            }
        # 记忆: alive_data.memories → database
        seen = {(m.get("id"), m.get("creation_date")) for m in rec["memories"]}
        for mid in mem_ids_of(c):
            e = db.get(str(mid))
            if not e:
                continue
            b = memory_brief(mid, e)
            key = (b["id"], b.get("creation_date"))
            if key not in seen:
                b["first_seen"] = date_label
                rec["memories"].append(b)
                seen.add(key)
    return cache

# ---------------------------------------------------------------------------
# 关系汇总
# ---------------------------------------------------------------------------

def summarize_relations(cache):
    """与主角结仇/结怨/死敌清单 (双方视角)。"""
    pid = cache["player_id"]
    out = []
    if pid is None:
        return out
    def scan(owner_id):
        rec = cache["characters"].get(str(owner_id))
        if not rec:
            return
        for mem in rec.get("memories") or []:
            if mem["type"] not in ("became_rivals", "became_grudge", "became_nemesis"):
                continue
            slot = {"became_rivals": "rival", "became_grudge": "grudge",
                    "became_nemesis": "nemesis"}[mem["type"]]
            other = (mem.get("participants") or {}).get(slot)
            if other is None:
                continue
            out.append({
                "other": other,
                "other_name": (cache["characters"].get(str(other)) or {}).get("name_zh"),
                "owner": owner_id,
                "type": mem["type"],
                "date": mem.get("creation_date"),
            })
    scan(pid)
    for cid in cache["characters"]:
        if int(cid) != pid:
            scan(int(cid))
    return out
