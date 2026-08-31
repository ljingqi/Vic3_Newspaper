# -*- coding: utf-8 -*-
"""主角一生记忆缓存 + 死后传记生成 流水线原型 (expck3)。

工作流 (对应「用每年自动存档读取主角相关人物记忆 → 主角死后触发生成」):
  1. scan    : 扫描 CK3 存档目录, 找出未并入缓存的存档 (按 meta_date 排序)
  2. melt    : rakaly json 熔化 → data/melt_<日期>.json (自动存档/手动存档格式均支持)
  3. extract : cache_lib.extract_snapshot 并入 expck3/cache/memories.json (跨年去重)
  4. detect  : 检查 cache.player_death (玩家角色 dead_data 出现即触发)
  5. bio     : 生成小传 md
  6. watch   : 循环执行 1-5, 玩家死后自动产出终传

用法:
  python pipeline.py scan           # 扫描并并入新存档, 打印状态与死亡检测结果
  python pipeline.py status         # 打印缓存状态
  python pipeline.py bio            # 生成小传 (output/边诚小传_867-869.md)
  python pipeline.py demo-death     # 模拟主角死亡, 演示「死后自动生成」链路
  python pipeline.py watch [秒]     # 循环模式
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache_lib as cl
import biography as bio

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE_PATH = os.path.join(HERE, "cache", "memories.json")
OUT_DIR = os.path.join(HERE, "output")
RAKALY = r"D:\Journal\tools\rakaly.exe"
DEFAULT_SAVE_DIR = (r"C:\Users\CHINE\Documents\Paradox Interactive"
                    r"\Crusader Kings III\save games")

# ---------------------------------------------------------------------------
# 存档读取
# ---------------------------------------------------------------------------

def read_save_envelope(path):
    """读取 SAV 信封明文头: 返回 (magic, meta_date, meta_player_name)。"""
    with open(path, "rb") as fp:
        head = fp.read(65536)
    magic = head[:8].decode("utf-8", "replace")
    def grab(patt):
        m = re.search(patt, head)
        return m.group(1).decode("utf-8", "replace") if m else None
    date = grab(rb"meta_date=([0-9.]+)")
    player = grab(rb'meta_player_name="([^"]*)"')
    return magic, date, player

def melt_save(save_path, out_path):
    """rakaly json 熔化存档 → out_path。"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    proc = subprocess.run([RAKALY, "json", save_path], capture_output=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"rakaly 失败: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    with open(out_path, "wb") as fp:
        fp.write(proc.stdout)
    return out_path

def scan_saves(save_dir):
    """返回 [{path, date, player}] 按日期排序。"""
    out = []
    if not os.path.isdir(save_dir):
        return out
    for fn in os.listdir(save_dir):
        if not fn.lower().endswith(".ck3"):
            continue
        p = os.path.join(save_dir, fn)
        try:
            magic, date, player = read_save_envelope(p)
        except Exception:
            continue
        if not date:
            continue
        out.append({"path": p, "date": date, "player": player, "magic": magic})
    out.sort(key=lambda x: cl.date_key(x["date"]) if hasattr(cl, "date_key") else x["date"])
    return out

def date_key(s):
    try:
        return tuple(int(x) for x in s.split("."))
    except Exception:
        return (9999, 0, 0)

def date_filekey(s):
    """'869.2.22' → '869_02_22' (与 melt 文件命名一致)。"""
    return "_".join(f"{int(x):02d}" for x in s.split("."))

# ---------------------------------------------------------------------------
# 流水线步骤
# ---------------------------------------------------------------------------

def step_scan(save_dir=DEFAULT_SAVE_DIR, dry=False):
    cache = cl.load_cache(CACHE_PATH)
    saves = scan_saves(save_dir)
    print(f"存档目录: {save_dir}")
    print(f"找到存档 {len(saves)} 个, 缓存已有来源: {cache.get('sources')}")
    print(f"缓存玩家: {cache.get('player_name')} (id={cache.get('player_id')})")
    new_saves = []
    for s in saves:
        if s["date"] in (cache.get("sources") or []):
            continue
        # 玩家名过滤: 缓存已锁定玩家时, 跳过其它玩家的存档 (避免无谓熔化)
        if cache.get("player_name") and s["player"] and \
                s["player"] != cache.get("player_name"):
            print(f"  [跳过] {os.path.basename(s['path'])} 玩家 {s['player']} 与缓存不一致")
            continue
        new_saves.append(s)
    print(f"待并入新存档: {[(s['date'], os.path.basename(s['path'])) for s in new_saves]}")
    for s in new_saves:
        date = s["date"]
        melt_path = os.path.join(DATA, f"melt_{date_filekey(date)}.json")
        if not os.path.isfile(melt_path):
            print(f"  熔化 {os.path.basename(s['path'])} ({s['magic']}) ...")
            melt_save(s["path"], melt_path)
        melt = cl.load_melt(melt_path)
        ok = cl.extract_snapshot(cache, melt, date)
        if ok:
            print(f"  并入 {date}: 相关人物 {len(cache['characters'])}")
    cl.save_cache(cache, CACHE_PATH)
    return cache

def step_detect(cache):
    death = cache.get("player_death")
    if death:
        print(f"[触发] 主角（{cache['player_id']}）已殁于 {death.get('date')}，"
              f"原因 {death.get('reason')}，凶手 {death.get('killer')}")
    else:
        print(f"[未触发] 主角（{cache['player_id']}）仍在世。")
    return death

def step_bio(cache, out_name=None):
    latest = cache.get("last_date")
    melt_path = os.path.join(DATA, f"melt_{date_filekey(latest)}.json")
    md = bio.generate_biography(cache, melt_path,
                                period=f"治政{len(cache.get('sources') or [])}年快照 · 截至 {latest}")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_name = out_name or f"边诚小传_至{latest}.md"
    out_path = os.path.join(OUT_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(md)
    print("已生成:", out_path)
    return out_path

def step_demo_death():
    """模拟主角死亡 → 演示「死后自动生成终传」链路。"""
    cache = cl.load_cache(CACHE_PATH)
    demo = json.loads(json.dumps(cache))          # 深拷贝, 不污染真实缓存
    demo["player_death"] = {
        "date": "869.12.31",
        "reason": "death_old_age",
        "killer": None,
    }
    print("== 演示: 模拟主角死亡 ==")
    print("  1) 下一年度存档扫描 → extract_snapshot 检测到玩家 dead_data")
    print("  2) cache.player_death 被写入:", demo["player_death"])
    death = step_detect(demo)
    if death:
        print("  3) 触发流水线 → 生成「终传」md")
        latest = demo.get("last_date")
        melt_path = os.path.join(DATA, f"melt_{date_filekey(latest)}.json")
        md = bio.generate_biography(demo, melt_path,
                                    period=f"主角殁于 {death.get('date')}（{death.get('reason')}），终传由历年记忆缓存自动汇编")
        out_path = os.path.join(OUT_DIR, "demo_主角死后自动生成_终传.md")
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(md)
        print("  已生成:", out_path)
        print()
        print(md.splitlines()[0])
        print(md.splitlines()[1])
    print("\n== 演示完成: 「每年自动存档读记忆 → 主角死后自动生成」工作流成立 ==")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        cache = step_scan()
        step_detect(cache)
    elif cmd == "status":
        cache = cl.load_cache(CACHE_PATH)
        n_mem = sum(len(c.get("memories") or []) for c in cache["characters"].values())
        print(f"缓存: {CACHE_PATH}")
        print(f"  玩家: {cache['player_id']}  来源档: {cache['sources']}  最后日期: {cache['last_date']}")
        print(f"  相关人物: {len(cache['characters'])}  累计记忆: {n_mem}")
        step_detect(cache)
    elif cmd == "bio":
        cache = cl.load_cache(CACHE_PATH)
        step_bio(cache)
    elif cmd == "demo-death":
        step_demo_death()
    elif cmd == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
        while True:
            try:
                cache = step_scan()
                death = step_detect(cache)
                if death:
                    step_bio(cache, out_name=f"终传_{date_filekey(death.get('date') or '')}.md")
                    print("终传已生成, 停止监控。")
                    break
            except Exception as e:
                print("扫描异常:", e)
            print(f"休眠 {interval}s ...")
            time.sleep(interval)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
