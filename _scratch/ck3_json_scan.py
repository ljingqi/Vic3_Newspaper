# -*- coding: utf-8 -*-
"""CK3 熔化 JSON 结构侦察: 顶层键、人物库、玩家角色、记忆、战争、死亡。"""
import json, re

MELT = r"D:\Journal\_scratch\ck3_melt.json"

def main():
    print("读取 melt.json ...")
    with open(MELT, encoding="utf-8") as fp:
        data = json.load(fp)
    print("顶层键:", list(data.keys()))
    print("顶层键数量:", len(data))

    # 玩家信息
    meta = data.get("meta_data") or {}
    print("\n=== meta_data ===")
    for k in ("version", "meta_date", "meta_player_name", "meta_title_name",
              "meta_house_name", "meta_player_tier", "save_game_version"):
        print(f"  {k}: {meta.get(k)!r}")

    print("\n=== 顶层 date ===", data.get("date"))

    # 找可能的人物库键
    for key in ("characters", "living_characters", "dead_characters",
                "dynasties", "houses", "wars", "active_wars", "provinces",
                "landed_data", "memory_manager", "historical"):
        if key in data:
            v = data[key]
            print(f"\n=== 顶层 {key}: type={type(v).__name__} ===")
            if isinstance(v, dict):
                print(f"  子键({len(v)}):", list(v.keys())[:20])
                for sub in list(v.keys())[:3]:
                    sv = v[sub]
                    if isinstance(sv, dict):
                        print(f"  {sub}: dict 子键({len(sv)}) 前10:", list(sv.keys())[:10])
                    else:
                        print(f"  {sub}: {type(sv).__name__} len={len(sv) if hasattr(sv,'__len__') else ''}")

    # 全局搜索 "player" 相关
    print("\n=== player 标记扫描 ===")
    for m in re.finditer(r'"player"', json.dumps(data, ensure_ascii=False)):
        pass
    # 简化: 统计字符串出现
    blob = json.dumps(data, ensure_ascii=False)
    for s in ("player", "was_player", "playable"):
        print(f"  {s!r}: {blob.count(s)}")

if __name__ == "__main__":
    main()
