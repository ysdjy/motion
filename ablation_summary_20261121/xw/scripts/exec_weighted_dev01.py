#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-XW 偏离 [dev-XW-01] 的运行包装层(plan_exec_weighted.md「偏离与运行记录」;2026-10-26 新建,只新建文件)。

━━━ 问题
正式批次(sprl1,16:58 启动)的 run 步在 18:22 因 FrameworkError 停下:A_dz(Adz,§2.3 次要臂「纯死区」)在单元
CA|iiwa_a|J3-offB-abs|000 上,入口 exec_weighted_testbed.task_specs 的预编译抛 XWCompileError:
    阶段 settle: reject_reason=None rejected_terms=[('eb_q4_target', '裁剪到硬件限位后 lb >= ub')]
原因:J3-offB 的 q4 目标按 R2 规则放在 E_kin 边界外 0.13 rad(tol 0.05 + 证明余量 0.05 + 取整 0.03)。iiwa_a 的 E_kin q4 下界
−2.042 本身就贴着关节 4 的硬件下限 −2.0944,目标因此落在硬件限位之外(−2.17 / −2.172),且超出量 0.076–0.078 rad > 容差 0.05。
A 的 target 项被 compile_spec 裁剪到限位、只告警;A_dz 把 target 换成 [x* − tol, x* + tol] = [−2.22, −2.12],整段在限位外,
裁剪后 lb = ub = −2.0944 → rejected_terms → 冻结框架按设计判为框架错误并停跑。
冻结代码下逐键纯编译(XT.offline_tables,不跑仿真)枚举全部 1349 个测试键 + 201 个校准键:只有 2 个键、3 个 (单元, 臂) 会这样,
全部是 Adz:CA|iiwa_a|J3-offB-abs|000、CA|iiwa_a|J3-offB-rel|000、CA|iiwa_a|J3-offB-unit|000(后两个同键)。其他臂、TC / TT / N 的
A_dz 都能编译。

━━━ 处理(N/A)
A_dz 的「容差内放松」在这些单元上没有定义:容差带里没有一个硬件上可达的构型。所以 A_dz 在这些单元上记为「不适用」(N/A):
不是 ok、不是 failed(情形结果)、不是 infra、不是拒收;不给任何臂记情形结果;只从涉及 A_dz 的比较(全是描述)里去掉这些单元,并披露个数。
A / A\\P / B1 / B2 / B3 / B1⁻ / B2⁻ 的作业、确认族 F1–F4、其他任何框架错误路径都与冻结版完全相同。判定只看编译结果与作业元数据,不看任何仿真结果。

━━━ 做法(冻结文件一律不改,只 import;exec_weighted.g0() 照常核对三份冻结代码的 sha16)
1. 加载 exec_weighted(XW,冻结):若 sys.modules 里已有同一文件的模块(analyze_exec_weighted 加载过)就直接用,不重复加载
   (edit_breadth 被加载两次会拒绝运行)。
2. 包 XW.load_xw(run_sim / peek_sim 都按模块全局名调用它):原版抛 FrameworkError 时,只有 na_info(d) 判定成立才改抛
   NotApplicableXW;其余一律照抛原来的 FrameworkError。na_info 的条件(全部满足):
     a. 目录里没有 xw_result.json,有 failed.json,returncode = 1;
     b. fail tail 里 FRAMEWORK_RE 的命中只有 XWCompileError,最后一行是入口 task_specs 的 XWCompileError,reject_reason = None,
        rejected_terms 非空且每一项的原因都恰好是「裁剪到硬件限位后 lb >= ub」;
     c. 目录完整:目录名的哈希 = sha1(key.json)[:16],key.json 里的 cmd = cmd.json;
     d. 臂由目录里记录的命令确定:cmd.json 的 xw.replace 非空(arm_cmd 只给 Adz 写 replace;validate_xw 不允许 replace 与 ik 同用),
        被拒的每一项都是 replace 里 op = target_to_range 的关节目标项 eb_q<j>_target,且在 cmd.ext.joints 里有对应的 target。
3. XW.run_batch 换成 run_batch_dev01:冻结版的副本(冻结版源码 sha16 在导入时核对 = RUN_BATCH_SRC_SHA16;模块全局名改写成 XW.<名>,
   计数表多一个 "n/a" 键),只多一个 except NotApplicableXW 分支:该键下的作业(作业元数据)必须全是 Adz,才记状态 "n/a";
   否则按框架错误停(与冻结版相同)。批次日志写 logs/<tag>_dev01_<时间>.jsonl(info = na_info 的记录)。
4. 只放行 g0 / status / run(含 --dry-run);smoke / run-cal / ref-b3 / build-* / decide / freeze 请用冻结入口。
   run --dry-run 时不往 manifest 追加事件(冻结版 dry-run 会追加),并在计数后列出各唯一键现有目录的状态(只读)。
   dev01-selftest:在临时目录里核对 N/A 只对目标情形成立、其他框架错误照停(不碰 results/)。

用法(项目根目录;远程先 source ~/fcl_setup/env.sh,再 export CUDA_VISIBLE_DEVICES=<卡> MUJOCO_GL=egl):
    .venv/bin/python exp_repair/exec_weighted_dev01.py g0
    .venv/bin/python exp_repair/exec_weighted_dev01.py run --dry-run --jobs 12 --devices cuda:0 cuda:1 cuda:2
    .venv/bin/python exp_repair/exec_weighted_dev01.py dev01-selftest [--real-dir results/exp_exec_weighted/sims/<host>/iiwa_a_c3448c02598df0cf]
    .venv/bin/python exp_repair/exec_weighted_dev01.py run --jobs 12 --devices cuda:0 cuda:1 cuda:2 …
分析用 exp_repair/analyze_exec_weighted_dev01.py(同一套判定)。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV_ID = "dev-XW-01"
NA_REASON = "裁剪到硬件限位后 lb >= ub"
NA_ARM = "Adz"
RUN_BATCH_SRC_SHA16 = "d1ae61d7d05c851d"                                # 冻结 exec_weighted.run_batch 的源码(inspect.getsource)sha16
LOAD_XW_SRC_SHA16 = "7b97c10480988370"                                  # 冻结 exec_weighted.load_xw 的源码 sha16
ALLOWED_CMDS = ("g0", "status", "run")
TAIL_RE = re.compile(r"XWCompileError: 阶段 (?P<phase>\S+): reject_reason=(?P<rr>.*?) rejected_terms=(?P<rt>\[.*\])\s*$")
NOTE = (f"[{DEV_ID}] A_dz 在关节目标 ± 容差整段落在硬件限位外的单元上不可编译(compile_spec:「{NA_REASON}」),按不适用(N/A)处理:"
        "不是情形结果、不计入任何臂,只从涉及 A_dz 的描述比较里去掉并披露;其余臂、F1–F4 与其他框架错误路径不变。"
        "由 exp_repair/exec_weighted_dev01.py / analyze_exec_weighted_dev01.py 在 import 时包装,冻结文件未改")


def _load_xw_module():
    m = sys.modules.get("exec_weighted")
    if m is not None and Path(getattr(m, "__file__", "")).resolve() == (HERE / "exec_weighted.py").resolve():
        return m
    spec = importlib.util.spec_from_file_location("exec_weighted", HERE / "exec_weighted.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["exec_weighted"] = m
    spec.loader.exec_module(m)
    return m


XW = _load_xw_module()
CM = XW.CM


def _src_sha16(fn) -> str:
    return hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()[:16]


class NotApplicableXW(RuntimeError):
    """[dev-XW-01] A_dz 的纯死区替换在硬件限位内为空:该 (单元, Adz) 不适用,不是情形结果,也不是要停跑的框架错误。"""

    def __init__(self, info: dict):
        super().__init__(f"[{DEV_ID}] N/A {info.get('dir')}: {info.get('rejected_terms')}")
        self.info = info


# ═══════════════════════════════════════════ 判定(只读)
def na_info(d) -> dict | None:
    """目录 d 是否是 [dev-XW-01] 的 N/A 情形;是 → 记录(dict),否 → None。只读文件,不看仿真结果。"""
    d = Path(d)
    try:
        if (d / "xw_result.json").exists() or not (d / "failed.json").exists():
            return None
        fj = CM.read_json_retry(d / "failed.json")
        tail = [str(x) for x in (fj.get("tail") or [])]
        if fj.get("returncode") != 1 or not tail:
            return None
        if set(XW.FRAMEWORK_RE.findall("\n".join(tail))) != {"XWCompileError"}:
            return None
        m = TAIL_RE.search(tail[-1])
        if m is None or m.group("rr") != "None":
            return None
        rt = ast.literal_eval(m.group("rt"))
        if not isinstance(rt, list) or not rt or any(not (isinstance(x, tuple) and len(x) == 2 and x[1] == NA_REASON) for x in rt):
            return None
        key_txt = (d / "key.json").read_text(encoding="utf-8")
        cmd = json.loads((d / "cmd.json").read_text(encoding="utf-8"))
        if not d.name.endswith("_" + hashlib.sha1(key_txt.encode("utf-8")).hexdigest()[:16]) or json.loads(key_txt).get("cmd") != cmd:
            return None
        rep = (cmd.get("xw") or {}).get("replace") or []
        if not rep:                                                      # 不是 A_dz(只有 Adz 的 cmd 带 xw.replace)
            return None
        t2r = {r["id"]: r for r in rep if r.get("op") == "target_to_range"}
        joints = {f"eb_q{jt['j']}_target": jt for jt in ((cmd.get("ext") or {}).get("joints") or []) if jt.get("mode") == "target"}
        terms = []
        for tid, _why in rt:
            if tid not in t2r or tid not in joints:
                return None
            x, tol = float(joints[tid]["target"]), float(t2r[tid]["tol"])
            terms.append({"id": tid, "target": x, "tol": tol, "range": [round(x - tol, 6), round(x + tol, 6)]})
        return {"dev": DEV_ID, "dir": XW._rel(d), "arm_from_cmd": NA_ARM, "phase": m.group("phase"),
                "rejected_terms": [list(x) for x in rt], "terms": terms, "reason": NA_REASON}
    except (OSError, ValueError, SyntaxError, KeyError, TypeError, AttributeError):   # 审查 verify:code #1:cmd 字段不是 dict 时也不判 N/A
        return None


# ═══════════════════════════════════════════ 包装
_ORIG_LOAD_XW = None
_ORIG_RUN_BATCH = None


def load_xw_dev01(d):
    try:
        return _ORIG_LOAD_XW(d)
    except XW.FrameworkError:
        info = na_info(d)
        if info is None:
            raise
        raise NotApplicableXW(info) from None


def run_batch_dev01(uniq: dict, jobs_n: int, salt: dict | None = None, tag: str = "batch") -> dict:
    """冻结 run_batch 的副本,只多 NotApplicableXW 一个分支(见模块说明 3)。"""
    XW.LOGS.mkdir(parents=True, exist_ok=True)
    log = XW.LOGS / f"{tag}_dev01_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    res = {"ok": 0, "failed": 0, "infra": 0, "budget_stop": 0, "framework": 0, "n/a": 0}
    stop = threading.Event()

    def one(k, v):
        if stop.is_set():
            return k, "skipped", None
        try:
            r = XW.run_sim(v["task"], v["bias"], v["cmd"], salt=salt)
            return k, ("ok" if r.get("ok") else "failed"), r.get("dir")
        except NotApplicableXW as e:                                     # [dev-XW-01]
            arms = sorted({j["arm"] for j in v["jobs"]})
            if arms != [NA_ARM]:                                         # 作业元数据里不全是 Adz:不适用 N/A,照冻结版停
                stop.set()
                return k, "framework", f"[{DEV_ID}] N/A 判定只对 Adz 作业成立,这个键下的臂是 {arms}:{e}"
            return k, "n/a", e.info
        except XW.FrameworkError as e:
            stop.set()
            return k, "framework", str(e)
        except XW.InfraError as e:
            return k, "infra", str(e)
        except XW.SimBudgetExceeded as e:
            return k, "budget_stop", str(e)
    with ThreadPoolExecutor(max(1, int(jobs_n))) as ex:
        futs = [ex.submit(one, k, v) for k, v in uniq.items()]
        for f in as_completed(futs):
            k, st, info = f.result()
            res[st] = res.get(st, 0) + 1
            v = uniq[k]
            with open(log, "a", encoding="utf-8") as lf:
                lf.write(json.dumps({"at": XW.now_s(), "status": st, "task": v["task"], "info": info, "jobs": v["jobs"]}, ensure_ascii=False) + "\n")
            print(f"[{XW.now_s()}] {st:11s} {v['task']} {info}  ({sum(res.values())}/{len(uniq)})", flush=True)
    if res.get("framework"):
        raise XW.FrameworkError(f"批次 {tag} 遇到框架错误,已停(见 {XW._rel(log)})")
    return {**res, "log": XW._rel(log)}


def apply() -> None:
    """在 XW 上装包装(幂等)。冻结函数的源码 sha16 不符就拒绝(副本只对这一版成立)。"""
    global _ORIG_LOAD_XW, _ORIG_RUN_BATCH
    if getattr(XW, "_dev_xw_01", False):
        return
    got = {"run_batch": _src_sha16(XW.run_batch), "load_xw": _src_sha16(XW.load_xw)}
    if got != {"run_batch": RUN_BATCH_SRC_SHA16, "load_xw": LOAD_XW_SRC_SHA16}:
        raise SystemExit(f"[{DEV_ID}] 冻结 exec_weighted 的 run_batch / load_xw 源码与包装层写成时不同:{got}")
    _ORIG_LOAD_XW, _ORIG_RUN_BATCH = XW.load_xw, XW.run_batch
    XW.load_xw = load_xw_dev01
    XW.run_batch = run_batch_dev01
    XW.NotApplicableXW = NotApplicableXW
    XW._dev_xw_01 = True


apply()


# ═══════════════════════════════════════════ dry-run 附带的只读扫描
def scan_existing() -> dict:
    """冻结登记表的全部唯一键:现有目录的状态(done / n/a / failed_case / framework / infra / not_run)。只读。"""
    reg, dx = XW.load_frozen()
    dec = XW.r2_dec()
    units = {u["uid"]: u for u in reg["test"]["units"]}
    J = XW.jobs_test(list(units.values()), dx, reg["test"].get("sens"))
    uniq, _ = XW.dedupe(J, units, dec)
    cnt, na, other = {}, [], []
    for v in uniq.values():
        d = XW.sim_dir(v["task"], v["bias"], v["cmd"])
        if (d / "xw_result.json").exists():
            st = "done"
        elif not (d / "failed.json").exists():
            st = "not_run"
        else:
            try:
                r = XW.load_xw(d)
                st = "failed_case" if not r.get("ok") else "done"
            except NotApplicableXW as e:
                st = "n/a"
                na.append({**e.info, "jobs": [(j["uid"], j["arm"], j["seed"], j["role"]) for j in v["jobs"]]})
            except XW.FrameworkError as e:
                st = "framework"
                other.append(str(e)[:300])
            except XW.InfraError as e:
                st = "infra"
                other.append(str(e)[:300])
        cnt[st] = cnt.get(st, 0) + 1
    return {"unique": len(uniq), "status": cnt, "n/a": na, "other_failures": other}


# ═══════════════════════════════════════════ 自检(临时目录,不碰 results/)
def _mk_dir(root: Path, task: str, cmd: dict, tail_last: str, extra_tail: list | None = None, rc=1, key_ok: bool = True) -> Path:
    key = json.dumps({"v": "xw1", "cmd": cmd, "host": "selftest"}, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    d = root / f"{task}_{h if key_ok else '0' * 16}"
    d.mkdir(parents=True)
    (d / "key.json").write_text(key, encoding="utf-8")
    (d / "cmd.json").write_text(json.dumps(cmd, ensure_ascii=False), encoding="utf-8")
    tail = ["  File \"exp_repair/exec_weighted_testbed.py\", line 450, in task_specs",
            "    raise XWCompileError(f\"阶段 {name}: reject_reason={comp.reject_reason} rejected_terms={comp.rejected_terms}\")"]
    tail = (extra_tail or []) + tail + [tail_last]
    (d / "failed.json").write_text(json.dumps({"returncode": rc, "tail": tail, "argv": [], "wall_s": 1.0}, ensure_ascii=False), encoding="utf-8")
    return d


def dev01_selftest(argv: list) -> int:
    log = []

    def ok(c, msg):
        log.append(("PASS" if c else "FAIL", msg))
        print(f"[{'PASS' if c else 'FAIL'}] {msg}", flush=True)
        if not c:
            raise AssertionError(msg)

    def kind(d) -> str:
        try:
            XW.load_xw(d)
            return "returned"
        except NotApplicableXW:
            return "n/a"
        except XW.FrameworkError:
            return "framework"
        except XW.InfraError:
            return "infra"
        except XW.Incomplete:
            return "incomplete"

    # 1. 真实目录(只读):包装后的 load_xw → N/A;冻结原版 → FrameworkError;不是基础设施失败(run_sim 不会改名重跑)
    real = argv[argv.index("--real-dir") + 1] if "--real-dir" in argv else None
    if real is None:
        cand = sorted(XW.SIMS.glob("iiwa_a_c3448c02598df0cf"))
        real = str(cand[0]) if cand else None
    if real:
        rd = Path(real) if Path(real).is_absolute() else XW.ROOT / real
        before = {p.name: p.stat().st_mtime_ns for p in rd.iterdir()}
        info = na_info(rd)
        ok(kind(rd) == "n/a" and info is not None, f"真实目录 {XW._rel(rd)}:包装后 load_xw → N/A;记录 = {json.dumps(info, ensure_ascii=False)}")
        try:
            _ORIG_LOAD_XW(rd)
            k0 = "returned"
        except XW.FrameworkError:
            k0 = "framework"
        ok(k0 == "framework", "同一目录:冻结原版 load_xw 仍抛 FrameworkError(包装没有改冻结函数本身)")
        ok(not XW.is_infra_failure(rd), "同一目录:is_infra_failure = False(run_sim 不会把它当基础设施失败改名重跑)")
        ok({p.name: p.stat().st_mtime_ns for p in rd.iterdir()} == before, "真实目录没有被写(文件与 mtime 不变)")
    else:
        print("[SKIP] 本机没有真实 N/A 目录(远程 sprl1 上跑时会自动找到 iiwa_a_c3448c02598df0cf)")

    # 2. 合成目录(临时目录)
    tmp = Path(argv[argv.index("--tmp") + 1]) if "--tmp" in argv else Path(tempfile.mkdtemp(prefix="xw_dev01_"))
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        base = {"F": 4.0, "V": 0.02, "tilt_deg": 15.0, "elbow_y": 0.1,
                "ext": {"joints": [{"j": 4, "mode": "target", "penalty": "quadratic", "weight": 2.0, "priority": "preference", "target": -2.17}]}}
        adz = {**base, "xw": {"replace": [{"id": "eb_q4_target", "op": "target_to_range", "tol": 0.05},
                                          {"id": "elbow", "op": "target_to_range", "tol": 0.04}, {"id": "ori", "op": "ori_dz", "tol": 0.05235987756}]}}
        good = f"__main__.XWCompileError: 阶段 settle: reject_reason=None rejected_terms=[('eb_q4_target', '{NA_REASON}')]"
        cases = [
            ("正例:Adz + 目标情形", adz, good, {}, "n/a"),
            ("别的拒收原因(lb >= ub)", adz, good.replace(NA_REASON, "lb >= ub"), {}, "framework"),
            ("别的拒收原因(sigma <= 0)", adz, good.replace(NA_REASON, "sigma <= 0"), {}, "framework"),
            ("多项被拒、其中一项原因不同", adz, good.replace("')]", f"'), ('ori_dz', 'sigma <= 0')]"), {}, "framework"),
            ("reject_reason 不是 None", adz, good.replace("reject_reason=None", "reject_reason=力位冲突"), {}, "framework"),
            ("同一原因但不是 A_dz(cmd 没有 xw.replace,如 A)", base, good, {}, "framework"),
            ("同一原因但臂是 B1(xw.pen,无 replace)", {**base, "xw": {"pen": {"eb_q4_target": "quadratic"}}}, good, {}, "framework"),
            ("被拒的项不在 replace 里", adz, good.replace("eb_q4_target", "eb_q1_target"), {}, "framework"),
            ("被拒的项是手肘(不是关节目标)", adz, good.replace("eb_q4_target", "elbow"), {}, "framework"),
            ("WrapperCompileError", adz, good.replace("__main__.XWCompileError", "press_ext_testbed.WrapperCompileError"), {}, "framework"),
            ("XWFormatError", adz, "__main__.XWFormatError: xw 有未知键 ['foo']", {}, "framework"),
            ("ExtFormatError 混在 tail 里", adz, good, {"extra_tail": ["ExtFormatError: joints 项不合法"]}, "framework"),
            ("返回码不是 1(超时)", adz, good, {"rc": "timeout"}, "framework"),
            ("目录名哈希与 key.json 不符", adz, good, {"key_ok": False}, "framework"),
        ]
        for name, cmd, last, kw, want in cases:
            d = _mk_dir(tmp / name.replace(" ", "_").replace("/", "_"), "iiwa_a", cmd, last, **kw)
            got = kind(d)
            ok(got == want, f"合成:{name} → {got}(应为 {want})")
        # xw_result.json 里有「求值失败」窗口(冻结版判框架错误)→ 仍是框架错误
        d = tmp / "qiuzhi" / "iiwa_a_0000000000000000"
        d.mkdir(parents=True)
        (d / "xw_result.json").write_text("{}", encoding="utf-8")
        (d / "ext_result.json").write_text(json.dumps({"windows": {"settle": {"accepted": False, "reason": "求值失败: KeyError"}}}), encoding="utf-8")
        (d / "cmd.json").write_text(json.dumps(adz), encoding="utf-8")
        orig_load_sim = XW.EB.load_sim
        XW.EB.load_sim = lambda dd: {"dir": str(dd), "ok": True, "ext_result": json.loads((Path(dd) / "ext_result.json").read_text())}
        try:
            ok(kind(d) == "framework", "合成:xw_result.json 有「求值失败」窗口 → 仍是框架错误")
        finally:
            XW.EB.load_sim = orig_load_sim

        # 3. run_batch_dev01:N/A 只对全是 Adz 的键记 n/a;混臂键 / 普通框架错误 → 停;日志写临时目录
        na_dir = _mk_dir(tmp / "rb", "iiwa_a", adz, good)
        fw_dir = _mk_dir(tmp / "rb2", "iiwa_a", adz, good.replace(NA_REASON, "lb >= ub"))
        saved = (XW.run_sim, XW.LOGS)
        XW.LOGS = tmp / "logs"

        def fake_run_sim(task, bias, cmd, salt=None, **_):
            if cmd.get("which") == "ok":
                return {"ok": True, "dir": "ok"}
            if cmd.get("which") == "case_fail":
                return {"ok": False, "dir": "case_fail"}
            return XW.load_xw(na_dir if cmd.get("which") == "na" else fw_dir)
        XW.run_sim = fake_run_sim
        try:
            j = lambda arm: {"uid": "CA|x", "arm": arm, "cfg": None, "seed": 0, "ik": False, "role": "main"}   # noqa: E731
            u1 = {"k_ok": {"task": "iiwa_a", "bias": {}, "cmd": {"which": "ok"}, "jobs": [j("A")]},
                  "k_case": {"task": "iiwa_a", "bias": {}, "cmd": {"which": "case_fail"}, "jobs": [j("B1")]},
                  "k_na": {"task": "iiwa_a", "bias": {}, "cmd": {"which": "na"}, "jobs": [j("Adz"), j("Adz")]}}
            r1 = run_batch_dev01(u1, 1, tag="st")
            ok(r1["ok"] == 1 and r1["failed"] == 1 and r1["n/a"] == 1 and r1["framework"] == 0, f"run_batch_dev01:ok / 情形失败 / n/a 各 1,不停:{r1}")
            lines = [json.loads(x) for x in (tmp / "logs" / Path(r1["log"]).name).read_text(encoding="utf-8").splitlines()]
            ok(any(x["status"] == "n/a" and x["info"]["reason"] == NA_REASON for x in lines), "批次日志里 n/a 行带 na_info 记录")
            for name, uu in (("N/A 判定成立但键下混有非 Adz 作业", {"k_na": {"task": "iiwa_a", "bias": {}, "cmd": {"which": "na"}, "jobs": [j("Adz"), j("A")]}}),
                             ("普通 XWCompileError(别的原因)", {"k_fw": {"task": "iiwa_a", "bias": {}, "cmd": {"which": "fw"}, "jobs": [j("Adz")]}})):
                try:
                    run_batch_dev01(uu, 1, tag="st")
                    stopped = False
                except XW.FrameworkError:
                    stopped = True
                ok(stopped, f"run_batch_dev01:{name} → FrameworkError 停跑")
        finally:
            XW.run_sim, XW.LOGS = saved
        ok(not any(str(p).startswith(str(XW.OUT)) for p in tmp.rglob("*")), f"自检只写临时目录 {tmp}")
    finally:
        if "--keep" not in argv:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"dev01-selftest 通过 {sum(1 for s, _ in log if s == 'PASS')} 项")
    return 0


# ═══════════════════════════════════════════ 主函数
def main() -> int:
    argv = sys.argv[1:]
    sub = argv[0] if argv else None
    if sub == "dev01-selftest":
        return dev01_selftest(argv[1:])
    if sub not in ALLOWED_CMDS:
        print(__doc__)
        raise SystemExit(f"[{DEV_ID}] 本包装层只放行 {ALLOWED_CMDS} 与 dev01-selftest;其余子命令请用冻结入口 exp_repair/exec_weighted.py")
    print(NOTE, flush=True)
    if sub == "run" and "--dry-run" in argv:
        def _no_manifest(devices, extra=None):
            print(f"[{DEV_ID}] run --dry-run:不往 manifest_{XW.HOST}.json 追加事件", flush=True)
        XW.write_manifest = _no_manifest
        rc = XW.main()
        print(json.dumps({"dev01_scan": scan_existing()}, ensure_ascii=False, indent=1), flush=True)
        return rc
    _orig_manifest = XW.write_manifest                                   # 审查 verify:science:manifest 事件要看得出用了包装层

    def _manifest_dev01(devices, extra=None):
        return _orig_manifest(devices, {**(extra or {}), "dev": DEV_ID, "wrapper": "exp_repair/exec_weighted_dev01.py",
                                        "wrapper_sha16": XW.sha16(Path(__file__))})
    XW.write_manifest = _manifest_dev01
    return XW.main()


if __name__ == "__main__":
    raise SystemExit(main())
