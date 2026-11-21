#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-XW 分析(plan_exec_weighted.md v2 §5–§8;2026-10-26 新建,只新建文件)。

读冻结的 cases_xw.json / decisions_xw.json 与仿真结果(只读;R2 目录经 exec_weighted.peek_sim 只读复用),按原契约逐维验收
(EB.evaluate),算 §6 的终点、§7 的检验与区间、灵敏度表、按构造相同格的标注、功效,写 results/exp_exec_weighted/analysis_xw.{md,json}。

标注口径(plan_supplement §0.7):确认性族 F1–F4 标【补充·预先登记】;其余一律【描述】。不显著的对比只写「没有检出差异(差值 95% 区间 [..])」,
不写成等价;「A ≈ B2」只在预先登记的 TOST(±0.10 Δ,两个单侧簇级符号翻转各 α = 0.05)成立时写。

确认性族(§7.2,Holm m = 4,α = 0.05,单侧,簇级精确符号翻转,端点 = 3 个种子的均值;无效执行与拒收记最差):
    F1  H*(簇 = (任务, 方向))  A vs B1  硬界违反量 v      v_B1 − v_A > 0
    F2  H*                      A vs B2  v                 v_B2 − v_A > 0
    F3  H* 中对 A、B3 都绑定的单元  A vs B3  v             v_B3 − v_A > 0(退路:与 B1 / B2 同键 → 取 F1 / F2 的 p;绑定簇 < 8 → 描述,p = 1)
    F4  C-a(簇 = (任务, 变体))  A vs A\\P  任务维最差余量 m   m_A − m_A\\P > 0

用法:
    .venv/bin/python exp_repair/analyze_exec_weighted.py                 # 冻结登记表 + 本机仿真
    .venv/bin/python exp_repair/analyze_exec_weighted.py --host sprl1-hostname   # 读远程主机跑的目录(sims/<host>/)
    .venv/bin/python exp_repair/analyze_exec_weighted.py --allow-unfrozen --partial  # 开发 / 冒烟:未冻结、缺仿真的作业跳过
    .venv/bin/python exp_repair/analyze_exec_weighted.py power           # §8 功效表(模拟)
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("exec_weighted", HERE / "exec_weighted.py")
XW = importlib.util.module_from_spec(_spec)
sys.modules["exec_weighted"] = XW
_spec.loader.exec_module(XW)
EB, ST, CM = XW.EB, XW.ST, XW.CM
import numpy as np                                                       # noqa: E402

LABEL_CONF, LABEL_DESC = "【补充·预先登记】", "【描述】"
FAMILY = ("F1", "F2", "F3", "F4")
ALPHA = 0.05
TOST_MARGIN = 0.10
SEEDS = (0, 1, 2)


# ═══════════════════════════════════════════ 读取
def peek_host(task: str, bias, cmd: dict, host: str) -> dict | None:
    """只读查 host 主机跑的目录;本机且门 r2_bitid 通过时空覆盖表 A 复用 R2 目录。"""
    if host == XW.HOST:
        return XW.peek_sim(task, bias, cmd)
    _ks, h = XW.sim_key(task, bias, cmd, host=host)
    d = XW.OUT / "sims" / host / f"{task}_{h}"
    if not d.exists():
        return None
    try:
        return XW.load_xw(d)
    except XW.Incomplete:
        return None


def collect(reg: dict, dx: dict, host: str, partial: bool) -> tuple:
    """作业 → 逐行指标。InfraError 的单元整组配对剔除(披露);FrameworkError 直接停。"""
    units = {u["uid"]: u for u in reg["test"]["units"]}
    dec = XW.r2_dec()
    J = XW.jobs_test(list(units.values()), dx, reg["test"].get("sens"))
    J += XW.jobs_ref(dx, [u for u in units.values() if u["cls"] == "N" and u["sub"] == "S0"])
    rows, missing, infra = [], [], set()
    cache: dict = {}
    for j in J:
        u, cmd, info = XW.job_cmd(j, units, dec)
        k = XW.ckey(u["task"], u["bias"], cmd)
        if k not in cache:
            try:
                cache[k] = ("ok", peek_host(u["task"], u["bias"], cmd, host))
            except XW.InfraError as e:
                cache[k] = ("infra", str(e))
        st, r = cache[k]
        if st == "infra":
            infra.add(u["uid"])
            continue
        if r is None:
            missing.append({"uid": u["uid"], "arm": j["arm"], "cfg": j["cfg"], "seed": j["seed"], "ik": j["ik"], "role": j["role"]})
            continue
        mt = XW.unit_metrics(u, r, dec)
        xr = r.get("xw_result") or {}
        rows.append({**{x: j[x] for x in ("uid", "arm", "cfg", "seed", "ik", "role")}, "cls": u["cls"], "sub": u["sub"], "task": u["task"],
                     "cluster": u["cluster"], "key": k, "src": r.get("src"), "dir": r.get("dir"), "m": mt,
                     "xw_ik_fallback": xr.get("xw_ik_fallback"), "refusal_bypassed": bool(xr.get("refusal_bypassed")),
                     "bookkeeping_errors": len(xr.get("bookkeeping_errors") or [])})
    rows = [r for r in rows if r["uid"] not in infra]
    if missing and not partial:
        raise SystemExit(f"缺 {len(missing)} 个仿真(例:{missing[:3]});开发时用 --partial")
    return rows, missing, sorted(infra), units


def cfg_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a[0]) - float(b[0])) < 1e-12 and abs(float(a[1]) - float(b[1])) < 1e-12 and a[2] == b[2]


def pick(rows: list, uid=None, arm=None, cfg="any", seed=None, ik=False, role=None) -> list:
    out = []
    for r in rows:
        if uid is not None and r["uid"] != uid:
            continue
        if arm is not None and r["arm"] != arm:
            continue
        if cfg != "any" and not cfg_eq(r["cfg"], cfg):
            continue
        if seed is not None and r["seed"] != seed:
            continue
        if ik is not None and r["ik"] != ik:
            continue
        if role is not None and r["role"] != role:
            continue
        out.append(r)
    return out


def row_id(r: dict) -> tuple:
    return (r["uid"], r["arm"], None if r["cfg"] is None else (float(r["cfg"][0]), float(r["cfg"][1]), r["cfg"][2]), r["seed"], r["ik"])


def uniq_check(rr: list, where: str) -> list:
    """每个聚合里同一 (uid, arm, cfg, seed, ik) 只能出现一次(灵敏度作业 role = sens 与主作业同配置时会产生重复行;审查 2026-10-26 #1)。"""
    ids = [row_id(r) for r in rr]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1}, key=str)[:3]
        raise AssertionError(f"{where}:聚合里有重复行 {dup}")
    return rr


def seed_mean(rows: list, uid: str, arm: str, field: str, cfg="any", seeds=SEEDS, ik=False, role: str | None = "auto") -> float | None:
    """3 个种子的均值;只取主作业(ik 时取 role = ik),不让灵敏度 / 参照作业的同配置行混进来。"""
    role = ("ik" if ik else "main") if role == "auto" else role
    vals = []
    for s in seeds:
        rr = pick(rows, uid, arm, cfg, s, ik, role=role)
        if not rr:
            return None
        if len(rr) > 1:
            raise AssertionError(f"seed_mean:{uid} {arm} {cfg} 种子 {s} 有 {len(rr)} 行")
        v = rr[0]["m"][field]
        if v is None:
            return None
        vals.append(float(v))
    return float(np.mean(vals))


def pick1(rows: list, uid: str, arm: str, cfg="any", seed: int = 0, ik: bool = False) -> dict | None:
    """单元 × 臂 × 种子的主作业行(ik 时 role = ik);没有返回 None,重复就报错。"""
    rr = pick(rows, uid, arm, cfg, seed, ik, role="ik" if ik else "main")
    if len(rr) > 1:
        raise AssertionError(f"pick1:{uid} {arm} {cfg} 种子 {seed} ik={ik} 有 {len(rr)} 行")
    return rr[0] if rr else None


# ═══════════════════════════════════════════ 统计工具
def cluster_test(units: dict, uids: list, fa, fb, key=lambda u: u["cluster"]) -> dict:
    """配对差 d_u = fb(u) − fa(u)(按方向取好号),簇内均值 d_c,簇级精确符号翻转(单侧)。fa / fb 返回 None 的单元剔除。
    key:聚类单位(默认 (任务, 变体);按任务聚类时传 lambda u: u["task"])。"""
    by = defaultdict(list)
    used = []
    for uid in uids:
        a, b = fa(uid), fb(uid)
        if a is None or b is None:
            continue
        by[key(units[uid])].append(b - a)
        used.append(uid)
    dc = {c: float(np.mean(v)) for c, v in by.items()}
    res = XW.cluster_signflip(dc) if dc else {"C": 0, "T": float("nan"), "p": float("nan"), "mean": float("nan")}
    ci = boot_ci(dc)
    return {**res, "n_units": len(used), "d_by_cluster": dc, "ci95": ci}


def boot_ci(dc: dict, n_boot: int = 4000, seed: int = 0) -> list:
    """簇均值差的 bootstrap 95% 区间(按簇重抽)。"""
    v = np.array(list(dc.values()), float)
    if len(v) < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    bs = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(1)
    return [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))]


def tost_cluster(dc: dict, margin: float) -> dict:
    """TOST(§7.3):两个单侧簇级符号翻转,H0a:均值 ≤ −margin(检验 d + margin > 0),H0b:均值 ≥ margin(检验 margin − d > 0)。"""
    if not dc:
        return {"p_lower": float("nan"), "p_upper": float("nan"), "equivalent": False}
    pl = XW.cluster_signflip({c: v + margin for c, v in dc.items()})["p"]
    pu = XW.cluster_signflip({c: margin - v for c, v in dc.items()})["p"]
    return {"p_lower": pl, "p_upper": pu, "margin": margin, "equivalent": bool(pl < ALPHA and pu < ALPHA)}


def mcnemar_rows(xa: list, xb: list) -> dict:
    return ST.mcnemar_paired(xa, xb)


def kendall_tau(a: list, b: list) -> float:
    n = len(a)
    if n < 2:
        return float("nan")
    num = den_a = den_b = 0.0
    for i, j in itertools.combinations(range(n), 2):
        da, db = np.sign(a[i] - a[j]), np.sign(b[i] - b[j])
        num += da * db
        den_a += da * da
        den_b += db * db
    return float(num / math.sqrt(den_a * den_b)) if den_a and den_b else float("nan")


def rate(k: int, n: int) -> dict:
    return ST.rate(k, n)


def fmt_ci(ci) -> str:
    return f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci and all(np.isfinite(ci)) else "[—]"


# ═══════════════════════════════════════════ 各部分
def family_spec(units: dict, dx: dict) -> dict:
    """确认族四个检验的 (单元, 对照臂 a, 处理臂 b, b 的 cfg, 确认端点, 剔除无效后的端点)。差值一律 b − a(F4:a = A\\P、b = A)。"""
    hs = sorted(u for u, x in units.items() if x["cls"] == "HS")
    ca = sorted(u for u, x in units.items() if x["cls"] == "CA")
    cH = XW.b3_cfg(dx, "H")
    cells = (dx.get("G5") or {}).get("F3_units")
    cells = hs if cells in (None, "all_HS") else sorted(cells)
    return {"F1": (hs, "A", "B1", "any", "v_conf", "v"), "F2": (hs, "A", "B2", "any", "v_conf", "v"),
            "F3": (cells if cH else [], "A", "B3", cH, "v_conf", "v"), "F4": (ca, "AP", "A", "any", "m_conf", "m")}


def confirmatory(rows: list, units: dict, dx: dict) -> dict:
    """§7.2 确认族。fa = 对照臂、fb = 处理臂;F1–F3:v_B − v_A,F4:m_A − m_A\\P(好号为正)。"""
    spec = family_spec(units, dx)
    cH = XW.b3_cfg(dx, "H")

    def fmean(arm, cfg, field, src=None):
        R = rows if src is None else src
        return lambda uid: seed_mean(R, uid, arm, field, cfg)
    F = {}
    for f in ("F1", "F2", "F4"):
        uids, a, b, cfg, fc, _fv = spec[f]
        F[f] = cluster_test(units, uids, fmean(a, "any", fc), fmean(b, cfg, fc))
    f3 = dx.get("F3") or {}
    mode = f3.get("mode", "own")
    if mode == "equals_F1":
        F["F3"] = {**F["F1"], "mode": mode, "note": "B3 的 H 类配置在全部 H* 单元上与 B1 编译键相同:p 取 F1"}
    elif mode == "equals_F2":
        F["F3"] = {**F["F2"], "mode": mode, "note": "B3 的 H 类配置在全部 H* 单元上与 B2 编译键相同:p 取 F2"}
    elif mode == "descriptive" or cH is None:
        F["F3"] = {"p": 1.0, "mode": "descriptive", "note": f3.get("why", "B3 未决定")}
    else:
        uids, a, b, cfg, fc, _fv = spec["F3"]
        res = cluster_test(units, uids, fmean(a, "any", fc), fmean(b, cfg, fc))
        if res["C"] < 8:
            F["F3"] = {**res, "p": 1.0, "mode": "descriptive", "note": f"对 A、B3 都绑定的簇 {res['C']} < 8"}
        else:
            F["F3"] = {**res, "mode": "own"}
    # Holm 族固定 m = 4:非有限的 p(空族、--partial、基础设施剔除后无数据)按 p = 1 计入,不让族缩小(审查 2026-10-26 #3)
    praw = {f: F[f].get("p") for f in FAMILY}
    pin = {f: (float(p) if (p is not None and math.isfinite(float(p))) else 1.0) for f, p in praw.items()}
    mapped = [f for f in FAMILY if pin[f] != praw[f] and not (praw[f] is not None and math.isfinite(float(praw[f])))]
    holm = ST.holm(pin, alpha=ALPHA)
    assert len(holm["adjusted"]) == 4 and all(math.isfinite(v) for v in holm["adjusted"].values())
    for f in FAMILY:
        F[f]["p_holm"] = holm["adjusted"][f]
        F[f]["reject"] = holm["reject"][f]
        F[f]["p_nonfinite_mapped_to_1"] = f in mapped
    return F


def confirmatory_supp(rows: list, units: dict, dx: dict) -> dict:
    """【描述】确认族的敏感性(§6、§7.1;审查 2026-10-26 #2 / #9):
    valid_only:剔除无效执行与拒收(任一臂任一种子无效 → 该单元剔除),端点改用不记最差的 v / m;
    unit_level:单元级符号翻转(蒙特卡罗 10⁶ 次,确认端点);
    task_cluster:按任务聚类(6 簇,最小可达 p = 1/64)的精确符号翻转。F3 在 B3 未决定时为空。"""
    spec = family_spec(units, dx)
    valid = [r for r in rows if r["m"]["validity"]["valid"]]
    out = {}
    for f in FAMILY:
        uids, a, b, cfg, fc, fv = spec[f]
        if not uids:
            out[f] = {"note": "B3 未决定或没有单元"}
            continue
        fa = lambda uid, a=a, fc=fc: seed_mean(rows, uid, a, fc)                         # noqa: E731
        fb = lambda uid, b=b, cfg=cfg, fc=fc: seed_mean(rows, uid, b, fc, cfg)          # noqa: E731
        va = lambda uid, a=a, fv=fv: seed_mean(valid, uid, a, fv)                       # noqa: E731
        vb = lambda uid, b=b, cfg=cfg, fv=fv: seed_mean(valid, uid, b, fv, cfg)         # noqa: E731
        d = [fb(u) - fa(u) for u in uids if fa(u) is not None and fb(u) is not None]
        vo = cluster_test(units, uids, va, vb)
        out[f] = {"valid_only": {**vo, "n_dropped": len(uids) - vo["n_units"]},
                  "unit_level": signflip_mc_one_sided(d),
                  "task_cluster": cluster_test(units, uids, fa, fb, key=lambda u: u["task"])}
    return out


def main_rows(rows: list, uids, arm: str, cfg="any", seed: int = 0, where: str = "") -> list:
    """一组单元上某臂某种子的主作业行(role = main、ik = False),带重复检查。"""
    S = set(uids)
    return uniq_check([r for r in pick(rows, arm=arm, cfg=cfg, seed=seed, role="main") if r["uid"] in S], f"{where}|{arm}")


def hs_desc(rows: list, units: dict, dx: dict) -> dict:
    hs = sorted(u for u, x in units.items() if x["cls"] == "HS")
    cH = XW.b3_cfg(dx, "H")
    out = {"arms": {}}
    arms = [("A", None), ("B1", None), ("B2", None), ("B1m", None), ("B2m", None)] + ([("B3", cH)] if cH else [])
    for arm, cfg in arms:
        rr = main_rows(rows, hs, arm, cfg if arm == "B3" else "any", 0, "hs_desc")
        o3 = defaultdict(int)
        for r in rr:
            o3[r["m"]["outcome3"]] += 1
        ex = [r for r in rr if r["m"]["validity"]["valid"]]
        out["arms"][arm] = {"n": len(rr), "outcome3": dict(o3), "all_pass": rate(sum(r["m"]["all_pass"] for r in rr), len(rr)),
                            "hard_pass": rate(sum(bool(r["m"]["hard_ok"]) for r in ex), len(ex)),
                            "safe_useful": rate(sum(r["m"]["safe_useful"] for r in rr), len(rr)),
                            "v_exec_mean": float(np.mean([r["m"]["v"] for r in ex])) if ex else None}
    pairs = {}                                                           # 二值终点:配对精确 McNemar + 配对差的簇 bootstrap 区间(B − A)
    for arm in ("B1", "B2") + (("B3",) if cH else ()):
        res = {}
        for name, fn in (("hard_pass", lambda r: bool(r["m"]["hard_ok"]) and r["m"]["validity"]["valid"]),
                         ("all_pass", lambda r: bool(r["m"]["all_pass"]))):
            xa, xb = [], []
            by = defaultdict(list)
            for uid in hs:
                a = pick1(rows, uid, "A", "any", 0)
                b = pick1(rows, uid, arm, cH if arm == "B3" else "any", 0)
                if a and b:
                    xa.append(fn(a))
                    xb.append(fn(b))
                    by[units[uid]["cluster"]].append(int(fn(b)) - int(fn(a)))
            dc = {c: float(np.mean(v)) for c, v in by.items()}
            res[name] = {"mcnemar": mcnemar_rows(xa, xb), "diff_B_minus_A": float(np.mean(np.array(xb, int) - np.array(xa, int))) if xa else None,
                         "diff_cluster_mean": float(np.mean(list(dc.values()))) if dc else None, "diff_ci95_cluster_boot": boot_ci(dc)}
        pairs[arm] = res
    vA = {uid: seed_mean(rows, uid, "A", "v_conf") for uid in hs}
    vB2 = {uid: seed_mean(rows, uid, "B2", "v_conf") for uid in hs}
    by = defaultdict(list)
    for uid in hs:
        if vA[uid] is not None and vB2[uid] is not None:
            by[units[uid]["cluster"]].append(vB2[uid] - vA[uid])
    dc = {c: float(np.mean(v)) for c, v in by.items()}
    out["tost_A_B2"] = {**tost_cluster(dc, TOST_MARGIN), "ci95": boot_ci(dc), "mean": float(np.mean(list(dc.values()))) if dc else None}
    out["pairs"] = pairs
    return out


def signflip_mc_one_sided(d: list, n: int = 1_000_000, seed: int = 0) -> dict:
    d = np.asarray(d, float)
    if len(d) == 0:
        return {"n": 0, "p": float("nan")}
    rng = np.random.default_rng(seed)
    T = d.sum()
    a = np.abs(d)
    hits, done, B = 0, 0, 100_000
    while done < n:
        s = rng.integers(0, 2, size=(B, len(d))) * 2 - 1
        hits += int(((s * a).sum(1) >= T - 1e-12).sum())
        done += B
    return {"n": int(len(d)), "p": (hits + 1) / (done + 1), "mean": float(d.mean())}


def by_sub(rows: list, units: dict, cls: str, arms: list, dx: dict, key=lambda u: (u["sub"], u.get("binding"))) -> dict:
    groups = defaultdict(list)
    for uid, u in units.items():
        if u["cls"] == cls:
            groups[str(key(u))].append(uid)
    cH = XW.b3_cfg(dx, "H")
    out = {}
    for g, uids in sorted(groups.items()):
        out[g] = {}
        for arm in arms:
            cfg = cH if arm == "B3" else "any"
            if arm == "B3" and cH is None:
                continue
            rr = main_rows(rows, uids, arm, cfg, 0, f"by_sub|{cls}|{g}")
            ex = [r for r in rr if r["m"]["validity"]["valid"]]
            res = {"n": len(rr), "all_pass": rate(sum(r["m"]["all_pass"] for r in rr), len(rr)),
                   "hard_pass_exec": rate(sum(bool(r["m"]["hard_ok"]) for r in ex), len(ex)),
                   "v_exec_mean": float(np.mean([r["m"]["v"] for r in ex if r["m"]["v"] is not None])) if ex and any(r["m"]["v"] is not None for r in ex) else None,
                   "outcome3": dict(_count(r["m"]["outcome3"] for r in rr))}
            if arm != "A":
                xa, xb, same = [], [], 0
                for uid in uids:
                    a, b = pick1(rows, uid, "A", "any", 0), pick1(rows, uid, arm, cfg, 0)
                    if a and b:
                        xa.append(a["m"]["all_pass"])
                        xb.append(b["m"]["all_pass"])
                        same += int(a["key"] == b["key"])
                res["mcnemar_vs_A"] = mcnemar_rows(xa, xb)
                res["by_construction_equal"] = f"{same}/{len(xa)}"
            out[g][arm] = res
    return out


def _count(it) -> dict:
    d = defaultdict(int)
    for x in it:
        d[x] += 1
    return d


def ik_desc(rows: list, units: dict) -> dict:
    """代价一致逆解(次要分析,§2.4)。按退路分层报告(审查 2026-10-26 #6):A 的分层 hard 位形项 k = 50(绝对值),B2 的障碍项按 κ 归一化后
    只有 5(比值同为 10:1),同样 400 步、步长截断的求解器里 A 的绝对拉力是 B2 的 10 倍,A 也可能因此更常退回包装层逆解。
    all = 全部配对;no_fallback = 两臂都没有退路的配对。差异若只在 all 里出现,归到增益 / 退路,不归到表示。"""
    uids = sorted(u for u, x in units.items() if x["cls"] == "HR2" and x.get("binding") and x["sub"] in ("elbow", "q"))
    out = {}
    for arm in ("B1", "B2"):
        res = {}
        for stratum in ("all", "no_fallback"):
            d = []
            for uid in uids:
                a, b = pick1(rows, uid, "A", "any", 0, ik=True), pick1(rows, uid, arm, "any", 0, ik=True)
                if not (a and b) or a["m"]["v_conf"] is None or b["m"]["v_conf"] is None:
                    continue
                if stratum == "no_fallback" and (a.get("xw_ik_fallback") or b.get("xw_ik_fallback")):
                    continue
                d.append(b["m"]["v_conf"] - a["m"]["v_conf"])
            res[stratum] = {"paired_signflip": ST.paired_signflip_test(d) if d else None, "n": len(d), "mean_vB_minus_vA": float(np.mean(d)) if d else None}
        out[arm] = res
    fb = [r for r in rows if r["ik"] and r["role"] == "ik"]
    out["ik_fallback"] = {"n": len(fb), "fallback": sum(1 for r in fb if r.get("xw_ik_fallback")),
                          "by_arm_cls": {f"{c}|{a}": {"n": sum(1 for r in fb if r["arm"] == a and r["cls"] == c),
                                                      "fallback": sum(1 for r in fb if r["arm"] == a and r["cls"] == c and r.get("xw_ik_fallback"))}
                                         for c in ("HR2", "TC") for a in ("A", "B1", "B2")}}
    out["gain_note"] = "A 的 hard 位形项 k = 50,B2 障碍项归一化后 k = 5(同 10:1 比值,绝对拉力差 10 倍);结论以 no_fallback 层为准并注明增益不对称"
    return out


def n_side(rows: list, units: dict, dx: dict) -> dict:
    uids = sorted(u for u, x in units.items() if x["cls"] == "N")
    cN = XW.b3_cfg(dx, "N")
    out = {}
    for arm, cfg in (("AP", "any"), ("Adz", "any"), ("B1", "any"), ("B2", "any")) + ((("B3", cN),) if cN else ()):
        xa, xb, same = [], [], 0
        for uid in uids:
            a, b = pick1(rows, uid, "A", "any", 0), pick1(rows, uid, arm, cfg, 0)
            if a and b:
                xa.append(a["m"]["all_pass"])
                xb.append(b["m"]["all_pass"])
                same += int(a["key"] == b["key"])
        mc = mcnemar_rows(xa, xb)
        diff = [int(y) - int(x) for x, y in zip(xa, xb)]
        out[arm] = {"mcnemar": mc, "diff_ci95": boot_ci({i: v for i, v in enumerate(diff)}) if diff else None, "by_construction_equal": f"{same}/{len(xa)}"}
    return out


def ca_desc(rows: list, units: dict, dx: dict) -> dict:
    uids = sorted(u for u, x in units.items() if x["cls"] == "CA")
    cC = XW.b3_cfg(dx, "C")
    out = {}
    for arm, cfg in (("A", "any"), ("AP", "any"), ("Adz", "any"), ("B1", "any"), ("B2", "any")) + ((("B3", cC),) if cC else ()):
        rr = main_rows(rows, uids, arm, cfg, 0, "ca_desc")
        out[arm] = {"n": len(rr), "prio_sat": rate(sum(r["m"]["prio_sat"] for r in rr), len(rr)),
                    "m_mean": float(np.mean([r["m"]["m_conf"] for r in rr])) if rr else None,
                    "task_kept_mean": float(np.mean([r["m"]["task_kept"] for r in rr if r["m"]["task_kept"] is not None])) if rr else None}
    return out


def r_desc(rows: list, units: dict) -> dict:
    uids = sorted(u for u, x in units.items() if x["cls"] == "R")
    return {arm: {uid: (pick1(rows, uid, arm)["m"]["outcome3"] if pick1(rows, uid, arm) else None) for uid in uids}
            for arm in ("A", "B1", "B2")}


def tc_desc(rows: list, units: dict, reg: dict) -> dict:
    """T-conf 按对:两套都过(A、A_dz、两套逆解);B1 每对至多过 1 个(按构造);机理量 D_obs / D_pred(二次模型)。"""
    pairs = reg["test"]["tc_pairs"]
    out = {"pairs": {}, "summary": {}}
    for arm, ik in (("A", False), ("Adz", False), ("B1", False), ("A", True), ("B1", True)):
        both = n = 0
        both_pp = n_pp = 0
        for p in pairs:
            ri = [x for x in [pick1(rows, f"TC|{p['pair']}|i", arm, "any", 0, ik)] if x]
            rii = [x for x in [pick1(rows, f"TC|{p['pair']}|ii", arm, "any", 0, ik)] if x]
            if not (ri and rii):
                continue
            b = bool(ri[0]["m"]["all_pass"] and rii[0]["m"]["all_pass"])
            both += int(b)
            n += 1
            if p["per_point_ok"]:
                both_pp += int(b)
                n_pp += 1
            ei = ((ri[0]["m"]["eval"] or {}).get("elbow") or {}).get("value")
            eii = ((rii[0]["m"]["eval"] or {}).get("elbow") or {}).get("value")
            d_obs = None if (ei is None or eii is None) else (eii - ei) * p["side"]
            out["pairs"].setdefault(p["pair"], {})[f"{arm}{'+ik' if ik else ''}"] = {"both": b, "pass_i": ri[0]["m"]["all_pass"],
                                                                                   "pass_ii": rii[0]["m"]["all_pass"], "D_obs": d_obs,
                                                                                   "D_pred": d_pred(p, arm)}
        out["summary"][f"{arm}{'+ik' if ik else ''}"] = {"both": rate(both, n), "both_per_point_subset": rate(both_pp, n_pp)}
    return out


def d_pred(p: dict, arm: str) -> float:
    """二次模型 δe* = κ_q s Δq / (κ_e + κ_q s²),κ = g / σ²;D_pred = δe*(ii) − δe*(i)(A:σ 随容差;B1 / A_dz 两套相同 → 0)。"""
    if arm != "A":
        return 0.0
    s, dq = p["s"], p["dq"]

    def de(te, tq):
        se, sq = 0.02 * te / 0.04, 0.02 * tq / 0.05
        ke, kq = 2.0 / se ** 2, 2.0 / sq ** 2
        return kq * s * dq / (ke + kq * s * s)
    return de(XW.TC["te_L"], XW.TC["tq_s"]) - de(XW.TC["te_s"], p["tq_L"])


def dims_table(rows: list, units: dict, cls: str, arms=("A", "B1", "Adz")) -> dict:
    out = {}
    for uid, u in sorted(units.items()):
        if u["cls"] != cls:
            continue
        out[uid] = {}
        for arm in arms:
            rr = [x for x in [pick1(rows, uid, arm)] if x]
            if rr:
                ev = rr[0]["m"]["eval"] or {}
                out[uid][arm] = {"all_pass": rr[0]["m"]["all_pass"], "dims": {k: v.get("ok") for k, v in ev.items()},
                                 "values": {k: v.get("value") for k, v in ev.items() if v.get("value") is not None}}
    return out


def seed_flip(rows: list, units: dict, dx: dict | None = None) -> dict:
    cH = XW.b3_cfg(dx or {}, "H")
    out = {}
    for cls, arms in (("HS", ("A", "B1", "B2", "B3")), ("CA", ("A", "AP"))):
        for arm in arms:
            if arm == "B3" and cH is None:
                continue
            cfg = cH if arm == "B3" else "any"
            flips = n = 0
            for uid, u in units.items():
                if u["cls"] != cls:
                    continue
                vals = [pick1(rows, uid, arm, cfg, s) for s in SEEDS]
                if all(vals):
                    ap = {bool(v["m"]["all_pass"]) for v in vals}
                    flips += int(len(ap) > 1)
                    n += 1
            out[f"{cls}|{arm}"] = rate(flips, n)
    return out


def sensitivity(rows: list, units: dict, reg: dict, dx: dict) -> dict:
    """§4.4:校准全表(decisions)+ 测试子集上各配置的终点、Kendall τ(校准排名 vs 测试排名)、B_oracle(逐单元事后最好,只作上界)。"""
    out = {"cal_tables": {c: (dx.get("b3") or {}).get(c, {}).get("table") for c in ("H", "N", "C")}}
    sens = reg["test"].get("sens") or {}
    for cls, key, field, better in (("H", "HS", "v_conf", min), ("N", "N", "cal", max), ("C", "CA", "m_conf", max)):
        uids = sens.get(key) or []
        cfg_vals = defaultdict(dict)
        for r in rows:                                                   # 只取主作业与灵敏度作业(G5 参照作业 role = ref 是 H 类配置,不属于 N 的网格)
            if r["role"] not in ("main", "sens"):
                continue
            if r["uid"] in set(uids) and r["seed"] == 0 and not r["ik"] and (r["arm"] == "B3" or (r["arm"] == "A" and cls != "H")):
                cfg = tuple(r["cfg"]) if r["cfg"] else (0.1, 1.0, "barrier")
                cfg_vals[cfg][r["uid"]] = r["m"][field]
        means = {c: float(np.mean([x for x in v.values() if x is not None])) for c, v in cfg_vals.items() if v}
        cal = {tuple(t["cfg"]): t["score"] for t in (out["cal_tables"].get(cls) or [])}
        common = [c for c in means if c in cal]
        tau = kendall_tau([cal[c] for c in common], [(-means[c] if better is min else means[c]) for c in common]) if len(common) >= 2 else float("nan")
        oracle = []
        for uid in uids:
            vals = [v[uid] for v in cfg_vals.values() if uid in v and v[uid] is not None]
            if vals:
                oracle.append(better(vals))
        out[cls] = {"test_means": {str(c): v for c, v in means.items()}, "kendall_tau": tau, "n_cfg": len(common),
                    "B_oracle_mean": float(np.mean(oracle)) if oracle else None, "n_units": len(uids)}
    return out


def power_table(reps: int = 3000, seed: int = 1) -> dict:
    """§8 簇级精确符号翻转的功效(簇均值差 ~ N(δ, 1),模拟;不是预测)。"""
    rng = np.random.default_rng(seed)
    out = {}
    for n in (12, 11):
        signs = np.array(list(itertools.product((1.0, -1.0), repeat=n)))
        for alpha in (0.0125, 0.05):
            row = {}
            for d in (0.5, 0.8, 1.0, 1.2):
                hits = 0
                for _ in range(reps):
                    x = rng.normal(d, 1.0, n)
                    p = float(((signs @ np.abs(x)) >= x.sum() - 1e-12).mean())
                    hits += p <= alpha
                row[str(d)] = hits / reps
            out[f"C={n}|alpha={alpha}"] = row
    return out


# ═══════════════════════════════════════════ 报告
def construct_equal(rows: list) -> dict:
    """按构造相同的格:同一单元两臂编译键相同的计数(分析里标注,不当证据)。"""
    by = defaultdict(dict)
    for r in rows:
        if r["seed"] == 0 and not r["ik"]:
            by[r["uid"]][(r["arm"], None if r["cfg"] is None else tuple(r["cfg"]))] = r["key"]
    cnt = defaultdict(lambda: [0, 0])
    for uid, d in by.items():
        a = d.get(("A", None))
        if a is None:
            continue
        cls = uid.split("|")[0]
        for (arm, cfg), k in d.items():
            if arm == "A":
                continue
            c = cnt[f"{cls}|{arm}{'' if cfg is None else str(cfg)}"]
            c[0] += int(k == a)
            c[1] += 1
    return {k: f"{v[0]}/{v[1]}" for k, v in sorted(cnt.items())}


def write_md(res: dict, path: Path) -> None:
    L = [f"# R-XW 执行层消融:分析(生成于 {res['generated']};主机 {res['host']})", ""]
    if res.get("partial"):
        L += ["> 开发 / 冒烟模式(--partial):缺 {} 个仿真的作业被跳过,下面的数不能当结果。".format(res["n_missing"]), ""]
    L += [f"- 单元数:{json.dumps(res['counts'], ensure_ascii=False)};基础设施剔除单元 {len(res['infra_excluded'])} 个:{res['infra_excluded'][:10]}",
          f"- B3 选择:{json.dumps(res['b3'], ensure_ascii=False)}",
          f"- 入口记账错误(不影响执行,只说明 refusal_bypassed 记录可能不全):{res.get('bookkeeping_errors', 0)} 个目录", ""]
    L += [f"## 确认性族 {LABEL_CONF}(Holm m = 4,α = 0.05,单侧,簇级精确符号翻转)", "",
          "| 检验 | 单元(簇) | 比较 | 终点 | 簇均值差的均值 | 95% 区间(簇 bootstrap) | p | Holm p | 拒绝 H0 |", "|---|---|---|---|---|---|---|---|---|"]
    lab = {"F1": ("H*", "B1 − A", "v"), "F2": ("H*", "B2 − A", "v"), "F3": ("H* 双绑定", "B3 − A", "v"), "F4": ("C-a", "A − A\\P", "m")}
    for f in FAMILY:
        x = res["confirmatory"][f]
        L.append(f"| {f} | {x.get('n_units', '—')}({x.get('C', '—')}) | {lab[f][1]} | {lab[f][2]} | {x.get('mean', float('nan')):+.3f} | {fmt_ci(x.get('ci95'))} | "
                 f"{x.get('p', float('nan')):.4f} | {x.get('p_holm', float('nan')):.4f} | {'是' if x.get('reject') else '否'} |")
    for f in FAMILY:
        x = res["confirmatory"][f]
        extra = "(p 非有限,按 p = 1 计入 Holm 族)" if x.get("p_nonfinite_mapped_to_1") else ""
        if not x.get("reject"):
            L.append(f"- {f}:没有检出差异(差值 95% 区间 {fmt_ci(x.get('ci95'))})。{x.get('note', '')}{extra}")
    L += ["", f"### 确认族的敏感性 {LABEL_DESC}(剔除无效执行与拒收 / 单元级符号翻转 10⁶ 次 / 按任务聚类 6 簇)", "",
          "| 检验 | 剔除无效:单元(簇)| 剔除无效:均值 [95% 区间] | 剔除无效:p | 剔除单元数 | 单元级:n | 单元级:p | 按任务:簇 | 按任务:p |",
          "|---|---|---|---|---|---|---|---|---|"]
    for f in FAMILY:
        x = (res.get("confirmatory_supp") or {}).get(f) or {}
        if "valid_only" not in x:
            L.append(f"| {f} | — | — | — | — | — | — | — | — |")
            continue
        vo, ul, tc = x["valid_only"], x["unit_level"], x["task_cluster"]
        L.append(f"| {f} | {vo['n_units']}({vo['C']}) | {vo.get('mean', float('nan')):+.3f} {fmt_ci(vo.get('ci95'))} | {vo.get('p', float('nan')):.4f} | "
                 f"{vo['n_dropped']} | {ul.get('n')} | {ul.get('p', float('nan')):.4f} | {tc['C']} | {tc.get('p', float('nan')):.4f} |")
    t = res["hs"]["tost_A_B2"]
    L += ["", f"- {LABEL_DESC} A vs B2 的 TOST(±{TOST_MARGIN} Δ):p_lower = {t['p_lower']:.4f},p_upper = {t['p_upper']:.4f} → "
          + ("**A ≈ B2(等价成立)**" if t["equivalent"] else f"等价不成立;没有检出差异时只写差值 95% 区间 {fmt_ci(t.get('ci95'))}"), ""]
    L += [f"## H* 描述 {LABEL_DESC}", "", "| 臂 | n | 三分类 | 全部达标 | 硬界达标(已执行) | 安全且有用 | 已执行 v 均值 |", "|---|---|---|---|---|---|---|"]
    for arm, x in res["hs"]["arms"].items():
        L.append(f"| {arm} | {x['n']} | {x['outcome3']} | {x['all_pass']['k']}/{x['all_pass']['n']} | {x['hard_pass']['k']}/{x['hard_pass']['n']} | "
                 f"{x['safe_useful']['k']}/{x['safe_useful']['n']} | {x['v_exec_mean'] if x['v_exec_mean'] is None else round(x['v_exec_mean'], 3)} |")
    L += ["", "| 配对(种子 0) | 终点 | n | b(A 过 B 不过) | c | 双侧精确 McNemar p | 差 B − A | 簇 bootstrap 95% 区间 |", "|---|---|---|---|---|---|---|---|"]
    for arm, x in res["hs"]["pairs"].items():
        for name in ("hard_pass", "all_pass"):
            y = x[name]
            mc = y["mcnemar"]
            dd = y["diff_B_minus_A"]
            L.append(f"| A vs {arm} | {name} | {mc['n']} | {mc['b']} | {mc['c']} | {mc['p']:.4f} | {'—' if dd is None else f'{dd:+.3f}'} | {fmt_ci(y['diff_ci95_cluster_boot'])} |")
    L += ["", f"## H-R2(按子类 × 绑定)、N 副作用、C-a、R、T {LABEL_DESC}", "", "完整数值见 analysis_xw.json(hr2 / n_side / ca / r / tc / tt / fv / ik / seed_flip / sensitivity)。", "",
          f"- 按构造相同的格(同单元两臂编译键相同,不当证据):{json.dumps(res['construct_equal'], ensure_ascii=False)[:1500]}",
          f"- T-conf 两套都过:{json.dumps(res['tc']['summary'], ensure_ascii=False)}",
          f"- 代价一致逆解(次要;按退路分层,A 的 hard 位形项 k = 50 vs B2 障碍归一化 k = 5,见 ik.gain_note):"
          f"{json.dumps({a: {s: res['ik'][a][s]['n'] for s in ('all', 'no_fallback')} for a in ('B1', 'B2')}, ensure_ascii=False)};退路 {json.dumps(res['ik']['ik_fallback'], ensure_ascii=False)[:600]}",
          f"- 换种子翻转率:{json.dumps(res['seed_flip'], ensure_ascii=False)}", "",
          f"## 功效(§8,模拟)", "", json.dumps(res.get("power") or {}, ensure_ascii=False)]
    CM.atomic_write_text(path, "\n".join(L) + "\n")


def run_all(rows: list, units: dict, reg: dict, dx: dict) -> dict:
    res = {}
    res["confirmatory"] = confirmatory(rows, units, dx)
    res["confirmatory_supp"] = confirmatory_supp(rows, units, dx)
    res["hs"] = hs_desc(rows, units, dx)
    res["hr2"] = by_sub(rows, units, "HR2", ["A", "B1", "B2", "B3"], dx)
    res["ik"] = ik_desc(rows, units)
    res["n_side"] = n_side(rows, units, dx)
    res["ca"] = ca_desc(rows, units, dx)
    res["r"] = r_desc(rows, units)
    res["tc"] = tc_desc(rows, units, reg)
    res["tt"] = dims_table(rows, units, "TT")
    res["fv"] = dims_table(rows, units, "FV", ("A", "B1"))
    res["seed_flip"] = seed_flip(rows, units, dx)
    res["sensitivity"] = sensitivity(rows, units, reg, dx)
    res["construct_equal"] = construct_equal([r for r in rows if r["role"] in ("main", "sens")])
    mr = [r for r in rows if r["role"] == "main"]
    res["boundary_rate"] = rate(sum(bool(r["m"]["boundary"]) for r in mr), len(mr))
    res["bookkeeping_errors"] = sum(1 for r in rows if r.get("bookkeeping_errors"))
    return res


def analyze(host: str, allow_unfrozen: bool, partial: bool, with_power: bool) -> dict:
    with XW.r2_write_guard():
        if allow_unfrozen:
            reg, dx = XW.load_reg(), XW.load_decisions_xw()
            if not reg or "test" not in reg:
                raise SystemExit("没有 cases_xw.json 的 test 部分")
        else:
            reg, dx = XW.load_frozen()
        rows, missing, infra, units = collect(reg, dx, host, partial)
    res = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": host, "partial": partial, "n_rows": len(rows), "n_missing": len(missing),
           "missing_sample": missing[:20], "infra_excluded": infra, "counts": reg["test"]["counts"],
           "b3": {c: (dx.get("b3") or {}).get(c, {}).get("chosen") for c in ("H", "N", "C")}}
    res.update(run_all(rows, units, reg, dx))
    if with_power:
        res["power"] = power_table()
    suffix = "_partial" if partial else ""
    CM.atomic_write_json(XW.OUT / f"analysis_xw{suffix}.json", {**res, "rows": [{k: v for k, v in r.items()} for r in rows]}, indent=1, default=float)
    write_md(res, XW.OUT / f"analysis_xw{suffix}.md")
    return res


# ═══════════════════════════════════════════ 离线自检(不读仿真):用合成指标跑全部聚合,核对计数与去重
def _fake_metrics(rng, hard: bool) -> dict:
    valid = bool(rng.random() > 0.1)
    v = float(rng.uniform(0, 1)) if hard else None
    m = float(rng.uniform(-1, 1))
    return {"validity": {"present": True, "valid": valid, "refused": False, "why": None if valid else "end_y_err"}, "all_pass": bool(rng.random() > 0.5),
            "eval": {"elbow": {"ok": True, "value": float(rng.uniform(0.05, 0.15))}}, "v": v, "hard_ok": (v == 0.0) if hard else None, "m": m,
            "task_ok": [True, True, True, True], "task_kept": 1.0, "prio_sat": bool(rng.random() > 0.3), "cal": m, "outcome3": "exec_ok" if valid else "invalid",
            "safe_useful": valid, "v_conf": (3.0 if not valid else v) if hard else None, "m_conf": -3.0 if not valid else m, "boundary": False}


def selftest() -> dict:
    """合成行:按 jobs_test + jobs_ref 生成(B3 各类取非 0.1 的配置,让 sens / ref 作业与主作业同配置重叠),检查
    (1) 每个聚合里 (uid, arm, cfg, seed, ik) 唯一;(2) H* / C-a / H-R2 各臂 n = 单元数;(3) Holm 族 m = 4 且 NaN 按 1 计;
    (4) 确认族敏感性四个检验都给出;(5) 灵敏度表不含 ref 作业的 H 类配置。"""
    reg = XW.load_reg()
    units = {u["uid"]: u for u in reg["test"]["units"]}
    dec = XW.r2_dec()
    dx = {"b3": {"H": {"chosen": [0.3, 1.0, "barrier"]}, "N": {"chosen": [0.3, 1.0, "barrier"]}, "C": {"chosen": [1.0, 1.0, "barrier"]}},
          "F3": {"mode": "own"}, "G5": {"F3_units": "all_HS"}}
    J = XW.jobs_test(list(units.values()), dx, reg["test"].get("sens"))
    J += XW.jobs_ref(dx, [u for u in units.values() if u["cls"] == "N" and u["sub"] == "S0"])
    rng = np.random.default_rng(3)
    keymet: dict = {}
    rows = []
    for j in J:
        u, cmd, _ = XW.job_cmd(j, units, dec)
        k = XW.ckey(u["task"], u["bias"], cmd)
        if k not in keymet:
            keymet[k] = _fake_metrics(rng, bool(XW.hard_items(u["contract"])))
        rows.append({**{x: j[x] for x in ("uid", "arm", "cfg", "seed", "ik", "role")}, "cls": u["cls"], "sub": u["sub"], "task": u["task"],
                     "cluster": u["cluster"], "key": k, "src": "fake", "dir": None, "m": keymet[k], "xw_ik_fallback": None, "refusal_bypassed": False})
    n_dup_raw = len(rows) - len({row_id(r) for r in rows})
    res = run_all(rows, units, reg, dx)
    nHS = sum(1 for u in units.values() if u["cls"] == "HS")
    nCA = sum(1 for u in units.values() if u["cls"] == "CA")
    log = []

    def ok(c, msg):
        log.append(("PASS" if c else "FAIL", msg))
        if not c:
            raise AssertionError(msg)
    ok(n_dup_raw > 0, f"合成行里确实有 sens / ref 与主作业同 (uid, arm, cfg, seed, ik) 的重复({n_dup_raw} 行)——检查有意义")
    ok(all(x["n"] == nHS for x in res["hs"]["arms"].values()), f"H* 各臂 n = {nHS}:{ {a: x['n'] for a, x in res['hs']['arms'].items()} }")
    ok(all(x["n"] == nCA for x in res["ca"].values()), f"C-a 各臂 n = {nCA}:{ {a: x['n'] for a, x in res['ca'].items()} }")
    for g, d in res["hr2"].items():
        ng = sum(1 for u in units.values() if u["cls"] == "HR2" and str((u["sub"], u.get("binding"))) == g)
        bad = {a: x["n"] for a, x in d.items() if x["n"] != ng and not (a == "B3" and g.startswith("('force'"))}
        ok(not bad, f"H-R2 {g} 各臂 n = {ng}(B3 力子类不跑):{bad or '一致'}")
    ok(all(res["confirmatory"][f]["n_units"] == nHS for f in ("F1", "F2", "F3")) and res["confirmatory"]["F4"]["n_units"] == nCA,
       f"F1–F3 用 {nHS} 个 H* 单元、F4 用 {nCA} 个 C-a 单元(每单元一行 / 种子)")
    ok(all("valid_only" in res["confirmatory_supp"][f] and res["confirmatory_supp"][f]["task_cluster"]["C"] <= 6 for f in FAMILY),
       "确认族四个检验都有剔除无效 / 单元级 / 按任务聚类的敏感性")
    F = {f: {"p": p} for f, p in zip(FAMILY, (0.01, float("nan"), 0.03, 0.2))}
    pin = {f: (x["p"] if math.isfinite(x["p"]) else 1.0) for f, x in F.items()}
    h = ST.holm(pin)
    ok(abs(h["adjusted"]["F1"] - 0.04) < 1e-12 and h["adjusted"]["F2"] == 1.0, f"NaN 的 p 按 1 计入后 Holm 仍是 m = 4:{h['adjusted']}")
    ncfg = set(res["sensitivity"]["N"]["test_means"])
    ok(ncfg <= {str((0.1, 1.0, "barrier")), str((0.3, 1.0, "barrier")), str((1.0, 1.0, "barrier"))}, f"N 灵敏度表只含 N 的 3 个 r_pref 网格点:{sorted(ncfg)}")
    sf = res["seed_flip"]
    ok(sf["HS|B3"]["n"] == nHS, f"换种子翻转率 B3 用选中的 H 配置({sf['HS|B3']['n']} 个单元)")
    return {"log": log, "n_rows": len(rows), "n_dup_raw": n_dup_raw}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="analyze", choices=["analyze", "power", "selftest"])
    ap.add_argument("--host", default=XW.HOST)
    ap.add_argument("--allow-unfrozen", action="store_true")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--no-power", action="store_true")
    a = ap.parse_args()
    if a.what == "power":
        print(json.dumps(power_table(), ensure_ascii=False, indent=1))
        return 0
    if a.what == "selftest":
        with XW.r2_write_guard():
            rep = selftest()
        for s_, m_ in rep["log"]:
            print(f"[{s_}] {m_}")
        print(f"analyze selftest 通过({rep['n_rows']} 行合成数据,其中 {rep['n_dup_raw']} 行与主作业重复)")
        return 0
    res = analyze(a.host, a.allow_unfrozen, a.partial, not a.no_power)
    print(json.dumps({"confirmatory": {f: {k: res["confirmatory"][f].get(k) for k in ("C", "n_units", "mean", "p", "p_holm", "reject", "mode")} for f in FAMILY},
                      "n_rows": res["n_rows"], "n_missing": res["n_missing"]}, ensure_ascii=False, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
