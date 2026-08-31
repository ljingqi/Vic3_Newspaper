# -*- coding: utf-8 -*-
"""检查明文 gamestate 的记忆管理器区域: 是否每个角色多条记忆(重复键)。"""
import re

GS = r"D:\Journal\_scratch\ck3_gamestate.txt"

def find_brace_end(text, start):
    depth = 0
    i = start
    n = len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1

def main():
    print("读取明文 gamestate ...")
    with open(GS, encoding="utf-8", errors="replace") as fp:
        text = fp.read()
    idx = text.find("character_memory_manager")
    print("character_memory_manager 位置:", idx)
    seg_start = max(0, idx - 200)
    print("=== 前缀 200 字符 ===")
    print(text[seg_start:idx + 50])
    # 找 manager 的 database 块
    db_kw = text.find("database", idx)
    brace = text.find("{", db_kw)
    end = find_brace_end(text, brace)
    print(f"\ndatabase 块: {brace} .. {end} (长度 {end - brace})")
    seg = text[brace:end]
    # 顶层键 (database 下缩进 2 tab 的 数字=)
    keys = re.findall(r'(?m)^\t\t([0-9]+)=', seg)
    print("database 顶层键数量:", len(keys))
    from collections import Counter
    c = Counter(keys)
    dup = {k: v for k, v in c.items() if v > 1}
    print("重复键数量:", len(dup), "共重复次数:", sum(dup.values()))
    top10 = sorted(dup.items(), key=lambda x: -x[1])[:15]
    for k, v in top10:
        print(f"  重复键 {k}: {v} 次")
    # 玩家 11368 的所有出现
    print("\n11368 出现次数:", c.get("11368"))
    # 打印每个 11368 块的内容(如果多个)
    for m in re.finditer(r'(?m)^\t\t11368=', seg):
        b = seg.find("{", m.start())
        e = find_brace_end(seg, b)
        print("--- 11368 块 ---")
        print(seg[m.start():e + 1][:500])
    # 打印前几个键的块, 看格式
    print("\n=== 前 3 个键的块 ===")
    for m in list(re.finditer(r'(?m)^\t\t([0-9]+)=', seg))[:3]:
        b = seg.find("{", m.start())
        e = find_brace_end(seg, b)
        print(f"--- key={m.group(1)} ---")
        print(seg[m.start():e + 1][:400])
        print()

if __name__ == "__main__":
    main()
