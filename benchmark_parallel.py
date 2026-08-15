#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报纸+杂志「顺序 vs 并行」基准 (不调用真实 DeepSeek API)。

做法: 用 output/巴西/data/snapshot_1873.json + tools/melt.json 作为同一份真实
存档数据, 把 journal.call_deepseek 替换成"睡固定秒数 + 返回固定文本"的假实现,
分别跑:
  1) 原版顺序: make_newspaper 完成后才跑 make_magazine (watch 旧行为);
  2) 新版并行: journal_save._generate_async (两线程同时跑报纸与杂志);
比较总墙钟耗时与两份输出 md 是否一致。

用法:
  python benchmark_parallel.py --sim 0           # 只测真实数据准备/IO, 不模拟 LLM
  python benchmark_parallel.py                    # 默认: 抬头/导言 5s, 正文板块 10s
  python benchmark_parallel.py --short 6 --long 12
"""
import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import journal
import journal_save

SNAP_PATH = os.path.join(REPO, "output", "巴西", "data", "snapshot_1873.json")
MELT_PATH = os.path.join(REPO, "tools", "melt.json")


def load_fixture():
    with open(SNAP_PATH, encoding="utf-8") as fp:
        snap = json.load(fp)
    snap.pop("_meta", None)  # 与 watch 线程里 extract_full_snapshot 的产物一致
    with open(MELT_PATH, "rb") as fp:
        melted = fp.read()
    return snap, melted


def make_fake_call(year, short_sim, long_sim):
    """假 DeepSeek 调用: 按消息类型睡不同秒数, 返回足以走完渲染管线的固定文本。"""
    def fake(messages, cfg, retries=3):
        sys_msg = ""
        if messages and isinstance(messages[0], dict):
            sys_msg = messages[0].get("content", "") or ""
        if "报纸的总编辑" in sys_msg:
            kind, sim = "masthead", short_sim
        elif "杂志的总编辑" in sys_msg:
            kind, sim = "intro", short_sim
        elif "开篇板块" in sys_msg or "文章标题" in sys_msg:
            kind, sim = "lead", long_sim
        else:
            kind, sim = "section", long_sim
        if sim > 0:
            time.sleep(sim)
        if kind == "masthead":
            return (f"# 《测试报》\n"
                    f"国名：{year}测试国｜都城：测试都｜政体：君主制｜年份：{year}")
        if kind == "intro":
            return (f"# 《测试刊》\n"
                    f"国名：测试国｜都城：测试都｜政体：君主制｜年份：{year}\n\n"
                    f"测试导言正文。")
        if kind == "lead":
            return "测试文章标题\n\n### 测试\n\n正文内容"
        return "### 测试\n\n正文内容"
    return fake


def run_sequential(year, snap, melted, cfg):
    """原版行为: 报纸全部生成完, 再生成杂志。"""
    journal.SESSION["folder"] = None
    ctx = journal_save.SaveContext(melted) if melted is not None else None
    t0 = time.perf_counter()
    journal_save.make_newspaper(year=year, force=True, snap=snap, ctx=ctx)
    journal_save.make_magazine(year=year, force=True,
                               melted=melted, snap=snap, ctx=ctx)
    return time.perf_counter() - t0


def run_parallel(year, snap, melted):
    """新版行为: _generate_async 前置步骤一次, 报纸/杂志两线程并行。"""
    journal.SESSION["folder"] = None
    t0 = time.perf_counter()
    journal_save._generate_async(year, snap, melted)
    return time.perf_counter() - t0


def read_body(path):
    """去掉 md 头部带生成时间的注释行后取正文 (便于两份输出比较)。"""
    with open(path, encoding="utf-8") as fp:
        txt = fp.read()
    i = txt.find("-->")
    return txt[i + 3:].lstrip() if i >= 0 else txt


def main():
    ap = argparse.ArgumentParser(description="报纸+杂志 顺序 vs 并行 基准 (不调 API)")
    ap.add_argument("--short", type=float, default=5.0,
                    help="模拟抬头/导言单次 LLM 耗时秒 (默认 5)")
    ap.add_argument("--long", type=float, default=10.0,
                    help="模拟正文板块单次 LLM 耗时秒 (默认 10)")
    ap.add_argument("--sim", type=float, default=None,
                    help="快捷开关: --sim 0 等价于 --short 0 --long 0")
    args = ap.parse_args()
    if args.sim is not None:
        args.short = args.long = args.sim

    snap0, melted = load_fixture()
    year = snap0.get("year")
    print(f"测试数据: {SNAP_PATH} (year={year}, snap={len(json.dumps(snap0))}B) "
          f"+ melt={os.path.getsize(MELT_PATH)/1e6:.0f}MB")
    print(f"模拟 LLM: 抬头/导言={args.short:.1f}s/次, 正文板块={args.long:.1f}s/次 "
          f"(未调用真实 API)")

    base_cfg = journal.load_config()
    tmp_root = tempfile.mkdtemp(prefix="journal_bench_")
    d_seq = os.path.join(tmp_root, "seq")
    d_par = os.path.join(tmp_root, "par")
    os.makedirs(d_seq)
    os.makedirs(d_par)
    cfg_seq = dict(base_cfg)
    cfg_seq["journal_dir"] = d_seq
    cfg_par = dict(base_cfg)
    cfg_par["journal_dir"] = d_par

    journal.call_deepseek = make_fake_call(year, args.short, args.long)
    try:
        journal.load_config = lambda: cfg_seq
        t_seq = run_sequential(year, copy.deepcopy(snap0), melted, cfg_seq)
        journal.load_config = lambda: cfg_par
        t_par = run_parallel(year, copy.deepcopy(snap0), melted)
    finally:
        journal.load_config = lambda: dict(base_cfg)

    # 输出一致性: 同一份数据, 两种调度的成品应逐字一致 (仅头部生成时间不同)
    folders = {"seq": d_seq, "par": d_par}
    diffs = []
    for name in ("报纸", "杂志"):
        seq_path = os.path.join(folders["seq"], "巴西", f"{name}_1873.md")
        par_path = os.path.join(folders["par"], "巴西", f"{name}_1873.md")
        if not (os.path.exists(seq_path) and os.path.exists(par_path)):
            diffs.append(f"{name}: 输出缺失 seq={os.path.exists(seq_path)} "
                         f"par={os.path.exists(par_path)}")
            continue
        if read_body(seq_path) != read_body(par_path):
            diffs.append(f"{name}: 正文不一致")
    if diffs:
        print("输出一致性: 不一致 -> " + "; ".join(diffs))
    else:
        print("输出一致性: 报纸/杂志正文逐字一致 OK")

    print(f"\n结果 (同一份存档数据, 墙钟秒):")
    print(f"  原版顺序: {t_seq:8.2f}s")
    print(f"  新版并行: {t_par:8.2f}s")
    saved = t_seq - t_par
    pct = saved / t_seq * 100 if t_seq else 0
    print(f"  并行节省: {saved:7.2f}s ({pct:.1f}%)")

    shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
