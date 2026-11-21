#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分层修正的升级判定实验(2026-11-08)。exp_sweep 任务(加长版)+ hmr2.run_program2 + pms.diag.DiagHMR。

每个探针带预期层级标签,看分层逻辑最后停在哪一层:
  none   不需处理(基线)        L0   执行异常,恢复后原样重跑      L1   规则补偿
  solver 求解器层补救            L1b  需要大模型 L1(不一一对应)    L2   需要 L2(策略冲突 / 不可达)
--mode decide:不调用大模型(replan_model = none、L1b = NoLLM),该叫大模型时记「需要 Lx」后停下 —— 只测判定对不对;
--mode llm --model oc:deepseek-v4.1-flash:真的调用,看 L1b / L2 能不能修好(第 2 步)。

命令(项目根目录,MUJOCO_GL=egl):
  .venv/bin/python pms/exp_levels.py run --seeds 0 1 2 3 4 --tag lv1 [--families comp strategy ...] [--device cuda:1]
  .venv/bin/python pms/exp_levels.py tally --tag lv1
结果:results/sweep/<tag>/levels/<探针>_s<种子>.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exp_sweep.hmr2 import run_program2   # noqa: E402
from exp_sweep.hmr2_run import get_task   # noqa: E402
from exp_sweep.program import verify_program   # noqa: E402
from exp_sweep.supervise_run import STRATEGY_PROBES, _add_helper, _disturber   # noqa: E402
from exp_sweep.sweep import ctx0, dump   # noqa: E402
from exp_sweep.tasks import PROBES   # noqa: E402
from exp_sweep.hmr2 import Supervisor2   # noqa: E402
from pms.diag import DiagHMR, NoLLM   # noqa: E402
from pms.prov import provenance   # noqa: E402

# 消融条件(实验 A,2026-11-08)。都用同一个大模型做 L1b / L2(--model)。
#   full     完整分层:L0 + 规则 L1 + 求解器诊断 + 大模型 L1b + L2
#   flat     不分层:不重跑、不做规则补偿、不诊断,阶段末一不过就调大模型 L2 重写策略
#   llm_l1   去掉规则层(阶段内监测 + 补偿、阶段间规则),连续量也交给大模型 L1b;注意这同时去掉了阶段内的平台计时、阶段内求解器补救和阶段内 L2 触发
#            (它们挂在规则层的阶段内监测上);总尝试数与完整版对齐(11-08 审查 P5)
#   no_A     去掉执行一致性监测(没有 L0)
#   no_diag  去掉求解器诊断(第二版 hmr2.Supervisor2 的原始逻辑)
#   flat_diag 不分层,但阶段末调大模型 L2 时把求解器诊断(压着的约束)一起给它(11-08 审查:区分「分层」与「诊断信息」各自的贡献)
CONDS = ("full", "flat", "llm_l1", "no_A", "no_diag", "flat_diag")


def make_sup(cond, contract, model, llm, pre):
    if cond == "full":
        return DiagHMR(contract, replan_model=model, l1b_llm=llm, pre_cycle=pre)
    if cond == "flat":
        return Supervisor2(contract, replan_model=model, l1b_llm=None, pre_cycle=pre, rule_on=False, gate_rule_max=0, l0_max=0)
    if cond == "llm_l1":
        sup = DiagHMR(contract, replan_model=model, l1b_llm=llm, pre_cycle=pre, rule_on=False, gate_rule_max=0)
        sup.l1b_gate = False                                                 # 11-08 审查:连续量也交给大模型 L1(不因约束压着直接跳 L2)
        sup.budget_n = sup.l0_max + 2 + sup.l2_max + 3                       # 与完整版(gate_rule_max = 2)同样的总尝试数
        return sup
    if cond == "no_A":
        return DiagHMR(contract, replan_model=model, l1b_llm=llm, pre_cycle=pre, exec_on=False)
    if cond == "flat_diag":
        sup = DiagHMR(contract, replan_model=model, l1b_llm=None, pre_cycle=pre, rule_on=False, gate_rule_max=0, l0_max=0, boost=1.0)
        sup.flat = True
        return sup
    if cond == "no_diag":
        return Supervisor2(contract, replan_model=model, l1b_llm=llm, pre_cycle=pre)
    raise ValueError(cond)


def _set(iid, **kv):
    def fn(contract):
        return [dict(i, **kv) if i["id"] == iid else i for i in contract]
    return fn


def _cripple(cl, sid, t_rel, attempt):
    """合成的求解器停滞(只测链路):补救开始前每个周期把采样噪声压到 0.01%、名义解清零。"""
    if attempt != 0 or getattr(cl, "_hmr_remedied", False):
        return
    if not hasattr(cl, "_tiny"):
        cl._tiny = cl.mppi.sigma * 1e-4
    if cl.mppi.sigma != cl._tiny:
        cl.mppi.sigma = cl._tiny
        cl.mppi._set_vectors()
    cl.mppi.knots.zero_()


def _wrist_pre(ctx):
    """局部最优探针的预备段:第 7 关节转到离上限 0.25 rad,末端位置不动。"""
    Q7_MAX = 3.016                                                            # FR3 第 7 关节上限(仿真模型 jnt_range)
    return {"gripper": "close", "terms": [
        {"id": "_q7", "level": "joint", "attr": "q", "joints": [7], "mode": "target", "target": Q7_MAX - 0.25,
         "sigma": 0.05, "weight": 4, "profile": "ramp_from_current", "t_ramp": 1.0},
        {"id": "_hold", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"], "mode": "target", "target": [float(x) for x in ctx["p0"]],
         "sigma": 0.005, "weight": 2}]}


def _wrist_contract(c):
    """局部最优探针的主段:末端不动,工具绕自身 z 轴再转 1.2 rad(第 7 关节已近上限,单靠它转不到)。"""
    return [{"id": "hold3", "cat": "LO", "desc": "末端保持在起始位置", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"], "stage": "go",
             "kind": "target", "target": [float(x) for x in c["p0"]], "tol": 0.005, "unit": "m", "sigma": 0.005, "weight": 2},
            {"id": "spin", "cat": "LO", "desc": "工具绕自身 z 轴相对阶段开始转 1.2 rad", "level": "tcp_motion", "attr": "ori", "frame": "start_tool",
             "axes": ["rx", "ry", "rz"], "stage": "go", "kind": "target", "target": [0.0, 0.0, 1.2], "tol": 0.035, "unit": "rad", "sigma": 0.02, "weight": 4,
             "profile": "ramp_from_current", "t_ramp": 1.0}]


# 探针:族 → [(名字, 任务, 设置)];设置键:bias(PROBES 名)/ bias_raw / strategy(STRATEGY_PROBES 名)/ helper(阶段, make)/ disturb / contract / pre_cycle / task_mod
STRAT_EXTRA = {
    "y_lock": ("follow_long", "track", lambda ctx: {"id": "_y_lock", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["y"], "mode": "range",
                                                    "lb": float(ctx["p0"][1] - 0.01), "ub": float(ctx["p0"][1] + 0.01), "sigma": 0.005, "penalty": "hard"}),
    "box_lock": ("seq_long", "press_hold", lambda ctx: {"id": "_x_box", "level": "tcp_motion", "attr": "pos", "frame": "surface:table", "axes": ["x"],
                                                         "mode": "upper", "ub": -0.065, "sigma": 0.005, "weight": 2, "penalty": "hard"}),
    "slow_lock": ("slide_long", "slide", lambda ctx: {"id": "_slow", "level": "tcp_motion", "attr": "speed", "frame": "base", "mode": "upper", "ub": 0.008,
                                                       "sigma": 0.005, "penalty": "hard"}),
}
FAMILIES = {
    "base": {"expect": {"none"}, "probes": [(f"base_{t}", t, {}) for t in
                                            ("config_long", "seq_long", "follow_long", "slide_long", "near_long", "tip_long", "period", "twist")]},
    "disturb": {"expect": {"L0", "none"}, "probes": [
        ("d_config", "config_long", {"disturb": "go,1.0,0.6,0,40,0"}),
        ("d_seq_up", "seq_long", {"disturb": "press_hold,0.6,0.5,0,0,25"}),
        ("d_follow", "follow_long", {"disturb": "track,3.0,0.6,0,0,-40"}),
        ("d_slide", "slide_long", {"disturb": "slide,2.0,0.5,30,0,0"}),
        ("d_near", "near_long", {"disturb": "track,3.0,0.6,0,40,0"})]},
    "comp": {"expect": {"L1"}, "probes": [
        ("follow", "follow_long", {"bias": "follow"}), ("align", "follow_long", {"bias": "align"}), ("tip", "tip_long", {"bias": "tip"}),
        ("near", "near_long", {"bias": "near"}), ("spot", "seq_long", {"bias": "spot"}),
        ("c_vy", "slide_long", {"bias_raw": {"kind": "scale", "value": 0.7, "id": "vy"}}),
        ("c_hold3", "config_long", {"bias_raw": {"kind": "add", "value": [0.012, -0.008, 0.0], "id": "hold3"}})]},
    "n121": {"expect": {"L1b"}, "probes": [
        ("keep2", "slide_long", {"bias": "keep2"}), ("arm", "config_long", {"bias": "arm"}), ("tap", "period", {"bias": "tap"}),
        ("touch", "seq_long", {"bias": "touch"}), ("hold", "seq_long", {"bias": "hold"}), ("twist", "twist", {"bias": "twist"})]},
    "strategy": {"expect": {"L2"}, "probes": [
        ("elbow_lock", "config_long", {"strategy": "elbow_lock"}), ("ceiling", "follow_long", {"strategy": "ceiling"}),
        ("y_lock", "follow_long", {"helper": "y_lock"}), ("box_lock", "seq_long", {"helper": "box_lock"}),
        ("slow_lock", "slide_long", {"helper": "slow_lock"})]},
    "infeasible": {"expect": {"L2"}, "probes": [
        ("i_high", "follow_long", {"contract": _set("follow", target=[0.0, 0.0, 0.60])}),
        ("i_joint", "config_long", {"contract": lambda c: c + [{"id": "q4", "cat": "INF", "desc": "第 4 关节角(目标超出上限 -0.152)", "level": "joint",
                                                                 "attr": "q", "joints": [4], "stage": "go", "kind": "target", "target": -0.05, "tol": 0.03,
                                                                 "unit": "rad", "sigma": 0.05, "weight": 2}]}),
        ("i_fast", "slide_long", {"contract": _set("vy", target=0.40, tol=0.04)})]},
    "solver": {"expect": {"solver"}, "probes": [
        ("syn_follow", "follow_long", {"pre_cycle": _cripple}), ("syn_tip", "tip_long", {"pre_cycle": _cripple})]},
    "localopt": {"expect": {"solver", "L2"}, "probes": [("lo_wall", "config_long", {"task_mod": "wall"}),   # 11-08:lo_wrist(第 7 关节近上限再转 1.2 rad)其他关节能补上,不是局部最优,已去掉
                                                        ("lo_wall2", "config_long", {"task_mod": "wall2"})]},
    # 11-08 补充(求解器诊断的样本量):墙的方向 / 距离 / 高度换几种;停滞换到别的任务。与上面两族合起来每族 6 个探针
    "localopt_x": {"expect": {"solver", "L2"}, "probes": [("lo_wall_ny", "config_long", {"task_mod": "wallp:y,-1,0.22,0.03"}),
                                                          ("lo_wall_hi", "config_long", {"task_mod": "wallp:y,1,0.20,0.05"}),
                                                          ("lo_wall_xhi", "config_long", {"task_mod": "wallp:x,1,0.20,0.05"}),
                                                          ("lo_wall_ny2", "config_long", {"task_mod": "wallp:y,-1,0.18,0.05"})]},
    "solver_x": {"expect": {"solver"}, "probes": [("syn_config", "config_long", {"pre_cycle": _cripple}), ("syn_seq", "seq_long", {"pre_cycle": _cripple}),
                                                  ("syn_slide", "slide_long", {"pre_cycle": _cripple}), ("syn_near", "near_long", {"pre_cycle": _cripple})]},
}


def _wall_contract(c):
    """局部最优探针:末端水平移到基座 y 方向 22 cm 外,中间有一堵墙(障碍盒,从桌面到比起点高 3 cm),要从墙上翻过去。"""
    return [{"id": "goal", "cat": "LO", "desc": "末端移到墙另一侧的目标点", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x", "y", "z"],
             "stage": "go", "kind": "target", "target": [float(c["p0"][0]), float(c["p0"][1] + 0.22), float(c["p0"][2])], "tol": 0.01, "unit": "m",
             "sigma": 0.01, "weight": 2, "profile": "ramp_from_current", "t_ramp": 1.0}]


def _wall_fixed(c):
    p0 = c["p0"]
    return {"obstacles": [[[float(p0[0] - 0.20), float(p0[1] + 0.07), 0.0], [float(p0[0] + 0.20), float(p0[1] + 0.12), float(p0[2] + 0.03)]]],
            "hand_pts": [[0, 0, 0, 0.03], [0, 0, -0.06, 0.04], [0, 0, -0.12, 0.05]]}


def _wall2_contract(c):
    return [{**_wall_contract(c)[0], "target": [float(c["p0"][0] + 0.18), float(c["p0"][1]), float(c["p0"][2])], "desc": "末端移到 +x 方向墙另一侧的目标点"}]


def _wall2_fixed(c):
    p0 = c["p0"]
    return {"obstacles": [[[float(p0[0] + 0.06), float(p0[1] - 0.20), 0.0], [float(p0[0] + 0.10), float(p0[1] + 0.20), float(p0[2] + 0.03)]]],
            "hand_pts": [[0, 0, 0, 0.03], [0, 0, -0.06, 0.04], [0, 0, -0.12, 0.05]]}


def _wallp(spec: str, c):
    """通用墙探针 wallp:<轴 x|y>,<方向 ±1>,<目标距离 m>,<墙高出起点 m>:目标在起点沿该轴 D 处,墙(轴对齐盒,厚 5 cm、横跨 ±20 cm)
    在起点外 7–12 cm,从桌面到起点高度 + h。"""
    ax, sg, D, h = spec.split(":")[1].split(",")
    i, sg, D, h = {"x": 0, "y": 1}[ax], float(sg), float(D), float(h)
    p0 = np.asarray(c["p0"], float)
    goal = p0.copy(); goal[i] += sg * D
    lo, hi = np.array([p0[0] - 0.20, p0[1] - 0.20, 0.0]), np.array([p0[0] + 0.20, p0[1] + 0.20, p0[2] + h])
    a, b = p0[i] + sg * 0.07, p0[i] + sg * 0.12
    lo[i], hi[i] = min(a, b), max(a, b)
    contract = [{**_wall_contract(c)[0], "target": [float(x) for x in goal], "desc": f"末端移到 {ax} 方向墙另一侧的目标点"}]
    fixed = {"obstacles": [[lo.tolist(), hi.tolist()]], "hand_pts": [[0, 0, 0, 0.03], [0, 0, -0.06, 0.04], [0, 0, -0.12, 0.05]]}
    return contract, fixed


def _install_fixed_loop():
    """任务字典带 fixed(障碍盒等执行器固定约束)时,hmr2.run_program2 建闭环要把它传给 make_loop(只影响带 fixed 的任务)。"""
    import exp_sweep.hmr2 as H
    if getattr(H.new_loop, "_fixed", False):
        return
    nl0 = H.new_loop

    def nl(task, seed, device):
        if task.get("fixed"):
            from cost_layers.config import make_loop
            return make_loop("tuned", mppi_seed=seed, device=device, fixed=task["fixed"], **({"scene": {"cubes": {}}} if task.get("scene") else {}))
        return nl0(task, seed, device)
    nl._fixed = True
    H.new_loop = nl


def build(probe_task: str, cfg: dict, c0):
    task, base = get_task(probe_task)
    if cfg.get("task_mod") == "wrist":
        task = {**task, "contract_fn": _wrist_contract, "pre": [(_wrist_pre, 8)]}
    if str(cfg.get("task_mod", "")).startswith("wallp:"):
        _install_fixed_loop()
        ct, fx = _wallp(cfg["task_mod"], c0)
        task = {**task, "contract_fn": (lambda c, ct=ct: ct), "fixed": fx, "verify_skip_s": {"*": 3.0},
                "stages": [{"id": "go", "time_s": 8.0, "timeout_s": 9.0, "helpers_fn": task["stages"][0]["helpers_fn"]}]}
    if cfg.get("task_mod") in ("wall", "wall2"):
        _install_fixed_loop()
        x_dir = cfg["task_mod"] == "wall2"                                    # wall2:目标在 +x 方向 18 cm,墙横在 x 方向
        task = {**task, "contract_fn": (_wall2_contract if x_dir else _wall_contract), "fixed": (_wall2_fixed if x_dir else _wall_fixed)(c0),
                "verify_skip_s": {"*": 3.0},
                "stages": [{"id": "go", "time_s": 8.0, "timeout_s": 9.0, "helpers_fn": task["stages"][0]["helpers_fn"]}]}
    bias = None
    if cfg.get("bias"):
        pr = PROBES[cfg["bias"]]
        assert pr["task"] == base, (cfg["bias"], base)
        bias = None if pr["bias"] is None else {**pr["bias"], "id": cfg["bias"]}
    if cfg.get("bias_raw"):
        bias = dict(cfg["bias_raw"])
    if cfg.get("strategy"):
        sp = STRATEGY_PROBES[cfg["strategy"]]
        task = _add_helper(task, sp["stage"], sp["make"])
    if cfg.get("helper"):
        t_name, stage, make = STRAT_EXTRA[cfg["helper"]]
        task = _add_helper(task, stage, make)
    contract = task["contract_fn"](c0)
    if cfg.get("contract"):
        contract = cfg["contract"](contract)
    pre = _disturber(cfg["disturb"], {}) if cfg.get("disturb") else cfg.get("pre_cycle")
    return task, base, contract, bias, pre


ORDER = {"none": 0, "fail_no_action": 0, "L0": 1, "L1": 2, "solver": 3, "L1b": 4, "L2": 5, "stop": 6}


def _lv_name(level: str, why) -> str:
    w = str(why)
    if level in ("需要L2", "L2"):
        return "L2"
    if level == "L1b" or (level == "stop" and "NO_LLM" in w):
        return "L1b"
    if level == "L1-求解器":
        return "solver"
    if level.startswith("L1-规则"):
        return "L1"
    if level == "L0":
        return "L0"
    return "stop" if level.startswith("stop") else level


def level_path(sup) -> list:
    """按时间顺序的层级事件(11-08 审查:调用大模型时 reached 只看 levels 会漏掉失败的 L2 / L1b)。
    同一次尝试里:阶段内规则补偿 → 阶段内求解器补救 → 阶段末的层级记录。大模型实际调用过的 L1b / L2 也算进去。"""
    ev = []
    for u in sup.rule_updates:
        if u["applied"]:
            ev.append((u.get("attempt", 0), 0 if u["where"] == "阶段内" else 2, "L1"))
    for k, lv in enumerate(sup.levels):
        ev.append((lv.get("attempt", 0), 1 if lv["level"] == "L1-求解器" else 3, _lv_name(lv["level"], lv.get("why"))))
    for rp in getattr(sup, "repairs", []):
        ev.append((rp.get("attempt", 0), 3, "L1b"))
    for rp in getattr(sup, "replans", []):
        ev.append((rp.get("attempt", 99) if isinstance(rp.get("attempt"), int) else 99, 4, "L2"))
    ev.sort(key=lambda x: (x[0], x[1]))
    return [e[2] for e in ev if e[2] != "stop"]


def reached(sup, final_pass) -> str:
    """这次运行最后到了哪一层(按最高的那一层计;大模型实际调用过的 L1b / L2 也算)。"""
    path = level_path(sup)
    if path:
        return max(path, key=lambda x: ORDER.get(x, 0))
    lv = [x["level"] for x in sup.levels]
    reasons = " ".join(str(x.get("why")) for x in sup.levels) + " " + str(sup.abort_reason or "")
    if "需要L2" in lv or "需要 L2" in reasons:
        return "L2"
    if "NO_LLM" in reasons or "L1b" in lv:
        return "L1b"
    if "L2" in lv:
        return "L2"
    if "L1-求解器" in lv:
        return "solver"
    if "L0" in lv:
        return "L0"
    if any(u["applied"] for u in sup.rule_updates):
        return "L1"
    return "none" if final_pass else "fail_no_action"


def cmd_run(a):
    c0 = ctx0(a.device)
    d = ROOT / "results" / "sweep" / a.tag / "levels"
    d.mkdir(parents=True, exist_ok=True)
    if a.mode == "llm":
        from pms.llm_oc import SPEND, install, make_llm_any
        install()
    for fam in a.families:
        for name, t_name, cfg in FAMILIES[fam]["probes"]:
            if a.probes and name not in a.probes:
                continue
            for seed in a.seeds:
                f = d / (f"{name}_s{seed}.json" if a.cond is None else f"{name}_{a.cond}_s{seed}.json")
                if f.exists() and not a.force:
                    continue
                task, base, contract, bias, pre = build(t_name, cfg, c0)
                if a.mode == "decide":
                    sup = DiagHMR(contract, replan_model="none", l1b_llm=NoLLM(), pre_cycle=pre)
                elif a.cond is None:
                    sup = DiagHMR(contract, replan_model=a.model, l1b_llm=make_llm_any(a.model), pre_cycle=pre)
                else:
                    sup = make_sup(a.cond, contract, a.model, make_llm_any(a.model), pre)
                sp0 = dict(SPEND) if a.mode == "llm" else None
                t0 = time.time()
                try:
                    ep = run_program2(task, copy.deepcopy(contract), bias, seed, a.device, hooks=sup)
                except Exception as e:                                    # noqa: BLE001  一个探针出错不影响整批
                    dump(f, {"probe": name, "family": fam, "seed": seed, "cond": a.cond, "mode": a.mode, "final_pass": False, "prov": provenance(a.device),
                             "error": f"{type(e).__name__}: {e}"})
                    print(f"{name} s{seed} 出错:{type(e).__name__}: {e}", flush=True); continue
                tk = {**task, "verify_skip_s": {**task["verify_skip_s"], **sup.verify_skip_adj}}
                final = verify_program(ep, ep["contract_final"], tk)
                fp = all(r["pass"] for r in final)
                lev = reached(sup, fp)
                path = level_path(sup)
                rep = sup.report()
                llm_stat = None
                if sp0 is not None:
                    lat = sum(x.get("latency_s") or 0 for x in rep["repairs"]) + sum(x.get("latency_s") or 0 for x in rep["replans"])
                    llm_stat = {"calls": SPEND["calls"] - sp0["calls"], "cost_usd": round(SPEND["list_cost"] - sp0["list_cost"], 5),
                                "tokens": SPEND["prompt_tokens"] + SPEND["completion_tokens"] - sp0["prompt_tokens"] - sp0["completion_tokens"],
                                "latency_s": round(lat, 1), "errors": SPEND["errors"] - sp0["errors"]}
                out = {"probe": name, "family": fam, "task": t_name, "seed": seed, "mode": a.mode, "cond": a.cond, "llm": llm_stat,
                       "model": a.model if a.mode == "llm" else None,
                       "expect": sorted(FAMILIES[fam]["expect"]), "reached": lev, "first_level": path[0] if path else "none", "level_path": path,
                       "decision_ok": lev in FAMILIES[fam]["expect"], "prov": provenance(a.device),
                       "final_pass": fp, "final_report": final, "stages": ep["stages"], "sim_s": round(time.time() - t0, 1),
                       "exec_alarms": len(rep["exec_events"]), **{k: rep.get(k, []) for k in ("levels", "rule_updates", "diagnoses", "replans", "repairs",
                                                                                       "exec_events", "aborted", "abort_reason", "gates")}}
                sup.close()
                dump(f, out)
                print(f"{fam:10s} {name:12s} s{seed}: 到达 {lev:15s} 预期 {sorted(FAMILIES[fam]['expect'])} {'✓' if out['decision_ok'] else '✗'} "
                      f"最终全过={fp} 执行报警 {out['exec_alarms']} 诊断 {[d_['action'][:12] for d_ in rep.get('diagnoses', [])]} ({out['sim_s']} s)", flush=True)
    if a.mode == "llm":
        print(f"OpenCode:调用 {SPEND['calls']} 次,标价合计 ${SPEND['list_cost']:.4f},错误 {SPEND['errors']} 次")


def cmd_atally(a):
    """实验 A 汇总:条件 × 族 的最终通过率、平均大模型调用次数 / 耗时 / 花费、平均仿真时长。"""
    d = ROOT / "results" / "sweep" / a.tag / "levels"
    agg = defaultdict(list)
    for f in sorted(d.glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("cond") is None:
            continue
        agg[(r["family"], r["cond"])].append(r)                               # 11-08 审查:出错的运行留在分母里(算失败),另外报个数
    fams = sorted({k[0] for k in agg})
    for fam in fams:
        for cond in CONDS:
            rs = agg.get((fam, cond))
            if not rs:
                continue
            L = [r.get("llm") or {} for r in rs]
            m = lambda k: sum(x.get(k, 0) or 0 for x in L) / len(rs)
            ne = sum("error" in r for r in rs)
            print(f"{fam:10s} {cond:8s} n={len(rs):3d}(出错 {ne}) 最终通过 {sum(bool(r.get('final_pass')) for r in rs):3d}/{len(rs):<3d} "
                  f"大模型 平均 {m('calls'):.2f} 次 / {m('latency_s'):.1f} s / ${m('cost_usd'):.4f}  仿真 {sum(r.get('sim_s', 0) for r in rs) / len(rs):.0f} s")


def cmd_tally(a):
    d = ROOT / "results" / "sweep" / a.tag / "levels"
    by = defaultdict(list)

    class _S:                                                                 # 用存档字段按新口径重算层级(11-08 审查后修的口径)
        def __init__(self, r):
            self.levels, self.rule_updates = r.get("levels", []), r.get("rule_updates", [])
            self.repairs, self.replans, self.abort_reason = r.get("repairs", []), r.get("replans", []), r.get("abort_reason")
    for f in sorted(d.glob("*.json")):
        r = json.loads(f.read_text())
        if "error" not in r and r.get("cond") is None:
            s_ = _S(r)
            r["reached"] = reached(s_, r["final_pass"])
            pth = level_path(s_)
            r["first_level"] = pth[0] if pth else "none"
            r["decision_ok"] = r["reached"] in FAMILIES[r["family"]]["expect"]
        by[r["family"]].append(r)
    for fam, rs in by.items():
        ok = [r for r in rs if "error" not in r]
        print(f"{fam:10s} 运行 {len(rs):3d}(出错 {len(rs) - len(ok)}) 判定正确 {sum(r['decision_ok'] for r in ok)}/{len(ok)} "
              f"最终全过 {sum(r['final_pass'] for r in ok)}/{len(ok)} 到达层级 {dict(Counter(r['reached'] for r in ok))} "
              f"执行报警的运行 {sum(r['exec_alarms'] > 0 for r in ok)} 首次层级 {dict(Counter(r.get('first_level') for r in ok))}")
        bad = [f"{r['probe']}s{r['seed']}→{r['reached']}" for r in ok if not r["decision_ok"]]
        if bad:
            print(f"           判定不对:{bad[:12]}{' …' if len(bad) > 12 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "tally", "atally"])
    ap.add_argument("--families", nargs="+", default=list(FAMILIES))
    ap.add_argument("--probes", nargs="*")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--tag", default="lv1")
    ap.add_argument("--mode", default="decide", choices=["decide", "llm"])
    ap.add_argument("--cond", default=None, choices=CONDS, help="实验 A 的消融条件(给了就按条件建监督器,文件名带条件)")
    ap.add_argument("--model", default="oc:deepseek-v4.1-flash")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    {"run": cmd_run, "tally": cmd_tally, "atally": cmd_atally}[a.cmd](a)


if __name__ == "__main__":
    main()
