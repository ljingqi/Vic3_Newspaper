# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 深度侦察6: 玩家战争/战斗参与、婚姻、头衔、出生地线索。"""
import json, traceback

MELT = r"D:\Journal\_scratch\ck3_melt.json"
PID = 11368

def show(label, fn):
    try:
        print(f"\n{'='*20} {label} {'='*20}")
        fn()
    except Exception:
        print("!! 段错误:")
        traceback.print_exc()

def main():
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    living = data.get("living") or {}
    db = data.get("character_memory_manager", {}).get("database") or {}

    def s_wars():
        aw = data.get("wars", {}).get("active_wars") or {}
        hits = []
        for k, w in aw.items():
            parts = []
            for side in ("attacker", "defender"):
                for p in (w.get(side) or {}).get("participants") or []:
                    parts.append(p.get("character"))
            if PID in parts:
                hits.append(k)
        print(f"玩家参与的活跃战争: {len(hits)} / {len(aw)}")
        for k in hits:
            w = aw[k]
            print(f"\n--- war {k} ---")
            print("  name:", w.get("name"))
            print("  start:", w.get("start_date"))
            cb = w.get("casus_belli") or {}
            print("  cb:", cb.get("type"), "titles:", cb.get("targeted_titles"))
            for side in ("attacker", "defender"):
                sideobj = w.get(side) or {}
                for p in sideobj.get("participants") or []:
                    mark = " <== 玩家" if p.get("character") == PID else ""
                    print(f"  {side}: char={p.get('character')} since={p.get('date')} casualties={p.get('casualties')}{mark}")
            br = w.get("battle_results") or []
            print(f"  battle_results: {len(br)}")
            for b in br[:5]:
                print("   ", json.dumps(b, ensure_ascii=False)[:200])

    show("玩家战争参与", s_wars)

    def s_combats():
        for key in ("combat_results", "combats"):
            v = (data.get("combats") or {}).get(key) or {}
            hits = []
            for k, c in v.items():
                if not isinstance(c, dict):
                    continue
                s = json.dumps(c, ensure_ascii=False)
                if f'"{PID}"' in s:
                    hits.append(k)
            print(f"{key}: 玩家相关 {len(hits)}/{len(v)}")
            for k in hits[:5]:
                c = v[k]
                print(f"--- {key} {k} ---")
                print("  location:", c.get("location"))
                for side in ("attacker", "defender"):
                    so = c.get(side) or {}
                    print(f"  {side}: main={so.get('main_participant')} cmd={so.get('commander')} ini={so.get('inital_soldiers')} surv={so.get('surviving_soldiers')} parts={so.get('participants')}")

    show("玩家战斗记录", s_combats)

    def s_battle_mem():
        # 玩家相关战斗记忆: 参与者含 PID 或 ruler=PID
        for k, e in db.items():
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t in ("battle_won_memory", "battle_lost_memory", "offensive_war",
                     "defensive_war", "war_won", "war_lost", "joined_allys_war"):
                parts = e.get("participants") or {}
                if PID in parts.values() or PID == parts.get("ruler"):
                    print(f"--- key={k} {t} ---")
                    print(json.dumps(e, ensure_ascii=False)[:500])

    show("玩家战役记忆", s_battle_mem)

    def s_marriage():
        for cid in ("43099", "39250"):
            c = living.get(cid)
            print(f"\n--- 角色 {cid} ---")
            if not c:
                print("  不在 living")
                continue
            print("  first_name:", c.get("first_name"))
            print("  birth:", c.get("birth"), "female:", c.get("female"))
            print("  family_data:", json.dumps(c.get("family_data"), ensure_ascii=False)[:250])
            if cid in db:
                print("  记忆:", json.dumps(db[cid], ensure_ascii=False)[:400])

    show("婚姻对象", s_marriage)

    def s_titles():
        lt = data.get("landed_titles") or {}
        print("landed_titles type:", type(lt).__name__)
        if isinstance(lt, dict):
            print("键数:", len(lt), "前5:", list(lt.keys())[:5])
            for tid in ("14906", "14907", "14908", "14909", "16108", "17459", "2101", "5790"):
                v = lt.get(tid)
                if v is None:
                    continue
                s = json.dumps(v, ensure_ascii=False)
                print(f"--- title {tid} ---")
                print(" ", s[:500])

    show("头衔", s_titles)

    def s_birthplace():
        # 出生地线索扫描
        blob = json.dumps(data, ensure_ascii=False)
        for s in ("birthplace", "birth_province", "birth_location", "place_of_birth"):
            print(f"  {s!r}: {blob.count(s)}")
        # 玩家 alive_data 里 location 相关 flags
        pc = living.get(str(PID)) or {}
        vars_ = (pc.get("alive_data") or {}).get("variables") or {}
        for item in vars_.get("data") or []:
            flag = item.get("flag") or ""
            if any(k in flag for k in ("birth", "origin", "home", "location", "capital", "province")):
                print("  玩家 flag:", json.dumps(item, ensure_ascii=False)[:200])

    show("出生地线索", s_birthplace)

if __name__ == "__main__":
    main()
