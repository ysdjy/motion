# -*- coding: utf-8 -*-
"""分层修正第二版(2026-11-07 新建;不改任何已有文件,和 supervise.py 的 on_fail="hier" 并存,便于对比)。

和第一版的区别:
  L1 用规则,在阶段执行过程中就补偿(不等阶段结束、不重跑);L2 由监控计时触发 —— 补偿之后整体残差不降,超过 plateau_s 就让大模型改整体策略。

信号(每个规划周期,50 Hz):
  单项统计量:从最后一次补偿生效 + settle_s(没补过则从验收窗口起点)累计到现在的实测样本,至少 rule_window_s(默认 1.5 s)才判,统计量与验收同口径(target 均值 / upper p95 /
    lower p5 / range p5–p95 / 接触位置均值)。不用阶段累计量 —— 累计量被补偿之前的样本拖住,补偿生效了也看不出来。
  归一化违背 v:target |统计量 − 目标|/tol;upper (统计量 − ub)/tol;lower (lb − 统计量)/tol;v > 1 即不达标。
  整体残差 R = Σ max(0, v_i − 1)(只累计超出容差的部分;全部达标时 R = 0)。

L0(同第一版):比较器 A 报警期间暂停 L1 与计时;阶段末若报过警 → 恢复段后原样重跑,不叫大模型。
L1 规则补偿(一一对应的连续量条目:target / lower / upper / range / contact_at;补偿量加在下发值上):
  触发:某项不达标持续 debounce_s,且距上次补偿已过 settle_s + rule_window_s。
  更新(逐分量割线):c ← c − e/ĝ。e = 统计量 − 瞄准值(target 瞄目标;界类瞄容差带内侧半个容差处);ĝ 初值 1,
    之后 ĝ = Δe/Δc(|Δc| ≥ 0.5 tol 时才更新);ĝ 落在 [g_lo, g_hi] 之外(含负值)→ 这一项判「补偿无效」,规则不再补它。
  限幅:单步 |Δc| ≤ step_max_tol·tol,累计 |c| ≤ comp_max_tol·tol。补偿立刻重新下发(同一阶段内,不重跑)。
监控 → L2(以最后一次补偿生效时刻为基准;没有可补的项时以首次不达标时刻为基准):
  settle_s + rule_window_s 之后:R = 0 → 成功;R ≥ (1 − eps)·R_u 持续 plateau_s → 「补偿后整体残差不变」→ L2;
  R > (1 + eps)·R_u 持续 worse_s → 撤回这次补偿 → L2;规则补偿次数达到 n_rule_max 仍不达标 → L2。
  L2 触发后结束这一阶段,调用大模型(仿真时间暂停 ≈ 真机原地保持),换策略后重新开始这一阶段。
阶段末门控(兜底;短阶段来不及在阶段内补偿):不过 → L0 / 阶段内已判 L2 → L2 / 规则可补的项在两次尝试之间按同一条割线规则补(最多 gate_rule_max 次)
  / (可选 l1b)大模型 L1 / 否则 L2。事件型条目(时长、切换阈值、周期、到达、构型、力矩)只在阶段末验收。
验收窗口:阶段内补偿过的阶段,连续量条目从「最后一次补偿生效 + settle_s」开始统计;时间型阶段不够 min_win_s 就延长(≤ ext_max_s);
  带时长条目或事件切换的阶段不延长,窗口不够时退回整段统计。
"""
from __future__ import annotations

import copy

import numpy as np

from exp_sweep.core import REPAIR_FIELDS, apply_patch, default_comp, eval_target, new_loop, perceived_frames, planner_term, true_frames
from exp_sweep.program import _Rz, _eff_scalar, _set_frames, contact_torque_z, normal_force, scene_friction, verify_program
from exp_sweep.supervise import LIVE_KINDS, Supervisor, _f, _stat

RULE_KINDS = ("target", "lower", "upper", "range", "contact_at")


# ───────────────────────────────────────────── 执行:program.run_program 的拷贝 + 阶段内换规格 / 延长 / 提前结束
def run_program2(task: dict, contract: list, bias: dict | None, seed: int, device: str, hooks) -> dict:
    """与 program.run_program 同一套执行(拷贝,逐行对应),多三件事:阶段内 hooks.respec 换规格、hooks.extension 延长时间型阶段、
    hooks.stop_stage 提前结束。没有发生这三件事时物理过程与 run_program(hooks=Supervisor) 逐位相同(hmr2_run selftest)。"""
    assert hooks is not None and hooks.monitor_cycles >= 1, "第二版需要逐周期监测(monitor_cycles ≥ 1)"
    cl = new_loop(task, seed, device)
    scene_friction(cl, task)
    p0, R0 = (a.copy() for a in cl.tcp())
    frames = true_frames(cl, task, p0, R0)
    cl.extra_frames.update(perceived_frames(frames, bias))
    ctx = {"p0": p0, "R0": R0, "q0": cl.d.qpos[:7].copy()}
    tq_log = []
    for spec_fn, n in task.get("pre", []):
        cl.run([spec_fn(ctx)] * n)
    dyn = task.get("dynamic", {})
    off = (np.asarray(bias["value"], float) if bias and bias["kind"] == "frame" else None)

    def live(t_rel):
        out = {}
        for name, fn in dyn.items():
            R, p = fn(t_rel, frames[name])
            out[name] = (R, p + (off if off is not None and bias["frame"] == name else 0.0))
        return out

    seq = next((i for i in contract if i["kind"] == "sequence"), None)
    order = list(seq["target"]) if seq is not None else [s["id"] for s in task["stages"]]
    stages = {s["id"]: s for s in task["stages"]}
    chunk = task.get("chunk", 5)
    t_prog = cl.t
    if dyn:
        cl.extra_frames.update(live(0.0))
    rec, w0 = [], len(cl.windows)
    hooks.start(cl=cl, task=task, frames=frames, ctx=ctx, t_prog=t_prog, tq_log=tq_log, w0=w0)

    def build_spec(sid, st, contract):
        in_stage = lambda i: i.get("stage") == sid or sid in i.get("also_stages", ())
        items = [i for i in contract if in_stage(i) and i["kind"] in ("target", "lower", "upper", "range", "path") and i.get("enabled", True)]
        ov = hooks.helpers_override or {}
        helpers = [dict(h) for h in ov[sid]] if sid in ov else st.get("helpers_fn", lambda c: [])(ctx)
        terms = [planner_term(i, bias) for i in items] + helpers
        stiff = None
        for i in contract:
            if not in_stage(i) or not i.get("enabled", True):
                continue
            if i["kind"] == "arrival":
                terms.append({"id": i["id"], "level": "tcp_motion", "attr": "pos", "frame": i["frame"], "axes": i["axes"], "mode": "target",
                              "target": i["goal"], "sigma": 0.005, "weight": 2, "profile": "ramp_from_current", "t_ramp": max(0.05, _eff_scalar(i, bias))})
            elif i["kind"] == "contact_at":
                terms.append(planner_term({**i, "kind": "target"}, bias))
            elif i["kind"] == "config":
                side = 1.0 if i["target"] == "left" else -1.0
                b = side * i["margin"] + float(np.asarray(i.get("comp", 0.0), float).reshape(-1)[0])
                if bias and bias.get("id") == i["id"]:
                    b += float(bias["value"])
                terms.append({"id": i["id"], "level": "joint", "attr": "link_pos", "link": 4, "axes": ["y"], "mode": "lower" if side > 0 else "upper",
                              ("lb" if side > 0 else "ub"): b, "sigma": 0.01, "weight": 4})
            elif i["kind"] == "contact" and "floor" in i:
                lb = i["floor"] + float(np.asarray(i.get("comp", 0.0), float).reshape(-1)[0])
                if bias and bias.get("id") == i["id"] and bias["kind"] == "add":
                    lb += float(bias["value"])
                terms.append({"id": i["id"], "level": "tcp_force", "attr": "force", "frame": i["frame"], "axes": ["z"], "mode": "lower", "lb": lb,
                              "sigma": 0.5, "weight": 6})
            elif i["kind"] == "stiffness":
                stiff = {"trans": [float(x) for x in np.asarray(i["target"], float)], "rot": 100.0, "frame": i["frame"]}
        per = next((i for i in contract if i.get("stage") == sid and i["kind"] == "period"), None)
        if per is not None:
            T = _eff_scalar(per, bias)
            F = per["force_peak"]
            terms.append({"id": per["id"], "level": "tcp_force", "attr": "force", "frame": per["frame"], "axes": ["z"], "mode": "target", "sigma": 2.0,
                          "weight": 3, "schedule": [[0.0, per["force_base"]], [0.35 * T, F], [0.7 * T, per["force_base"]], [T, per["force_base"]]], "period": T})
        spec = {"terms": terms}
        if stiff is not None:
            spec["stiffness"] = stiff
        if st.get("gripper"):
            spec["gripper"] = st["gripper"]
        if next((i for i in contract if i.get("stage") == sid and i["kind"] == "torque" and i.get("enabled", True)), None) is not None:
            spec["terms"].append({"id": "_twist", "level": "tcp_motion", "attr": "ori", "frame": "_tw", "axes": ["rx", "ry", "rz"], "mode": "target",
                                  "target": [0, 0, 0], "sigma": 0.02, "weight": 4})
        return spec

    def run_stage(sid, st, contract):
        spec = build_spec(sid, st, contract)
        dur = next((i for i in contract if i.get("stage") == sid and i["kind"] == "duration"), None)
        trig = next((i for i in contract if i.get("stage") == sid and i["kind"] == "trigger"), None)
        t_need = _eff_scalar(dur, bias) if dur is not None else st.get("time_s")
        thr = _eff_scalar({**trig, "comp": trig.get("comp", 0.0)}, None) if trig is not None else None
        f_scale = float(bias["value"]) if (bias and trig is not None and bias.get("id") == trig["id"] and bias["kind"] == "sensor_scale") else 1.0
        tq = next((i for i in contract if i.get("stage") == sid and i["kind"] == "torque" and i.get("enabled", True)), None)
        if tq is not None:
            Rtw, ptw = cl.tcp()[1].copy(), cl.tcp()[0].copy()
            cl.extra_frames["_tw"] = (Rtw, ptw)
            tau_t = float(tq["target"]) + float(np.asarray(tq.get("comp", 0.0), float).reshape(-1)[0])
            t_scale = float(bias["value"]) if (bias and bias.get("id") == tq["id"] and bias["kind"] == "sensor_scale") else 1.0
            th, tau_f = 0.0, 0.0
        first = True
        rec_ = (hooks.recover or {}).pop(sid, None)
        if rec_ is not None:
            t_r = cl.t
            while cl.t - t_r < rec_["max_s"]:
                cl.step_window(spec if first else None, chunk)
                first = False
                if dyn:
                    fr = live(cl.t - t_prog)
                    cl.extra_frames.update(fr)
                    _set_frames(cl, fr)
                if hooks.recovered(cl):
                    break
            rec_.update(t_start=round(t_r, 3), t_end=round(cl.t, 3), ok=bool(hooks.recovered(cl)))
        t0, done, why, f_at = cl.t, False, "timeout", None
        fixed_len = dur is not None or trig is not None or t_need is None
        ext = 0.0
        while cl.t - t0 < st["timeout_s"] + ext:
            for j_ in range(0, chunk, hooks.monitor_cycles):
                cl.step_window(spec if first else None, min(hooks.monitor_cycles, chunk - j_))
                first = False
                hooks.on_cycles(cl, sid, t0)
                if hooks.respec is not None:                                 # 阶段内规则补偿:换补偿量后的规格下一个周期生效,不重跑
                    contract, hooks.respec = hooks.respec, None
                    spec, first = build_spec(sid, st, contract), True
                if hooks.stop_stage:
                    break
            if hooks.stop_stage:
                why = "supervisor:" + str(hooks.stop_stage); hooks.stop_stage = None
                break
            ext = 0.0 if fixed_len else hooks.extension(sid, t0, t_need)
            if tq is not None:
                tau = contact_torque_z(cl)
                a = min(1.0, chunk * 0.02 / 0.05)
                tau_f += a * (tau - tau_f)
                tq_log.append((cl.t, tau))
                th = float(np.clip(th + tq["k_adm"] * (tau_t - t_scale * tau_f) * chunk * 0.02, -0.4, 0.4))
                fr = {"_tw": (_Rz(th) @ Rtw, ptw)}
                cl.extra_frames.update(fr)
                _set_frames(cl, fr)
            if dyn:
                fr = live(cl.t - t_prog)
                cl.extra_frames.update(fr)
                _set_frames(cl, fr)
            if thr is not None and normal_force(cl) * f_scale >= thr:
                done, why, f_at = True, "trigger", normal_force(cl); break
            if t_need is not None and thr is None and cl.t - t0 >= t_need + ext - 1e-9:
                done, why = True, "time"; break
        return {"id": sid, "t0": t0, "t1": cl.t, "done": done, "exit": why, "f_at_switch": f_at, "extension_s": round(ext, 3)}, contract

    for sid in order:
        st = stages.get(sid)
        if st is None:
            rec.append({"id": sid, "t0": cl.t, "t1": cl.t, "done": False, "exit": "unknown_stage"}); continue
        r_, contract = run_stage(sid, st, contract)
        while True:
            act, new_contract = hooks.on_stage_end(cl, sid, r_, rec, contract)
            if act != "retry":
                break
            if new_contract is not None:
                contract = new_contract
            r2, contract = run_stage(sid, st, contract)
            r_ = {**r2, "attempts": r_.get("attempts", []) + [{k: v for k, v in r_.items() if k != "attempts"}]}
        rec.append(r_)
        if hooks.aborted:
            break
    log = cl.arrays()
    return {"cl": cl, "log": log, "w0": w0, "stages": rec, "torque_log": np.asarray(tq_log).reshape(-1, 2), "frames": frames, "ctx": ctx, "t_prog": t_prog,
            "dyn_fn": live if dyn else None, "contract_final": contract,
            "accepted": all(w["accepted"] or w.get("reason") == "这个窗口没有新规格" for w in cl.windows[w0:]),
            "reject_reason": next((w.get("reason") for w in cl.windows[w0:] if not w["accepted"] and w.get("reason") != "这个窗口没有新规格"), None),
            "rejected_terms": [x for w in cl.windows[w0:] for x in (w.get("rejected_terms") or [])]}


# ───────────────────────────────────────────── 规则补偿的数学(阶段内与阶段间共用)
def violation(kind: str, item: dict, stat) -> np.ndarray:
    """逐分量归一化违背 v(> 1 即不达标)。"""
    s, tol = np.asarray(stat, float), float(item["tol"])
    if kind in ("target", "contact_at"):
        return np.abs(s.reshape(-1) - eval_target(item)) / tol
    if kind == "upper":
        return (s.reshape(-1) - np.atleast_1d(np.asarray(item["ub"], float))) / tol
    if kind == "lower":
        return (np.atleast_1d(np.asarray(item["lb"], float)) - s.reshape(-1)) / tol
    s = s.reshape(-1, 2)                                                      # range:[p5, p95]
    return np.maximum((np.atleast_1d(np.asarray(item["lb"], float)) - s[:, 0]) / tol, (s[:, 1] - np.atleast_1d(np.asarray(item["ub"], float))) / tol)


def aim_error(kind: str, item: dict, stat) -> np.ndarray:
    """逐分量瞄准误差 e = 统计量 − 瞄准值;只对不达标的分量非零。target 瞄目标;界类瞄容差带内侧半个容差处。"""
    s, tol = np.asarray(stat, float), float(item["tol"])
    v = violation(kind, item, stat)
    bad = v > 1.0
    if kind in ("target", "contact_at"):
        e = s.reshape(-1) - eval_target(item)
    elif kind == "upper":
        e = s.reshape(-1) - (np.atleast_1d(np.asarray(item["ub"], float)) - 0.5 * tol)
    elif kind == "lower":
        e = s.reshape(-1) - (np.atleast_1d(np.asarray(item["lb"], float)) + 0.5 * tol)
    else:
        s = s.reshape(-1, 2)
        lb, ub = np.atleast_1d(np.asarray(item["lb"], float)), np.atleast_1d(np.asarray(item["ub"], float))
        e = np.where(s[:, 0] < lb - tol, s[:, 0] - (lb + 0.5 * tol), s[:, 1] - (ub - 0.5 * tol))
    return np.where(bad, e, 0.0)


def excess(kind, item, stat) -> float:
    return float(max(0.0, np.max(violation(kind, item, stat)) - 1.0))


def secant_step(item: dict, e: np.ndarray, st: dict, g_lo: float, g_hi: float, step_max_tol: float, comp_max_tol: float):
    """一项的一步割线补偿。st = {"g": 逐分量 ĝ, "prev": (c, e) 或 None}。返回 (新 comp, 信息);新 comp 为 None 表示判「补偿无效」。"""
    tol = float(item["tol"])
    c_raw = item.get("comp", default_comp(item))
    vec_shape = np.ndim(c_raw) > 0 or np.ndim(item.get("target", item.get("lb", item.get("ub", 0.0)))) > 0   # 11-07:单元素列表目标的 comp 也要是列表,否则补丁被拒
    c = np.atleast_1d(np.asarray(c_raw, float)).astype(float)
    g = st.setdefault("g", np.ones_like(c))
    info = {"e": _f(e), "c_old": _f(c)}
    if st.get("prev") is not None:
        c_p, e_p = st["prev"]
        dc, de = c - c_p, e - e_p
        for k in range(len(c)):
            if abs(dc[k]) >= 0.5 * tol and e[k] != 0.0:
                gr = de[k] / dc[k]
                info.setdefault("g_raw", []).append(round(float(gr), 3))
                if not (g_lo <= gr <= g_hi):
                    info["fail"] = f"分量 {k} 灵敏度 ĝ = {gr:.3f} 不在 [{g_lo}, {g_hi}]"
                    return None, info
                g[k] = gr
    step = np.clip(-e / g, -step_max_tol * tol, step_max_tol * tol)
    c_new = np.clip(c + step, -comp_max_tol * tol, comp_max_tol * tol)
    st["prev"] = (c.copy(), e.copy())
    info.update(g=_f(g, 3), c_new=_f(c_new))
    return (c_new.tolist() if (c_new.size > 1 or vec_shape) else float(c_new[0])), info


class _NoLLM:
    def ask(self, *a, **k):
        raise RuntimeError("第二版默认不用大模型 L1(打开 l1b 才会调用)")


# ───────────────────────────────────────────── 监督
class Supervisor2(Supervisor):
    def __init__(self, contract: list, *, replan_model: str, l1b_llm=None, rule_window_s: float = 1.5, settle_s: float = 0.5,
                 debounce_s: float = 0.5, plateau_s: float = 1.5, eps: float = 0.1, worse_s: float = 0.5, g_lo: float = 0.3, g_hi: float = 3.0,
                 step_max_tol: float = 4.0, comp_max_tol: float = 10.0, n_rule_max: int = 6, gate_rule_max: int = 2, min_win_s: float = 1.0,
                 ext_max_s: float = 6.0, rule_on: bool = True, exec_on: bool = True, **kw):
        kw.setdefault("monitor_cycles", 1)
        super().__init__(contract, on_fail="hier", repair_llm=l1b_llm or _NoLLM(), replan_model=replan_model, exec_monitor=exec_on, **kw)
        self.rule_on = rule_on                                                # 11-08 消融用:False = 不做规则补偿(阶段内与阶段间)
        self.l1b = l1b_llm is not None
        self.rule_window_s, self.settle_s, self.debounce_s, self.plateau_s, self.eps, self.worse_s = rule_window_s, settle_s, debounce_s, plateau_s, eps, worse_s
        self.g_lo, self.g_hi, self.step_max_tol, self.comp_max_tol = g_lo, g_hi, step_max_tol, comp_max_tol
        self.n_rule_max, self.gate_rule_max, self.min_win_s, self.ext_max_s = n_rule_max, gate_rule_max, min_win_s, ext_max_s
        self.respec = None
        self.rule_updates, self.monitor_log, self.verify_skip_adj = [], [], {}
        self._s = {}                                                          # (阶段, t0) → 阶段内规则状态
        self._gs = {}                                                         # 阶段 → 阶段间规则状态(跨尝试)
        self._wn = max(2, int(round(rule_window_s / 0.02)))
        self._sn = int(round(settle_s / 0.02))

    # ── 阶段内
    def _state(self, sid, t0):
        key = (sid, t0)
        if key not in self._s:
            self._s[key] = {"sid": sid, "t0": t0, "n0": {}, "bad_since": {}, "rule": {}, "dead": set(), "base_t": None, "R_u": None, "upd_t": None,
                            "plateau_t": None, "worse_t": None, "n_upd": 0, "pending_l2": None, "last_contract": None, "R": None}
        return self._s[key]

    def _window_stats(self, s):
        """各可判项的窗口统计量(只取最后一次补偿生效 + settle 之后的样本)。"""
        out = {}
        for iid, tr in self._tracks.items():
            if tr.kind not in RULE_KINDS or (tr.kind in LIVE_KINDS and tr.model is None):
                continue
            n0 = s["n0"].get(iid, 0) + (self._sn if s["upd_t"] is not None or s.get("settle_after_reset") else 0)
            xs = tr.x[n0:]                                                   # 从上次补偿生效 + settle(或验收窗口起点)累计到现在,与验收同口径
            if len(xs) < self._wn:                                           # 样本不够 rule_window_s 不判(11-07:0.5 s 窗口把跟随运动物体的周期性滞后当成偏差)
                continue
            x = np.asarray(xs, float)
            st_fn = (lambda y: y.mean(0)) if tr.kind == "contact_at" else (lambda y: _stat(tr.kind, tr.item, y)[0])
            h = len(x) // 2
            out[iid] = (tr, st_fn(x), st_fn(x[:h]), st_fn(x[h:]))
        return out

    @staticmethod
    def _stationary(kind, item, sa, sb) -> tuple[bool, str]:
        """偏差平稳性:样本前后两半都不达标、偏差方向一致、大小相差不超过一半,才当系统偏差去补;
        否则是周期性 / 过渡性的波动(11-07 tip_long:跟随运动物体时补偿方向来回翻转),不补。"""
        va, vb = violation(kind, item, sa), violation(kind, item, sb)
        if va.max() <= 1.0 or vb.max() <= 1.0:
            return False, f"前后两半不都超差(v = {va.max():.2f} / {vb.max():.2f})"
        ea, eb = aim_error(kind, item, sa), aim_error(kind, item, sb)
        both = (np.abs(ea) > 0) & (np.abs(eb) > 0)
        if np.any(np.sign(ea[both]) != np.sign(eb[both])):
            return False, f"前后两半偏差方向相反({_f(ea)} / {_f(eb)})"
        big = np.maximum(np.abs(ea), np.abs(eb))
        if np.any(np.abs(ea - eb) > 0.5 * big + 1e-12):
            return False, f"前后两半偏差大小差一半以上({_f(ea)} / {_f(eb)})"
        return True, ""

    def on_cycles(self, cl, sid: str, t0: float) -> None:
        super().on_cycles(cl, sid, t0)
        if not self.rule_on:
            return
        s = self._state(sid, t0)
        if s["pending_l2"] is not None:
            return
        t = cl.t
        ex = self._ex.get((sid, t0))
        if ex is not None and (any(t - a["t"] <= 0.5 for a in ex["alarms"]) or any(o is not None for o in ex["over"].values())):
            s["plateau_t"] = s["worse_t"] = None                              # 比较器 A 报警期间:残差不代表补偿效果,暂停;
            s["bad_since"] = {}                                               # 统计起点重置到报警结束 + settle 之后(11-07:上推后规则把掉下去的力当偏差补了 3 次)
            for iid, tr in self._tracks.items():
                s["n0"][iid] = len(tr.x)
            s["settle_after_reset"] = True
            return
        ws = {k: v for k, v in (self._window_stats(s) or {}).items() if not v[0].item.get("report_only")}   # 11-08 审查:只报告的条目(optimize)不计入残差
        if not ws:
            return
        R = sum(excess(tr.kind, tr.item, w[1]) for tr, *w in ws.values())
        s["R"] = R
        failing = [iid for iid, (tr, stat, _, _) in ws.items() if excess(tr.kind, tr.item, stat) > 0]
        for iid in list(s["bad_since"]):
            if iid not in failing:
                s["bad_since"].pop(iid)
        for iid in failing:
            s["bad_since"].setdefault(iid, t)
        if s["base_t"] is not None and t >= s["base_t"] + (self.settle_s if s["upd_t"] is not None else 0.0) + self.rule_window_s:
            if R <= 1e-9:                                                     # 进入容差:停止计时
                s["base_t"] = s["R_u"] = s["plateau_t"] = s["worse_t"] = None
            elif s["R_u"] is not None and R > (1 + self.eps) * s["R_u"] and s["upd_t"] is not None:
                s["worse_t"] = s["worse_t"] or t; s["plateau_t"] = None
                if t - s["worse_t"] >= self.worse_s:
                    if s["last_contract"] is not None:                       # 越补越坏:先撤回这次补偿
                        self.respec = self._contract_now = s["last_contract"]
                    return self._trigger_l2(s, [f"补偿后整体残差变大 {s['R_u']:.2f} → {R:.2f},持续 {self.worse_s} s(已撤回这次补偿)"])
            elif s["R_u"] is not None and R >= (1 - self.eps) * s["R_u"]:
                s["plateau_t"] = s["plateau_t"] or t; s["worse_t"] = None
                if t - s["plateau_t"] >= self.plateau_s:
                    what = "补偿后" if s["upd_t"] is not None else "没有可规则补偿的项,"
                    return self._trigger_l2(s, [f"{what}整体残差不变 {s['R_u']:.2f} → {R:.2f},持续 {self.plateau_s} s"])
            else:
                s["plateau_t"] = s["worse_t"] = None
        due = [iid for iid in failing if t - s["bad_since"][iid] >= self.debounce_s]
        if not due:
            return
        ready = s["upd_t"] is None or t >= s["upd_t"] + self.settle_s + self.rule_window_s
        if not ready:
            return
        if s["n_upd"] >= self.n_rule_max:
            return self._trigger_l2(s, [f"阶段内规则补偿 {s['n_upd']} 次仍不达标 {due}"])
        patch, infos, n_dead = [], [], 0
        for iid in due:
            if iid in s["dead"]:
                n_dead += 1
                continue
            tr, stat, sa, sb = ws[iid]
            item = next(i for i in self._contract_now_or0() if i["id"] == iid)
            ok_, why_ = self._stationary(tr.kind, item, sa, sb)
            if not ok_:
                infos.append({"id": iid, "skip": "非平稳,不补:" + why_})
                continue
            st_ = s["rule"].setdefault(iid, {})
            c_new, info = secant_step(item, aim_error(tr.kind, item, stat), st_, self.g_lo, self.g_hi, self.step_max_tol, self.comp_max_tol)
            infos.append({"id": iid, **info})
            if c_new is None:
                s["dead"].add(iid); n_dead += 1
            else:
                patch.append({"id": iid, "field": "comp", "value": c_new})
        if not patch:
            if n_dead and s["base_t"] is None:                              # 有项被判「补偿无效」:以现在为基准等平台计时 → L2
                s["base_t"], s["R_u"] = t, R
            if infos and t - s.get("skip_log_t", -9.0) >= 1.0:              # 只有非平稳的项:不补、不计时,留给阶段末门控(记录限频 1 s)
                s["skip_log_t"] = t
                self.rule_updates.append({"stage": sid, "attempt": self._attempt.get(sid, 0), "t": round(t, 3), "where": "阶段内", "applied": False,
                                          "items": infos, "R": round(R, 3)})
            return
        cur = self._contract_now_or0()
        new_c, probs = apply_patch(cur, patch, REPAIR_FIELDS)
        if probs and len(probs) >= len(patch):                               # 补丁全被拒:如实记录,不当成补过(11-07 发现形状不符被静默拒掉)
            self.rule_updates.append({"stage": sid, "attempt": self._attempt.get(sid, 0), "t": round(t, 3), "where": "阶段内", "applied": False,
                                      "items": infos, "R": round(R, 3), "problems": probs})
            for p_ in patch:
                s["dead"].add(p_["id"])
            if s["base_t"] is None:
                s["base_t"], s["R_u"] = t, R
            return
        rejected = {iid for iid, _ in probs}                                 # 11-08 审查:部分被拒时,被拒的条目判补偿无效,不算补过
        for iid in rejected:
            s["dead"].add(iid)
        s["last_contract"] = copy.deepcopy(cur)
        self.respec = self._contract_now = new_c
        for iid, tr in self._tracks.items():
            s["n0"][iid] = len(tr.x)
        s["n_upd"] += 1
        for p_ in patch:                                                      # 逐条记补偿生效时刻:验收窗口只截被补过的条目(11-08 审查)
            if p_["id"] not in rejected:
                s.setdefault("upd_item", {})[p_["id"]] = t
        s["upd_t"] = s["base_t"] = t
        s["R_u"], s["plateau_t"], s["worse_t"] = R, None, None
        self.rule_updates.append({"stage": sid, "attempt": self._attempt.get(sid, 0), "t": round(t, 3), "where": "阶段内", "applied": True,
                                  "items": infos, "R": round(R, 3), "problems": probs})

    def _contract_now_or0(self):
        return self._contract_now if self._contract_now is not None else self.contract0

    def _trigger_l2(self, s, why):
        s["pending_l2"] = why
        self.stop_stage = "L2: " + why[0]
        self.monitor_log.append({"stage": s["sid"], "attempt": self._attempt.get(s["sid"], 0), "t": round(self.cl.t, 3), "event": "L2 触发", "why": why})

    def extension(self, sid, t0, t_need) -> float:
        s = self._s.get((sid, t0))
        if s is None or s["upd_t"] is None:
            return 0.0
        need_end = s["upd_t"] + self.settle_s + self.min_win_s
        return float(np.clip(need_end - (t0 + t_need), 0.0, self.ext_max_s))

    # ── 阶段末
    def _gate_rows(self, cl, sid, r_, rec, contract):
        """连续量条目的验收窗口从最后一次阶段内补偿 + settle 开始(窗口够 min_win_s 时);其余同第一版。"""
        s = self._s.get((sid, r_["t0"]))
        task = self.task
        adj = self.item_windows(s, sid, r_["t0"], r_["t1"], contract)       # 11-08 审查:只截被补过的条目;窗口不够长或没补过就清掉旧值
        for i in self._stage_items(sid, contract):
            if i["id"] in adj:
                self.verify_skip_adj[i["id"]] = adj[i["id"]]
            else:
                self.verify_skip_adj.pop(i["id"], None)
        if adj:
            task = {**task, "verify_skip_s": {**task["verify_skip_s"], **adj}}
        items = self._stage_items(sid, contract)
        if not items:
            return []
        ep = {"cl": cl, "log": cl.arrays(), "stages": rec + [r_], "torque_log": np.asarray(self.tq_log).reshape(-1, 2),
              "frames": self.frames, "ctx": self.ctx, "t_prog": self.t_prog}
        return verify_program(ep, items, task)

    def item_windows(self, s, sid, t0, t1, contract) -> dict:
        """被阶段内补偿过的条目:验收窗口从它最后一次补偿生效 + settle 开始(剩下的窗口够 min_win_s 时)。返回 {id: 相对 t0 的跳过秒数}。"""
        out = {}
        if s is None:
            return out
        sk0 = self.task["verify_skip_s"]
        for iid, tu in (s.get("upd_item") or {}).items():
            w = tu + self.settle_s
            if t1 - w >= self.min_win_s - 1e-9:
                out[iid] = max(sk0.get(iid, sk0["*"]), w - t0)
        return out

    def on_stage_end(self, cl, sid, r_, rec, contract):
        s = self._s.get((sid, r_["t0"]))
        act, new_c = super().on_stage_end(cl, sid, r_, rec, contract)
        if s is not None and s["pending_l2"] is not None and self.gates and self.gates[-1]["stage"] == sid and self.gates[-1]["pass"]:
            self.levels.append({"stage": sid, "attempt": self.gates[-1]["attempt"], "level": "L2 取消", "why": ["阶段内判 L2,但阶段末验收已通过"]})
        return act, new_c

    def _hier(self, cl, sid, r_, rows, contract, g, ex):
        lv = self._lv.setdefault(sid, {"l0": 0, "l1": 0, "l2": 0, "prev_rows": None, "prev_patched": set(), "hard_fail": 0, "last": None, "n": 0})
        s = self._s.get((sid, r_["t0"]))
        gs = self._gs.setdefault(sid, {"n": 0, "rule": {}, "dead": set()})
        failing = [r for r in rows if not r["pass"]]
        if lv["n"] >= (getattr(self, "budget_n", None) or self.l0_max + self.gate_rule_max + self.l2_max + 3):   # budget_n:消融时与完整版对齐总尝试数
            return self._stop(sid, g, f"阶段 {sid} 尝试 {lv['n']} 次仍不过", "abort(budget)")
        if ex is not None and ex["alarms"] and lv["l0"] < self.l0_max:
            lv["l0"] += 1
            if not any(i["kind"] == "trigger" and i.get("stage") == sid for i in contract):
                rec = {"stage": sid, "max_s": self.recover_max_s}
                self.recover[sid] = rec
                self.recoveries.append(rec)
            return self._retry(sid, g, lv, rows, "L0", [f"执行一致性报警 {[a['kind'] for a in ex['alarms']]}"], None)
        if s is not None and s["pending_l2"] is not None:
            return self._l2(cl, sid, r_, rows, contract, g, s["pending_l2"])
        by_id = {i["id"]: i for i in contract}
        patch, infos = [], []
        if gs["n"] < self.gate_rule_max:                                     # 阶段间规则补偿(短阶段来不及在阶段内补时的兜底)
            for r in failing:
                item = by_id.get(r["id"])
                if item is None or item["kind"] not in RULE_KINDS or r.get("measured") is None or r["id"] in gs["dead"]:
                    continue
                c_new, info = secant_step(item, aim_error(item["kind"], item, r["measured"]), gs["rule"].setdefault(r["id"], {}),
                                          self.g_lo, self.g_hi, self.step_max_tol, self.comp_max_tol)
                infos.append({"id": r["id"], **info})
                if c_new is None:
                    gs["dead"].add(r["id"])
                else:
                    patch.append({"id": r["id"], "field": "comp", "value": c_new})
        if patch:
            gs["n"] += 1
            new_c, probs = apply_patch(contract, patch, REPAIR_FIELDS)
            if probs and len(probs) >= len(patch):
                self.rule_updates.append({"stage": sid, "attempt": g["attempt"], "t": round(r_["t1"], 3), "where": "阶段间", "applied": False,
                                          "items": infos, "problems": probs})
                return self._l2(cl, sid, r_, rows, contract, g, [f"规则补丁被拒 {probs}"])
            self.rule_updates.append({"stage": sid, "attempt": g["attempt"], "t": round(r_["t1"], 3), "where": "阶段间", "applied": True,
                                      "items": infos, "problems": probs})
            return self._retry(sid, g, lv, rows, "L1-规则(阶段间)", [f"不达标 {[r['id'] for r in failing]}"], new_c)
        rest = [r["id"] for r in failing]
        if self.l1b and lv["l1"] < self.l1_max:                              # 可选:规则管不了的项交给大模型 L1
            lv["l1"] += 1
            self._retries[sid] = lv["l1"]
            new_c, rep = self._repair(sid, rows, contract)
            rep["level"] = "L1b"
            self.repairs.append(rep)
            if rep["error"] and not rep["patch"]:
                return self._stop(sid, g, f"L1b 调用失败:{rep['error'][:200]}", "abort(L1 error)")
            if rep["patch"] and not rep["infeasible"]:
                return self._retry(sid, g, lv, rows, "L1b", [f"规则管不了 {rest}"], new_c)
        why = [f"阶段末仍不达标 {rest}"] + ([f"规则判补偿无效 {sorted(gs['dead'] | (s['dead'] if s else set()))}"] if gs["dead"] or (s and s["dead"]) else [])
        return self._l2(cl, sid, r_, rows, contract, g, why)

    def _l2(self, cl, sid, r_, rows, contract, g, why):
        out = self._escalate_l2(cl, sid, r_, rows, contract, g, why)
        if out[0] == "retry":                                                 # 换了策略:规则的灵敏度估计作废,重新开始
            self._gs[sid] = {"n": 0, "rule": {}, "dead": set()}
        return out

    def report(self) -> dict:
        r = super().report()
        r.update(rule_updates=self.rule_updates, monitor_log=self.monitor_log, verify_skip_adj=self.verify_skip_adj, version="hmr2")
        r["config"].update(rule_window_s=self.rule_window_s, settle_s=self.settle_s, debounce_s=self.debounce_s, plateau_s=self.plateau_s, eps=self.eps,
                           worse_s=self.worse_s, g_lo=self.g_lo, g_hi=self.g_hi, step_max_tol=self.step_max_tol, comp_max_tol=self.comp_max_tol,
                           n_rule_max=self.n_rule_max, gate_rule_max=self.gate_rule_max, min_win_s=self.min_win_s, ext_max_s=self.ext_max_s, l1b=self.l1b)
        return r
