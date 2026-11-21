#!/usr/bin/env python3
"""实验 A 的配对统计(2026-11-08):完整分层 vs 其余各臂。
分析单元:(探针, 种子) 配对;成败用 McNemar 精确检验(Holm 校正 5 个比较);
大模型调用 / 花费 / 延迟 / 仿真时长的差用探针层面的聚类 bootstrap 给 95% 区间(种子在探针内相关)。
  .venv/bin/python pms/stats_A.py --tag lvA [--families ...]
"""
import argparse
import json
from collections import defaultdict
from math import comb
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CONDS = ["flat", "flat_diag", "llm_l1", "no_A", "no_diag"]


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out, run = [0.0] * len(ps), 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def boot(diffs_by_probe, B=5000, seed=0):
    rng = np.random.default_rng(seed)
    keys = list(diffs_by_probe)
    if not keys:
        return (np.nan, np.nan, np.nan)
    arr = [np.asarray(diffs_by_probe[k], float) for k in keys]
    est = float(np.mean(np.concatenate(arr)))
    bs = []
    for _ in range(B):
        pick = rng.integers(len(keys), size=len(keys))
        bs.append(np.mean(np.concatenate([arr[i] for i in pick])))
    return (est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="lvA")
    ap.add_argument("--families", nargs="*")
    a = ap.parse_args()
    d = ROOT / "results" / "sweep" / a.tag / "levels"
    R = defaultdict(dict)
    for f in d.glob("*.json"):
        r = json.loads(f.read_text())
        if r.get("cond") is None or (a.families and r["family"] not in a.families):
            continue
        R[(r["family"], r["probe"], r["seed"])][r["cond"]] = r
    out = {}
    print(f"{'对比':22s} {'配对':>4s} {'完整过':>6s} {'对方过':>6s} {'只完整过':>8s} {'只对方过':>8s} {'p(McNemar)':>10s} {'Holm':>6s} | "
          "Δ调用 / Δ花费$ / Δ延迟s(对方 − 完整,探针聚类 bootstrap 95%)")
    rows, ps = [], []
    for c in CONDS:
        pairs = [(k, v["full"], v[c]) for k, v in R.items() if "full" in v and c in v]
        b = sum(bool(x.get("final_pass")) and not bool(y.get("final_pass")) for _, x, y in pairs)
        cc = sum(bool(y.get("final_pass")) and not bool(x.get("final_pass")) for _, x, y in pairs)
        p = mcnemar_exact(b, cc)
        dif = {m: defaultdict(list) for m in ("calls", "cost_usd", "latency_s")}
        for (fam, pr, s), x, y in pairs:
            for m in dif:
                dif[m][pr].append(((y.get("llm") or {}).get(m, 0) or 0) - ((x.get("llm") or {}).get(m, 0) or 0))
        bt = {m: boot(dif[m]) for m in dif}
        rows.append((c, len(pairs), sum(bool(x.get("final_pass")) for _, x, _ in pairs), sum(bool(y.get("final_pass")) for _, _, y in pairs), b, cc, p, bt))
        ps.append(p)
    hp = holm(ps)
    for (c, n, fx, fy, b, cc, p, bt), h in zip(rows, hp):
        fmt = lambda t, k: f"{t[0]:+.{k}f} [{t[1]:+.{k}f}, {t[2]:+.{k}f}]"
        print(f"full vs {c:13s} {n:4d} {fx:6d} {fy:6d} {b:8d} {cc:8d} {p:10.2g} {h:6.2g} | {fmt(bt['calls'], 2)} / {fmt(bt['cost_usd'], 4)} / {fmt(bt['latency_s'], 1)}")
        out[c] = {"pairs": n, "full_pass": fx, "other_pass": fy, "only_full": b, "only_other": cc, "p": p, "p_holm": h,
                  "d_calls": bt["calls"], "d_cost": bt["cost_usd"], "d_latency": bt["latency_s"]}
    print("\n按族:完整 vs 平铺(只完整过 / 只平铺过)")
    fams = sorted({k[0] for k in R})
    for fam in fams:
        line = f"  {fam:10s}"
        for c in CONDS:
            pairs = [(v["full"], v[c]) for k, v in R.items() if k[0] == fam and "full" in v and c in v]
            b = sum(bool(x.get("final_pass")) and not bool(y.get("final_pass")) for x, y in pairs)
            cc = sum(bool(y.get("final_pass")) and not bool(x.get("final_pass")) for x, y in pairs)
            line += f" | {c} {b}/{cc}(n={len(pairs)})"
        print(line)
    (ROOT / "results" / "sweep" / a.tag / "stats_A.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
