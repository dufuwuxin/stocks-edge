#!/usr/bin/env python3
"""
longrun_collect.py — Codespace 长跑采集 (突破 Actions 6h 限制)

用途:
  1. 补全 K 线覆盖率 (当前 2577/5343 ≈ 48%, 腾讯单次约 1750 次后 501 限流,
     Actions 单次 5min 跑不完 → 放 Codespace 里错峰分批跑数小时)
  2. 分钟级实时采集 (交易时段每 1min 拉一次, Actions cron 最快只能 5min)

设计:
  - 断点续传: 进度写 data/bulk/_longrun_progress.json, 中断后从断点继续
  - 限流自适应: 遇到 501/429 自动退避 (60s → 120s → 300s)
  - 增量写入: 每批立即追加到 day_qfq_recent.csv, 不攒在内存
  - 可中断: Ctrl+C 安全退出, 进度已保存

用法 (Codespace 内):
  python3 scripts/longrun_collect.py kline           # 补K线, 跑到全覆盖
  python3 scripts/longrun_collect.py kline --max-hours 4
  python3 scripts/longrun_collect.py realtime        # 分钟级实时采集 (盘中)
"""
import argparse
import glob
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
      "Referer": "https://gu.qq.com/"}

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from paths import BULK
except Exception:
    BULK = os.environ.get("STOCKS_KLINE_BULK") or "/workspaces/stocks-data-kline/data/bulk"

PROGRESS = os.path.join(BULK, "_longrun_progress.json")
RECENT = os.path.join(BULK, "day_qfq_recent.csv")
UNIVERSE = os.path.join(BULK, "universe.csv")


def log(msg):
    print(f"[{datetime.now(CST):%H:%M:%S}] {msg}", flush=True)


def load_universe():
    codes = []
    if not os.path.exists(UNIVERSE):
        log(f"universe 不存在: {UNIVERSE}")
        return codes
    with open(UNIVERSE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            codes.append(line.split("|")[0].strip())
    return [c for c in codes if c]


def load_covered():
    """已覆盖的代码集合 (所有 bulk csv + recent)"""
    have = set()
    files = glob.glob(os.path.join(BULK, "day_qfq_*.csv"))
    for p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                have.add(line.split("|")[0].strip())
    return have


def load_progress():
    if os.path.exists(PROGRESS):
        try:
            return json.load(open(PROGRESS, encoding="utf-8"))
        except Exception:
            pass
    return {"done": [], "failed": [], "runs": 0, "last_ts": None}


def save_progress(prog):
    prog["last_ts"] = datetime.now(CST).isoformat(timespec="seconds")
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False)


def fetch_kline(code, n=120):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,,,{n},qfq")
    for attempt in range(3):
        try:
            body = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                          timeout=15).read()
            d = json.loads(body.decode("utf-8"))
            node = (d.get("data") or {}).get(code) or {}
            arr = node.get("qfqday") or node.get("day") or []
            rows = []
            for r in arr:
                if len(r) < 6:
                    continue
                try:
                    rows.append([r[0], float(r[1]), float(r[2]),
                                 float(r[3]), float(r[4]), float(r[5])])
                except ValueError:
                    continue
            return rows, None
        except urllib.error.HTTPError as e:
            if e.code in (501, 429):
                return [], f"ratelimit_{e.code}"
            return [], f"http_{e.code}"
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
    return [], "network"


def run_kline(max_hours=4.0, batch_pause=0.8):
    """补K线主循环"""
    t0 = time.time()
    universe = load_universe()
    covered = load_covered()
    prog = load_progress()
    prog["runs"] = prog.get("runs", 0) + 1

    todo = [c for c in universe if c not in covered]
    log(f"universe={len(universe)} covered={len(covered)} todo={len(todo)} "
        f"(第 {prog['runs']} 轮)")

    if not todo:
        log("已全覆盖 ✅")
        return 0

    backoff = 60
    n_ok = 0
    n_fail = 0
    out = open(RECENT, "a", encoding="utf-8")

    try:
        for i, code in enumerate(todo):
            if time.time() - t0 > max_hours * 3600:
                log(f"达到时间上限 {max_hours}h, 退出 (下次继续)")
                break

            rows, err = fetch_kline(code)
            if rows:
                for r in rows:
                    out.write(f"{code}|{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}\n")
                out.flush()
                n_ok += 1
                backoff = 60
                if code not in prog["done"]:
                    prog["done"].append(code)
            else:
                n_fail += 1
                if err and err.startswith("ratelimit"):
                    log(f"限流 {err}, 退避 {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 600)
                else:
                    prog["failed"].append(code)
                save_progress(prog)
                continue

            if n_ok % 100 == 0:
                cov = len(covered) + n_ok
                log(f"进度 {i+1}/{len(todo)}  新增{n_ok}  失败{n_fail}  "
                    f"覆盖率 {cov}/{len(universe)} ({cov/len(universe)*100:.1f}%)")
                save_progress(prog)

            time.sleep(batch_pause + random.uniform(0, 0.3))
    except KeyboardInterrupt:
        log("用户中断")
    finally:
        out.close()
        save_progress(prog)

    covered2 = load_covered()
    log(f"本轮结束: 新增 {n_ok}, 失败 {n_fail}, 覆盖率 "
        f"{len(covered2)}/{len(universe)} ({len(covered2)/len(universe)*100:.1f}%)")
    return 0


def run_realtime(interval=60):
    """分钟级实时采集 (交易时段)"""
    log(f"实时采集启动, 每 {interval}s (Ctrl+C 退出)")
    live = os.path.join(os.path.dirname(BULK), "market")
    os.makedirs(live, exist_ok=True)

    def in_session():
        now = datetime.now(CST)
        if now.weekday() >= 5:
            return False
        m = now.hour * 60 + now.minute
        return 555 <= m <= 905

    n = 0
    try:
        while True:
            if not in_session():
                log("非交易时段, 等待...")
                time.sleep(60)
                continue
            codes = load_universe()
            quotes = {}
            for i in range(0, len(codes), 60):
                chunk = codes[i:i + 60]
                url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
                try:
                    body = urllib.request.urlopen(
                        urllib.request.Request(url, headers=UA), timeout=15).read()
                    text = body.decode("gbk", "replace")
                    import re
                    for m in re.finditer(r'v_([a-z0-9]+)="([^"]*)"', text):
                        p = m.group(2).split("~")
                        if len(p) < 40:
                            continue
                        try:
                            quotes[m.group(1)] = {
                                "code": m.group(1), "name": p[1],
                                "price": float(p[3] or 0),
                                "prev_close": float(p[4] or 0),
                                "open": float(p[5] or 0),
                                "high": float(p[33] or 0),
                                "low": float(p[34] or 0),
                                "chg_pct": float(p[32] or 0),
                                "turnover": float(p[38] or 0),
                                "pe": float(p[39] or 0),
                                "mktcap": (float(p[44] or 0)) * 1e8,
                                "floatcap": (float(p[45] or 0)) * 1e8,
                                "pb": float(p[46] or 0),
                                "vol_ratio": 1.0,
                                "time": p[30] or "",
                            }
                        except (ValueError, IndexError):
                            continue
                except Exception as e:
                    log(f"batch {i//60+1} 失败: {e}")
                time.sleep(0.2)

            ds = datetime.now(CST).strftime("%Y-%m-%d")
            with open(os.path.join(live, f"snapshot_{ds}.json"), "w", encoding="utf-8") as f:
                json.dump(quotes, f, ensure_ascii=False)
            n += 1
            log(f"第 {n} 次快照: {len(quotes)} 只 -> snapshot_{ds}.json")
            time.sleep(interval)
    except KeyboardInterrupt:
        log("退出")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["kline", "realtime"])
    ap.add_argument("--max-hours", type=float, default=4.0)
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    if args.mode == "kline":
        return run_kline(max_hours=args.max_hours)
    if args.mode == "realtime":
        return run_realtime(interval=args.interval)


if __name__ == "__main__":
    sys.exit(main())
