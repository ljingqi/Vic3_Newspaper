# -*- coding: utf-8 -*-
"""CK3 存档结构侦察脚本: 扫描明文 gamestate 的顶层结构、关键库与标记。"""
import re, sys, io

GS = r"D:\Journal\_scratch\ck3_gamestate.txt"

def find_brace_end(text, start):
    """从 text[start]=='{' 匹配配对 '}' (含嵌套字符串与注释)。"""
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
    print("读取 gamestate ...")
    with open(GS, encoding="utf-8", errors="replace") as fp:
        text = fp.read()
    n = len(text)
    print(f"总字符数: {n:,}")

    print("\n=== 前 1500 字符 ===")
    print(text[:1500])

    print("\n=== 顶层块 (缩进 0 的 key) ===")
    # 顶部通常是 meta_data={...} 然后 data 开始
    for m in re.finditer(r"(?m)^([a-zA-Z0-9_]+)=", text[:200000]):
        print(f"  {m.group(1)}")

    print("\n=== 关键标记出现次数 ===")
    for marker in ["player=yes", "living_characters", "dead_characters",
                   "memories", "war=", "battle=", "dynasty=", "dynasties",
                   "character_memory", "birth=", "death=", "death_date",
                   "killer", "employment_history", "player_character",
                   "active_wars", "all_wars"]:
        cnt = text.count(marker)
        print(f"  {marker!r}: {cnt}")

    print("\n=== player=yes 上下文 ===")
    for m in re.finditer(r"player=yes", text):
        s = max(0, m.start() - 400)
        e = min(n, m.end() + 100)
        seg = text[s:e]
        # 找所属人物块: 向前找 'x={' 形式的 id
        print("----")
        print(seg[:520].replace("\n", " "))
        if m.start() > 200000:
            break

if __name__ == "__main__":
    main()
