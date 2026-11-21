# -*- coding: utf-8 -*-
"""求解器层诊断(2026-11-08;exp_sweep 任务版 DiagHMR 与阶段图版 GraphHMR 共用)。

诊断看最近 win_s 秒里哪些约束「压着」(实测处在界上或越界的样本比例 ≥ press_frac),按来源分三类:
  strategy  策略项(规划器 / 大模型写的辅助项,编号以 _ 开头):做法与要求冲突           → 直接 L2
  fixed     执行器固定约束(关节限位、关节速度上限、TCP 速度上限、工作空间、障碍盒、可达边界)
            或契约里的硬约束:可能是局部最优(例如被墙挡住、其实能绕),也可能真的不可达  → 先求解器补救,不行再 L2(由 L2 判不可达)
  (无)      没有约束压着:采样退化                                                        → 求解器补救
求解器补救 = 采样噪声放大 boost 倍、持续 boost_s 秒,平台计时重新开始;每个阶段只补救一次。
阶段末(阶段内来不及判平台)按同样的分类:策略项压着 → L2;规则补不了的连续量且这一阶段没补救过 → 下一趟全程放大噪声重跑;
其余(不一一对应的量)→ 大模型 L1(L1b)。
判定实验:replan_model = "none" 时该升级 L2 就停下记「需要 L2」;l1b_llm = NoLLM() 时该调 L1b 就停下记「需要 L1b」。
"""
from __future__ import annotations

import numpy as np

from cost_layers.cost import FIXED
from exp_sweep.hmr2 import RULE_KINDS, Supervisor2


class NoLLM:
    """判定实验用:分层逻辑走到「调用大模型 L1」时返回错误,由 Supervisor2 记录后停下。"""

    def ask(self, *a, **k):
        return {"text": "", "error": "NO_LLM:需要 L1b(本次实验不调用大模型)", "usage": {}}


class SolverDiagMixin:
    def _diag_init(self, boost=3.0, boost_s=2.0, limit_margin=0.15, win_s=0.5, press_frac=0.3):
        self.boost, self.boost_s, self.limit_margin, self.win_s, self.press_frac = boost, boost_s, limit_margin, win_s, press_frac
        self.diagnoses, self._boost_until, self._sigma0 = [], None, None
        self._boosted_stage, self._boost_next = set(), set()

    # ── 哪些约束压着
    def _active_constraints(self, cl) -> list:
        L = cl.log
        every = max(1, int(round(0.02 / cl.log_dt)))
        n = len(L["t"])
        k = max(2, int(round(self.win_s / 0.02)))
        idx = list(range(n - 1, -1, -every))[:k][::-1]
        if len(idx) < 2:
            return []
        q, dq = np.asarray([L["q"][i] for i in idx]), np.asarray([L["dq"][i] for i in idx])
        out = []
        frac = lambda b: float(np.mean(b))
        model = cl.cost_new
        roll = cl.measured_roll(q, dq)
        if model is not None:
            for t in model.terms:                                            # 规格里的硬约束项:策略项(_ 开头)或契约硬约束
                if t.penalty != "hard" or t.kind != "deadzone" or t.level in ("tcp_force", "contact"):
                    continue
                try:
                    x = model.value(t, roll)[0].detach().cpu().numpy()      # (S, nd)
                except Exception:                                            # noqa: BLE001
                    continue
                m = 0.5 * t.sigma
                hit = np.zeros(len(x), bool)
                if t.ub is not None:
                    hit |= np.any(x >= np.asarray(t.ub) - m, axis=-1)
                if t.lb is not None:
                    hit |= np.any(x <= np.asarray(t.lb) + m, axis=-1)
                if frac(hit) >= self.press_frac:
                    out.append({"source": "strategy" if str(t.id).startswith("_") else "fixed", "kind": "硬约束项", "id": t.id, "frac": round(frac(hit), 2)})
        lim = cl.lim
        near = [j + 1 for j in range(7) if q[-1, j] - lim.q_min[j] < self.limit_margin or lim.q_max[j] - q[-1, j] < self.limit_margin]
        if near:
            out.append({"source": "fixed", "kind": "关节限位", "joints": near})
        f = {**FIXED, **(getattr(model, "fixed", None) or {})}
        hit = np.any(np.abs(dq) >= 0.9 * f["dq_frac"] * lim.dq_max, axis=-1)
        if frac(hit) >= self.press_frac:
            out.append({"source": "fixed", "kind": "关节速度上限", "frac": round(frac(hit), 2)})
        p = roll["p"][0, 1:].detach().cpu().numpy()
        v = roll["twist"][0, :, :3].norm(dim=-1).detach().cpu().numpy()
        v_max = f["tcp_speed_contact"] if (model is not None and model.contact is not None) else f["tcp_speed_max"]
        if frac(v >= 0.9 * v_max) >= self.press_frac:
            out.append({"source": "fixed", "kind": "TCP 速度上限", "v_max": v_max})
        lo, hi = np.asarray(f["workspace_lb"]), np.asarray(f["workspace_ub"])
        if frac(np.any((p - lo < 0.01) | (hi - p < 0.01), axis=-1)) >= self.press_frac:
            out.append({"source": "fixed", "kind": "工作空间边界"})
        J = roll["J"][0, 1:].detach().cpu().numpy()
        manip = np.sqrt(np.clip(np.linalg.det(J @ np.swapaxes(J, -1, -2)), 0, None))
        if frac(manip < 1.5 * f["manip_min"]) >= self.press_frac:
            out.append({"source": "fixed", "kind": "可达边界(可操作度低)", "manip": round(float(manip[-1]), 4)})
        if f.get("obstacles") and f.get("hand_pts"):
            R = roll["R"][0, 1:].detach().cpu().numpy()
            hp = np.asarray(f["hand_pts"], float)
            pts = p[:, None, :] + np.einsum("sij,nj->sni", R, hp[:, :3])
            r = hp[:, 3] if hp.shape[1] > 3 else np.zeros(len(hp))
            boxes = np.asarray(f["obstacles"], float)
            gap = np.full(len(p), np.inf)
            for lo_b, hi_b in boxes:
                dvec = np.maximum(np.maximum(lo_b - pts, pts - hi_b), 0.0)
                gap = np.minimum(gap, (np.linalg.norm(dvec, axis=-1) - r).min(-1))
            if frac(gap < 0.015) >= self.press_frac:
                out.append({"source": "fixed", "kind": "障碍物", "gap": round(float(gap[-1]), 4)})
        return out

    def _boost_on(self, cl, until):
        if self._boost_until is None:
            self._sigma0 = cl.mppi.sigma
        cl.mppi.sigma = max(self._sigma0, getattr(cl, "_sigma_default", self._sigma0)) * self.boost   # 11-09:放大要从「当前值与默认值的较大者」起
        cl.mppi._set_vectors()                                                # (11-08 改成只乘当前值后,噪声被压到近零的停滞时 ×3 仍近零,补救失效;lv1b solver 11/20)
        self._sigma_boosted = cl.mppi.sigma
        self._boost_until = until
        cl._hmr_remedied = True                                               # 合成探针据此停止注入

    def _boost_off(self, cl):
        """11-08 审查:放大期间若装过新规格,闭环已经按新规格(含加速度上限)重设了噪声,不能再用旧值盖回去;否则恢复放大前的值。"""
        if cl.mppi.sigma == getattr(self, "_sigma_boosted", None):
            cl.mppi.sigma = self._sigma0
            cl.mppi._set_vectors()
        self._boost_until = None

    # ── 阶段内:平台超时之后
    def _trigger_l2(self, s, why):
        cl = self.cl
        act = self._active_constraints(cl)
        strat = [c for c in act if c["source"] == "strategy"]
        pred_bad = [iid for iid, tr in self._tracks.items() if tr.state.get("pred_ok") is False]
        d = {"stage": s["sid"], "attempt": self._attempt.get(s["sid"], 0), "t": round(cl.t, 3), "where": "阶段内", "why": why, "active": act,
             "pred_bad": pred_bad, "cost_min": cl.mppi.last.get("cost_min"), "ess": cl.mppi.last.get("ess")}
        if not strat and s["sid"] not in self._boosted_stage and self.boost > 1.0:
            self._boosted_stage.add(s["sid"])
            self._boost_on(cl, cl.t + self.boost_s)
            s["plateau_t"], s["worse_t"] = None, None
            s["base_t"], s["R_u"], s["upd_t"] = cl.t, s.get("R"), cl.t
            for iid, tr in self._tracks.items():
                s["n0"][iid] = len(tr.x)
            d["action"] = f"求解器补救:采样噪声 ×{self.boost},{self.boost_s} s"
            self.diagnoses.append(d)
            self.levels.append({"stage": s["sid"], "attempt": d["attempt"], "level": "L1-求解器",
                                "why": why + [("固定 / 契约约束压着,可能是局部最优" if act else "没有约束压着,疑似采样退化") + f" {act}"]})
            return None
        d["action"] = "升级 L2(" + ("策略项压着" if strat else "求解器补救后仍不降") + ")"
        self.diagnoses.append(d)
        return super()._trigger_l2(s, why + [f"压着的约束 {act}"])

    def on_cycles(self, cl, sid, t0):
        if sid in self._boost_next:                                           # 阶段末判的「放大噪声重跑」:这一趟全程放大
            self._boost_next.discard(sid)
            self._boost_on(cl, float("inf"))
        if self._boost_until is not None and cl.t >= self._boost_until:      # 补救时段结束:恢复采样噪声
            self._boost_off(cl)
        super().on_cycles(cl, sid, t0)

    def on_stage_abandon(self, cl, sid):
        """11-09 审查:阶段被安全中断 / 总时长超限打断(不交给 HMR)时的收尾:恢复采样噪声、清掉阶段内状态的指针。"""
        if self._boost_until is not None:
            self._boost_off(cl)
        self._boost_next.discard(sid)
        self._sid = None

    def on_stage_end(self, cl, sid, r_, rec, contract):
        if self._boost_until == float("inf"):                                 # 全程放大的那一趟结束:恢复
            self._boost_off(cl)
        return super().on_stage_end(cl, sid, r_, rec, contract)

    # ── 阶段末
    def _hier(self, cl, sid, r_, rows, contract, g, ex):
        s = self._s.get((sid, r_["t0"]))
        lv = self._lv.setdefault(sid, {"l0": 0, "l1": 0, "l2": 0, "prev_rows": None, "prev_patched": set(), "hard_fail": 0, "last": None, "n": 0})
        if (ex is not None and ex["alarms"] and lv["l0"] < self.l0_max) or (s is not None and s["pending_l2"] is not None):
            return super()._hier(cl, sid, r_, rows, contract, g, ex)        # L0 / 阶段内已判 L2:照第二版
        act = self._active_constraints(cl)
        strat = [c for c in act if c["source"] == "strategy"]
        by_id = {i["id"]: i for i in contract}
        failing = [r for r in rows if not r["pass"]]
        if getattr(self, "flat", False) and failing:                          # 消融 flat_diag:不分层,一不过就 L2,但带上诊断
            d = {"stage": sid, "attempt": g["attempt"], "t": round(cl.t, 3), "where": "阶段末", "active": act, "failing": [r["id"] for r in failing],
                 "action": "升级 L2(flat_diag)"}
            self.diagnoses.append(d)
            return self._l2(cl, sid, r_, rows, contract, g, [f"阶段末仍不达标 {d['failing']}", f"压着的约束 {act}"])
        cont = [r for r in failing if (by_id.get(r["id"]) or {}).get("kind") in RULE_KINDS]
        gs = self._gs.get(sid, {"n": 0, "dead": set()})
        dead = gs["dead"] | (s["dead"] if s else set())
        d = {"stage": sid, "attempt": g["attempt"], "t": round(cl.t, 3), "where": "阶段末", "active": act, "failing": [r["id"] for r in failing]}
        if strat:
            d["action"] = "升级 L2(策略项压着)"
            self.diagnoses.append(d)
            return self._l2(cl, sid, r_, rows, contract, g, [f"阶段末仍不达标 {d['failing']}", f"策略项压着 {strat}"])
        if cont and len(cont) == len(failing) and all(r["id"] in dead for r in cont) and sid not in self._boosted_stage and self.boost > 1.0:
            self._boosted_stage.add(sid)                                      # 规则补不了的连续量、没补救过:下一趟全程放大噪声
            self._boost_next.add(sid)
            d["action"] = f"求解器补救(下一趟全程噪声 ×{self.boost})"
            self.diagnoses.append(d)
            return self._retry(sid, g, lv, rows, "L1-求解器", [f"规则判补偿无效 {sorted(dead)}", f"压着的约束 {act}"], None)
        l1b0 = self.l1b
        if getattr(self, "l1b_gate", True) and act and not [r for r in failing if (by_id.get(r["id"]) or {}).get("kind") not in RULE_KINDS]:
            self.l1b = False                                                  # 只有连续量不过、又有约束压着:不交给 L1b,走 L2
        try:
            return super()._hier(cl, sid, r_, rows, contract, g, ex)
        finally:
            self.l1b = l1b0

    def _escalate_l2(self, cl, sid, r_, rows, contract, g, trigger, veto=None):
        if self.replan_model == "none":                                       # 判定实验:记「需要 L2」后停下
            self.levels.append({"stage": sid, "attempt": g["attempt"], "level": "需要L2", "why": list(trigger)})
            return self._stop(sid, g, "需要 L2(本次实验不调用大模型):" + "; ".join(map(str, trigger)), "stop(need L2)")
        return super()._escalate_l2(cl, sid, r_, rows, contract, g, trigger, veto)

    def report(self) -> dict:
        r = super().report()
        r["diagnoses"] = self.diagnoses
        return r


class DiagHMR(SolverDiagMixin, Supervisor2):
    def __init__(self, contract, *, boost=3.0, boost_s=2.0, limit_margin=0.15, **kw):
        super().__init__(contract, **kw)
        self._diag_init(boost, boost_s, limit_margin)
