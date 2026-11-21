#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-XW 分析的 [dev-XW-01] 包装层(plan_exec_weighted.md §16;2026-10-26 新建,只新建文件;同日按科学审查改第 3–6 条)。

偏离本身见 exp_repair/exec_weighted_dev01.py 的模块说明:A_dz 在关节目标 ± 容差整段落在硬件限位外的单元上(冻结代码下枚举:
CA|iiwa_a|J3-offB-{abs,rel,unit}|000 三个,两个编译键)不可编译,按不适用(N/A)处理。analyze_exec_weighted.py 冻结(sha16 在
cases_xw.json meta.code_sha 里),不改;本文件 import 它不变,在 import 时只包下面几处,然后原样调 analyze_exec_weighted.main():

  1. 先按路径加载冻结的 analyze_exec_weighted(AN;它自己加载 exec_weighted),再按路径加载 exec_weighted_dev01(复用同一个
     exec_weighted 模块对象,包上 load_xw;判定条件见那里的 na_info)。不改 sys.path。
  2. AN.peek_host:N/A 目录不再让分析停下,改为返回占位记录(src = "xw_na");其他 FrameworkError 照抛(分析照冻结版停)。
  3. AN.collect:原版照跑(缺仿真、--partial、基础设施整组剔除、FrameworkError 停都不变),之后去掉 src = "xw_na" 的行——这些行
     不进任何聚合,不当任何臂的情形结果。去掉的行必须全是 Adz(作业元数据),否则 FrameworkError 停。
     再核对 N/A 集合 = 已披露的集合(DISCLOSED_NA:3 个 (单元, Adz)、种子 0 主作业;在 sprl1 主机 da88a21e8aee 上另核对 2 个目录名):
     多出任何一个 → 拒绝运行(完整分析与 --partial 都拒);完整分析(不带 --partial)时还必须一个不少(基础设施整组剔除的单元除外)。
     缺仿真:冻结 collect 在完整分析时本来就拒绝(「缺 N 个仿真」);N/A 键有占位记录,不算缺。所以完整分析只在「除已披露的
     N/A 键以外一个仿真都不缺」时才往下跑,并写 analysis_xw.{md,json}。
  4. AN.run_all:原版照跑(结果逐值不变,F1–F4 与其他全部输出同冻结版),之后只追加:
     a. 冻结 ca 表(ca_desc,按臂各自聚合)的 Adz 列加一个键 dev_xw_01_flag =「n = 29,与其他列的单元集不同,不可直接比较」
        (只在 A_dz 的单元集与其他臂不同时加;数值不动);
     b. dev_xw_01:偏离说明、N/A 行与单元、按类计数、各类 A_dz 计入行数、N/A 集合核对结果;
        ca_common_units【描述】:C-a 上全部臂(A、A\\P、A_dz、B1、B2、B3)都有种子 0 主作业行的共同单元(应为 29 个 / 10 簇),
          全部臂在这同一单元集上用冻结 ca_desc 原样聚合,再给 A_dz − 各臂的配对差(按簇均值 + 簇 bootstrap 95% 区间,不给 p)。
          C-a 上涉及 A_dz 的比较论文只引用这一版;A、A\\P、B1、B2、B3 之间的 C-a 描述仍以冻结 ca 表(32 单元 / 11 簇)为准,F4 仍在 32 单元上;
        ca_adz_worst_case【描述】:灵敏度,N/A 簇(iiwa_a|J3-offB)的 A_dz 记最坏(m_conf = −3、按优先级满足 = 否;task_kept 不补,
          与冻结版对无效执行的处理相同),32 个单元;其他臂即冻结 ca 表。
  5. AN.write_md:原版写完后(a)在摘要列表里插一行偏离标记;(b)在「功效」一节之前插一节「C-a 上涉及 A_dz 的比较」
     (Adz 列标记行、共同单元表与配对差、最坏情形行),全部标【描述】。
  6. dev01-selftest:只用合成指标,不读任何真实仿真(真实读取函数换成一调用就报错的桩),输出只写临时目录。见 dev01_selftest。

用法(参数与输出文件同 analyze_exec_weighted.py):
    .venv/bin/python exp_repair/analyze_exec_weighted_dev01.py                       # 完整分析 → analysis_xw.{md,json};缺仿真(N/A 键除外)就拒绝
    .venv/bin/python exp_repair/analyze_exec_weighted_dev01.py --host da88a21e8aee   # 本机读拉回的 sprl1 目录(sims/da88a21e8aee/)
    .venv/bin/python exp_repair/analyze_exec_weighted_dev01.py dev01-selftest        # 合成数据自检(不读真实仿真,不算真实 F4)
    .venv/bin/python exp_repair/analyze_exec_weighted_dev01.py selftest              # 冻结版离线自检(合成行,经包装)
    --partial 会在真实数据上算出 F1–F4 的部分结果:最终分析之前不用(§16 [run-02] 的规则:身份核对一律不算、不打印 F4)。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


AN = _load("analyze_exec_weighted", "analyze_exec_weighted.py")          # 冻结,不改
DEV = _load("exec_weighted_dev01", "exec_weighted_dev01.py")             # 复用 AN.XW,包 load_xw
XW = AN.XW
assert DEV.XW is XW and getattr(XW, "_dev_xw_01", False), "exec_weighted_dev01 没有包在分析用的同一个 exec_weighted 模块上"
NA_SRC = "xw_na"
WC_SRC = "dev01_worst_case"
DISCLOSED_NA = (("CA|iiwa_a|J3-offB-abs|000", "Adz"), ("CA|iiwa_a|J3-offB-rel|000", "Adz"), ("CA|iiwa_a|J3-offB-unit|000", "Adz"))
DISCLOSED_HOST = "da88a21e8aee"                                          # sprl1 容器的主机名(目录名里的哈希含主机名)
DISCLOSED_NA_DIRS = ("iiwa_a_c3448c02598df0cf", "iiwa_a_43150c428929835e")
DISCLOSED_CLUSTER = "iiwa_a|J3-offB"
EXPECT_COMMON = (29, 10)                                                 # C-a 32 个单元 / 11 簇去掉 N/A 簇的 3 个单元
FLAG_KEY = "dev_xw_01_flag"
FLAG_FMT = "n = {n},与其他列的单元集不同,不可直接比较"
WORST = {"m_conf": -3.0, "prio_sat": False}
CITE = ("C-a 上涉及 A_dz 的比较,论文只引用共同单元版本(全部臂同一单元集);A、A\\P、B1、B2、B3 之间的 C-a 描述仍以预先登记的冻结 ca 表"
        "(32 单元 / 11 簇)为准,F4 仍在 32 单元上;冻结 ca 表的 Adz 列与最坏情形行只作披露,不直接比较;"
        "C-a 上 B1、B2、B3 与 A 是同一个编译键(§2.5),共同单元表里的 B1 / B2 / B3 行与 A_dz − B1 / B2 / B3 按构造与 A 行相同,不当证据")
LABEL = AN.LABEL_DESC
ARM_NAME = {"AP": "A\\P"}
NA_SEEN: dict = {}                                                       # 目录 → na_info
DEV_REC: dict = {"na_rows": []}

_ORIG_PEEK_HOST, _ORIG_COLLECT, _ORIG_RUN_ALL, _ORIG_WRITE_MD = AN.peek_host, AN.collect, AN.run_all, AN.write_md


# ═══════════════════════════════════════════ 读取
def peek_host(task, bias, cmd: dict, host: str):
    try:
        return _ORIG_PEEK_HOST(task, bias, cmd, host)
    except DEV.NotApplicableXW as e:
        NA_SEEN[e.info["dir"]] = e.info
        return {"dir": e.info["dir"], "ok": False, "failed": True, "refused": False, "series": None, "ext_result": None, "fail_tail": None,
                "src": NA_SRC, "na": e.info}


def check_disclosed(na: list, host: str, partial: bool, infra: list) -> dict:
    """N/A 行必须落在已披露的集合里;完整分析时必须正好等于它(基础设施整组剔除的单元除外)。不符 → SystemExit。"""
    got = sorted({(r["uid"], r["arm"]) for r in na})
    dirs = sorted({Path(str(r["dir"])).name for r in na})
    shape = [(r["uid"], r["arm"], r["seed"], r["role"], r["ik"]) for r in na if not (r["seed"] == 0 and r["role"] == "main" and not r["ik"])]
    dup = len(na) != len(got)
    check_dirs = host == DISCLOSED_HOST
    extra = sorted(set(got) - set(DISCLOSED_NA))
    extra_dirs = sorted(set(dirs) - set(DISCLOSED_NA_DIRS)) if check_dirs else []
    if extra or extra_dirs or shape or dup:
        raise SystemExit(f"[{DEV.DEV_ID}] N/A 集合超出已披露的范围:多出 {extra} / 目录 {extra_dirs} / 非种子 0 主作业 {shape} / 重复行 {dup};拒绝运行")
    lack = sorted(x for x in set(DISCLOSED_NA) - set(got) if x[0] not in set(infra))
    lack_dirs = sorted(set(DISCLOSED_NA_DIRS) - set(dirs)) if (check_dirs and not set(u for u, _ in DISCLOSED_NA) & set(infra)) else []
    if not partial and (lack or lack_dirs):
        raise SystemExit(f"[{DEV.DEV_ID}] 完整分析要求 N/A 集合正好等于已披露的 3 个 (单元, Adz) / 2 个目录;少了 {lack} / 目录 {lack_dirs};拒绝运行")
    return {"disclosed": [list(x) for x in DISCLOSED_NA], "got": [list(x) for x in got], "dirs": dirs, "dirs_checked": check_dirs,
            "missing_from_disclosed": [list(x) for x in lack], "partial": partial, "ok": True}


def collect(reg: dict, dx: dict, host: str, partial: bool) -> tuple:
    rows, missing, infra, units = _ORIG_COLLECT(reg, dx, host, partial)   # 完整分析时缺仿真已在这里 SystemExit
    if missing and not partial:
        raise SystemExit(f"[{DEV.DEV_ID}] 缺 {len(missing)} 个仿真(N/A 键不算缺);拒绝运行")
    na = [r for r in rows if r.get("src") == NA_SRC]
    bad = [(r["uid"], r["arm"]) for r in na if r["arm"] != DEV.NA_ARM]
    if bad:
        raise XW.FrameworkError(f"[{DEV.DEV_ID}] N/A 目录对应了非 Adz 的作业 {bad[:5]}:不适用 N/A,照冻结版停")
    DEV_REC["disclosed_check"] = check_disclosed(na, host, partial, infra)
    DEV_REC["na_rows"] = [{k: r[k] for k in ("uid", "arm", "cfg", "seed", "ik", "role", "cls", "sub", "task", "cluster", "dir")}
                          | {"na": NA_SEEN.get(r["dir"])} for r in na]
    return [r for r in rows if r.get("src") != NA_SRC], missing, infra, units


# ═══════════════════════════════════════════ C-a 上涉及 A_dz 的比较【描述】
def ca_arms(dx: dict) -> list:
    """与冻结 ca_desc 相同的臂与配置顺序。"""
    cC = XW.b3_cfg(dx, "C")
    return [("A", "any"), ("AP", "any"), ("Adz", "any"), ("B1", "any"), ("B2", "any")] + ([("B3", cC)] if cC else [])


def paired_adz_minus(rows: list, units: dict, uids: list, arm: str, cfg) -> dict:
    """【描述】A_dz − arm 的配对差(种子 0 主作业):m_conf 与按优先级满足(0/1),先单元内差、再簇内均值,报簇均值的均值与簇 bootstrap 区间。"""
    by_m, by_p = defaultdict(list), defaultdict(list)
    adz_only = x_only = n = none_skipped = 0
    for u in uids:
        a, x = AN.pick1(rows, u, "Adz", "any", 0), AN.pick1(rows, u, arm, cfg, 0)
        if not (a and x):
            continue
        cl = units[u]["cluster"]
        pa, px = bool(a["m"]["prio_sat"]), bool(x["m"]["prio_sat"])
        by_p[cl].append(int(pa) - int(px))
        adz_only += int(pa and not px)
        x_only += int(px and not pa)
        n += 1
        ma, mx = a["m"]["m_conf"], x["m"]["m_conf"]
        if ma is None or mx is None:
            none_skipped += 1
        else:
            by_m[cl].append(float(ma) - float(mx))
    dm = {c: float(np.mean(v)) for c, v in sorted(by_m.items())}
    dp = {c: float(np.mean(v)) for c, v in sorted(by_p.items())}
    return {"n_units": n, "C": len(dp),
            "m_conf_minus": {"mean_cluster": float(np.mean(list(dm.values()))) if dm else None, "ci95_cluster_boot": AN.boot_ci(dm),
                             "d_by_cluster": dm, "n_none_skipped": none_skipped},
            "prio_sat_minus": {"adz_only": adz_only, "x_only": x_only, "mean_cluster": float(np.mean(list(dp.values()))) if dp else None,
                               "ci95_cluster_boot": AN.boot_ci(dp)}}


def dev_ca(rows: list, units: dict, dx: dict, na_ca: list) -> tuple:
    """(共同单元版本, 最坏情形版本)。共同单元 = C-a 上全部臂都有种子 0 主作业行的单元;聚合一律调冻结 ca_desc。"""
    ca_all = sorted(u for u, x in units.items() if x["cls"] == "CA")
    arms = ca_arms(dx)
    has = {a: {u for u in ca_all if AN.pick1(rows, u, a, cfg, 0)} for a, cfg in arms}
    common = [u for u in ca_all if all(u in has[a] for a, _ in arms)]
    clusters = sorted({units[u]["cluster"] for u in common})
    excl = [u for u in ca_all if u not in common]
    others = [has[a] for a, _ in arms if a != "Adz"]
    cm = {"label": LABEL, "cite": CITE,
          "rule": "C-a 上 A、A\\P、A_dz、B1、B2、B3 都有种子 0 主作业行的单元;全部臂在同一单元集上按冻结 ca_desc 聚合",
          "n_units": len(common), "C": len(clusters), "expected": list(EXPECT_COMMON),
          "matches_expected": (len(common), len(clusters)) == EXPECT_COMMON, "units": common, "clusters": clusters,
          "excluded_units": excl, "excluded_clusters": sorted({units[u]["cluster"] for u in excl}),
          "units_with_row_by_arm": {a: len(has[a]) for a, _ in arms},
          "adz_unit_set_equals_others": all(has["Adz"] == s for s in others),
          "arms": AN.ca_desc(rows, {u: units[u] for u in common}, dx),
          "paired_adz_minus": {a: paired_adz_minus(rows, units, common, a, cfg) for a, cfg in arms if a != "Adz"}}
    imp = []
    for u in na_ca:
        if AN.pick1(rows, u, "Adz", "any", 0) is not None:
            raise AssertionError(f"[{DEV.DEV_ID}] N/A 单元 {u} 竟然有 Adz 行")
        x = units[u]
        imp.append({"uid": u, "arm": "Adz", "cfg": None, "seed": 0, "ik": False, "role": "main", "cls": x["cls"], "sub": x["sub"], "task": x["task"],
                    "cluster": x["cluster"], "key": None, "src": WC_SRC, "dir": None,
                    "m": {"m_conf": WORST["m_conf"], "prio_sat": WORST["prio_sat"], "task_kept": None},
                    "xw_ik_fallback": None, "refusal_bypassed": False, "bookkeeping_errors": 0})
    rw = rows + imp                                                      # 只用于这一张灵敏度表,不进任何别的聚合
    wc = {"label": LABEL,
          "rule": "N/A 单元的 A_dz 记最坏:m_conf = −3、按优先级满足 = 否(task_kept 不补,同冻结版对无效执行的处理);全部 C-a 单元",
          "imputed_units": list(na_ca), "imputed_clusters": sorted({units[u]["cluster"] for u in na_ca}), "imputed": {**WORST, "task_kept": None},
          "arms": AN.ca_desc(rw, {u: units[u] for u in ca_all}, dx),
          "paired_adz_minus": {a: paired_adz_minus(rw, units, ca_all, a, cfg) for a, cfg in arms if a != "Adz"}}
    return cm, wc


def run_all(rows: list, units: dict, reg: dict, dx: dict) -> dict:
    out = _ORIG_RUN_ALL(rows, units, reg, dx)
    na = DEV_REC.get("na_rows") or []
    na_ca = sorted({r["uid"] for r in na if r["cls"] == "CA"})
    cm, wc = dev_ca(rows, units, dx, na_ca)
    adz = (out.get("ca") or {}).get("Adz")
    if adz is not None and not cm["adz_unit_set_equals_others"]:
        adz[FLAG_KEY] = FLAG_FMT.format(n=adz["n"])                      # 只加标记键,冻结数值不动
    adz_left = Counter(r["cls"] for r in rows if r["arm"] == DEV.NA_ARM and r["role"] == "main" and r["seed"] == 0 and not r["ik"])
    adz_units = Counter(x["cls"] for x in units.values() if x["cls"] in ("N", "CA", "TC", "TT"))
    out["dev_xw_01"] = {"note": DEV.NOTE, "n_na_rows": len(na), "na_units": sorted({r["uid"] for r in na}),
                        "na_by_cls": dict(Counter(r["cls"] for r in na)), "na_dirs": sorted({r["dir"] for r in na}), "na_rows": na,
                        "disclosed_check": DEV_REC.get("disclosed_check"),
                        "adz_rows_used_by_cls": dict(adz_left), "adz_units_by_cls": dict(adz_units),
                        "ca_flag": {"column": "ca.Adz", "key": FLAG_KEY, "flag": None if adz is None else adz.get(FLAG_KEY)},
                        "ca_common_units": cm, "ca_adz_worst_case": wc,
                        "unaffected": "A / A\\P / B1 / B2 / B3 / B1⁻ / B2⁻ 的全部行与确认族 F1–F4 不受影响(只去掉了 Adz 行);"
                                      "冻结 run_all 的全部输出逐值不变,ca.Adz 只多一个标记键"}
    return out


# ═══════════════════════════════════════════ 报告
def _f(v, signed: bool = True) -> str:
    return "—" if v is None else (f"{v:+.3f}" if signed else f"{v:.3f}")


def md_section(res: dict) -> list:
    dv = res.get("dev_xw_01") or {}
    cm, wc = dv.get("ca_common_units") or {}, dv.get("ca_adz_worst_case") or {}
    flag = ((res.get("ca") or {}).get("Adz") or {}).get(FLAG_KEY)
    L = [f"## [dev-XW-01] C-a 上涉及 A_dz 的比较 {LABEL}", "",
         "- 冻结 `ca` 表(json `ca`,按臂各自聚合)的 Adz 列:" + (f"{flag}(json `ca.Adz.{FLAG_KEY}`)。" if flag else "单元集与其他列相同,没有标记。"),
         f"- {CITE}。共同单元 = C-a 上全部臂(含 A_dz)都有种子 0 主作业行的单元:{cm.get('n_units')} 个 / {cm.get('C')} 簇"
         f"(预期 {EXPECT_COMMON[0]} / {EXPECT_COMMON[1]}:{'相符' if cm.get('matches_expected') else '不符'});去掉的单元 {cm.get('excluded_units')}"
         f"(簇 {cm.get('excluded_clusters')})。聚合口径同冻结 ca_desc。",
         f"- 最坏情形灵敏度:N/A 单元 {wc.get('imputed_units')}(簇 {wc.get('imputed_clusters')})的 A_dz 记 m_conf = −3、按优先级满足 = 否"
         "(task_kept 不补),全部 C-a 单元;只作披露。", "",
         "| 版本 | 臂 | n | 按优先级满足 | m_conf 均值 | task_kept 均值 |", "|---|---|---|---|---|---|"]
    for ver, tab in (("共同单元", cm.get("arms") or {}), ("最坏情形", wc.get("arms") or {})):
        for arm, x in tab.items():
            if ver == "最坏情形" and arm != "Adz":
                continue
            L.append(f"| {ver} | {ARM_NAME.get(arm, arm)} | {x['n']} | {x['prio_sat']['k']}/{x['prio_sat']['n']} | {_f(x['m_mean'])} | {_f(x['task_kept_mean'], False)} |")
    L += ["", "最坏情形只列 A_dz;其他臂在全部 C-a 单元上,数值即冻结 ca 表。", "",
          "| 配对(种子 0) | 版本 | 单元(簇) | m_conf 差:簇均值 [簇 bootstrap 95% 区间] | 按优先级满足:仅 A_dz 过 / 仅另一臂过 | 按优先级满足差:簇均值 [95% 区间] |",
          "|---|---|---|---|---|---|"]
    for ver, d in (("共同单元", cm.get("paired_adz_minus") or {}), ("最坏情形", wc.get("paired_adz_minus") or {})):
        for arm, y in d.items():
            mm, pp = y["m_conf_minus"], y["prio_sat_minus"]
            L.append(f"| A_dz − {ARM_NAME.get(arm, arm)} | {ver} | {y['n_units']}({y['C']}) | {_f(mm['mean_cluster'])} {AN.fmt_ci(mm['ci95_cluster_boot'])} | "
                     f"{pp['adz_only']} / {pp['x_only']} | {_f(pp['mean_cluster'])} {AN.fmt_ci(pp['ci95_cluster_boot'])} |")
    return L


def write_md(res: dict, path: Path) -> None:
    _ORIG_WRITE_MD(res, path)
    dv = res.get("dev_xw_01") or {}
    cm = dv.get("ca_common_units") or {}
    nca = len((cm.get("units") or [])) + len((cm.get("excluded_units") or []))
    line = (f"- {DEV.NOTE}。本次 N/A {dv.get('n_na_rows', 0)} 行 / {len(dv.get('na_units') or [])} 个单元:{dv.get('na_units')};"
            f"A_dz 实际计入的行数(种子 0 主作业)= {dv.get('adz_rows_used_by_cls')},对应单元数 = {dv.get('adz_units_by_cls')};"
            f"C-a 上涉及 A_dz 的比较见下文「[dev-XW-01] C-a 上涉及 A_dz 的比较」一节(涉及 A_dz 的 C-a 比较只引用共同单元版本,{cm.get('n_units')}/{nca} 个单元;其余臂之间的 C-a 描述与 F4 仍按冻结的 32 个单元)。")
    L = Path(path).read_text(encoding="utf-8").splitlines()
    i = next((k for k, s in enumerate(L) if s.startswith("- 入口记账错误")), None)
    if i is None:
        L.append(line)
    else:
        L.insert(i + 1, line)
    sec = md_section(res)
    j = next((k for k, s in enumerate(L) if s.startswith("## 功效")), None)
    if j is None:
        L += [""] + sec
    else:
        L[j:j] = sec + [""]
    XW.CM.atomic_write_text(path, "\n".join(L) + "\n")


AN.peek_host, AN.collect, AN.run_all, AN.write_md = peek_host, collect, run_all, write_md


# ═══════════════════════════════════════════ 合成数据自检(不读真实仿真)
def _invalid_metrics() -> dict:
    return {"validity": {"present": True, "valid": False, "refused": False, "why": "n/a"}, "all_pass": False, "eval": None, "v": None, "hard_ok": None,
            "m": None, "task_ok": [], "task_kept": None, "prio_sat": False, "cal": -3.0, "outcome3": "invalid", "safe_useful": False,
            "v_conf": None, "m_conf": -3.0, "boundary": None}


def dev01_selftest(argv: list) -> int:
    """S1 冻结登记表 + 冻结决定(只读输入,不含任何结果)生成全部作业;假 peek_host 给每个编译键一组合成指标(按键哈希定种子,
       冻结 _fake_metrics),已披露的 2 个 N/A 键抛 NotApplicableXW;XW.peek_sim / XW.load_xw 换成一调用就报错的桩,写文件的函数
       只许写临时目录。按 sprl1 主机名算出的 N/A 目录名必须等于已披露的。
    S2 完整分析(冻结 analyze,XW.OUT 指向临时目录):写出 analysis_xw.{json,md};N/A 正好 3 行 / 2 个目录;ca.Adz n = 29 且带标记,
       其他列 32 且无标记;共同单元 29 / 10 簇、各臂 n = 29;最坏情形 Adz n = 32;md 里有标记行、引用说明与新节(在「功效」之前)。
    S3 同一批行:冻结 run_all 与包装 run_all 的全部冻结键逐值相同(只多 ca.Adz 的标记键与 dev_xw_01),F1–F4 相同。
    S4 共同单元表、A_dz − A 配对差、最坏情形 A_dz 行按行独立重算一致;最坏情形其他臂 = 冻结 ca 表。
    S5 拒绝:缺一个非 N/A 仿真 / 缺第二个 N/A 键 / 多一个未披露的 N/A → 完整分析拒绝且不写文件;多一个未披露的 N/A 在 --partial
       时也拒;N/A 落在非 Adz 作业上 → FrameworkError;--partial 时只有一部分 N/A、缺若干仿真 → 照跑并写 _partial。
    S6 真实 results/exp_exec_weighted/(顶层与 logs/)的文件名、大小、mtime 不变。"""
    t0 = time.time()
    log = []

    def ok(c, msg):
        log.append(("PASS" if c else "FAIL", msg))
        print(f"[{'PASS' if c else 'FAIL'}] {msg}", flush=True)
        if not c:
            raise AssertionError(msg)

    def expect(exc, fn, msg):
        try:
            fn()
            got = None
        except exc as e:                                                 # noqa: PERF203
            got = e
        ok(got is not None, f"{msg} → {type(got).__name__ if got else '没有拒绝'}:{str(got)[:160] if got else ''}")

    real_out = XW.OUT

    def snap() -> dict:
        s = {}
        for d in (real_out, real_out / "logs"):
            if d.exists():
                for e in os.scandir(d):
                    if e.is_file():
                        st = e.stat()
                        s[str(Path(d) / e.name)] = (st.st_size, st.st_mtime_ns)
        return s
    before = snap()

    host = DISCLOSED_HOST
    reg, dx = XW.load_frozen()                                           # 冻结输入,不含任何仿真结果
    units = {u["uid"]: u for u in reg["test"]["units"]}
    dec = XW.r2_dec()
    J = XW.jobs_test(list(units.values()), dx, reg["test"].get("sens"))
    J += XW.jobs_ref(dx, [u for u in units.values() if u["cls"] == "N" and u["sub"] == "S0"])
    k_jobs, k_tbc = defaultdict(set), {}
    for j in J:
        u, cmd, _ = XW.job_cmd(j, units, dec)
        k = XW.ckey(u["task"], u["bias"], cmd)
        k_jobs[k].add((j["uid"], j["arm"]))
        k_tbc[k] = (u["task"], u["bias"], cmd)
    na_keys = sorted(k for k, s in k_jobs.items() if s <= set(DISCLOSED_NA))
    ok(len(na_keys) == 2 and set().union(*(k_jobs[k] for k in na_keys)) == set(DISCLOSED_NA),
       f"S1 已披露的 3 个 (单元, Adz) 恰好对应 2 个编译键,键下没有别的作业")
    dname = {k: f"{k_tbc[k][0]}_{XW.sim_key(*k_tbc[k], host=host)[1]}" for k in na_keys}
    ok(sorted(dname.values()) == sorted(DISCLOSED_NA_DIRS), f"S1 按主机 {host} 算出的 N/A 目录名 = 已披露的 {sorted(dname.values())}")
    na_second = next(k for k in na_keys if dname[k] == DISCLOSED_NA_DIRS[1])
    other_keys = sorted(k for k in k_jobs if k not in na_keys)
    undisclosed_adz = next(k for k in other_keys if k_jobs[k] and all(a == "Adz" for _, a in k_jobs[k])
                           and any(units[u]["cls"] == "CA" for u, _ in k_jobs[k]))
    a_key = next(k for k in other_keys if any(a == "A" for _, a in k_jobs[k]))

    S = {"drop": set(), "na": set(na_keys)}

    def fake_peek(task, bias, cmd, h):
        k = XW.ckey(task, bias, cmd)
        d = f"results/exp_exec_weighted/sims/{h}/{task}_{XW.sim_key(task, bias, cmd, host=h)[1]}"
        if k in S["drop"]:
            return None
        if k in S["na"]:
            raise DEV.NotApplicableXW({"dev": DEV.DEV_ID, "dir": d, "arm_from_cmd": DEV.NA_ARM, "reason": DEV.NA_REASON, "synthetic": True})
        return {"dir": d, "ok": True, "src": "dev01_selftest", "xw_result": {}, "fake_key": k}

    def fake_metrics(u, r, dec_=None):
        if r.get("src") == NA_SRC:
            return _invalid_metrics()
        seed = int(hashlib.sha1(r["fake_key"].encode("utf-8")).hexdigest()[:8], 16)
        return AN._fake_metrics(np.random.default_rng(seed), bool(XW.hard_items(u["contract"])))

    def forbid(*a, **k):
        raise AssertionError("dev01-selftest 读了真实仿真")

    tmp = Path(tempfile.mkdtemp(prefix="xw_dev01_an_"))
    g = globals()
    saved = {"peek": g["_ORIG_PEEK_HOST"], "um": XW.unit_metrics, "peek_sim": XW.peek_sim, "load_xw": XW.load_xw, "OUT": XW.OUT,
             "wj": XW.CM.atomic_write_json, "wt": XW.CM.atomic_write_text}

    def guard(fn):
        def w(path, *a, **k):
            if not str(Path(path).resolve()).startswith(str(tmp.resolve())):
                raise AssertionError(f"dev01-selftest 往临时目录以外写:{path}")
            return fn(path, *a, **k)
        return w

    def reset():
        NA_SEEN.clear()
        DEV_REC.clear()
        DEV_REC["na_rows"] = []

    def analyze(out: Path, partial: bool):
        out.mkdir(parents=True, exist_ok=True)
        XW.OUT = out
        reset()
        return AN.analyze(host, False, partial, False)

    g["_ORIG_PEEK_HOST"] = fake_peek
    XW.unit_metrics, XW.peek_sim, XW.load_xw = fake_metrics, forbid, forbid
    XW.CM.atomic_write_json, XW.CM.atomic_write_text = guard(saved["wj"]), guard(saved["wt"])
    try:
        # ── S2 完整分析
        o1 = tmp / "full"
        analyze(o1, False)
        files = sorted(p.name for p in o1.iterdir())
        ok(files == ["analysis_xw.json", "analysis_xw.md"], f"S2 完整分析写出 {files}")
        R = json.loads((o1 / "analysis_xw.json").read_text(encoding="utf-8"))
        dv = R["dev_xw_01"]
        ok(R["partial"] is False and R["n_missing"] == 0, "S2 不是 partial,缺 0 个仿真")
        ok(dv["n_na_rows"] == 3 and dv["na_units"] == sorted(u for u, _ in DISCLOSED_NA) and dv["na_by_cls"] == {"CA": 3},
           f"S2 N/A 3 行 / 3 个 C-a 单元:{dv['na_units']}")
        ok(sorted(Path(d).name for d in dv["na_dirs"]) == sorted(DISCLOSED_NA_DIRS) and dv["disclosed_check"]["dirs_checked"],
           f"S2 N/A 目录 = 已披露的 2 个:{[Path(d).name for d in dv['na_dirs']]}")
        ca = R["ca"]
        ok(ca["Adz"]["n"] == 29 and ca["Adz"].get(FLAG_KEY) == FLAG_FMT.format(n=29)
           and all(x["n"] == 32 and FLAG_KEY not in x for a, x in ca.items() if a != "Adz"),
           f"S2 冻结 ca 表:Adz n = 29 带标记「{ca['Adz'].get(FLAG_KEY)}」,其他列 {sorted((a, x['n']) for a, x in ca.items() if a != 'Adz')} 无标记")
        cm, wc = dv["ca_common_units"], dv["ca_adz_worst_case"]
        ok(cm["n_units"] == 29 and cm["C"] == 10 and cm["matches_expected"] and cm["excluded_clusters"] == [DISCLOSED_CLUSTER]
           and set(cm["arms"]) == {a for a, _ in ca_arms(dx)} and all(x["n"] == 29 for x in cm["arms"].values())
           and all(y["n_units"] == 29 and y["C"] == 10 for y in cm["paired_adz_minus"].values()),
           f"S2 共同单元 29 / 10 簇,全部臂 {sorted(cm['arms'])} n = 29,配对差 29(10)")
        ok(wc["arms"]["Adz"]["n"] == 32 and wc["imputed_clusters"] == [DISCLOSED_CLUSTER] and wc["imputed_units"] == sorted(u for u, _ in DISCLOSED_NA),
           "S2 最坏情形:A_dz 32 个单元,补的是 iiwa_a|J3-offB 的 3 个")
        md = (o1 / "analysis_xw.md").read_text(encoding="utf-8")
        sec = "## [dev-XW-01] C-a 上涉及 A_dz 的比较"
        ok(FLAG_FMT.format(n=29) in md and CITE in md and sec in md and md.index(sec) < md.index("## 功效") and LABEL in md[md.index(sec):md.index("## 功效")]
           and "[dev-XW-01] A_dz 在关节目标" in md, "S2 md:标记行、引用说明、【描述】新节在「功效」之前、摘要偏离行")

        # ── S3 冻结 run_all vs 包装 run_all(同一批合成行)
        XW.OUT = tmp / "unused"
        reset()
        rows, missing, infra, U = collect(reg, dx, host, False)
        ok(not missing and not infra and not any((r["uid"], r["arm"]) in set(DISCLOSED_NA) for r in rows), f"S3 collect:{len(rows)} 行,N/A 行已去掉")
        base = _ORIG_RUN_ALL(rows, U, reg, dx)
        wr = run_all(rows, U, reg, dx)
        w2 = copy.deepcopy(wr)
        w2["ca"]["Adz"].pop(FLAG_KEY)
        dvw = w2.pop("dev_xw_01")

        def dump(o):
            return json.dumps(o, ensure_ascii=False, default=str)
        ok(set(wr) - set(base) == {"dev_xw_01"} and dump(base) == dump(w2),
           f"S3 冻结 run_all 的全部 {len(base)} 个键逐值相同(包装只多 dev_xw_01 与 ca.Adz.{FLAG_KEY})")
        ok(dump(base["confirmatory"]) == dump(wr["confirmatory"]) and dump(base["confirmatory_supp"]) == dump(wr["confirmatory_supp"]),
           "S3 F1–F4 与确认族敏感性逐值相同")

        # ── S4 独立重算
        cmw, wcw = dvw["ca_common_units"], dvw["ca_adz_worst_case"]
        cset = set(cmw["units"])

        def main0(rr, arm, cfg, uset):
            return [r for r in rr if r["uid"] in uset and r["arm"] == arm and r["seed"] == 0 and r["role"] == "main" and not r["ik"]
                    and (cfg == "any" or AN.cfg_eq(r["cfg"], cfg))]
        bad = []
        for arm, cfg in ca_arms(dx):
            rr = main0(rows, arm, cfg, cset)
            x = cmw["arms"][arm]
            if not (len(rr) == 29 and x["prio_sat"]["k"] == sum(bool(r["m"]["prio_sat"]) for r in rr)
                    and abs(x["m_mean"] - float(np.mean([r["m"]["m_conf"] for r in rr]))) < 1e-12):
                bad.append(arm)
        ok(not bad, f"S4 共同单元表按行独立重算一致(不一致:{bad or '无'})")
        A0 = {r["uid"]: r for r in main0(rows, "A", "any", cset)}
        Z0 = {r["uid"]: r for r in main0(rows, "Adz", "any", cset)}
        byc = defaultdict(list)
        for u in cset:
            byc[units[u]["cluster"]].append(Z0[u]["m"]["m_conf"] - A0[u]["m"]["m_conf"])
        exp_d = float(np.mean([np.mean(v) for v in byc.values()]))
        ok(abs(cmw["paired_adz_minus"]["A"]["m_conf_minus"]["mean_cluster"] - exp_d) < 1e-12, f"S4 A_dz − A 的 m_conf 簇均值差独立重算一致({exp_d:+.4f})")
        z29 = main0(rows, "Adz", "any", {u for u, x in units.items() if x["cls"] == "CA"})
        exp_m = (sum(r["m"]["m_conf"] for r in z29) + 3 * WORST["m_conf"]) / 32
        ok(len(z29) == 29 and abs(wcw["arms"]["Adz"]["m_mean"] - exp_m) < 1e-12 and wcw["arms"]["Adz"]["prio_sat"]["k"] == sum(bool(r["m"]["prio_sat"]) for r in z29)
           and wcw["arms"]["Adz"]["prio_sat"]["n"] == 32, f"S4 最坏情形 A_dz:m 均值 = (29 行之和 − 9) / 32 = {exp_m:+.4f},按优先级满足 k 不变、n = 32")
        ok(all(dump(wcw["arms"][a]) == dump(base["ca"][a]) for a, _ in ca_arms(dx) if a != "Adz"), "S4 最坏情形表的其他臂 = 冻结 ca 表")

        # ── S5 拒绝与 partial
        o = tmp / "refuse_missing"
        S["drop"] = {other_keys[0]}
        expect(SystemExit, lambda: analyze(o, False), "S5 缺一个非 N/A 仿真 → 完整分析拒绝")
        ok(not any(o.iterdir()), "S5 拒绝时没有写文件")
        o = tmp / "refuse_na2"
        S["drop"] = {na_second}
        expect(SystemExit, lambda: analyze(o, False), "S5 缺第二个 N/A 键(未跑)→ 完整分析拒绝")
        ok(not any(o.iterdir()), "S5 拒绝时没有写文件")
        S["drop"], S["na"] = set(), set(na_keys) | {undisclosed_adz}
        o = tmp / "refuse_extra"
        expect(SystemExit, lambda: analyze(o, False), f"S5 多一个未披露的 N/A({sorted(k_jobs[undisclosed_adz])})→ 完整分析拒绝")
        o2 = tmp / "refuse_extra_partial"
        expect(SystemExit, lambda: analyze(o2, True), "S5 多一个未披露的 N/A → --partial 也拒绝")
        ok(not any(o.iterdir()) and not any(o2.iterdir()), "S5 拒绝时没有写文件")
        S["na"] = set(na_keys) | {a_key}
        o = tmp / "refuse_nonadz"
        expect(XW.FrameworkError, lambda: analyze(o, False), f"S5 N/A 落在含 A 作业的键上({sorted(k_jobs[a_key])[:2]})→ FrameworkError")
        S["na"], S["drop"] = set(na_keys) - {na_second}, {na_second, other_keys[0]}
        o = tmp / "partial"
        analyze(o, True)
        P = json.loads((o / "analysis_xw_partial.json").read_text(encoding="utf-8"))
        ok(sorted(p.name for p in o.iterdir()) == ["analysis_xw_partial.json", "analysis_xw_partial.md"] and P["partial"] is True
           and P["dev_xw_01"]["n_na_rows"] == 1 and P["n_missing"] >= 3, f"S5 --partial:N/A 1 行、缺 {P['n_missing']} 个作业 → 照跑,写 _partial")
    finally:
        g["_ORIG_PEEK_HOST"] = saved["peek"]
        XW.unit_metrics, XW.peek_sim, XW.load_xw, XW.OUT = saved["um"], saved["peek_sim"], saved["load_xw"], saved["OUT"]
        XW.CM.atomic_write_json, XW.CM.atomic_write_text = saved["wj"], saved["wt"]
        reset()
        if "--keep" not in argv:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"临时目录保留:{tmp}")
    ok(snap() == before, f"S6 真实 {XW._rel(real_out)}(顶层与 logs/)的文件名、大小、mtime 不变")
    print(f"analyze dev01-selftest 通过 {sum(1 for s, _ in log if s == 'PASS')} 项({time.time() - t0:.0f} s;只用合成指标,没有读任何真实仿真)")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "dev01-selftest":
        return dev01_selftest(sys.argv[2:])
    print(DEV.NOTE, flush=True)
    rc = AN.main()
    if DEV_REC.get("na_rows") is not None and (len(sys.argv) < 2 or sys.argv[1] not in ("power", "selftest")):
        print(json.dumps({"dev_xw_01": {"n_na_rows": len(DEV_REC["na_rows"]), "na": [(r["uid"], r["arm"], r["seed"], r["role"], r["dir"])
                                                                                     for r in DEV_REC["na_rows"]]}}, ensure_ascii=False, indent=1), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
