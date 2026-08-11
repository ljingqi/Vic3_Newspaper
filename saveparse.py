#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维多利亚3 存档解析器(不依赖 debug_log 的读取方法)。
========================================================
原理: .v3 存档是 SAV01033 信封格式, 内含元数据与 ZIP 压缩的 gamestate。
  - 信封头含: 版本号(如 1.13.9E2)、国家名等文本。
  - gamestate 是**二进制**(默认"压缩二进制"格式), 需 Rakaly melter 熔化
    或把游戏存档格式设为 Text(需 debug 模式)才能得到纯文本。

本工具: 读取信封元数据 + 提取 gamestate + 报告格式状态,
       为后续精确数值/文化名/战争数据解析做准备(可接入 journal.py)。

用法:
  python saveparse.py               扫描最新存档并报告
  python saveparse.py <路径.v3>     指定存档
"""
import io
import os
import re
import sys
import zipfile

SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents",
                        "Paradox Interactive", "Victoria 3", "save games")

def find_latest_v3():
    if not os.path.isdir(SAVE_DIR):
        return None
    v3s = [os.path.join(SAVE_DIR, f) for f in os.listdir(SAVE_DIR) if f.endswith(".v3")]
    if not v3s:
        return None
    return max(v3s, key=os.path.getmtime)

def parse_envelope(path):
    """读取 SAV 信封, 返回 (magic, version, texts, zip_offset, gamestate_bytes)。"""
    with open(path, "rb") as fp:
        data = fp.read()
    magic = data[:8].decode("utf-8", "replace")  # 通常是 SAV01033
    # 从信封头部抓取可见文本(版本号、国家名等)
    head = data[:4096].decode("utf-8", "replace")
    texts = re.findall(r"[一-鿿A-Za-z0-9_.\- ]{2,40}", head)
    idx = data.find(b"PK\x03\x04")
    gamestate = None
    gs_head = ""
    if idx > 0:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data[idx:]))
            for n in zf.namelist():
                gs = zf.read(n)
                gamestate = gs
                gs_head = gs[:8].hex()
        except Exception as e:
            return magic, texts, None, None, f"ZIP读取失败: {e}"
    return magic, texts, idx, (gs_head, len(gamestate) if gamestate else 0)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else find_latest_v3()
    if not path:
        print("未找到存档, 请先游玩让游戏写入 autosave.v3")
        return 1
    print(f"存档: {path}")
    magic, texts, zip_off, gs_info = parse_envelope(path)
    print(f"信封头: {magic}")
    print(f"元数据文本: {texts[:8]}")
    if zip_off:
        gs_head, gs_len = gs_info
        print(f"gamestate: {gs_len/1e6:.1f} MB, 头={gs_head}")
        if gs_head.startswith("ad55"):
            print("  → 二进制格式(默认), 需 [Rakaly melter](https://github.com/rakaly/parsers/releases)")
            print("    或: 游戏 debug 模式把『存档格式』设为 Text, 再扫描即可解析纯文本。")
        else:
            print("  → 疑似文本格式, 可进一步用 Clausewitz 解析器提取数据。")
    else:
        print("未找到 ZIP gamestate。")
    print("说明: 接入完整解析后, 可精确读取 GDP/生活水平/前三大文化名/战争参与方等 debug_log 拿不到的数据。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
