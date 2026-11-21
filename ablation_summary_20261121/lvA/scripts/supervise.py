# -*- coding: utf-8 -*-
"""阶段监督(2026-11-01 新建;只新建文件 + program.run_program 加了 hooks 参数,不改 cost_layers/)。

挂法:program.run_program(task, contract, bias, seed, device, hooks=Supervisor(...))。hooks=None 时和以前逐位相同。
三层,频率从高到低:
  1. 实时检测(规则,每 monitor_cycles 个规划周期一次,默认 1 = 50 Hz)。对当前阶段的契约项,用和验收同一个 compile_spec + CostModel.value
     (验收侧的项:契约值、不带 comp、真值参考系),并用和 verify_program 同一种统计量(target 均值 / lower p5 / upper p95 / range p5–p95 /
     contact 接触比例):
       a) 实测:阶段开始 + verify_skip_s 到现在的实测样本 →「如果现在结束,这一项过不过」;
       b) 预测:把规划器当前计划里还没执行的参考关节轨迹(最多 0.5 s)接在实测样本后面再算一次 →「照现在的计划走下去」;
          力项没有接触模型的预测,只给实测;动态参照项的预测段用当前时刻的参考系(不偷看未来);
       c) 漂移累计:最新实测样本的容差比 z = 偏差 / tol,双边 CUSUM:S± ← max(0, S± + (±z − 1)·dt),超过 drift_h(秒·容差)报警。
          逐周期看一个点会把短暂越界和持续偏离混在一起,累计量才能把「慢慢漂出去」和「抖一下」分开。
     contact 看接触比例,contact_at 看处于接触时的平均位置(50 Hz 取样格;验收用全部样本,差在毫米以下)。
     依赖相邻样本的量(lin_acc 是速度差分)每批都接上前一个样本做上下文,和验收对整段一次求值逐位一致。
     只记事件,不改执行。事件型的项(duration / trigger / period / arrival / config / torque / stiffness / sequence)只在阶段门控时判。
  2. 阶段门控(规则)。阶段按自己的退出条件结束后,用 verify_program 只验 stage 等于这一阶段的契约项:
       过 → 进下一阶段;不过 → on_fail:
         abort    停下,后续阶段不执行;
         retry    原样重跑这一阶段,最多 max_retries 次,还不过就停;
         repair   先让大模型只改这一阶段未达标项的执行侧补偿 comp(契约锁定,同 llm_io.REPAIR_SYSTEM),再重跑,最多 max_retries 次,还不过就停;
         continue 只记录,照旧往下走(= 以前的行为 + 记录)。
  3. 意图审计(模型,可选,audit_model 不为 None 时开)。阶段门控通过后,把原始一句话指令、这一阶段的说明、规则验收表、阶段末的观测
     (两张渲染图 + 实测状态摘要)交给 VLM。只能否决不能放行:规则判不过的阶段不送审。VLM 判不符合时记 veto,on_veto = record 只记录 /
     abort 停下。它看的是原始指令 + 观测而不是规格:规格本身写错或漏项时规则验收照样全过,只有这一层能指出来;
     指出之后正确的处理是重装源规格,这里只把它的建议记下来,不自动改契约。

2026-11-06 分层修正(HMR,规则判定;全部新功能默认关,关着时和 11-04 版逐位相同):
  比较器 A(执行一致性,exec_monitor=True):每个规划周期读 1 kHz 日志里规划器下发的参考与实测 ——
     TCP 跟踪误差(去掉力轴分量:那根轴上参考本来就压在表面里)超过 exec_pos_m 持续 exec_hold_s;
     有力轴且目标力为常数时,力轴实测力与目标力之差超过 exec_force_n 持续 exec_hold_s;接触保护触发。
     报警说明「机器人没做到规划器要它做的」(扰动 / 本体 / 接触冲击),这一阶段的不达标先按 L0 处理,不叫大模型。
  比较器 B 的停滞判据:未达标且最近 stall_win_s 内瞬时容差比 z 的改善不足 stall_frac(和方法章程序形态回报同一口径)。
  提前结束(early_stop_s,默认关):某项实测与预测都判不过、且停滞,持续 early_stop_s → 结束这一阶段交给门控。
  on_fail = "hier":
     L0  这一阶段比较器 A 报过警,且 L0 次数 < l0_max → 原样重跑,不调用大模型;
     L1  局部修正(同 repair:只改未达标项的 comp,契约锁定),最多 l1_max 轮;
     L2  策略重规划(大模型看全部上下文 + 渲染图,重写这一阶段的策略项与全部 comp,契约锁定),每阶段 l2_max 次。升级条件(任一):
         L1 轮数用尽;L1 声明不可达或给不出可用补丁;L1 后被补的项归一化偏差改善 < no_progress;
         L1 后原来达标的项变成不达标(改好一项坏一项);hard 契约项连续两次不达标;(可选)L1 自己报 escalate。
     预算用尽 → 中止并记录原因。
  on_veto = "replan":意图审计否决 → L2(此时开放 source_patch:按原话修正契约值),重跑这一阶段并再审一次。
"""
from __future__ import annotations

import base64
import copy
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from cost_layers.cost import CostModel
from cost_layers.spec import compile_spec
from exp_sweep.core import EDIT_FIELDS, REPAIR_FIELDS, _verify_term, apply_patch, contract_view, eval_target, planner_term
from exp_sweep.program import CONTACT_N, normal_force, verify_program

LIVE_KINDS = ("target", "lower", "upper", "range")                  # 实时检测用 CostModel 求值的项;contact 另算接触比例
N_DOWN = np.array([0.0, 0.0, -1.0])


def _stat(kind: str, item: dict, x: np.ndarray):
    """和 verify_program 同一种统计量。x (S, nd)。返回 (统计量, 偏差, 是否达标)。"""
    if kind == "target":
        tgt = eval_target(item)
        stat = x.mean(0); dev = stat - tgt
        return stat, dev, bool(np.all(np.abs(dev) <= item["tol"]))
    if kind == "upper":
        stat = np.percentile(x, 95, axis=0); dev = stat - np.atleast_1d(item["ub"])
        return stat, dev, bool(np.all(dev <= item["tol"]))
    if kind == "lower":
        stat = np.percentile(x, 5, axis=0); dev = stat - np.atleast_1d(item["lb"])
        return stat, dev, bool(np.all(dev >= -item["tol"]))
    lo, hi = np.percentile(x, 5, axis=0), np.percentile(x, 95, axis=0)
    stat = np.stack([lo, hi], -1); dev = np.stack([lo - np.atleast_1d(item["lb"]), hi - np.atleast_1d(item["ub"])], -1)
    return stat, dev, bool(np.all(lo >= np.atleast_1d(item["lb"]) - item["tol"]) and np.all(hi <= np.atleast_1d(item["ub"]) + item["tol"]))


def _bounds(kind: str, item: dict):
    """瞬时容差比用的上 / 下参照(None = 这一侧不管)。target 两侧都以目标为参照。"""
    if kind == "target":
        t = eval_target(item); return t, t
    hi = np.atleast_1d(np.asarray(item["ub"], float)) if kind in ("upper", "range") else None
    lo = np.atleast_1d(np.asarray(item["lb"], float)) if kind in ("lower", "range") else None
    return hi, lo


def _f(v, n=4):
    if v is None:
        return None
    a = np.round(np.asarray(v, float), n)
    return a.tolist() if a.ndim else float(a)


class _Track:
    """一个契约项在当前阶段里的实时状态。"""

    def __init__(self, sup, item: dict, t0: float):
        self.item, self.kind, self.id = item, item["kind"], item["id"]
        self.t_from = t0 + sup.task["verify_skip_s"].get(item["id"], sup.task["verify_skip_s"]["*"])
        self.i_next = None                                               # 下一个要取的日志下标(和 verify_program 同一个 50 Hz 取样格)
        self.x = []                                                      # 已求值的实测样本 (nd,)
        self.prev = None                                                 # 上一批最后一个样本 (q, dq, F, t):lin_acc 这类相邻样本差分的量要它做上下文
        self.n_in = 0                                                    # contact:处于接触的样本数
        self.s_up = self.s_lo = 0.0
        self.state = {"meas_ok": None, "pred_ok": None, "drift": None, "stall": None}
        self.zhist = []                                                  # (t, 最新样本的瞬时容差比 z):停滞判据用
        self.first = {}                                                  # 各种报警第一次出现的时刻
        self.bad_since = None                                            # 实测或预测任一判不过、一直持续到现在的起点
        self.force = item.get("level") == "tcp_force"
        self.dyn = item.get("frame") in sup.task.get("dynamic", {})
        self.model = self.term = None
        if self.kind in LIVE_KINDS:
            comp = compile_spec({"terms": [_verify_term(item)]}, sup.all_frames, sup.cl.lim)
            if comp.ok and comp.terms:
                self.model = CostModel(comp, sup.all_frames, sup.cl.lim, sup.cl.dev, dtype=sup.cl.kin.dtype)
                self.term = comp.terms[0]
            else:
                self.error = comp.reject_reason or str(comp.rejected_terms)


class Supervisor:
    def __init__(self, contract: list, *, monitor_cycles: int = 1, drift_h: float = 0.25, on_fail: str = "continue", max_retries: int = 1,
                 repair_llm=None, audit_model: str | None = None, instruction: str | None = None, stage_notes: dict | None = None,
                 on_veto: str = "record", image_dir: Path | None = None, keep_timeline: bool = True, audit_votes: int = 1,
                 exec_monitor: bool = False, exec_pos_m: float = 0.015, exec_force_n: float = 3.0, exec_hold_s: float = 0.15,
                 stall_win_s: float = 0.5, stall_frac: float = 0.05, early_stop_s: float | None = None,
                 l0_max: int = 1, l1_max: int = 3, l2_max: int = 1, no_progress: float = 0.2, replan_model: str | None = None,
                 l1_escalate_flag: bool = False, pre_cycle=None):
        assert on_fail in ("abort", "retry", "repair", "continue", "hier") and on_veto in ("record", "abort", "replan")
        assert on_fail not in ("repair", "hier") or repair_llm is not None, "on_fail=repair / hier 需要 repair_llm"
        assert not (on_fail == "hier" or on_veto == "replan") or replan_model, "L2 重规划需要 replan_model"
        assert audit_model is None or instruction, "意图审计需要原始一句话指令"
        assert on_veto != "replan" or audit_model, "on_veto=replan 需要开意图审计"
        self.exec_monitor, self.exec_pos_m, self.exec_force_n, self.exec_hold_s = exec_monitor, float(exec_pos_m), float(exec_force_n), float(exec_hold_s)
        self.stall_win_s, self.stall_frac, self.early_stop_s = float(stall_win_s), float(stall_frac), early_stop_s
        self.l0_max, self.l1_max, self.l2_max, self.no_progress = int(l0_max), int(l1_max), int(l2_max), float(no_progress)
        self.replan_model, self.l1_escalate_flag, self.pre_cycle = replan_model, l1_escalate_flag, pre_cycle
        self.helpers_override, self.stop_stage, self.recover = {}, None, {}   # program.run_stage 读这三个
        self.recover_max_s, self.recoveries = 1.5, []
        self.exec_events, self.levels, self.replans, self.early_stops = [], [], [], []
        self._lv, self._ex = {}, {}                                      # 每阶段的分层计数 / 当前尝试的比较器 A 状态
        self._exec_i, self._exec_alarm, self._attempt = 0, {}, {}
        self.monitor_cycles, self.drift_h, self.on_fail, self.max_retries = int(monitor_cycles), float(drift_h), on_fail, int(max_retries)
        self.repair_llm, self.audit_model, self.instruction, self.on_veto = repair_llm, audit_model, instruction, on_veto
        self.stage_notes, self.image_dir, self.keep_timeline = stage_notes or {}, image_dir, keep_timeline
        self.audit_votes = int(audit_votes)
        self.contract0 = copy.deepcopy(contract)
        self.aborted, self.abort_reason = False, None
        self.events, self.timeline, self.gates, self.audits, self.repairs = [], [], [], [], []
        self.monitor_ms = []
        self._tracks, self._sid, self._retries, self._history = {}, None, {}, {}
        self._renderer = None

    # ───────────────────────────── program.run_program 调用的三个入口
    def start(self, *, cl, task, frames, ctx, t_prog, tq_log, w0):
        self.cl, self.task, self.frames, self.ctx, self.t_prog, self.tq_log, self.w0 = cl, task, frames, ctx, t_prog, tq_log, w0
        self.all_frames = {"base": (np.eye(3), np.zeros(3)), "tool": (ctx["R0"], ctx["p0"]), **frames}
        self.every = max(1, int(round(0.02 / cl.log_dt)))

    def on_cycles(self, cl, sid: str, t0: float) -> None:
        """实时检测:每 monitor_cycles 个规划周期调用一次。"""
        t_a = time.perf_counter()
        key = (sid, t0)
        if self._sid != key:                                             # 新阶段(或同一阶段的重跑):按当前契约重建
            self._sid = key
            self._tracks = {i["id"]: _Track(self, i, t0) for i in self._stage_items(sid, self._contract_now)
                            if i["kind"] in LIVE_KINDS + ("contact", "contact_at")}
        L = cl.log
        n = len(L["t"])
        pred = self._predicted(cl)
        for tr in self._tracks.values():
            if tr.kind in LIVE_KINDS and tr.model is None:
                continue
            new = self._new_indices(tr, L, n)
            if new:
                if tr.kind == "contact":
                    tr.n_in += int(sum(-L["F"][i][2] > CONTACT_N for i in new)); tr.x.extend([None] * len(new))
                elif tr.kind == "contact_at":                            # 接触位置:处于接触的样本在参照系 xy 里的平均位置(验收用 1 kHz 全部样本,这里用 50 Hz 取样格)
                    R, pf = self.all_frames[tr.item["frame"]]
                    tr.x.extend([((np.asarray(L["p"][i]) - pf) @ R)[:2] for i in new if -L["F"][i][2] > CONTACT_N])
                else:
                    q = np.asarray([L["q"][i] for i in new]); dq = np.asarray([L["dq"][i] for i in new])
                    F = np.asarray([L["F"][i] for i in new]) if tr.force else None
                    ts = [L["t"][i] for i in new]
                    if tr.prev is not None:                              # 接上前一个样本,算完丢掉它的输出 —— 和验收对整段一次求值逐位一致
                        q0, dq0, F0, t_0 = tr.prev
                        x_ = self._values(tr, np.concatenate([q0[None], q]), np.concatenate([dq0[None], dq]),
                                          None if F is None else np.concatenate([F0[None], F]), [t_0] + ts)[1:]
                    else:
                        x_ = self._values(tr, q, dq, F, ts)
                    tr.prev = (q[-1], dq[-1], None if F is None else F[-1], ts[-1])
                    tr.x.extend(list(x_))
            if not tr.x:
                continue
            self._judge(tr, cl.t, pred, n_new=len(new))
        self.monitor_ms.append((time.perf_counter() - t_a) * 1e3)
        if self.exec_monitor:
            self._exec_check(cl, sid, t0)
        if self.pre_cycle is not None:                                   # 测试用的外部扰动(supervise_run --disturb):作用在下一个规划周期
            self.pre_cycle(cl, sid, cl.t - t0, self._attempt.get(sid, 0))

    # ───────────────────────────── 比较器 A:执行一致性(规划器下发的参考 vs 实测)
    def _exec_check(self, cl, sid: str, t0: float) -> None:
        key = (sid, t0)
        L = cl.log
        n = len(L["t"])
        ex = self._ex.get(key)
        if ex is None:                                                   # 新的一次尝试:从这里开始读日志
            ex = self._ex[key] = {"over": {"track": None, "force": None}, "peak": {"track": 0.0, "force": 0.0}, "alarms": [],
                                  "armed": {"track": None, "force": None}, "n_guard": len(cl.guard_trips), "n_cyc": len(cl.cycles), "resets": 0}
            self._exec_i = max(self._exec_i, n - 20)
        i0, self._exec_i = self._exec_i, n
        if n <= i0:
            return
        P, Pr, T = np.asarray(L["p"][i0:n]), np.asarray(L["p_ref"][i0:n]), L["t"][i0:n]
        e = Pr - P
        fa = cl.force_cfg
        sig = {"track": np.linalg.norm(e, axis=1)}
        if fa is not None:
            nn = np.asarray(fa["n"], float); nn = nn / max(np.linalg.norm(nn), 1e-9)
            sig["track"] = np.linalg.norm(e - (e @ nn)[:, None] * nn, axis=1)    # 力轴方向上参考本来就压在表面里,不算跟踪误差
            fd = fa.get("F_des")
            if fd is not None and fa.get("sched") is None and np.ndim(fd) == 0:
                Fn = np.asarray(L["F"][i0:n]) @ nn
                sig["force"] = np.abs(Fn - float(fd))
        thr = {"track": self.exec_pos_m, "force": self.exec_force_n}
        for k, v in sig.items():
            ex["peak"][k] = max(ex["peak"][k], float(v.max()))
            for t_, x in zip(T, v):
                arm = ex["armed"][k]                                     # 先跟上过(误差 < 阈值一半持续 0.2 s)才开始判:接触建立前、斜坡起步时的误差不算执行异常
                if arm is not True:
                    ex["armed"][k] = (arm if arm is not None else t_) if x < 0.5 * thr[k] else None
                    if ex["armed"][k] is not None and t_ - ex["armed"][k] >= 0.2:
                        ex["armed"][k] = True
                    continue
                if x > thr[k]:
                    if ex["over"][k] is None:
                        ex["over"][k] = [t_, float(x), False]
                    o = ex["over"][k]
                    o[1] = max(o[1], float(x))
                    if not o[2] and t_ - o[0] >= self.exec_hold_s:      # 持续够久:报一次,直到回到阈值以下
                        o[2] = True
                        self._exec_alarm_add(ex, sid, {"t": round(t_, 3), "kind": k, "peak": round(o[1], 4), "thr": thr[k]})
                else:
                    ex["over"][k] = None
        if len(cl.guard_trips) > ex["n_guard"]:                          # 接触保护触发:执行层自己已经停下,这里记成执行异常
            for g in cl.guard_trips[ex["n_guard"]:]:
                self._exec_alarm_add(ex, sid, {"t": round(g["t"], 3), "kind": "guard", "peak": round(g["force"], 2), "thr": g["limit"]})
            ex["n_guard"] = len(cl.guard_trips)
        # 规划器的漂移重置(参考与实测差 > 2 cm 就把参考拉回实测)会把跟踪误差截断在 2 cm 以内,单看误差持续时间漏报侧推(11-06 实测);
        # 所以另数「漂移重置」:去掉接触建立 / 脱离那一拍的重置(力轴切换时执行层本来就会重置),0.5 s 内 ≥ 2 次报一次警
        n0 = max(0, n - 3000)
        t_tail, c_tail = np.asarray(L["t"][n0:n]), L["contact"][n0:n]
        for c in cl.cycles[ex["n_cyc"]:]:
            if not c.get("reset"):
                continue
            ex["resets"] += 1
            j = int(np.searchsorted(t_tail, c["t"] - 1e-9))
            flipped = 0 < j < len(c_tail) and c_tail[j - 1] != c_tail[max(0, j - 21)]
            after_guard = any(0 <= c["t"] - gt["t"] <= 0.04 for gt in cl.guard_trips[-3:])
            if flipped or after_guard:
                continue
            dr = ex.setdefault("drift_resets", [])
            dr.append(c["t"])
            recent = [t_ for t_ in dr if c["t"] - t_ <= 0.5 + 1e-9]
            if len(recent) >= 2 and not ex.get("drift_alarmed_until", -1) >= c["t"]:
                ex["drift_alarmed_until"] = c["t"] + 0.5
                self._exec_alarm_add(ex, sid, {"t": round(c["t"], 3), "kind": "drift_reset", "peak": len(recent), "thr": 2})
        ex["n_cyc"] = len(cl.cycles)

    def recovered(self, cl) -> bool:
        """L0 恢复段的结束条件:最近 0.2 s 跟踪误差(去掉力轴)< 阈值一半,有常数目标力时力误差也 < 阈值一半。"""
        L = cl.log
        n = len(L["t"])
        if n < 200:
            return False
        e = np.asarray(L["p_ref"][n - 200:n]) - np.asarray(L["p"][n - 200:n])
        fa = cl.force_cfg
        if fa is not None:
            nn = np.asarray(fa["n"], float); nn = nn / max(np.linalg.norm(nn), 1e-9)
            e = e - (e @ nn)[:, None] * nn
            fd = fa.get("F_des")
            if fd is not None and fa.get("sched") is None and np.ndim(fd) == 0:
                if np.max(np.abs(np.asarray(L["F"][n - 200:n]) @ nn - float(fd))) >= 0.5 * self.exec_force_n:
                    return False
        return bool(np.max(np.linalg.norm(e, axis=1)) < 0.5 * self.exec_pos_m)

    def _exec_alarm_add(self, ex, sid, ev):
        ex["alarms"].append(ev)
        self.exec_events.append({"stage": sid, "attempt": self._attempt.get(sid, 0), **ev})

    def on_stage_end(self, cl, sid: str, r_: dict, rec: list, contract: list):
        """阶段门控 + 意图审计。返回 (动作, 新契约或 None);动作 = next / retry(abort 时设 self.aborted 并返回 next)。"""
        self._contract_now = contract
        live = self._sid == (sid, r_["t0"])                              # 这一阶段跑过实时检测(monitor_cycles > 0)
        rows = self._gate_rows(cl, sid, r_, rec, contract)
        ok = all(r["pass"] for r in rows)
        n_try = self._retries.get(sid, 0)
        hier = self.on_fail == "hier" or self.on_veto == "replan"
        g = {"stage": sid, "attempt": self._attempt.get(sid, 0) if hier else n_try, "t0": r_["t0"], "t1": r_["t1"], "exit": r_["exit"], "pass": ok, "rows": rows,
             "monitor": self._stage_monitor_summary(sid, r_, rows) if live else None}
        key = (sid, r_["t0"])
        ex = self._ex.get(key)
        g["exec"] = None if ex is None else {"alarms": ex["alarms"], "peak": {k: round(v, 4) for k, v in ex["peak"].items()}, "resets": ex["resets"]}
        self.gates.append(g)
        self._sid = None
        if ok:
            g["action"] = "next"
            if self.audit_model:
                a = self._audit(cl, sid, r_, rows)
                self.audits.append(a)
                if a.get("veto") and self.on_veto == "abort":
                    self._abort(f"意图审计否决阶段 {sid}: {a.get('reason')}")
                    g["action"] = "abort(veto)"
                elif a.get("veto") and self.on_veto == "replan":
                    return self._escalate_l2(cl, sid, r_, rows, contract, g, trigger=["意图审计否决"], veto=a)
            return "next", None
        if self.on_fail == "hier":
            return self._hier(cl, sid, r_, rows, contract, g, ex)
        if self.on_fail == "continue":
            g["action"] = "continue"
            return "next", None
        if self.on_fail == "abort" or n_try >= self.max_retries:
            self._abort(f"阶段 {sid} 验收不过" + ("" if self.on_fail == "abort" else f",已重跑 {n_try} 次"))
            g["action"] = "abort"
            return "next", None
        self._retries[sid] = n_try + 1
        if self.on_fail == "retry":
            g["action"] = "retry"
            return "retry", None
        new_c, rep = self._repair(sid, rows, contract)
        self.repairs.append(rep)
        if not rep["patch"] or rep["problems"] and len(rep["problems"]) >= len(rep["patch"]):   # 没有可用补丁:原样重跑没有意义
            self._abort(f"阶段 {sid} 验收不过,修复没有给出可用补丁({rep['error'] or '补丁为空或全部被拒'})")
            g["action"] = "abort(no_patch)"
            return "next", None
        self._contract_now = new_c
        g["action"] = "repair+retry"
        return "retry", new_c

    # ───────────────────────────── 实时检测细节
    _contract_now = None

    def _stage_items(self, sid, contract):
        return [i for i in (contract or self.contract0) if i.get("stage") == sid and i.get("enabled", True) and i["kind"] != "sequence"]

    def _new_indices(self, tr, L, n):
        if tr.i_next is None:
            t = L["t"]
            j = next((k for k in range(max(0, n - 4000), n) if t[k] >= tr.t_from), None) if n and t[-1] >= tr.t_from else None
            if j is None:
                return []
            tr.i_next = j
        out = list(range(tr.i_next, n, self.every))
        if out:
            tr.i_next = out[-1] + self.every
        return out

    def _values(self, tr, q, dq, F, times, frame_now=None) -> np.ndarray:
        cl = self.cl
        roll = cl.measured_roll(q, dq, F=F, n=N_DOWN if F is not None else None)
        m, term = tr.model, tr.term
        if not tr.dyn:
            return m.value(term, roll)[0].detach().cpu().numpy()
        name = tr.item["frame"]
        if frame_now is not None:                                        # 预测段:整段用同一个参考系,一次求值
            m.frames[name] = (m.T(frame_now[0]), m.T(frame_now[1]))
            return m.value(term, roll)[0].detach().cpu().numpy()
        xs = []
        for j, ti in enumerate(times):
            R, p = frame_now if frame_now is not None else self.task["dynamic"][name](ti - self.t_prog, self.frames[name])
            m.frames[name] = (m.T(R), m.T(p))
            sub = {kk: (v[:, j:j + 2] if kk in ("q", "p", "R", "O", "J") else v[:, j:j + 1] if kk in ("dq", "ddq", "twist") else v) for kk, v in roll.items()}
            xs.append(m.value(term, sub)[0, 0].detach().cpu().numpy())
        return np.stack(xs)

    def _predicted(self, cl):
        """规划器当前计划里还没执行的那一段:(时刻, q, dq)。"""
        plan = getattr(cl.exe, "plan", None)
        if plan is None:
            return None
        stamp, Q, DQ = plan[0], np.asarray(plan[1]), np.asarray(plan[2])
        ts = stamp + 0.02 * np.arange(len(Q))
        k = ts > cl.t + 1e-9
        return (ts[k], Q[k], DQ[k]) if k.any() else None

    def _judge(self, tr, t_now, pred, n_new):
        item, kind = tr.item, tr.kind
        rec = {"t": round(t_now, 3), "id": tr.id}
        if kind == "contact_at":
            xy = np.asarray(tr.x).mean(0); dev = xy - np.asarray(item["target"], float)
            ok = bool(np.all(np.abs(dev) <= item["tol"]))
            rec.update(meas=_f(xy), meas_ok=ok)
            self._transition(tr, "meas_ok", ok, t_now, extra={"measured": _f(xy), "deviation": _f(dev)})
        elif kind == "contact":
            frac = tr.n_in / len(tr.x)
            ok = frac >= item["target"] - item["tol"]
            rec.update(meas=_f(frac), meas_ok=ok)
            self._transition(tr, "meas_ok", ok, t_now, extra={"measured": _f(frac)})
        else:
            x = np.asarray(tr.x)
            stat, dev, ok = _stat(kind, item, x)
            rec.update(meas=_f(stat), meas_ok=ok)
            self._transition(tr, "meas_ok", ok, t_now, extra={"measured": _f(stat), "deviation": _f(dev)})
            if pred is not None and not tr.force:
                ts, Q, DQ = pred
                keep = ts >= tr.t_from
                if keep.any():
                    fr_now = None
                    if tr.dyn:
                        fr_now = self.task["dynamic"][item["frame"]](t_now - self.t_prog, self.frames[item["frame"]])
                    q_, dq_, t_ = Q[keep], DQ[keep], list(ts[keep])
                    if tr.prev is not None:
                        xp = self._values(tr, np.concatenate([tr.prev[0][None], q_]), np.concatenate([tr.prev[1][None], dq_]), None,
                                          [tr.prev[3]] + t_, frame_now=fr_now)[1:]
                    else:
                        xp = self._values(tr, q_, dq_, None, t_, frame_now=fr_now)
                    sp, dp, okp = _stat(kind, item, np.concatenate([x, xp], 0))
                    rec.update(pred=_f(sp), pred_ok=okp)
                    self._transition(tr, "pred_ok", okp, t_now, extra={"predicted": _f(sp), "deviation": _f(dp)})
            if n_new:                                                    # 漂移累计:最新一个实测样本
                hi, lo = _bounds(kind, item)
                xl, dt = x[-1], 0.02 * n_new
                z_up = float(np.max((xl - hi) / item["tol"])) if hi is not None else -np.inf
                z_lo = float(np.max((lo - xl) / item["tol"])) if lo is not None else -np.inf
                if hi is not None:
                    tr.s_up = max(0.0, tr.s_up + (z_up - 1.0) * dt)
                if lo is not None:
                    tr.s_lo = max(0.0, tr.s_lo + (z_lo - 1.0) * dt)
                drift = "up" if tr.s_up > self.drift_h else "down" if tr.s_lo > self.drift_h else None
                rec.update(z=_f(max(z_up, z_lo), 3), s_up=_f(tr.s_up, 3), s_lo=_f(tr.s_lo, 3), drift=drift)
                self._transition(tr, "drift", drift, t_now, extra={"s_up": _f(tr.s_up, 3), "s_lo": _f(tr.s_lo, 3)})
                zc = max(z_up, z_lo)                                     # 停滞:未达标,且最近 stall_win_s 内瞬时 z 改善不足 stall_frac
                tr.zhist.append((t_now, zc))
                while tr.zhist and tr.zhist[0][0] < t_now - self.stall_win_s - 0.1:
                    tr.zhist.pop(0)
                old = next((z for t_, z in tr.zhist if t_ >= t_now - self.stall_win_s - 1e-9), None)
                span = t_now - tr.zhist[0][0]
                stall = None
                if span >= self.stall_win_s - 0.03 and old is not None:
                    stall = bool(tr.state["meas_ok"] is False and zc > 1.0 and (old - zc) < self.stall_frac * max(old, 1e-9))
                rec["stall"] = stall
                self._transition(tr, "stall", stall, t_now, extra={"z": _f(zc, 3), "z_before": _f(old, 3)})
        bad = tr.state["meas_ok"] is False or tr.state["pred_ok"] is False
        tr.bad_since = (tr.bad_since if tr.bad_since is not None else t_now) if bad else None
        if (self.early_stop_s is not None and self.stop_stage is None and tr.state["meas_ok"] is False and tr.state["pred_ok"] is False
                and tr.state["stall"] and tr.bad_since is not None and t_now - tr.bad_since >= self.early_stop_s):
            self.stop_stage = f"{tr.id} 实测与预测都不过且停滞 {t_now - tr.bad_since:.2f} s"
            self.early_stops.append({"t": round(t_now, 3), "stage": self._sid[0], "id": tr.id, "reason": self.stop_stage})
        if self.keep_timeline:
            self.timeline.append({"stage": self._sid[0], **rec})

    def _transition(self, tr, key, val, t, extra=None):
        old = tr.state[key]
        if val == old:
            return
        tr.state[key] = val
        bad = (val is not None) if key == "drift" else (val is True) if key == "stall" else (val is False)
        if bad:
            tr.first.setdefault(key, t)
        if old is None and not bad:                                      # 第一次判出来就是「过 / 没有漂移」:不算事件
            return
        self.events.append({"t": round(t, 3), "stage": self._sid[0], "id": tr.id, "kind": key, "value": val, **(extra or {})})

    def _stage_monitor_summary(self, sid, r_, rows):
        """这一阶段实时检测的总结:每项最终判定、报警第一次出现的时刻,以及比阶段结束早多少秒开始持续报「不过」(实测或预测任一)。"""
        out = {}
        final = {r["id"]: r["pass"] for r in rows}
        for iid, tr in self._tracks.items():
            lead = None
            if tr.bad_since is not None:
                lead = round(r_["t1"] - tr.bad_since, 3)
            out[iid] = {"final_pass": final.get(iid), "samples": len(tr.x), "first_alarm": {k: round(v, 3) for k, v in tr.first.items()},
                        "fail_lead_s": lead, "error": getattr(tr, "error", None)}
        if self.monitor_ms:
            out["_cost_ms"] = {"mean": round(float(np.mean(self.monitor_ms)), 2), "p95": round(float(np.percentile(self.monitor_ms, 95)), 2),
                               "calls": len(self.monitor_ms)}
            self.monitor_ms = []
        return out

    # ───────────────────────────── 阶段门控
    def _gate_rows(self, cl, sid, r_, rec, contract):
        items = self._stage_items(sid, contract)
        if not items:
            return []
        ep = {"cl": cl, "log": cl.arrays(), "stages": rec + [r_], "torque_log": np.asarray(self.tq_log).reshape(-1, 2),
              "frames": self.frames, "ctx": self.ctx, "t_prog": self.t_prog}
        return verify_program(ep, items, self.task)

    def _abort(self, why):
        self.aborted, self.abort_reason = True, why

    def _repair(self, sid, rows, contract):
        """L1:只让大模型改这一阶段未达标项的 comp(契约锁定)。补丁里别的编号一律丢掉。"""
        from exp_sweep.llm_io import REPAIR_SYSTEM, REPAIR_SYSTEM_L1, ask_json, repair_user
        if self.l1_escalate_flag:
            REPAIR_SYSTEM = REPAIR_SYSTEM_L1                             # noqa: N806  (11-06 可选:允许 L1 自己报 escalate)
        items = self._stage_items(sid, contract)
        ids = {i["id"] for i in items}
        view = contract_view(items, with_comp=True)
        for r in rows:
            if not r["pass"]:
                self._history.setdefault(r["id"], []).append({"attempt": self._retries[sid] - 1, "comp": next(v["comp"] for v in view if v["id"] == r["id"]),
                                                              "measured": r.get("measured"), "deviation": r.get("deviation")})
        try:
            q = ask_json(self.repair_llm, REPAIR_SYSTEM, repair_user(view, rows, self._history))
        except Exception as e:                                           # noqa: BLE001  11-06:额度用完会抛 QuotaExhausted,别让整个进程崩掉
            q = {"json": None, "error": f"{type(e).__name__}: {str(e)[:300]}", "latency_s": None}
        js = q["json"] if isinstance(q["json"], dict) else {}
        failing = {r["id"] for r in rows if not r["pass"]}
        patch = [p for p in (js.get("patch") or []) if isinstance(p, dict) and p.get("id") in ids & failing]
        dropped = [p for p in (js.get("patch") or []) if p not in patch]
        new, problems = apply_patch(contract, patch, REPAIR_FIELDS)
        rep = {"stage": sid, "attempt": self._retries[sid], "patch": patch, "dropped": dropped, "problems": problems,
               "infeasible": js.get("infeasible") or [], "latency_s": q["latency_s"], "error": q["error"]}
        if rep["infeasible"]:
            rep["note"] = "大模型声明不可达;仍按补丁重跑一次,结果以复验为准"
        if self.l1_escalate_flag and js.get("escalate") is True:
            rep["escalate"], rep["escalate_reason"] = True, js.get("escalate_reason")
        return new, rep

    # ───────────────────────────── 分层修正(on_fail = "hier")
    @staticmethod
    def _viol(r: dict | None):
        """一行验收结果的归一化违背量(偏差 / 容差,达标侧记 0);没有数值偏差的行返回 None。"""
        if r is None or r.get("deviation") is None or not r.get("tol"):
            return None
        try:
            d = np.asarray(r["deviation"], float)
        except (TypeError, ValueError):
            return None
        k, tol = r["kind"], float(r["tol"])
        if k == "lower":
            v = np.maximum(0.0, -d)
        elif k == "upper":
            v = np.maximum(0.0, d)
        elif k == "range":
            v = np.maximum(0.0, np.maximum(-d[..., 0], d[..., 1]))
        else:
            v = np.abs(d)
        return float(np.max(v) / tol)

    def _hier(self, cl, sid, r_, rows, contract, g, ex):
        lv = self._lv.setdefault(sid, {"l0": 0, "l1": 0, "l2": 0, "prev_rows": None, "prev_patched": set(), "hard_fail": 0, "last": None, "n": 0})
        failing = [r for r in rows if not r["pass"]]
        if lv["n"] >= self.l0_max + 2 * self.l1_max + self.l2_max + 1:  # 总尝试数上限(防止 L0 / L1 / L2 来回)
            return self._stop(sid, g, f"阶段 {sid} 尝试 {lv['n']} 次仍不过", "abort(budget)")
        if ex is not None and ex["alarms"] and lv["l0"] < self.l0_max:  # L0:比较器 A 报过警 —— 先当执行层问题,恢复后原样重跑,不叫大模型
            lv["l0"] += 1
            if not any(i["kind"] == "trigger" and i.get("stage") == sid for i in contract):   # 事件切换的阶段(如碰到就停)不做恢复段,免得越过事件
                rec = {"stage": sid, "max_s": self.recover_max_s}
                self.recover[sid] = rec                                  # program.run_stage 先执行到跟踪恢复再开始计时
                self.recoveries.append(rec)
            return self._retry(sid, g, lv, rows, "L0", [f"执行一致性报警 {[a['kind'] for a in ex['alarms']]}"], None)
        trig = []
        if lv["l1"] >= self.l1_max:
            trig.append(f"L1 已用 {lv['l1']} 轮仍不过")
        if lv["last"] == "L1" and lv["prev_rows"] is not None:
            prev = {r["id"]: r for r in lv["prev_rows"]}
            imp = []
            for r in failing:
                if r["id"] in lv["prev_patched"]:
                    a, b = self._viol(prev.get(r["id"])), self._viol(r)
                    if a is not None and b is not None and a > 0:
                        imp.append((r["id"], round((a - b) / a, 3)))
            if imp and all(x < self.no_progress for _, x in imp):
                trig.append(f"补偿无效:被补的项归一化偏差改善 {imp} 都 < {self.no_progress}")
            broke = [r["id"] for r in failing if prev.get(r["id"], {}).get("pass") and r["id"] not in lv["prev_patched"]]
            if broke:
                trig.append(f"改好一项坏一项:{broke} 上一轮达标、这一轮不达标")
        hard = {i["id"] for i in contract if i.get("penalty") == "hard"}
        hf = [r["id"] for r in failing if r["id"] in hard]
        lv["hard_fail"] = lv["hard_fail"] + 1 if hf else 0
        if lv["hard_fail"] >= 2:
            trig.append(f"硬约束项 {hf} 连续两次不达标")
        if trig:
            return self._escalate_l2(cl, sid, r_, rows, contract, g, trig)
        lv["l1"] += 1                                                    # L1:局部修正
        self._retries[sid] = lv["l1"]
        new_c, rep = self._repair(sid, rows, contract)
        rep["level"] = "L1"
        self.repairs.append(rep)
        if rep["error"] and not rep["patch"]:                            # 调用失败(超时 / 额度)不是策略问题,不升级 L2
            return self._stop(sid, g, f"L1 调用失败:{rep['error'][:200]}", "abort(L1 error)")
        usable = bool(rep["patch"]) and not (rep["problems"] and len(rep["problems"]) >= len(rep["patch"]))
        t2 = ([f"L1 声明不可达 {[x.get('id') for x in rep['infeasible'] if isinstance(x, dict)]}"] if rep["infeasible"] else []) + \
             ([f"L1 给不出可用补丁({rep['error'] or '补丁为空或全部被拒'})"] if not usable else []) + \
             ([f"L1 自报需升级:{rep.get('escalate_reason')}"] if rep.get("escalate") else [])
        if t2:
            return self._escalate_l2(cl, sid, r_, rows, contract, g, t2)
        lv["prev_patched"] = {p["id"] for p in rep["patch"]}
        return self._retry(sid, g, lv, rows, "L1", [f"不达标 {[r['id'] for r in failing]}"], new_c)

    def _retry(self, sid, g, lv, rows, level, why, new_c):
        lv["prev_rows"], lv["last"], lv["n"] = rows, level, lv["n"] + 1
        self._attempt[sid] = self._attempt.get(sid, 0) + 1
        if new_c is not None:
            self._contract_now = new_c
        g["action"] = f"{level}+retry"
        self.levels.append({"stage": sid, "attempt": g["attempt"], "level": level, "why": why})
        return "retry", new_c

    def _stop(self, sid, g, why, action):
        self._abort(why)
        g["action"] = action
        self.levels.append({"stage": sid, "attempt": g["attempt"], "level": "stop", "why": [why]})
        return "next", None

    def _escalate_l2(self, cl, sid, r_, rows, contract, g, trigger, veto=None):
        lv = self._lv.setdefault(sid, {"l0": 0, "l1": 0, "l2": 0, "prev_rows": None, "prev_patched": set(), "hard_fail": 0, "last": None, "n": 0})
        if lv["l2"] >= self.l2_max:
            if veto is not None:                                         # 审计否决但 L2 预算用尽:只记录(同 on_veto=record)
                self.levels.append({"stage": sid, "attempt": g["attempt"], "level": "veto(no budget)", "why": trigger})
                return "next", None
            return self._stop(sid, g, f"阶段 {sid} 需要 L2 但预算用尽:{trigger}", "abort(L2 budget)")
        lv["l2"] += 1
        new_c, helpers, rep = self._replan(cl, sid, r_, rows, contract, trigger, veto)
        self.replans.append(rep)
        if rep["error"]:
            return self._stop(sid, g, f"L2 失败:{rep['error']}", "abort(L2 error)")
        if rep["infeasible"] and not rep["changed"]:
            return self._stop(sid, g, f"L2 判定换做法也达不到:{rep['infeasible']}", "abort(L2 infeasible)")
        self.helpers_override[sid] = helpers
        for s2 in rep.get("later_changed", []):                          # 同一个策略错误在后续阶段里也改掉
            self.helpers_override[s2] = rep["later_helpers_after"][s2]
        lv.update(l0=0, l1=0, prev_rows=None, prev_patched=set(), hard_fail=0)
        out = self._retry(sid, g, lv, rows, "L2", trigger, new_c)
        lv["last"] = "L2"
        return out

    def _ask_replan(self, system, user, imgs):
        """L2 的大模型调用(11-07 抽出来,子类可替换:阶段图版加阶段图补丁、测试用脚本化 L2)。"""
        return ask_vision(self.replan_model, system, user, imgs, timeout_s=240.0)

    def _helpers_now(self, sid):
        if sid in self.helpers_override:
            return copy.deepcopy(self.helpers_override[sid])
        st = next(s for s in self.task["stages"] if s["id"] == sid)
        return copy.deepcopy(st.get("helpers_fn", lambda c: [])(self.ctx))

    _HELPER_KEYS = set(("id", "level", "attr", "frame", "axes", "joints", "link", "ref_axis", "tool_axis", "sigma", "weight", "penalty", "priority",
                        "profile", "t_ramp", "point", "center", "mode", "target", "lb", "ub"))

    def _check_helpers(self, cl, sid, contract, helpers):
        """契约检查:新策略项 + 这一阶段的契约项一起过 compile_spec(和执行时同一个编译器),有任何一项被拒就退回。"""
        if not isinstance(helpers, list) or not all(isinstance(h, dict) for h in helpers):
            return None, "helpers 不是对象列表"
        ids = {i["id"] for i in contract}
        out = []
        for h in helpers:
            h = {k: v for k, v in h.items() if k in self._HELPER_KEYS}
            h["id"] = str(h.get("id", f"_h{len(out)}"))
            if not h["id"].startswith("_"):
                h["id"] = "_" + h["id"]
            if h["id"] in ids:
                return None, f"策略项编号 {h['id']} 与契约项重名"
            out.append(h)
        in_stage = lambda i: i.get("stage") == sid or sid in i.get("also_stages", ())
        terms = [planner_term(i) for i in contract if in_stage(i) and i["kind"] in ("target", "lower", "upper", "range") and i.get("enabled", True)]
        frames = {**self.all_frames, **{k: v for k, v in cl.extra_frames.items() if k not in self.all_frames}}
        comp = compile_spec({"terms": terms + out}, frames, cl.lim)
        if not comp.ok or comp.rejected_terms:
            return None, f"契约检查不通过:{comp.reject_reason or comp.rejected_terms}"
        return out, None

    def _replan(self, cl, sid, r_, rows, contract, trigger, veto):
        """L2:大模型看全部上下文,重写这一阶段的策略项与 comp;契约锁定(审计否决时开放 source_patch)。"""
        from exp_sweep.llm_io import REPLAN_SYSTEM, replan_user
        items = self._stage_items(sid, contract)
        ids = {i["id"] for i in items}
        helpers0 = self._helpers_now(sid)
        keep = ("id", "kind", "pass", "measured", "deviation", "tol", "target", "lb", "ub", "error")
        gate_hist = [{"attempt": gg["attempt"], "action": gg.get("action", "(本次)"), "rows": [{k: r[k] for k in keep if k in r} for r in gg["rows"]]}
                     for gg in self.gates if gg["stage"] == sid]
        l1_hist = [{k: rp.get(k) for k in ("attempt", "patch", "infeasible", "problems", "escalate_reason") if rp.get(k)}
                   for rp in self.repairs if rp["stage"] == sid]
        curves = {}                                                      # 各项瞬时容差比 z 的曲线(本次尝试,0.25 s 一个点)
        for x in self.timeline:
            if x["stage"] == sid and "z" in x and r_["t0"] - 1e-9 <= x["t"] <= r_["t1"] + 1e-9:
                c = curves.setdefault(x["id"], [])
                if not c or x["t"] - c[-1][0] >= 0.25 - 1e-9:
                    c.append([round(x["t"] - r_["t0"], 2), x["z"]])
        mon = {"z_curves(t_rel_s, z)": curves, "events": [e for e in self.events if e["stage"] == sid][-30:],
               "summary": (self.gates[-1].get("monitor") or {}) if self.gates and self.gates[-1]["stage"] == sid else {}}
        plan = ";".join(f"{i + 1}. {s_['id']}" + (f"({self.stage_notes[s_['id']]})" if s_['id'] in self.stage_notes else "") + (" ← 当前" if s_["id"] == sid else "")
                        for i, s_ in enumerate(self.task["stages"]))
        order = [s_["id"] for s_ in self.task["stages"]]
        later_ids = order[order.index(sid) + 1:]
        later0 = {s2: self._helpers_now(s2) for s2 in later_ids}
        later = {s2: {"contract": contract_view(self._stage_items(s2, contract), with_comp=False), "helpers": later0[s2]} for s2 in later_ids}
        ctx = {"instruction": self.instruction, "stage_table": plan, "stage": sid, "contract": contract_view(items, with_comp=True), "helpers": helpers0,
               "later": later,
               "gate_history": gate_hist, "l1_history": l1_hist, "monitor": mon, "exec_alarms": [e for e in self.exec_events if e["stage"] == sid],
               "trigger": trigger,
               "veto": None if veto is None else {"note": "意图审计否决:契约与原话不符,允许 source_patch", "reason": veto.get("reason"),
                                                  "missing_requirements": veto.get("missing_requirements"), "suspect_items": veto.get("suspect_items")}}
        imgs = self._render(cl, sid)
        user = replan_user(json.loads(json.dumps(ctx, ensure_ascii=False, default=_jsonable)))
        rep = {"stage": sid, "trigger": trigger, "veto": veto is not None, "model": self.replan_model, "helpers_before": helpers0, "calls": [], "error": None,
               "changed": False, "infeasible": [], "source_rejected": [], "problems": []}
        t0, new_c, helpers, err = time.time(), None, None, None
        for k in range(2):                                               # 契约检查不通过:带原因退回改写一次
            r = self._ask_replan(REPLAN_SYSTEM, user if k == 0 else user + f"\n\n你上一次的输出未通过检查:{err}。请改正后重新输出完整 JSON。", imgs)
            js = r.get("json") if isinstance(r.get("json"), dict) else None
            rep["calls"].append({"error": r.get("error"), "text": None if js else (r.get("text") or "")[:2000]})
            if js is None:
                err = r.get("error") or "没有返回 JSON"; continue
            helpers, err = self._check_helpers(cl, sid, contract, js.get("helpers", helpers0))
            if err:
                continue
            later_new = {}
            lh = js.get("later_helpers") or {}
            for s2, hl in (lh.items() if isinstance(lh, dict) else []):
                if s2 not in later0:
                    continue                                             # 只许改后续阶段;当前及之前的阶段不在这里改
                hl2, e2 = self._check_helpers(cl, s2, contract, hl)
                if e2:
                    err = f"later_helpers[{s2}] {e2}"; break
                later_new[s2] = hl2
            if err:
                continue
            rep["later_helpers_before"] = {s2: later0[s2] for s2 in later_new}
            rep["later_helpers_after"] = later_new
            comp_ops = [{"id": c.get("id"), "field": "comp", "value": c.get("value")} for c in (js.get("comp") or []) if isinstance(c, dict) and c.get("id") in ids]
            new_c, probs = apply_patch(contract, comp_ops, REPAIR_FIELDS)
            src = [p for p in (js.get("source_patch") or []) if isinstance(p, dict)]
            if src and veto is None:
                rep["source_rejected"] = src                                 # 契约锁定:不是审计否决触发的 L2 不许改验收
            elif src:
                new_c, p2 = apply_patch(new_c, [p for p in src if p.get("id") in ids], EDIT_FIELDS); probs += p2
            rep.update(diagnosis=js.get("diagnosis"), comp_patch=comp_ops, source_patch=src if veto is not None else [], problems=probs,
                       infeasible=js.get("infeasible") or [])
            break
        rep["latency_s"] = round(time.time() - t0, 2)
        if err:
            rep["error"] = err
            return None, None, rep
        rep["helpers_after"] = helpers
        same = lambda a, b: json.dumps(a, sort_keys=True, default=_jsonable) == json.dumps(b, sort_keys=True, default=_jsonable)
        rep["later_changed"] = [s2 for s2, h in rep.get("later_helpers_after", {}).items() if not same(h, later0[s2])]
        rep["changed"] = not same(helpers, helpers0) or not same(new_c, contract) or bool(rep["later_changed"])
        return new_c, helpers, rep

    # ───────────────────────────── 意图审计
    def _render(self, cl, sid):
        import mujoco
        from PIL import Image
        if self._renderer is None:
            self._renderer = mujoco.Renderer(cl.m, 480, 640)
        p = cl.tcp()[0]
        imgs = []
        for az, el in ((150.0, -25.0), (60.0, -15.0)):
            cam = mujoco.MjvCamera()
            cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            cam.lookat[:] = p
            cam.distance, cam.azimuth, cam.elevation = 0.9, az, el
            self._renderer.update_scene(cl.d, camera=cam)
            buf = io.BytesIO()
            Image.fromarray(self._renderer.render()).save(buf, format="PNG")
            imgs.append(buf.getvalue())
        if self.image_dir is not None:
            self.image_dir.mkdir(parents=True, exist_ok=True)
            for k, b in enumerate(imgs):
                (self.image_dir / f"{sid}_{self._retries.get(sid, 0)}_{k}.png").write_bytes(b)
        return imgs

    def _observation(self, cl, sid, t0=None):
        import mujoco
        p, R = cl.tcp()
        tilt = float(np.degrees(np.arccos(np.clip(-R[2, 2], -1, 1))))
        obs = {"t_s": round(cl.t, 2), "tcp_base_m": _f(p, 4), "tool_tilt_from_down_deg": round(tilt, 1),
               "normal_force_on_table_N": round(normal_force(cl), 2)}
        rel = {}
        for name, (Rf, pf) in self.frames.items():
            if name in self.task.get("dynamic", {}):
                Rf, pf = self.task["dynamic"][name](cl.t - self.t_prog, (Rf, pf))
            rel[name] = _f((p - pf) @ Rf, 4)
        obs["tcp_in_frames_m"] = rel
        if t0 is not None:                                               # 和验收同口径的阶段统计(跳过 verify_skip_s["*"]):跟随移动物体时阶段末瞬时值可能正赶上最大速度,
            t_from = t0 + self.task["verify_skip_s"]["*"]                # follow 对照在 t = 6 s 物体 6.3 cm/s 时瞬时滞后 1.2 cm、阶段均值只差 1 mm(11-03)
            T, P = np.asarray(cl.log["t"]), np.asarray(cl.log["p"])
            idx = np.flatnonzero(T >= t_from - 1e-9)[::10]                 # 50 Hz 采样足够
            if len(idx):
                st = {}
                for name, (Rf0, pf0) in self.frames.items():
                    rr = []
                    for i in idx:
                        Rf, pf = (self.task["dynamic"][name](T[i] - self.t_prog, (Rf0, pf0)) if name in self.task.get("dynamic", {}) else (Rf0, pf0))
                        rr.append((P[i] - pf) @ Rf)
                    rr = np.asarray(rr)
                    st[name] = {"mean": _f(rr.mean(0), 4), "max_abs_dev_from_mean": _f(np.abs(rr - rr.mean(0)).max(0), 4)}
                obs["stage_stats"] = {"window_s": [round(t_from, 2), round(cl.t, 2)], "tcp_in_frames_m": st}
        tid = mujoco.mj_name2id(cl.m, mujoco.mjtObj.mjOBJ_GEOM, "table")
        if tid >= 0:                                                     # 机械臂(含夹爪/笔)任一碰撞体到桌面的最近距离;TCP 高度换算不出是否贴着桌面
            ft = np.zeros(6)
            gap = min((mujoco.mj_geomDistance(cl.m, cl.d, tid, g, 0.5, ft) for g in range(cl.m.ngeom)
                       if g != tid and cl.m.geom_bodyid[g] != 0 and cl.m.geom_contype[g] | cl.m.geom_conaffinity[g]), default=None)
            if gap is not None:                                          # 是否贴着桌面由规则算好再给模型:lite 比不出 0.0003 m < 0.001 m
                obs["robot_min_gap_to_table_mm"] = round(float(gap) * 1e3, 1)
                obs["touching_table"] = bool(gap <= 1e-3 or obs["normal_force_on_table_N"] > CONTACT_N)
        return obs

    AUDIT_SYSTEM = """你在监督一台机械臂。一个阶段刚结束,程序已经用实测数据按这一阶段的规格逐项验收,全部达标。
你的任务是判断:这一阶段做完后的状态是否真的符合用户原话里对这一阶段的要求。规格是由程序或大模型从原话整理出来的,可能写错数值、漏掉要求、用错参考系;
逐项验收只能检查规格里写了的东西,所以验收全过不代表符合原话。你只能否决,不能放行:看不出问题就判符合。
原话通常描述整个任务,会给你完整的阶段表。只审原话里归这一阶段负责的部分:后续阶段才做的事(例如还没抬起、还没加到保持力)这时没做是正常的,不算违背;
只有这一阶段该做到的没做到、或做出了原话不允许的状态,才判不符合。依据是实测状态和图:验收表缺了某一项本身不是否决理由(写进 missing_requirements),
缺项对应的实测状态确实违背原话才否决;数值偏差是否超差由程序按 quantity 判(位置 5 mm、角度 2°,其他量用原话容差或期望值的 20%),你只需如实填 quantity、expected、measured;「竖直」写成 angle_deg、期望 0,实测用 tool_tilt_from_down_deg。
「一直保持 / 跟随」这类持续性要求按 stage_stats 里的阶段均值判断(和逐项验收同口径);tcp_in_frames_m 是阶段末瞬时值,跟随移动物体时有正常的跟踪滞后,只作参考。
「是否接触/离开桌面」看 touching_table(规则算好的:机械臂任一部位到桌面 ≤1 mm 或有法向力就是 true)和 robot_min_gap_to_table_mm,不要拿 TCP 坐标推断;
法向力为 0 不代表离开了桌面(可能只是轻放在桌面上)。
你会看到:用户原话、完整阶段表和这一阶段的说明、逐项验收表(实测值与契约)、阶段末的实测状态摘要、两张阶段末的渲染图(场景里移动的参照物不一定画得出来,以状态摘要为准)。
先把原话里归这一阶段的要求逐条拆出来(含姿态、是否接触、位置、力等隐含要求),每条找对应的实测量逐一对比,再下结论。只输出一个 JSON 对象:
{"checks": [{"requirement": "原话里归这一阶段的一条要求", "evidence": "对应的实测量名和数值(必须来自状态摘要或验收表)",
             "quantity": "position_m" | "angle_deg" | "angle_rad" | "force_N" | "time_s" | "speed_m_s" | "other"(expected / measured 的物理量和单位),
             "expected": 原话要求的数值或数组(换算成 quantity 的单位;只写原话给了数值的分量,例如原话只给 x、y 就不要写 z;没有数值要求写 null),
             "measured": 和 expected 分量一一对应的实测值(照抄状态摘要/验收表), "tolerance": 原话写了容差才填,否则 null, "ok": true 或 false}],
 "intent_met": true 或 false(任一 check 的 ok 为 false 就是 false), "reason": "一两句话", "missing_requirements": ["原话要求了、但逐项验收里没有对应项或对应项写错的要求"], "suspect_items": [{"id": "验收表里的编号", "reason": "为什么怀疑它和原话不一致"}]}"""

    def _audit(self, cl, sid, r_, rows):
        obs = self._observation(cl, sid, r_['t0'])
        imgs = self._render(cl, sid)
        plan = ";".join(f"{i + 1}. {s_}" + (f"({self.stage_notes[s_]})" if s_ in self.stage_notes else "") + (" ← 当前" if s_ == sid else "")
                        for i, s_ in enumerate(st_["id"] for st_ in self.task["stages"]))
        user = ("用户原话:" + self.instruction + "\n\n完整阶段表:" + plan + f"\n这一阶段:{sid}。" + self.stage_notes.get(sid, "") +
                f"\n阶段用时 {r_['t1'] - r_['t0']:.2f} s,退出方式 {r_['exit']}。" +
                "\n\n逐项验收(全部达标;空表 = 这一阶段规格里没有任何验收项):\n" +
                json.dumps([{k: v for k, v in r.items() if k not in ("cat",)} for r in rows], ensure_ascii=False) +
                "\n\n阶段末实测状态:\n" + json.dumps(obs, ensure_ascii=False))
        t0 = time.time()
        with ThreadPoolExecutor(self.audit_votes) as ex:                  # 同一份输入并行问 audit_votes 次,取多数(lite 偶尔数据列对了结论写反)
            rs = list(ex.map(lambda _: ask_vision(self.audit_model, self.AUDIT_SYSTEM, user, imgs), range(self.audit_votes)))
        votes = []
        for r in rs:
            js = r.get("json") if isinstance(r.get("json"), dict) else {}
            v = "veto" if js.get("intent_met") is False else "ok" if js.get("intent_met") is True else "error"     # 调用失败 / 没有给出判断:单独记,不当成通过
            for c in js.get("checks") or []:                          # 数值比较交给代码:lite 会写出「-2.06 cm 对 -5 cm」却判 ok
                c["rule_ok"] = _rule_check(c)
            if v == "ok" and any(c.get("rule_ok") is False for c in js.get("checks") or []):
                v = "veto"
            votes.append({"verdict": v, "reason": js.get("reason"), "checks": js.get("checks") or [], "missing_requirements": js.get("missing_requirements") or [],
                          "suspect_items": js.get("suspect_items") or [], "error": r.get("error"), "raw": None if js else r.get("text")})
        n_ok, n_veto = sum(v["verdict"] == "ok" for v in votes), sum(v["verdict"] == "veto" for v in votes)
        verdict = "error" if n_ok + n_veto == 0 else "veto" if n_veto >= n_ok else "ok"     # 有效票里否决不少于符合就否决(平票偏否决:否决只记建议)
        veto = verdict == "veto"
        rep = next((v for v in votes if v["verdict"] == verdict), votes[0])
        return {"stage": sid, "attempt": self._retries.get(sid, 0), "model": self.audit_model, "verdict": verdict, "veto": veto,
                "n_ok": n_ok, "n_veto": n_veto, "n_error": len(votes) - n_ok - n_veto,
                **{k: rep[k] for k in ("reason", "checks", "missing_requirements", "suspect_items", "error", "raw")},
                "votes": votes if len(votes) > 1 else None,
                "observation": obs, "latency_s": round(time.time() - t0, 2),
                "suggestion": "重装源规格(补项 / 改契约),不改验收" if veto else None}

    def close(self) -> None:
        """显式关掉渲染器:留给解释器退出时析构的话,EGL 已经先卸载了,会打一串 EGL_NOT_INITIALIZED。"""
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def report(self) -> dict:
        return {"aborted": self.aborted, "abort_reason": self.abort_reason, "gates": self.gates, "audits": self.audits, "repairs": self.repairs,
                "events": self.events, "timeline": self.timeline if self.keep_timeline else None,
                "levels": self.levels, "replans": self.replans, "exec_events": self.exec_events, "early_stops": self.early_stops,
                "recoveries": self.recoveries,
                "config": {"monitor_cycles": self.monitor_cycles, "drift_h": self.drift_h, "on_fail": self.on_fail, "max_retries": self.max_retries,
                           "audit_model": self.audit_model, "audit_votes": self.audit_votes, "on_veto": self.on_veto,
                           "exec_monitor": self.exec_monitor, "exec_pos_m": self.exec_pos_m, "exec_force_n": self.exec_force_n, "exec_hold_s": self.exec_hold_s,
                           "stall_win_s": self.stall_win_s, "stall_frac": self.stall_frac, "early_stop_s": self.early_stop_s,
                           "l0_max": self.l0_max, "l1_max": self.l1_max, "l2_max": self.l2_max, "no_progress": self.no_progress,
                           "replan_model": self.replan_model, "l1_escalate_flag": self.l1_escalate_flag}}


def _jsonable(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


# 意图审计里数值比较用的容差由代码定,不让模型自己选(11-03:模型给位置 0.035–0.05 m,把偏 3 cm 的按压位置放过了)。
RULE_TOL = {"position_m": 0.005, "angle_deg": 2.0, "angle_rad": 0.035}
RULE_REL = 0.2                                                         # 其他量:原话写了容差用原话的,否则 |期望| 的 20%


def _rule_check(c: dict):
    """模型给的 expected / measured 都是数(或等长数组)时,用代码判是否超差;不是数值要求返回 None。"""
    try:
        e, m = np.atleast_1d(np.asarray(c.get("expected"), float)), np.atleast_1d(np.asarray(c.get("measured"), float))
    except (TypeError, ValueError):
        return None
    if e.shape != m.shape or not (np.all(np.isfinite(e)) and np.all(np.isfinite(m))):
        return None
    tol = RULE_TOL.get(c.get("quantity"))
    if tol is None:
        try:
            tol = float(c.get("tolerance"))
        except (TypeError, ValueError):
            tol = RULE_REL * float(np.max(np.abs(e)))
        if not np.isfinite(tol) or tol <= 0:
            return None
    return bool(np.max(np.abs(m - e)) <= tol)


_KEY_IDX = 0                                                         # ask_vision 当前用第几把 key(进程内,额度用完后往后换)


def ask_vision(model: str, system: str, user: str, images: list, timeout_s: float = 120.0) -> dict:
    """Gemini 看图(PNG 字节),要求只回 JSON。密钥先用 cost_layers.llm.Gemini 的同一个文件;那把 key 当天额度用完(429 且报 PerDay)时
    换 api_key_gemini4(11-03:两把都是免费档,flash-lite 每把每天 500 次)。"""
    import requests

    from cost_layers.llm import GEMINI_URL, KEY_FILE
    global _KEY_IDX
    keys = [Path(KEY_FILE).expanduser(), Path(KEY_FILE).expanduser().with_name("api_key_gemini4")]
    keys = [k.read_text().strip() for k in keys if k.exists()]
    key = keys[min(_KEY_IDX, len(keys) - 1)]
    parts = [{"text": user}] + [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(b).decode()}} for b in images]
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    for attempt in range(4):
        try:
            rep = requests.post(GEMINI_URL.format(model), json=body, timeout=timeout_s, headers={"Content-Type": "application/json", "X-goog-api-key": key})
        except Exception as e:                                           # noqa: BLE001  超时 / 断网:退避后再试
            err = f"{type(e).__name__}: {e}"
            if attempt == 3:
                return {"error": err, "text": ""}
            time.sleep(2 ** attempt * 2); continue
        if rep.status_code == 429 and "PerDay" in rep.text and _KEY_IDX + 1 < len(keys):
            _KEY_IDX += 1; key = keys[_KEY_IDX]; continue
        if rep.status_code in (429, 500, 503):
            time.sleep(2 ** attempt * 2); continue
        break
    if rep.status_code != 200:
        return {"error": f"HTTP {rep.status_code}: {rep.text[:300]}", "text": ""}
    try:
        text = "".join(p.get("text", "") for p in rep.json()["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError):
        return {"error": "返回里没有文本", "text": rep.text[:300]}
    try:
        js = json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        try:
            js = json.loads(text[a:b + 1]) if a >= 0 and b > a else None
        except json.JSONDecodeError:
            js = None
    return {"text": text, "json": js, "error": None}
