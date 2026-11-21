#!/usr/bin/env python3
"""论文仿真实验章节用到的全部数字,一次算出(2026-11-09)。只读结果文件,不跑仿真。
  .venv/bin/python pms/paper_numbers.py > ccfa-workfiles/manuscript/spinabrain_preprint/numbers.json
"""
import json
import math
from collections import defaultdict
from math import comb
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIX = ("comp", "n121", "strategy", "disturb", "solver")
CONDS = ("full", "flat", "flat_diag", "llm_l1", "no_A", "no_diag")


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h)), round(100 * (c + h))]


def sign_p(b, c):
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def boot_ratio(groups, fa, fb, B=5000, seed=0):
    """1 − Σa/Σb 的探针聚类 bootstrap(groups: probe -> list of (ra, rb))。"""
    rng = np.random.default_rng(seed)
    keys = list(groups)
    A = lambda ks: sum(fa(x) for k in ks for x in groups[k])
    Bs = lambda ks: sum(fb(x) for k in ks for x in groups[k])
    est = 1 - A(keys) / Bs(keys)
    bs = []
    for _ in range(B):
        ks = [keys[i] for i in rng.integers(len(keys), size=len(keys))]
        if Bs(ks) > 0:
            bs.append(1 - A(ks) / Bs(ks))
    return {"reduction_pct": round(100 * est), "ci": [round(100 * np.percentile(bs, 2.5)), round(100 * np.percentile(bs, 97.5))],
            "a": A(keys), "b": Bs(keys), "n_probes": len(keys)}


def boot_mean_diff(groups, f, B=5000, seed=0):
    rng = np.random.default_rng(seed)
    keys = list(groups)
    arr = [np.array([f(x) for x in groups[k]], float) for k in keys]
    est = float(np.mean(np.concatenate(arr)))
    bs = [np.mean(np.concatenate([arr[i] for i in rng.integers(len(keys), size=len(keys))])) for _ in range(B)]
    return {"mean": round(est, 3), "ci": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)], "n_probes": len(keys)}


g = lambda r, k: ((r.get("llm") or {}).get(k, 0) or 0)
out = {}

# ---- A 消融
R = defaultdict(dict)
for f in (ROOT / "results/sweep/lvA/levels").glob("*.json"):
    r = json.loads(f.read_text())
    R[(r["family"], r["probe"], r["seed"])][r["cond"]] = r
fam_tab = {}
for fam in FIX + ("base", "infeasible", "localopt"):
    fam_tab[fam] = {c: f"{sum(bool(v[c].get('final_pass')) for k, v in R.items() if k[0] == fam and c in v)}/"
                       f"{sum(1 for k, v in R.items() if k[0] == fam and c in v)}" for c in CONDS}
out["A_family_table"] = fam_tab
out["A_fixable_totals"] = {c: sum(bool(v[c].get("final_pass")) for k, v in R.items() if k[0] in FIX and c in v) for c in CONDS}
for other in ("flat", "flat_diag", "llm_l1", "no_A", "no_diag"):
    pairs = [(k, v["full"], v[other]) for k, v in R.items() if k[0] in FIX + ("base", "infeasible", "localopt") and "full" in v and other in v]
    b = sum(bool(x.get("final_pass")) and not bool(y.get("final_pass")) for _, x, y in pairs)
    c = sum(bool(y.get("final_pass")) and not bool(x.get("final_pass")) for _, x, y in pairs)
    per = defaultdict(lambda: [0, 0])
    for (fam, pr, s), x, y in pairs:
        per[pr][0] += bool(x.get("final_pass")); per[pr][1] += bool(y.get("final_pass"))
    pb = sum(a > d for a, d in per.values()); pc = sum(d > a for a, d in per.values())
    fixp = [(k, x, y) for k, x, y in pairs if k[0] in FIX]
    out[f"A_full_vs_{other}"] = {"pairs": len(pairs), "full_pass": sum(bool(x.get("final_pass")) for _, x, _ in pairs),
                                 "other_pass": sum(bool(y.get("final_pass")) for _, _, y in pairs), "only_full": b, "only_other": c,
                                 "mcnemar_p": sign_p(b, c), "probe_level": [pb, pc], "probe_sign_p": round(sign_p(pb, pc), 4),
                                 "fixable_full": sum(bool(x.get("final_pass")) for _, x, _ in fixp),
                                 "fixable_other": sum(bool(y.get("final_pass")) for _, _, y in fixp), "fixable_n": len(fixp)}
    grp = defaultdict(list)
    for (fam, pr, s), x, y in pairs:
        grp[pr].append((x, y))
    out[f"A_full_vs_{other}"]["calls_diff_other_minus_full"] = boot_mean_diff(grp, lambda t: g(t[1], "calls") - g(t[0], "calls"))
# 两边都修好的配对:开销
grp = defaultdict(list)
for k, v in R.items():
    if "full" in v and "flat" in v and v["full"].get("final_pass") and v["flat"].get("final_pass"):
        grp[k[1]].append((v["full"], v["flat"]))
out["A_matched_success_full_vs_flat"] = {"calls": boot_ratio(grp, lambda t: g(t[0], "calls"), lambda t: g(t[1], "calls")),
                                         "cost": boot_ratio(grp, lambda t: g(t[0], "cost_usd"), lambda t: g(t[1], "cost_usd")),
                                         "n_pairs": sum(len(x) for x in grp.values())}
# 诊断(局部最优 + 停滞,含扩充族)
grp = defaultdict(list); passes = [0, 0]
for k, v in R.items():
    if k[0] in ("localopt", "localopt_x", "solver", "solver_x") and "full" in v and "no_diag" in v:
        grp[k[1]].append((v["full"], v["no_diag"]))
        passes[0] += bool(v["full"].get("final_pass")); passes[1] += bool(v["no_diag"].get("final_pass"))
out["diag_calls"] = {**boot_ratio(grp, lambda t: g(t[0], "calls"), lambda t: g(t[1], "calls")), "n_pairs": sum(len(x) for x in grp.values()),
                     "pass_full_vs_nodiag": passes}
for fams, name in ((("localopt", "localopt_x"), "diag_localopt"), (("solver", "solver_x"), "diag_solver")):
    xs = [(v["full"], v["no_diag"]) for k, v in R.items() if k[0] in fams and "full" in v and "no_diag" in v]
    out[name] = {"n": len(xs), "calls": [sum(g(a, "calls") for a, _ in xs), sum(g(b, "calls") for _, b in xs)],
                 "pass": [sum(bool(a.get("final_pass")) for a, _ in xs), sum(bool(b.get("final_pass")) for _, b in xs)]}
# 无效输出导致的平铺失败
inv = 0; flat_fail = 0
for k, v in R.items():
    if "flat" in v and k[0] in FIX + ("base", "infeasible", "localopt") and not v["flat"].get("final_pass"):
        flat_fail += 1
        if "契约检查不通过" in json.dumps(v["flat"].get("replans") or [], ensure_ascii=False) + str(v["flat"].get("abort_reason")):
            inv += 1
out["flat_failures"] = {"total": flat_fail, "invalid_output": inv}

# ---- 混合故障(监测)
rows = []
for f in sorted((ROOT / "results/sweep/lvM/runs").glob("*.json")):
    pass
inst = json.loads((ROOT / "results/sweep/lvM/instances.json").read_text())
M = []
for x in inst:
    fa = ROOT / f"results/sweep/lvM/runs/i{x['id']:03d}_full.json"; fb = ROOT / f"results/sweep/lvM/runs/i{x['id']:03d}_noA.json"
    if fa.exists() and fb.exists():
        a, b = json.loads(fa.read_text()), json.loads(fb.read_text())
        rule = lambda r: sum(1 for u in r.get("rule_updates", []) if u.get("applied"))
        M.append((bool(a["final_pass"]), bool(b["final_pass"]), rule(a), rule(b)))
d = [mb - ma for _, _, ma, mb in M]
rng = np.random.default_rng(0)
bs = [np.mean(rng.choice(d, len(d))) for _ in range(5000)] if d else [0]
out["monitor_mixed"] = {"n": len(M), "pass_full": sum(x[0] for x in M), "pass_noA": sum(x[1] for x in M),
                        "rule_updates_full": sum(x[2] for x in M), "rule_updates_noA": sum(x[3] for x in M),
                        "diff_mean": round(float(np.mean(d)), 2) if d else None,
                        "diff_ci": [round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]}

print(json.dumps(out, ensure_ascii=False, indent=1))
