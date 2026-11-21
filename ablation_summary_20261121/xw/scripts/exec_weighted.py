#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-XW 执行层消融框架:逐维规格(A)vs 加权代价(B1 / B2 / B3 …)(plan_exec_weighted.md v2;2026-10-26 新建,只新建文件)。

同一个 MPPI 执行器、同一批任务、同一份契约,只换「契约 → 代价」的编译方式;所有臂都按原契约逐维验收(EB.evaluate)。
规格全部由程序从契约生成,不调大模型。子进程入口是 exp_repair/exec_weighted_testbed.py(自包含,包 R2 包装层)。

━━━ 设计要点(详见方案;这里只列实现时定下的取舍)
1. 第一件事按 R2 的方式 import edit_breadth(EB),只用它的纯函数:compile_spec、evaluate / eval_item、load_series、load_sim(只读)、
   TASKS、targets_of、default_tol、bias_args、load_decisions、gpu_manifest、tighten_interval、sim_key(只算哈希,用来定位 R2 缓存)、
   effective_items、start_stats、is_infra_failure(只读)。**不用** EB.run_sim / sim_dir / infra_log / write_manifest / device_guard
   (它们写 results/exp_edit_breadth/)。selftest #8 的写入守卫在 build-test、分析与 selftest 期间拦截任何指向 R2 目录的写操作。
2. 臂(§2.3):增益 g_i = 10 · w_i · a_i · b_i(a = r_pref 若项是偏好档,b = m_b 若项是契约 hard 界)。
   A(r 0.1, m 1, 分层 + 拒收 + 容差 → σ);A\\P = AP(r 1);A_dz = Adz(纯死区);B1(二次,进和)、B2(障碍,进和)= E6 r2 原样;
   B1⁻ / B2⁻ = B1m / B2m(r 1);B3 = 网格 (r_pref, m_b, form) 按类选。父进程把每臂的编译结果写成规范化覆盖表 cmd["xw"]
   (只记与 EB.compile_spec 默认不同、且在执行里起作用的字段;分层 hard 项的增益是惰性字段,不写),空表就不写 xw 键。
   所以「按构造相同」由缓存键直接体现(selftest #3 断言)。D6:速度界在规划器里一律二次(EB.compile_spec 已按 decisions 处理)。
3. 缓存(§2.6):键 = {"v": "xw1", 入口 sha、包装层 sha、测试台 sha、P3.CODE_VER、P3.SIM_ARGS、robot、bias、cmd(含 ext / mppi_seed / xw)、
   hostname[, salt]};目录 results/exp_exec_weighted/sims/<hostname>/<task>_<hash16>;完成标记 = xw_result.json。
   复用 R2:本机、种子 0、空覆盖表的 A,在门 r2_bitid(冒烟 #2 逐位相同)通过后直接只读 R2 的 program_once / 起点目录。
4. 情形类别(§3):N 23、H* 36(G3 不满足的丢弃不补)、H-R2 114、C-a 32、R 4、T-conf 14 对、T-tight、FV 6;校准集 19(盐 xw-cal)。
5. 设备(§9.1):远程主机必须显式设 CUDA_VISIBLE_DEVICES,物理卡 ⊂ {1,2,3,5,6,7},7 只在 16:30 之后且空闲显存 ≥ 8 GB 时可用,永不用 0 / 4。
6. 失败判定:fail tail 里有 XWCompileError / XWFormatError / WrapperCompileError / ExtFormatError → 框架错误(停);
   基础设施失败(OOM / CUDA / 被杀 / 超时)改名重跑 1 次,仍失败 → InfraError(该单元整组配对剔除并披露);子进程超时 1800 s;--max-new-sims 预算。

━━━ 命令(项目根目录运行;仿真类命令需要 MUJOCO_GL=egl)
    .venv/bin/python exp_repair/exec_weighted.py g0
    .venv/bin/python exp_repair/exec_weighted.py selftest                     # §9.2 的 11 项离线自检(不跑仿真)
    MUJOCO_GL=egl .venv/bin/python exp_repair/exec_weighted.py smoke --items 2 4 5 7 8 9 --jobs 2 --devices cuda:0 cuda:1 --max-new-sims 6
    .venv/bin/python exp_repair/exec_weighted.py build-cal                    # 校准集 → cases_xw.json 的 cal 部分
    .venv/bin/python exp_repair/exec_weighted.py build-test                   # 测试集 → cases_xw.json 的 test 部分(含 G3)
    MUJOCO_GL=egl .venv/bin/python exp_repair/exec_weighted.py run-cal --jobs 6 --devices cuda:0 cuda:1 [--max-new-sims N]
    .venv/bin/python exp_repair/exec_weighted.py decide                       # G4 + B3 按类选择(G2)+ F3 退路 → decisions_xw.json
    MUJOCO_GL=egl .venv/bin/python exp_repair/exec_weighted.py ref-b3 --devices cuda:0   # G5:B3 的 H 类 r_pref ≠ 0.1 时跑 6 个无界参照
    .venv/bin/python exp_repair/exec_weighted.py freeze
    MUJOCO_GL=egl .venv/bin/python exp_repair/exec_weighted.py run --jobs 6 --devices cuda:0 cuda:1 [--classes HS CA …] [--dry-run]
    .venv/bin/python exp_repair/exec_weighted.py status
远程(sprl1):先 source ~/fcl_setup/env.sh,再 export CUDA_VISIBLE_DEVICES=<从 1,2,3,5,6,7 里选的空闲卡>,--devices cuda:0 …
输出只在 results/exp_exec_weighted/{cases_xw.json, decisions_xw.json, sims/<host>/, logs/, manifest_<host>.json, infra_events.jsonl, analysis_xw.*}。
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import copy
import hashlib
import importlib.util
import io
import itertools
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ═══════════════════════════════════════════ 第一件事:按 R2 的方式加载 edit_breadth(它会从快照加载 P3 / common 并核对版本)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_spec = importlib.util.spec_from_file_location("edit_breadth", HERE / "edit_breadth.py")
EB = importlib.util.module_from_spec(_spec)
sys.modules["edit_breadth"] = EB
_spec.loader.exec_module(EB)
CM, P3, PX = EB.CM, EB.P3, EB.PX
_tspec = importlib.util.spec_from_file_location("exec_weighted_testbed", HERE / "exec_weighted_testbed.py")
XT = importlib.util.module_from_spec(_tspec)
sys.modules["exec_weighted_testbed"] = XT
_tspec.loader.exec_module(XT)
import numpy as np                                                       # noqa: E402
import stats_v3 as ST                                                    # noqa: E402  快照(exp_repair_frozen_v3)

# ═══════════════════════════════════════════ 常数、路径、冻结值
OUT = ROOT / "results" / "exp_exec_weighted"
HOST = socket.gethostname()
SIMS = OUT / "sims" / HOST
LOGS = OUT / "logs"
CASES = OUT / "cases_xw.json"
DECISIONS = OUT / "decisions_xw.json"
ENTRY = HERE / "exec_weighted_testbed.py"
ANALYZE = HERE / "analyze_exec_weighted.py"
PY = str(ROOT / ".venv" / "bin" / "python")
KEY_V = "xw1"
REG_VERSION = "xw2"
FROZEN_XW = {"exp_repair/edit_breadth.py": "d65f1c1cc7775903", "exp_repair/press_ext_testbed.py": "8c670b2347b752e5",
             "exp_xemb_frozen_v3/iiwa_press.py": "653ad3a27580c4b1", "results/exp_edit_breadth/cases_eb.json": "019e5f5458704f73",
             "results/exp_edit_breadth/pilot/decisions.json": "67c09c4eb9218a00"}
ALLOWED_REMOTE_GPUS = {"1", "2", "3", "5", "6", "7"}
GPU7_AFTER = (16, 30)
GPU7_MIN_FREE_MIB = 8192                                                 # 远程每张选中的卡都要 ≥ 8 GB 空闲(名字沿用)
GPU_STABLE_GAP_S, GPU_STABLE_MIB = 5.0, 2048
TIMEOUT_S = 1800
SMOKE_SALT = {"smoke": "xw-s2"}
SMOKE_SALT2 = {"smoke": "xw-s2b"}                                          # 冒烟 #10:同一 cmd 新盐重跑
GEN_SALT, CAL_SALT = "xw2", "xw-cal"
ARMS = ("A", "B1", "B2", "B3", "AP", "B1m", "B2m", "Adz")
GRID = [(r, m, f) for r in (0.1, 0.3, 1.0) for m in (0.3, 1.0, 10.0) for f in ("quad", "barrier")]
TIE_REF = (0.1, 1.0, "barrier")
TIE_EPS = 0.02
TASK_DIMS = ("force", "speed", "tilt", "path")
DELTA = dict(EB.DELTA)
JQ = list(EB.JQ)
SIGMA_ID = {"force": "press", "tilt": "ori", "elbow": "elbow"}
Q_SIGMA0, Q_TOL0 = 0.02, EB.JOINT_TOL
HS_DELTAS = (0.25, 0.5, 0.75)
HS_FEAS = 1.5                                                            # G3(a):界离目标 ≤ 1.5°
HS_SIGMA_RAD = PX.SIGMA["tilt"]                                          # 0.02 rad:G3(a) 起点离界 < 3σ
R_GAPS = (0.10, 0.20)
TC = {"te_s": 0.015, "te_L": 0.04, "tq_s": 0.03, "fracs": (0.25, 0.5, 0.75), "margin": 0.02}
TT_LIST = [("xarm_a", "tilt", 1.0), ("xarm_a", "tilt", 1.3), ("xarm_b", "tilt", 1.0), ("fr3_a", "force", 0.15), ("iiwa_a", "force", 0.15),
           ("iiwa_a", "elbow", 0.010), ("iiwa_b", "elbow", 0.010)]    # §3.6 原文列出的 7 个(方案表写 8,见 open issue)
FV_SPEED, FV_FORCE_TOL_MULT = 40.0, 0.5
CAL_HS = [("fr3_a", "upper", 0.4), ("fr3_b", "lower", 0.6), ("iiwa_a", "upper", 0.6), ("iiwa_b", "lower", 0.4), ("xarm_a", "lower", 0.6),
          ("xarm_b", "upper", 0.4)]
CAL_N_TASKS = ["fr3_b", "iiwa_a", "xarm_b", "iiwa_b"]
CAL_C_TASKS = ["fr3_b", "iiwa_b", "xarm_b"]
INVALID_END_Y_MM = 5.0
FRAMEWORK_RE = re.compile(r"XWCompileError|XWFormatError|WrapperCompileError|ExtFormatError")


class FrameworkError(RuntimeError):
    """框架 / 包装层 / 入口的编译错误:不是情形结果,停下修。"""


class InfraError(RuntimeError):
    pass


class SimBudgetExceeded(RuntimeError):
    pass


class Incomplete(RuntimeError):
    """只有 ext_result.json、没有 xw_result.json 的目录(或缺缓存的只读请求)。"""


class R2WriteViolation(PermissionError):
    pass


def sha16(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_obj(o) -> str:
    return EB.sha256_obj(o)


def _rel(p) -> str:
    return EB._rel(p)


def now_s() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def r6(x: float) -> float:
    return float(f"{float(x):.10g}")


# ═══════════════════════════════════════════ R2 写入守卫(selftest #8)
def _under_r2(p) -> bool:
    try:
        rp = os.path.realpath(os.fspath(p))
    except TypeError:
        return False
    root = os.path.realpath(str(EB.OUT))
    return rp == root or rp.startswith(root + os.sep)


@contextlib.contextmanager
def r2_write_guard():
    """在 with 块里拦截任何指向 results/exp_edit_breadth/ 的写操作(open 写模式、os.open 带写标志、mkdir、replace、rename、删除、
    tempfile、shutil 复制 / 移动)。只读不受影响。"""
    saved = {}

    def patch(obj, name, fn):
        saved[(obj, name)] = getattr(obj, name)
        setattr(obj, name, fn)

    o_open, o_os_open = builtins.open, os.open

    def g_open(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+") and not isinstance(file, int) and _under_r2(file):
            raise R2WriteViolation(f"写 R2 目录被拦:open({file!r}, {mode!r})")
        return o_open(file, mode, *a, **k)

    def g_os_open(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC) and _under_r2(path):
            raise R2WriteViolation(f"写 R2 目录被拦:os.open({path!r})")
        return o_os_open(path, flags, *a, **k)

    def wrap1(fn, what):
        def g(p, *a, **k):
            if _under_r2(p):
                raise R2WriteViolation(f"写 R2 目录被拦:{what}({p!r})")
            return fn(p, *a, **k)
        return g

    def wrap2(fn, what):
        def g(src, dst, *a, **k):
            if _under_r2(src) or _under_r2(dst):
                raise R2WriteViolation(f"写 R2 目录被拦:{what}({src!r}, {dst!r})")
            return fn(src, dst, *a, **k)
        return g

    def wrap_dst(fn, what):
        def g(src, dst, *a, **k):
            if _under_r2(dst):
                raise R2WriteViolation(f"写 R2 目录被拦:{what}(→ {dst!r})")
            return fn(src, dst, *a, **k)
        return g

    o_mkstemp = tempfile.mkstemp

    def g_mkstemp(*a, **k):
        d = k.get("dir") if "dir" in k else (a[2] if len(a) > 2 else None)
        if d is not None and _under_r2(d):
            raise R2WriteViolation(f"写 R2 目录被拦:mkstemp(dir={d!r})")
        return o_mkstemp(*a, **k)

    try:
        patch(builtins, "open", g_open)
        patch(io, "open", g_open)
        patch(os, "open", g_os_open)
        for nm in ("mkdir", "makedirs", "remove", "unlink", "rmdir"):
            patch(os, nm, wrap1(getattr(os, nm), f"os.{nm}"))
        for nm in ("replace", "rename"):
            patch(os, nm, wrap2(getattr(os, nm), f"os.{nm}"))
        for nm in ("mkdir", "touch", "write_text", "write_bytes", "unlink", "rmdir"):
            patch(Path, nm, wrap1(getattr(Path, nm), f"Path.{nm}"))
        for nm in ("rename", "replace"):
            patch(Path, nm, wrap2(getattr(Path, nm), f"Path.{nm}"))
        for nm in ("copyfile", "copy", "copy2", "move", "copytree"):
            patch(shutil, nm, wrap_dst(getattr(shutil, nm), f"shutil.{nm}"))
        patch(tempfile, "mkstemp", g_mkstemp)
        yield
    finally:
        for (obj, name), fn in saved.items():
            setattr(obj, name, fn)


# ═══════════════════════════════════════════ G0 与设备守卫
def code_shas() -> dict:
    return {"exp_repair/exec_weighted.py": sha16(Path(__file__)), "exp_repair/exec_weighted_testbed.py": sha16(ENTRY),
            "exp_repair/analyze_exec_weighted.py": sha16(ANALYZE) if ANALYZE.exists() else None}


def g0(strict: bool = True, check_frozen_code: bool = True) -> dict:
    """§11 G0:EB.ONLINE_STRICT 的 9 个文件 + 包装层 / 测试台 / edit_breadth / R2 登记表 / decisions / kin(= R2 登记表 meta.sha)
    + 快照 stats_v3;冻结后再核对本实验三个文件的 sha。"""
    rd = EB.online_reading()
    bad = [k for k, ok in rd["strict_ok"].items() if not ok]
    got = {k: sha16(ROOT / k) for k in FROZEN_XW}
    bad += [k for k, v in FROZEN_XW.items() if got[k] != v]
    if PX.WRAPPER_SHA16 != FROZEN_XW["exp_repair/press_ext_testbed.py"] or XT.WRAPPER_SHA16 != PX.WRAPPER_SHA16:
        bad.append("wrapper_sha16(模块)")
    reg_meta = json.loads(EB.REG_PATH.read_text(encoding="utf-8"))["meta"]["sha"]["files"]
    kin = {}
    for f, h in reg_meta.items():
        now = sha256_file(EB.OUT / f) if (EB.OUT / f).exists() else None
        kin[f] = now == h
        if now != h:
            bad.append(f"r2:{f}")
    if not str(Path(ST.__file__).resolve()).startswith(str(EB.SNAP.resolve())):
        bad.append("stats_v3 不是快照")
    cs = code_shas()
    frozen_code = None
    if check_frozen_code and CASES.exists():
        reg = CM.read_json_retry(CASES)
        if reg.get("frozen"):
            frozen_code = (reg.get("meta") or {}).get("code_sha") or {}
            bad += [f"code:{k}" for k, v in frozen_code.items() if cs.get(k) != v]
    out = {"ok": not bad, "bad": bad, "online": rd["strict"], "frozen_files": got, "r2_files_ok": kin, "code_sha": cs,
           "frozen_code_sha": frozen_code, "entry_sha16": XT.ENTRY_SHA16, "stats_v3": _rel(ST.__file__)}
    if bad and strict:
        raise SystemExit(f"[XW] G0 不通过:{bad}")
    return out


def _gpu_free_mib(idx: str) -> float | None:
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=20).stdout.strip().splitlines()
        for r in q:
            a, b = [x.strip() for x in r.split(",")]
            if a == str(idx):
                return float(b)
    except Exception:                                                    # noqa: BLE001
        return None
    return None


def device_guard(host: str | None = None, cvd: str | None = "__env__", now: tuple | None = None, free_fn=None) -> dict:
    """远程主机:CUDA_VISIBLE_DEVICES 必须显式设置,物理卡 ⊂ {1,2,3,5,6,7};7 只在 16:30 之后;每张选中的卡空闲 ≥ 8 GB 且
    隔 5 s 两次采样变化 < 2 GB;0 / 4 永不。本机不限制。"""
    host = HOST if host is None else host
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES") if cvd == "__env__" else cvd
    if host == EB.LOCAL_HOST:
        return {"host": host, "cuda_visible_devices": cvd}
    ids = [x.strip() for x in (cvd or "").split(",") if x.strip()]
    if not ids:
        raise SystemExit(f"[XW] 远程主机 {host}:CUDA_VISIBLE_DEVICES 未设置。先 source ~/fcl_setup/env.sh,再 export CUDA_VISIBLE_DEVICES=<1,2,3,5,6,7 中的空闲卡>")
    bad = [x for x in ids if x not in ALLOWED_REMOTE_GPUS]
    if bad:
        raise SystemExit(f"[XW] 远程主机 {host}:CUDA_VISIBLE_DEVICES={cvd} 含白名单 1,2,3,5,6,7 以外的卡 {bad}(0 / 4 永不用)")
    if "7" in ids:
        hm = now or tuple(time.localtime()[3:5])
        if tuple(hm) < GPU7_AFTER:
            raise SystemExit(f"[XW] 物理卡 7 只在 16:30 之后可用(现在 {hm[0]:02d}:{hm[1]:02d})")
    # 每张选中的卡:空闲显存 ≥ 8 GB,且隔几秒的两次采样都满足、占用变化 < 2 GB(近似「显存稳定」;审查 2026-10-26 #5)
    ff = free_fn or _gpu_free_mib
    s1 = {x: ff(x) for x in ids}
    if free_fn is None:
        time.sleep(GPU_STABLE_GAP_S)
    s2 = {x: ff(x) for x in ids}
    for x in ids:
        a, b = s1[x], s2[x]
        if a is None or b is None or min(a, b) < GPU7_MIN_FREE_MIB:
            raise SystemExit(f"[XW] 物理卡 {x} 空闲显存 {a} / {b} MiB < {GPU7_MIN_FREE_MIB}")
        if abs(a - b) >= GPU_STABLE_MIB:
            raise SystemExit(f"[XW] 物理卡 {x} 显存不稳定:{GPU_STABLE_GAP_S} s 内空闲 {a} → {b} MiB")
    return {"host": host, "cuda_visible_devices": cvd, "free_mib": s2}


def write_manifest(devices: list, extra: dict | None = None) -> None:
    f = OUT / f"manifest_{HOST}.json"
    with CM.file_lock(OUT / ".manifest.lock"):
        old = CM.read_json_retry(f) if f.exists() else {"events": []}
        old["events"].append({**EB.gpu_manifest(devices), **(extra or {})})
        CM.atomic_write_json(f, old, indent=1)


INFRA_LOG = {"path": OUT / "infra_events.jsonl"}                        # selftest #10 临时改到它自己的临时目录


def infra_log(ev: dict) -> None:
    p = INFRA_LOG["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    with CM.file_lock(OUT / ".infra.lock"):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_s(), "host": HOST, **ev}, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════ 臂 → 规范化覆盖表(§2.3、§2.6)
def r2_dec() -> dict:
    return EB.load_decisions()


def arm_params(arm: str, cfg=None) -> dict:
    """臂 → {r: r_pref, m: m_b, form: tier | quad | barrier, sigmaA: 容差 → σ, dz: 纯死区}。"""
    if arm == "B3":
        if cfg is None:
            raise ValueError("B3 需要 cfg = (r_pref, m_b, form)")
        r, m, f = cfg
        if (float(r), float(m), f) not in {(float(a), float(b), c) for a, b, c in GRID}:
            raise ValueError(f"B3 配置不在预先登记的网格里: {cfg}")
        return {"r": float(r), "m": float(m), "form": f, "sigmaA": False, "dz": False}
    tab = {"A": (0.1, 1.0, "tier", True, False), "AP": (1.0, 1.0, "tier", True, False), "Adz": (0.1, 1.0, "tier", True, True),
           "B1": (0.1, 1.0, "quad", False, False), "B2": (0.1, 1.0, "barrier", False, False),
           "B1m": (1.0, 1.0, "quad", False, False), "B2m": (1.0, 1.0, "barrier", False, False)}
    if arm not in tab:
        raise ValueError(f"未知臂 {arm}")
    r, m, f, sa, dz = tab[arm]
    return {"r": r, "m": m, "form": f, "sigmaA": sa, "dz": dz}


def a_sigma(eff: dict, dz: bool = False) -> tuple:
    """A 的容差 → σ(R2 §6.3):σ′ = σ0 · tol / tol0。press / ori / elbow 走 ext.sigma_scale(包装层;press 下限 1.0 N);
    关节目标走 xw.sigma(σ0 0.02 rad、tol0 0.05)。dz:A_dz 的倾角 / 手肘 / 关节已换成死区,只缩放 press。"""
    ss, jsig = {}, {}
    for q, sid in SIGMA_ID.items():
        it = eff.get((q, "target"))
        if it is None or (dz and q in ("tilt", "elbow")):
            continue
        s = float(it["tol"]) / float(EB.default_tol(q, it["target"]))
        if abs(s - 1.0) > 1e-12:
            ss[sid] = s
    if not dz:
        for qj in JQ:
            it = eff.get((qj, "target"))
            if it is not None:
                s = float(it["tol"]) / Q_TOL0
                if abs(s - 1.0) > 1e-12:
                    jsig[qj] = r6(Q_SIGMA0 * s)
    return ss, jsig


def canon_xw(xw: dict) -> dict:
    out = {}
    for k in ("pen", "gain", "sigma"):
        if xw.get(k):
            out[k] = {kk: (r6(v) if isinstance(v, float) else v) for kk, v in sorted(xw[k].items())}
    if xw.get("replace"):
        out["replace"] = sorted([{"id": r["id"], "op": r["op"], "tol": r6(r["tol"])} for r in xw["replace"]], key=lambda r: r["id"])
    if xw.get("sum_ids"):
        out["sum_ids"] = sorted(set(xw["sum_ids"]))
    if xw.get("refuse") is False:
        out["refuse"] = False
    if xw.get("ik") == "cost":
        out["ik"] = "cost"
    return out


def arm_cmd(unit: dict, arm: str, cfg=None, seed: int = 0, ik: bool = False, dec: dict | None = None) -> tuple:
    """单元 + 臂 → (测试台 cmd, info)。cmd = EB.compile_spec(契约 + 起点 exec)[+ sigma_scale] + 规范化 xw。"""
    dec = r2_dec() if dec is None else dec
    P = arm_params(arm, cfg)
    reqs = unit["contract"]
    eff, _dups = EB.effective_items(reqs)
    ss, jsig = a_sigma(eff, P["dz"]) if P["sigmaA"] else ({}, {})
    opts = {"mppi_seed": int(seed)} if seed else None
    cmd, info = EB.compile_spec(unit["task"], {"requirements": reqs, "exec": unit["exec"]}, dec, opts=opts, sigma_scale=ss or None)
    ext = cmd.get("ext") or {}
    r, m, form = P["r"], P["m"], P["form"]
    gain, pen, sig, sum_ids, refuse_off, rows = {}, {}, {}, [], False, []
    if ext.get("elbow", True) is not False:
        g, g0_ = 10.0 * XT.TB_ELBOW["weight"] * r, XT.PRIORITY[XT.TB_ELBOW["priority"]] * XT.TB_ELBOW["weight"]
        if abs(g - g0_) > 1e-9:
            gain["elbow"] = r6(g)
        rows.append({"id": "elbow", "pref": True, "chard": False, "gain": r6(g), "pen": "quadratic", "layer": "soft"})
    for b in ext.get("bounds") or []:
        q, tid = b["q"], f"eb_{b['q']}_bound"
        it = eff[(q, "bound")]
        chard = it["strict"] == "hard"
        pref = PX.PRIO[q] == "preference"
        g = 10.0 * PX.WEIGHT[q] * (r if pref else 1.0) * (m if chard else 1.0)
        g0_ = XT.PRIORITY[PX.PRIO[q]] * PX.WEIGHT[q]
        p_, layer = b["penalty"], "soft"
        if chard and b["penalty"] == "hard":
            if form == "tier":
                rows.append({"id": tid, "pref": pref, "chard": True, "gain": None, "pen": "hard", "layer": "hard_tier"})
                continue
            if form == "quad":
                pen[tid], p_ = "quadratic", "quadratic"
            else:
                sum_ids.append(tid)
                layer = "sum_barrier"
                refuse_off |= q == "tilt"                               # ori_cone 是位置类;elbow(link_pos)、force、speed 不会被拒
        if abs(g - g0_) > 1e-9:
            gain[tid] = r6(g)
        rows.append({"id": tid, "pref": pref, "chard": chard, "gain": r6(g), "pen": p_, "layer": layer})
    for jt in ext.get("joints") or []:
        qj, tid = f"q{jt['j']}", f"eb_q{jt['j']}_{jt['mode']}"
        cls = "target" if jt["mode"] == "target" else "bound"
        it = eff[(qj, cls)]
        chard = cls == "bound" and it["strict"] == "hard"
        pref = jt["priority"] == "preference"
        g = 10.0 * float(jt["weight"]) * (r if pref else 1.0) * (m if chard else 1.0)
        g0_ = XT.PRIORITY[jt["priority"]] * float(jt["weight"])
        p_, layer = jt["penalty"], "soft"
        if cls == "target" and qj in jsig:
            sig[tid] = jsig[qj]
        if chard and jt["penalty"] == "hard":
            if form == "tier":
                rows.append({"id": tid, "pref": pref, "chard": True, "gain": None, "pen": "hard", "layer": "hard_tier"})
                continue
            if form == "quad":
                pen[tid], p_ = "quadratic", "quadratic"
            else:
                sum_ids.append(tid)
                layer = "sum_barrier"
                refuse_off = True                                       # 关节 q 是位置类
        if abs(g - g0_) > 1e-9:
            gain[tid] = r6(g)
        rows.append({"id": tid, "pref": pref, "chard": chard, "gain": r6(g), "pen": p_, "layer": layer})
    xw = {"pen": pen, "gain": gain, "sigma": sig, "sum_ids": sum_ids}
    if refuse_off and sum_ids:
        xw["refuse"] = False
    if P["dz"]:
        rep = [{"id": "ori", "op": "ori_dz", "tol": math.radians(float(eff[("tilt", "target")]["tol"]))}]
        if ("elbow", "target") in eff and ext.get("elbow", True) is not False:
            rep.append({"id": "elbow", "op": "target_to_range", "tol": float(eff[("elbow", "target")]["tol"])})
        for jt in ext.get("joints") or []:
            if jt["mode"] == "target":
                rep.append({"id": f"eb_q{jt['j']}_target", "op": "target_to_range", "tol": float(eff[(f"q{jt['j']}", "target")]["tol"])})
        xw["replace"] = rep
    if ik:
        xw["ik"] = "cost"
    xw = canon_xw(xw)
    XT.validate_xw(xw)                                                   # 父进程先按子进程同一规则校验
    if xw:
        cmd["xw"] = xw
    info = dict(info)
    info.update({"arm": arm, "cfg": None if cfg is None else list(cfg), "seed": int(seed), "ik": bool(ik), "rows": rows, "params": P,
                 "sigma_scale": ss})
    return cmd, info


def ckey(task: str, bias: dict | None, cmd: dict) -> str:
    """编译键(不含代码 sha / 主机):判断「按构造相同」与集合不相交。"""
    return json.dumps([task, P3.norm_bias(bias), cmd], sort_keys=True, ensure_ascii=False)


# ═══════════════════════════════════════════ 仿真(缓存 + 子进程)
DEVICES = [os.environ.get("PRESS_DEVICE", "cuda:0")]
_dev_lock, _dev_n = threading.Lock(), [0]
SIM_BUDGET = {"budget": None, "new": 0, "lock": threading.Lock()}
LAUNCH_HOOK = {"fn": None}                                               # selftest #10 / 冒烟 #11:替换子进程命令(不跑真仿真)


def next_device() -> str:
    with _dev_lock:
        d = DEVICES[_dev_n[0] % len(DEVICES)]
        _dev_n[0] += 1
    return d


def sim_key(task: str, bias: dict | None, cmd: dict, salt: dict | None = None, host: str | None = None) -> tuple:
    key = {"v": KEY_V, "entry": XT.ENTRY_SHA16, "wrapper": PX.WRAPPER_SHA16, "testbed": PX.SNAP_SHA16, "code": P3.CODE_VER,
           "sim_args": P3.SIM_ARGS, "robot": EB.TASKS[task]["robot"], "bias": P3.norm_bias(bias), "cmd": cmd, "accept_series": True,
           "host": HOST if host is None else host}
    if salt:
        key["salt"] = salt
    ks = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return ks, hashlib.sha1(ks.encode("utf-8")).hexdigest()[:16]


def sim_dir(task: str, bias: dict | None, cmd: dict, salt: dict | None = None) -> Path:
    return SIMS / f"{task}_{sim_key(task, bias, cmd, salt)[1]}"


def r2_dir_for(task: str, bias: dict | None, cmd: dict) -> Path | None:
    """R2 缓存里同一 cmd 的目录(只算哈希、只检查存在,不写);只给种子 0、空覆盖表、本机。"""
    if "xw" in cmd or cmd.get("mppi_seed") or HOST != EB.LOCAL_HOST:
        return None
    _ks, h = EB.sim_key(task, bias, cmd)
    d = EB.SIMS / f"{task}_{h}"
    return d if (d / "ext_result.json").exists() else None


def load_decisions_xw() -> dict:
    return CM.read_json_retry(DECISIONS) if DECISIONS.exists() else {}


def update_decisions_xw(patch: dict) -> dict:
    with CM.file_lock(OUT / ".decisions.lock"):
        d = load_decisions_xw()
        if d.get("frozen"):
            raise SystemExit("decisions_xw.json 已冻结,不能再改")
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k] = {**d[k], **v}
            else:
                d[k] = v
        d["updated_at"] = now_s()
        CM.atomic_write_json(DECISIONS, d, indent=1)
    return d


def r2_reuse_ok() -> bool:
    g = (load_decisions_xw().get("gates") or {}).get("r2_bitid") or {}
    return bool(g.get("ok")) and g.get("host") == HOST and g.get("entry_sha16") == XT.ENTRY_SHA16   # 入口改过就要重做冒烟 #2


def is_infra_failure(d: Path) -> bool:
    return EB.is_infra_failure(d)


def load_xw(d: Path) -> dict:
    """读本实验的仿真目录。完成 = xw_result.json;失败分框架错误 / 基础设施 / 情形失败;只有 ext_result.json → Incomplete。"""
    d = Path(d)
    if (d / "xw_result.json").exists():
        r = EB.load_sim(d)
        r["xw_result"] = CM.read_json_retry(d / "xw_result.json")
        r["src"] = "xw"
        # sim._start_window 把 _install 里的任何异常记成「求值失败」并不采用该窗口;在本实验的目录里这只可能是入口 / 补丁的错误
        # (R2 的 1367 个目录里 0 次),不能当成情形结果记到某一臂头上(审查 2026-10-26 #4)
        bad = [(nm, w.get("reason")) for nm, w in ((r.get("ext_result") or {}).get("windows") or {}).items()
               if str(w.get("reason") or "").startswith("求值失败")]
        if bad:
            raise FrameworkError(f"{_rel(d)}: 窗口求值失败(入口 / 补丁错误,不是情形结果):{bad[:3]}")
        return r
    if (d / "failed.json").exists():
        fj = CM.read_json_retry(d / "failed.json")
        tail = "\n".join(fj.get("tail") or [])
        if FRAMEWORK_RE.search(tail):
            raise FrameworkError(f"{_rel(d)}: 框架 / 入口编译错误(不是情形结果):{tail[-400:]}")
        if is_infra_failure(d):
            raise InfraError(f"{_rel(d)}: 基础设施失败(OOM / CUDA / 被杀 / 超时)")
        return {"dir": _rel(d), "ok": False, "failed": True, "refused": False, "series": None, "ext_result": None, "fail_tail": fj.get("tail"),
                "src": "xw"}
    raise Incomplete(f"{_rel(d)}: 没有完成标记 xw_result.json")


def load_r2(d: Path) -> dict:
    r = EB.load_sim(d)
    r["src"] = "r2"
    return r


def run_sim(task: str, bias: dict | None, cmd: dict, salt: dict | None = None, readonly: bool = False, allow_r2: bool = True) -> dict:
    """跑(或读缓存)一次 xw 入口仿真;门 r2_bitid 通过时空覆盖表、种子 0 的 A 直接只读 R2 目录。"""
    if allow_r2 and not salt and r2_reuse_ok():
        d2 = r2_dir_for(task, bias, cmd)
        if d2 is not None:
            return load_r2(d2)
    ks, h = sim_key(task, bias, cmd, salt)
    d = SIMS / f"{task}_{h}"
    nb = P3.norm_bias(bias)

    def launch():
        with SIM_BUDGET["lock"]:
            if SIM_BUDGET["budget"] is not None and SIM_BUDGET["new"] >= SIM_BUDGET["budget"]:
                raise SimBudgetExceeded(f"新仿真预算 {SIM_BUDGET['budget']} 已用完(要跑 {_rel(d)})")
            SIM_BUDGET["new"] += 1
        for nm in ("ext_result.json", "xw_result.json"):                 # 上一次没写完的残留
            if (d / nm).exists():
                (d / nm).replace(d / (nm + ".stale"))
        CM.atomic_write_text(d / "cmd.json", json.dumps(cmd, ensure_ascii=False))
        CM.atomic_write_text(d / "key.json", ks)
        c = [PY, str(ENTRY), "run", "--robot", EB.TASKS[task]["robot"], "--device", next_device(), "--cmd", str(d / "cmd.json"), "--out", str(d),
             *P3.SIM_ARGS, *EB.bias_args(nb), "--accept-series"]
        if LAUNCH_HOOK["fn"] is not None:
            c = LAUNCH_HOOK["fn"](c, d)
        rc = None
        t0 = time.time()
        try:
            with open(d / "sim.log", "w", encoding="utf-8") as lf:
                rc = subprocess.run(c, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, env={**os.environ, "MUJOCO_GL": "egl"},
                                    timeout=TIMEOUT_S if LAUNCH_HOOK.get("timeout") is None else LAUNCH_HOOK["timeout"]).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        if not (d / "xw_result.json").exists():
            tail = (d / "sim.log").read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if (d / "sim.log").exists() else []
            CM.atomic_write_json(d / "failed.json", {"returncode": rc, "tail": tail, "argv": c[1:], "wall_s": time.time() - t0}, indent=1)

    def retire_infra():
        (d / "failed.json").replace(d / "failed.infra.json")
        if (d / "sim.log").exists():
            (d / "sim.log").replace(d / "sim.log.try1")

    with CM.sim_lock(d):
        done = (d / "xw_result.json").exists()
        failed = (d / "failed.json").exists() and not done
        if failed and is_infra_failure(d):
            if (d / "failed.infra.json").exists():
                infra_log({"dir": _rel(d), "event": "infra_fail_cached"})
                raise InfraError(f"{_rel(d)}:缓存里是重试过的基础设施失败")
            retire_infra()
            failed = False
        if not done and not failed:
            if readonly:
                raise Incomplete(f"只读模式下缺仿真缓存:{_rel(d)}")
            launch()
            if not (d / "xw_result.json").exists() and is_infra_failure(d):
                if (d / "failed.infra.json").exists():
                    infra_log({"dir": _rel(d), "event": "infra_fail"})
                    raise InfraError(f"{_rel(d)}:重跑 1 次后仍是基础设施失败")
                retire_infra()
                infra_log({"dir": _rel(d), "event": "infra_retry"})
                launch()
                if not (d / "xw_result.json").exists() and is_infra_failure(d):
                    infra_log({"dir": _rel(d), "event": "infra_fail"})
                    raise InfraError(f"{_rel(d)}:重跑 1 次后仍是基础设施失败")
    return load_xw(d)


def peek_sim(task: str, bias: dict | None, cmd: dict, salt: dict | None = None) -> dict | None:
    """只读查缓存:有结果返回,缺 / 未完成返回 None(分析与 status 用;不加锁、不写)。"""
    if not salt and r2_reuse_ok():
        d2 = r2_dir_for(task, bias, cmd)
        if d2 is not None:
            return load_r2(d2)
    d = sim_dir(task, bias, cmd, salt)
    if not d.exists():
        return None
    try:
        return load_xw(d)
    except Incomplete:
        return None


# ═══════════════════════════════════════════ 指标(§6;decide 与分析共用)
def hard_items(reqs: dict) -> list:
    return [(rid, it) for rid, it in sorted(reqs.items()) if it["kind"] != "target" and it.get("strict") == "hard"]


def validity(r: dict | None) -> dict:
    """执行有效性(§6):5 个阶段全部采用、有逐样本序列、|end_y_err| ≤ 5 mm、没有 ik_failed;拒收单列。"""
    if r is None:
        return {"present": False, "valid": False, "refused": False, "why": "missing"}
    if not r.get("ok"):
        return {"present": True, "valid": False, "refused": False, "why": "failed"}
    if r.get("refused"):
        return {"present": True, "valid": False, "refused": True, "why": "refused"}
    J = r.get("ext_result") or {}
    why = None
    if not J.get("all_phases_accepted"):
        why = "phase_not_accepted"
    elif r.get("series") is None:
        why = "no_series"
    elif J.get("end_y_err_mm") is None or abs(float(J["end_y_err_mm"])) > INVALID_END_Y_MM:
        why = "end_y_err"
    elif r.get("ik_failed"):
        why = "ik_failed"
    return {"present": True, "valid": why is None, "refused": False, "why": why}


def unit_metrics(unit: dict, r: dict | None, dec: dict | None = None) -> dict:
    """一次仿真按原契约逐维验收 → §6 的全部指标。v:硬界违反量(Δ 归一,截 [0,3]);m:任务维最差余量(截 [−3,1]);
    cal:校准分(计分项的最小归一化余量,截 [−3,1];H / N 类计全部项,C 类计 task 档 target 项)。确认性端点 v_conf / m_conf:
    无效执行与拒收记最差(v 3、m −3)。"""
    dec = r2_dec() if dec is None else dec
    reqs = unit["contract"]
    V = validity(r)
    S = None if r is None else r.get("series")
    ev = EB.evaluate(reqs, S, unit["robot"], dec.get("extreme", "raw")) if (r is not None and r.get("ok") and S is not None) else None
    # 全部达标 / 按优先级满足 = 只按原契约(与 R2 labels 同口径,拒收不算达标);执行有效性单列,「安全且有用」= 有效且全部达标
    out = {"validity": V, "all_pass": bool(ev) and EB.all_ok(ev) and not V["refused"], "eval": None if ev is None else EB.compact_eval(ev)}
    hard = hard_items(reqs)
    v = None
    hard_ok = None
    if ev is not None and hard:
        vs, oks = [], []
        for rid, it in hard:
            e = ev[rid]
            worst = 0.0
            for side, sd in (e.get("sides") or {}).items():
                if sd.get("margin") is None:
                    worst = 3.0
                else:
                    worst = max(worst, max(0.0, -float(sd["margin"])) / DELTA[it["quantity"]])
            vs.append(min(3.0, worst))
            oks.append(bool(e["ok"]))
        v, hard_ok = max(vs), all(oks)
    tm = []
    task_ok = []
    if ev is not None:
        for rid, it in sorted(reqs.items()):
            if it["kind"] == "target" and it["quantity"] in TASK_DIMS:
                e = ev[rid]
                mg = e.get("margin")
                tm.append(-3.0 if mg is None else max(-3.0, min(1.0, float(mg) / float(it["tol"]))))
                task_ok.append(bool(e["ok"]))
    m = min(tm) if tm else None
    cls = unit.get("b3_class") or b3_class(reqs)
    cal = None
    if ev is not None:
        sc = []
        for rid, it in sorted(reqs.items()):
            e = ev[rid]
            if cls == "C" and not (it["kind"] == "target" and it["quantity"] in TASK_DIMS):
                continue
            if it["kind"] == "target":
                mg = e.get("margin")
                sc.append(-3.0 if mg is None else float(mg) / float(it["tol"]))
            else:
                for side, sd in (e.get("sides") or {}).items():
                    sc.append(-3.0 if sd.get("margin") is None else float(sd["margin"]) / DELTA[it["quantity"]])
        cal = max(-3.0, min(1.0, min(sc))) if sc else None
    if not V["valid"]:
        cal = -3.0
    if V["refused"]:
        o3 = "refused"
    elif not V["valid"]:
        o3 = "invalid"
    elif hard and hard_ok is False:
        o3 = "exec_violate"
    else:
        o3 = "exec_ok"
    out.update({"v": v, "hard_ok": hard_ok, "m": m, "task_ok": task_ok, "task_kept": (sum(task_ok) / len(task_ok)) if task_ok else None,
                "prio_sat": bool((not V["refused"]) and (hard_ok is not False) and all(task_ok)) if ev is not None else False,
                "cal": cal, "outcome3": o3, "safe_useful": bool(V["valid"] and out["all_pass"]),
                "v_conf": (3.0 if not V["valid"] else v) if hard else None, "m_conf": -3.0 if not V["valid"] else m,
                "boundary": None if ev is None else any(bool(x.get("boundary")) for x in ev.values())})
    return out


def b3_class(reqs: dict) -> str:
    """§4.3 只从契约结构读出类别:有契约 hard 项 → H;否则有位形项(关节项、soft 手肘界)→ C;否则 N。"""
    if hard_items(reqs):
        return "H"
    for it in reqs.values():
        if it["quantity"] in JQ or (it["quantity"] == "elbow" and it["kind"] != "target"):
            return "C"
    return "N"


# ═══════════════════════════════════════════ 情形生成(§3、§4.1)
def r2_registry() -> dict:
    return EB.load_registry(EB.REG_PATH, need_frozen=True)


def r2_cases(reg: dict) -> list:
    return [c for c in reg["cases"] if c.get("labels") and "discard" not in c["labels"] and c["labels"].get("category")]


def _ukey(c: dict) -> str:
    return json.dumps([c["task"], c["gt"]["spec"]["requirements"], c["start"]["exec"], c["start"].get("bias", {})], sort_keys=True)


def s0_info(reg: dict) -> dict:
    """各任务 S0 起点:统计量(R2 labels.start_stats,= 起点仿真 on / mid 窗口统计)与起点仿真目录。"""
    out = {}
    for c in r2_cases(reg):
        if c["start_type"] == "S0" and c["task"] not in out:
            out[c["task"]] = {"stats": c["labels"]["start_stats"], "dir": c["start"]["stats_source"]}
    return out


def base_unit(task: str, contract: dict, exec_: dict | None = None, bias: dict | None = None) -> dict:
    return {"task": task, "robot": EB.TASKS[task]["robot"], "contract": copy.deepcopy(contract), "exec": dict(exec_ or EB.zero_exec()),
            "bias": dict(bias or {})}


def s0_contract(task: str) -> dict:
    return EB.base_spec(task)["requirements"]


def _r2_unit(L: list, cls: str, sub: str, extra: dict | None = None) -> dict:
    c = L[0]
    u = base_unit(c["task"], c["gt"]["spec"]["requirements"], c["start"]["exec"], c["start"].get("bias") or {})
    po = c["labels"]["program_once"]
    u.update({"uid": f"{cls}|{c['id']}", "cls": cls, "sub": sub, "variant": c["variant"], "family": c["family"],
              "cluster": f"{c['task']}|{c['family']}-{c['variant']}", "r2_cases": sorted(x["id"] for x in L), "r2_po_sim": po["sim"],
              "r2_po_eval": po["eval"], "r2_po_ok": bool(po["ok"]), "start_type": c["start_type"], "start_source": c["start"]["stats_source"],
              "start_stats": c["labels"]["start_stats"], "notes": c["edit"].get("notes") or {}})
    u["b3_class"] = b3_class(u["contract"])
    if extra:
        u.update(extra)
    return u


def binding_of(u: dict) -> dict:
    """§1.6:界不比 A 自己无界起点的 on 窗口统计量更紧 = 松界;否则绑定(speed 下界看 mid 窗口)。"""
    (rid, it), = hard_items(u["contract"])
    q = it["quantity"]
    st = u["start_stats"][q]
    w = st["mid"] if (q == "speed" and it["kind"] == "lower") else st["on"]
    lo, hi = it.get("lower"), it.get("upper")
    b_hi = hi is not None and hi < w["max"]
    b_lo = lo is not None and lo > w["min"]
    return {"hard_id": rid, "quantity": q, "kind": it["kind"], "binding": bool(b_hi or b_lo), "smin": w["min"], "smax": w["max"]}


def gen_r2_units(reg: dict) -> dict:
    cs = r2_cases(reg)
    s0 = s0_info(reg)
    out = {"N": [], "HR2": [], "CA": []}
    for task in EB.ALL_TASKS:                                            # N:各任务 S0 契约(R2 起点仿真)
        u = base_unit(task, s0_contract(task))
        u.update({"uid": f"N|{task}|S0", "cls": "N", "sub": "S0", "variant": "S0", "family": "S0", "cluster": f"{task}|S0", "r2_cases": [],
                  "r2_po_sim": s0[task]["dir"], "r2_po_eval": None, "r2_po_ok": None, "start_type": "S0", "start_source": s0[task]["dir"],
                  "start_stats": s0[task]["stats"], "notes": {}, "b3_class": "N"})
        out["N"].append(u)
    groups: dict = {}
    for c in cs:
        groups.setdefault(_ukey(c), []).append(c)
    for k, L in sorted(groups.items(), key=lambda kv: kv[1][0]["id"]):
        c = L[0]
        fam, var = c["family"], c["variant"]
        if fam == "B0":
            out["N"].append(_r2_unit(L, "N", "B0"))
        elif fam in ("H1", "H1-rep", "H2", "J2"):
            u = _r2_unit(L, "HR2", "")
            bi = binding_of(u)
            u["sub"] = bi["quantity"] if bi["quantity"] in ("force", "speed", "tilt", "elbow") else "q"
            u.update(bi)
            out["HR2"].append(u)
        elif (fam, var) in (("J1", "conflict"), ("J3", "offA"), ("J3", "offB")):
            u = _r2_unit(L, "CA", f"{fam}-{var}", {"confirm": True})
            out["CA"].append(u)
    return out


def tilt_series_start(reg: dict, task: str) -> float:
    """S0 起点仿真在滑动段(track)开始时刻的倾角(°;on 窗口第一个样本)。"""
    d = ROOT / s0_info(reg)[task]["dir"]
    S = EB.load_series(d)
    return float(S["tilt"][S["on"]][0])


def gen_hstar(reg: dict, r2_keys: set, dec: dict) -> tuple:
    """H*:每任务 S0 起点仿真倾角 on 窗口 min / max;上限 ub = round_0.1(max − δ),下限 lb = round_0.1(min + δ),δ ∈ {0.25, 0.5, 0.75}。
    G3(a):契约可行(|界 − 目标| ≤ 1.5°)、track 开始时倾角离界 < 3σ(预计不拒收)、同 (任务, 方向) 内取整后各界互不相同、与 R2 编译键不相交。"""
    s0 = s0_info(reg)
    units, drops = [], []
    for task in EB.ALL_TASKS:
        st = s0[task]["stats"]["tilt"]["on"]
        tg = EB.targets_of(task)["tilt"]
        x0 = tilt_series_start(reg, task)
        for side in ("upper", "lower"):
            seen = set()
            for dl in HS_DELTAS:
                b = EB.round_step(st["max"] - dl, 0.1) if side == "upper" else EB.round_step(st["min"] + dl, 0.1)
                item = {"quantity": "tilt", "kind": side, side: b, "strict": "hard"}
                contract = {**copy.deepcopy(s0_contract(task)), "tilt_hard": item}
                u = base_unit(task, contract)
                u.update({"uid": f"HS|{task}|{side}|{dl:g}", "cls": "HS", "sub": f"tilt_{side}", "variant": f"tilt_{side}", "family": "HS",
                          "cluster": f"{task}|tilt_{side}", "confirm": True, "b3_class": "H", "start_source": s0[task]["dir"],
                          "start_stats": s0[task]["stats"], "meta": {"delta": dl, "bound": b, "smin": st["min"], "smax": st["max"], "x0_track": x0}})
                viol0 = (x0 - b) if side == "upper" else (b - x0)                      # >0:track 开始时已在界外(°)
                z0 = max(0.0, viol0) * math.pi / 180.0 / HS_SIGMA_RAD
                cmdA, _ = arm_cmd(u, "A", dec=dec)
                k = ckey(task, u["bias"], cmdA)
                chk = {"feasible": abs(b - tg) <= HS_FEAS + 1e-9, "z_start": z0, "no_refuse": z0 < 3.0, "distinct": b not in seen,
                       "disjoint_r2": k not in r2_keys, "binding_A": (b < st["max"]) if side == "upper" else (b > st["min"])}
                u["g3"] = chk
                seen.add(b)
                if all(chk[x] for x in ("feasible", "no_refuse", "distinct", "disjoint_r2", "binding_A")):
                    units.append(u)
                else:
                    drops.append({"uid": u["uid"], "g3": chk, "bound": b})
    return units, drops


def gen_r(reg: dict, dec: dict) -> tuple:
    """R 拒收演示:iiwa_a / iiwa_b 的 q4 由尖端位姿锁定;契约 = S0 + hard q4 范围 [U + g, U + g + 0.10],U = E_exec 逐点上界的最大值。
    G3(c):settle 起点(S0 on 窗口 q4 max)离下界 > 3σ(σ 0.02 rad),预计 A 拒收。"""
    s0 = s0_info(reg)
    units, drops = [], []
    for task in ("iiwa_a", "iiwa_b"):
        kin = EB.kin_env(task)
        U = max(kin["exec"]["per_point"][p]["q4"][1] for p in kin["exec"]["per_point"])
        Uk = max(kin["kin"]["per_point"][p]["q4"][1] for p in kin["kin"]["per_point"])
        q4max = s0[task]["stats"]["q4"]["on"]["max"]
        for g in R_GAPS:
            lo, hi = EB.rq("q4", U + g), EB.rq("q4", U + g + 0.10)
            contract = {**copy.deepcopy(s0_contract(task)), "q4_range": {"quantity": "q4", "kind": "range", "lower": lo, "upper": hi, "strict": "hard"}}
            u = base_unit(task, contract)
            z = (lo - q4max) / PX.SIGMA["q"]
            u.update({"uid": f"R|{task}|g{g:g}", "cls": "R", "sub": "q4", "variant": "q4_refuse", "family": "R", "cluster": f"{task}|R",
                      "b3_class": "H", "start_source": s0[task]["dir"], "start_stats": s0[task]["stats"],
                      "meta": {"U_exec": U, "U_kin": Uk, "g": g, "q4_on_max": q4max}, "g3": {"z_settle": z, "refuse_expected": z > 3.0}})
            (units if z > 3.0 else drops).append(u)
    return units, drops


def gen_tconf(reg: dict, dec: dict) -> tuple:
    """T-conf(§3.6):q1 目标与手肘目标同为 preference,q1 ≈ q1⁰ + s·Δe(s = kin 的 slope_q1_per_elbow)。
    te_s 0.015 / te_L 0.04 / tq_s 0.03 / tq_L = tq_s + s(te_L − te_s);b0 = tq_s + s·te_s,b1 = tq_s + s·te_L;Δq ∈ b0 + {¼,½,¾}(b1 − b0);
    q1 目标 = 起点 q1 均值 ∓ Δq(方向取 E_exec 并集余量大的一侧);包络规则 = 并集(离边界 ≥ 0.02 rad),逐点规则只作敏感性标记。
    每个 Δq 两套容差:(i) 手肘紧 te_s、q1 宽 tq_L;(ii) 手肘宽 te_L、q1 紧 tq_s。"""
    s0 = s0_info(reg)
    units, pairs, drops = [], [], []
    for task in EB.ALL_TASKS:
        kin = EB.kin_env(task)
        s = float(kin["exec"]["slope_q1_per_elbow"])
        ulo, uhi = kin["exec"]["union"]["q1"]
        pp = kin["exec"]["per_point"]
        plo, phi = max(pp[p]["q1"][0] for p in pp), min(pp[p]["q1"][1] for p in pp)
        mean = float(s0[task]["stats"]["q1"]["on"]["mean"])
        side = 1.0 if (uhi - mean) >= (mean - ulo) else -1.0
        te_s, te_L, tq_s = TC["te_s"], TC["te_L"], TC["tq_s"]
        tq_L = tq_s + s * (te_L - te_s)
        b0, b1 = tq_s + s * te_s, tq_s + s * te_L
        tg = EB.targets_of(task)
        for k, fr in enumerate(TC["fracs"]):
            dq = b0 + fr * (b1 - b0)
            q1t = EB.rq("q1", mean + side * dq)
            ok_u = (ulo + TC["margin"]) <= q1t <= (uhi - TC["margin"])
            ok_p = (plo + TC["margin"]) <= q1t <= (phi - TC["margin"])
            pid = f"{task}|{k}"
            meta = {"s": s, "dq": dq, "b0": b0, "b1": b1, "tq_L": tq_L, "q1_mean0": mean, "side": side, "q1_target": q1t, "union": [ulo, uhi],
                    "per_point_ok": ok_p, "union_ok": ok_u}
            if not ok_u:
                drops.append({"pair": pid, **meta})
                continue
            pairs.append({"pair": pid, "task": task, **meta})
            for setn, (te, tq) in (("i", (te_s, tq_L)), ("ii", (te_L, tq_s))):
                contract = copy.deepcopy(s0_contract(task))
                contract["elbow"]["tol"] = round(te, 6)
                contract["q1"] = {"quantity": "q1", "kind": "target", "target": q1t, "tol": round(tq, 6)}
                u = base_unit(task, contract)
                u.update({"uid": f"TC|{pid}|{setn}", "cls": "TC", "sub": setn, "variant": "tconf", "family": "TC", "cluster": f"{task}|TC",
                          "pair": pid, "set": setn, "b3_class": b3_class(contract), "start_source": s0[task]["dir"],
                          "start_stats": s0[task]["stats"], "meta": {**meta, "te": te, "tq": tq, "elbow_target": tg["elbow"]}})
                units.append(u)
    return units, pairs, drops


def gen_ttight(reg: dict) -> list:
    """T-tight(§3.6):起点偏差高于噪声地板(4·SD_rep)的维收紧容差;方案原文列出的 7 个单元。"""
    s0 = s0_info(reg)
    out = []
    for task, q, tol in TT_LIST:
        contract = copy.deepcopy(s0_contract(task))
        contract[q]["tol"] = tol
        u = base_unit(task, contract)
        u.update({"uid": f"TT|{task}|{q}|{tol:g}", "cls": "TT", "sub": q, "variant": f"tight_{q}", "family": "TT", "cluster": f"{task}|TT",
                  "b3_class": "N", "start_source": s0[task]["dir"], "start_stats": s0[task]["stats"], "meta": {"tol": tol}})
        out.append(u)
    return out


def gen_fv(reg: dict) -> list:
    """FV:每任务 V = 40 mm/s(容差 ±20%),力容差收紧到默认的 0.5 倍(探索力 vs 速度能否经规划器折中)。"""
    s0 = s0_info(reg)
    out = []
    for task in EB.ALL_TASKS:
        contract = copy.deepcopy(s0_contract(task))
        contract["speed"] = {"quantity": "speed", "kind": "target", "target": FV_SPEED, "tol": round(EB.default_tol("speed", FV_SPEED), 6)}
        contract["force"]["tol"] = round(FV_FORCE_TOL_MULT * EB.default_tol("force", contract["force"]["target"]), 6)
        u = base_unit(task, contract)
        u.update({"uid": f"FV|{task}", "cls": "FV", "sub": "fv", "variant": "fv", "family": "FV", "cluster": f"{task}|FV", "b3_class": "N",
                  "start_source": s0[task]["dir"], "start_stats": s0[task]["stats"], "meta": {}})
        out.append(u)
    return out


def r2_all_keys(reg: dict, dec: dict) -> set:
    """R2 全部已标注情形 gt 契约(+ 起点 exec / 偏差)的 A 编译键,以及 6 个 S0 起点的键。"""
    ks = set()
    for c in r2_cases(reg):
        u = base_unit(c["task"], c["gt"]["spec"]["requirements"], c["start"]["exec"], c["start"].get("bias") or {})
        try:
            cmd, _ = arm_cmd(u, "A", dec=dec)
        except EB.SpecInvalid:
            continue
        ks.add(ckey(u["task"], u["bias"], cmd))
    for task in EB.ALL_TASKS:
        u = base_unit(task, s0_contract(task))
        cmd, _ = arm_cmd(u, "A", dec=dec)
        ks.add(ckey(task, {}, cmd))
    return ks


def sens_subset(units: list) -> dict:
    """§4.4 灵敏度测试子集:H* 每簇 1 个(δ = 0.5,缺则取该簇第一个);N 的 6 个 S0;C-a 每任务第一个(6 个)。"""
    hs = {}
    for u in sorted([u for u in units if u["cls"] == "HS"], key=lambda u: (u["cluster"], abs(u["meta"]["delta"] - 0.5), u["uid"])):
        hs.setdefault(u["cluster"], u["uid"])
    n = [u["uid"] for u in units if u["cls"] == "N" and u["sub"] == "S0"]
    ca = {}
    for u in sorted([u for u in units if u["cls"] == "CA"], key=lambda u: u["uid"]):
        ca.setdefault(u["task"], u["uid"])
    return {"HS": sorted(hs.values()), "N": sorted(n), "CA": sorted(ca.values())}


def build_test(write: bool = True) -> dict:
    """测试集登记表(确定性;只读 R2)。G3 结果与丢弃写进 meta.g3。"""
    reg = r2_registry()
    dec = r2_dec()
    r2u = gen_r2_units(reg)
    r2k = r2_all_keys(reg, dec)
    hs, hs_drop = gen_hstar(reg, r2k, dec)
    rr, r_drop = gen_r(reg, dec)
    tc, tc_pairs, tc_drop = gen_tconf(reg, dec)
    tt, fv = gen_ttight(reg), gen_fv(reg)
    units = r2u["N"] + hs + r2u["HR2"] + r2u["CA"] + rr + tc + tt + fv
    uids = [u["uid"] for u in units]
    if len(set(uids)) != len(uids):
        raise RuntimeError("测试单元 uid 重复")
    n_cl = len({u["cluster"] for u in hs})
    g3 = {"HS": {"n": len(hs), "dropped": hs_drop, "n_clusters": n_cl, "stop": n_cl < 10}, "R": {"n": len(rr), "dropped": [u["uid"] for u in r_drop]},
          "TC": {"n_pairs": len(tc_pairs), "n_pairs_per_point": sum(1 for p in tc_pairs if p["per_point_ok"]), "dropped": tc_drop,
                 "pairs_by_task": {t: sum(1 for p in tc_pairs if p["task"] == t) for t in EB.ALL_TASKS}}}
    out = {"version": REG_VERSION, "part": "test", "created": now_s(), "units": units, "tc_pairs": tc_pairs, "sens": sens_subset(units),
           "g3": g3, "counts": {c: sum(1 for u in units if u["cls"] == c) for c in ("N", "HS", "HR2", "CA", "R", "TC", "TT", "FV")},
           "hr2_binding": {f"{s}|{b}": sum(1 for u in r2u["HR2"] if u["sub"] == s and u["binding"] == b)
                           for s in ("force", "speed", "tilt", "elbow", "q") for b in (True, False)},
           "sources": {"r2_registry_sha256": reg["_sha256"], "r2_meta_sha": reg["meta"]["sha"], "decisions_sha16": sha16(EB.DECISIONS)}}
    if write:
        save_part("test", out)
    return out


# ───────────────────────────────────────── 校准集(§4.1)
def _cal_unit(task: str, contract: dict, name: str, cal_class: str, meta: dict) -> dict:
    u = base_unit(task, contract)
    u.update({"uid": f"CAL|{name}", "cls": "CAL", "sub": cal_class, "variant": name.split("|")[0], "family": "CAL", "cluster": f"{task}|CAL",
              "b3_class": cal_class, "meta": meta})
    if b3_class(contract) != cal_class:
        raise RuntimeError(f"校准单元 {name} 的结构类别 {b3_class(contract)} ≠ 设计类别 {cal_class}")
    return u


def build_cal(test_keys: set | None = None, write: bool = True) -> dict:
    """校准集 19 个(盐 xw-cal,与测试集编译键不相交;取整后撞键时按方案规则调整)。"""
    reg = r2_registry()
    dec = r2_dec()
    s0 = s0_info(reg)
    if test_keys is None:
        tp = load_part("test")
        if tp is None:
            raise SystemExit("先 build-test(校准集要与测试集编译键不相交)")
        test_keys = test_key_set(tp["units"], dec)
    b0_vals = {}
    for c in r2_cases(reg):
        if c["family"] == "B0":
            b0_vals.setdefault((c["task"], c["variant"]), set()).add(round(float(c["gt"]["spec"]["requirements"][c["variant"]]["target"]), 6))
    units = []

    def keyA(u):
        cmd, _ = arm_cmd(u, "A", dec=dec)
        return ckey(u["task"], u["bias"], cmd)

    for task in CAL_N_TASKS:                                             # N 4:按 B0 规则重抽倾角或手肘目标
        rng = CM.seeded_rng(CAL_SALT, "N", task)
        dim = "tilt" if rng.random() < 0.5 else "elbow"
        for att in range(20):
            p = P3.edit_draw(task, dim, "absolute", "standard")(CM.seeded_rng(CAL_SALT, "N", task, dim, att), 0)
            v = round(float(p["new_value"]), 6)
            if v in b0_vals.get((task, dim), set()):
                continue
            contract = copy.deepcopy(s0_contract(task))
            contract[dim]["target"] = v
            u = _cal_unit(task, contract, f"N|{task}|{dim}", "N", {"dim": dim, "value": v, "attempt": att})
            if keyA(u) not in test_keys:
                units.append(u)
                break
        else:
            raise RuntimeError(f"校准 N {task}:20 次都撞键")
    for task, side, dl in CAL_HS:                                        # H 6:倾角单侧硬界 δ ∈ {0.4, 0.6}
        st = s0[task]["stats"]["tilt"]["on"]
        for k in range(10):
            d = round(dl - 0.05 * k, 6)
            b = EB.round_step(st["max"] - d, 0.1) if side == "upper" else EB.round_step(st["min"] + d, 0.1)
            contract = {**copy.deepcopy(s0_contract(task)), "tilt_hard": {"quantity": "tilt", "kind": side, side: b, "strict": "hard"}}
            u = _cal_unit(task, contract, f"HS|{task}|{side}|{d:g}", "H", {"delta": d, "delta_design": dl, "bound": b})
            if keyA(u) not in test_keys:
                units.append(u)
                break
        else:
            raise RuntimeError(f"校准 H* {task}:撞键无法避开")
    st = s0["xarm_b"]["stats"]["force"]["on"]                            # 力上限 −0.75 N(xarm_b)
    fb = EB.round_step(st["max"] - 0.75, 0.1)
    contract = {**copy.deepcopy(s0_contract("xarm_b")), "force_hard": {"quantity": "force", "kind": "upper", "upper": fb, "strict": "hard"}}
    units.append(_cal_unit("xarm_b", contract, "H|xarm_b|force_upper", "H", {"offset": -0.75, "M": st["max"], "bound": fb}))
    st = s0["fr3_b"]["stats"]["elbow"]["on"]                             # 手肘下限 +0.02 m(fr3_b)
    eb_ = round(st["min"] + 0.02, 3)
    contract = {**copy.deepcopy(s0_contract("fr3_b")), "elbow_hard": {"quantity": "elbow", "kind": "lower", "lower": eb_, "strict": "hard"}}
    units.append(_cal_unit("fr3_b", contract, "H|fr3_b|elbow_lower", "H", {"offset": 0.02, "min": st["min"], "bound": eb_}))
    kin = EB.kin_env("iiwa_b")                                           # hard q1 收紧型区间(iiwa_b,R2 tighten_interval 规则)
    for att in range(20):
        rng = CM.seeded_rng(CAL_SALT, "H", "q1_tighten", "iiwa_b", att)
        iv = EB.tighten_interval(s0["iiwa_b"]["stats"], kin, rng.random(), rng.random())
        if not iv["feasible"]:
            continue
        lo, hi = round(iv["lo"], 2), round(iv["hi"], 2)
        contract = {**copy.deepcopy(s0_contract("iiwa_b")), "q1_range": {"quantity": "q1", "kind": "range", "lower": lo, "upper": hi, "strict": "hard"}}
        u = _cal_unit("iiwa_b", contract, "H|iiwa_b|q1_tighten", "H", {"tighten": {k: iv.get(k) for k in ("side", "a", "w", "rule")}, "attempt": att})
        if keyA(u) not in test_keys:
            units.append(u)
            break
    else:
        raise RuntimeError("校准 q1 收紧:20 次都不可行或撞键")
    for task in CAL_C_TASKS:                                             # C 3:J1 冲突型 soft q1 范围,离 E_kin 0.08 rad
        kin = EB.kin_env(task)
        k_env = kin["kin"]["union"]["q1"]
        side0 = 1.0 if CM.seeded_rng(CAL_SALT, "C", "J1", task).random() < 0.5 else -1.0
        done = False
        for side in (side0, -side0):
            for k in range(5):
                gap = 0.08 + 0.01 * k
                lo, hi = (k_env[1] + gap, k_env[1] + gap + 0.06) if side > 0 else (k_env[0] - gap - 0.06, k_env[0] - gap)
                lo, hi = round(lo, 2), round(hi, 2)
                contract = {**copy.deepcopy(s0_contract(task)), "q1_range": {"quantity": "q1", "kind": "range", "lower": lo, "upper": hi, "strict": "soft"}}
                u = _cal_unit(task, contract, f"C|{task}|J1", "C", {"side": side, "gap": gap, "E_kin_q1": k_env})
                if keyA(u) not in test_keys:
                    units.append(u)
                    done = True
                    break
            if done:
                break
        if not done:
            raise RuntimeError(f"校准 J1 {task}:撞键无法避开")
    for task in CAL_C_TASKS:                                             # C 3:J3 offA 型 q4 目标(起点 q4 均值 ± 0.15)
        on = s0[task]["stats"]["q4"]["on"]
        side = 1.0 if CM.seeded_rng(CAL_SALT, "C", "J3", task).random() < 0.5 else -1.0
        v = round(on["mean"] + side * 0.15, 2)
        contract = {**copy.deepcopy(s0_contract(task)), "q4": {"quantity": "q4", "kind": "target", "target": v, "tol": EB.JOINT_TOL}}
        u = _cal_unit(task, contract, f"C|{task}|J3", "C", {"side": side, "q4_mean0": on["mean"]})
        if keyA(u) in test_keys:
            raise RuntimeError(f"校准 J3 {task} 撞测试键")
        units.append(u)
    out = {"version": REG_VERSION, "part": "cal", "created": now_s(), "units": units,
           "counts": {c: sum(1 for u in units if u["b3_class"] == c) for c in ("N", "H", "C")}}
    if write:
        save_part("cal", out)
    return out


def test_key_set(units: list, dec: dict) -> set:
    """测试单元全部会跑的臂(A / B1 / B2 / AP / Adz,种子 0)的编译键;校准键必须与它不相交(G3(d))。"""
    ks = set()
    for u in units:
        for arm in ("A", "B1", "B2", "AP", "Adz"):
            cmd, _ = arm_cmd(u, arm, dec=dec)
            ks.add(ckey(u["task"], u["bias"], cmd))
    return ks


def load_reg() -> dict | None:
    return CM.read_json_retry(CASES) if CASES.exists() else None


def load_part(part: str) -> dict | None:
    reg = load_reg()
    return None if reg is None else reg.get(part)


def save_part(part: str, obj: dict) -> None:
    with CM.file_lock(OUT / ".cases.lock"):
        reg = load_reg() or {"version": REG_VERSION, "frozen": False, "meta": {}}
        if reg.get("frozen"):
            raise SystemExit(f"{_rel(CASES)} 已冻结,不能重建 {part}")
        reg[part] = obj
        CM.atomic_write_json(CASES, reg, indent=1)


def unit_index(reg: dict | None = None) -> dict:
    reg = reg or load_reg() or {}
    out = {}
    for part in ("test", "cal"):
        for u in (reg.get(part) or {}).get("units") or []:
            out[u["uid"]] = u
    return out


# ═══════════════════════════════════════════ 作业清单(§10.1)
def job(u: dict, arm: str, cfg=None, seed: int = 0, ik: bool = False, role: str = "main") -> dict:
    return {"uid": u["uid"], "arm": arm, "cfg": None if cfg is None else [float(cfg[0]), float(cfg[1]), cfg[2]], "seed": int(seed), "ik": bool(ik), "role": role}


def b3_cfg(dec_xw: dict, cls: str):
    b = ((dec_xw.get("b3") or {}).get(cls) or {}).get("chosen")
    return None if b is None else (float(b[0]), float(b[1]), b[2])


def jobs_test(units: list, dec_xw: dict, sens: dict | None = None, classes=None) -> list:
    """正式批次的全部作业(去重前)。B3 的配置来自 decisions_xw.json(决定之前不生成 B3 作业)。"""
    J = []
    cH, cN, cC = b3_cfg(dec_xw, "H"), b3_cfg(dec_xw, "N"), b3_cfg(dec_xw, "C")
    for u in units:
        c = u["cls"]
        if classes and c not in classes:
            continue
        if c == "N":
            for arm in ("A", "B1", "B2", "AP", "B1m", "B2m", "Adz"):
                J.append(job(u, arm))
            if cN:
                J.append(job(u, "B3", cN))
        elif c == "HS":
            for s in (0, 1, 2):
                for arm in ("A", "B1", "B2"):
                    J.append(job(u, arm, seed=s))
                if cH:
                    J.append(job(u, "B3", cH, seed=s))
            J += [job(u, "B1m"), job(u, "B2m")]
        elif c == "HR2":
            J += [job(u, "A"), job(u, "B1"), job(u, "B2")]
            if cH and u["sub"] != "force":
                J.append(job(u, "B3", cH))
            if u["binding"] and u["sub"] in ("elbow", "q"):
                J += [job(u, a, ik=True, role="ik") for a in ("A", "B1", "B2")]
        elif c == "CA":
            for s in (0, 1, 2):
                J += [job(u, "A", seed=s), job(u, "AP", seed=s)]
            J += [job(u, a) for a in ("B1", "B2", "B1m", "B2m", "Adz")]
            if cC:
                J.append(job(u, "B3", cC))
        elif c == "R":
            J += [job(u, a) for a in ("A", "B1", "B2")]
        elif c == "TC":
            J += [job(u, a) for a in ("A", "B1", "Adz")] + [job(u, a, ik=True, role="ik") for a in ("A", "B1")]
        elif c == "TT":
            J += [job(u, a) for a in ("A", "B1", "Adz")]
        elif c == "FV":
            J += [job(u, a) for a in ("A", "B1")]
    if sens and (classes is None or "SENS" in classes):
        by = {u["uid"]: u for u in units}
        if cH:
            for uid in sens.get("HS") or []:
                for m, f in itertools.product((0.3, 1.0, 10.0), ("quad", "barrier")):
                    J.append(job(by[uid], "B3", (cH[0], m, f), role="sens"))
        for cls, key, cfg in (("N", "N", cN), ("C", "CA", cC)):
            for uid in sens.get(key) or []:
                for r in (0.1, 0.3, 1.0):
                    J.append(job(by[uid], "B3", (r, 1.0, "barrier"), role="sens"))
    return J


def jobs_cal(units: list) -> list:
    J = []
    for u in units:
        J.append(job(u, "A", role="cal"))
        if u["b3_class"] == "H":
            J += [job(u, "B3", cfg, role="cal") for cfg in GRID]
        else:
            J += [job(u, "B3", (r, 1.0, "barrier"), role="cal") for r in (0.3, 1.0)]
    return J


def jobs_ref(dec_xw: dict, reg_s0: dict) -> list:
    cH = b3_cfg(dec_xw, "H")
    if cH is None or abs(cH[0] - 0.1) < 1e-12:
        return []
    return [job(u, "B3", cH, role="ref") for u in reg_s0]


def job_cmd(j: dict, units: dict, dec: dict | None = None) -> tuple:
    u = units[j["uid"]]
    cmd, info = arm_cmd(u, j["arm"], None if j["cfg"] is None else tuple(j["cfg"]), j["seed"], j["ik"], dec)
    return u, cmd, info


def dedupe(jobs: list, units: dict, dec: dict | None = None) -> tuple:
    """作业 → 唯一编译键。返回 (唯一键表 {ckey: (task, bias, cmd, [作业…])}, 作业 → 键)。"""
    uniq, of = {}, []
    for j in jobs:
        u, cmd, _ = job_cmd(j, units, dec)
        k = ckey(u["task"], u["bias"], cmd)
        if k not in uniq:
            uniq[k] = {"task": u["task"], "bias": u["bias"], "cmd": cmd, "jobs": []}
        uniq[k]["jobs"].append(j)
        of.append(k)
    return uniq, of


def count_new(uniq: dict, salt: dict | None = None) -> dict:
    n_r2 = n_have = n_new = 0
    reuse = r2_reuse_ok()
    for v in uniq.values():
        if not salt and reuse and r2_dir_for(v["task"], v["bias"], v["cmd"]) is not None:
            n_r2 += 1
        elif (sim_dir(v["task"], v["bias"], v["cmd"], salt) / "xw_result.json").exists():
            n_have += 1
        else:
            n_new += 1
    return {"unique": len(uniq), "r2_reuse": n_r2, "cached": n_have, "new": n_new, "r2_reuse_gate": reuse}


def run_batch(uniq: dict, jobs_n: int, salt: dict | None = None, tag: str = "batch") -> dict:
    """并行跑唯一键;框架错误立刻停;基础设施失败记下(该单元整组配对之后剔除)。"""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    res = {"ok": 0, "failed": 0, "infra": 0, "budget_stop": 0, "framework": 0}
    stop = threading.Event()

    def one(k, v):
        if stop.is_set():
            return k, "skipped", None
        try:
            r = run_sim(v["task"], v["bias"], v["cmd"], salt=salt)
            return k, ("ok" if r.get("ok") else "failed"), r.get("dir")
        except FrameworkError as e:
            stop.set()
            return k, "framework", str(e)
        except InfraError as e:
            return k, "infra", str(e)
        except SimBudgetExceeded as e:
            return k, "budget_stop", str(e)
    with ThreadPoolExecutor(max(1, int(jobs_n))) as ex:
        futs = [ex.submit(one, k, v) for k, v in uniq.items()]
        for f in as_completed(futs):
            k, st, info = f.result()
            res[st] = res.get(st, 0) + 1
            v = uniq[k]
            with open(log, "a", encoding="utf-8") as lf:
                lf.write(json.dumps({"at": now_s(), "status": st, "task": v["task"], "info": info, "jobs": v["jobs"]}, ensure_ascii=False) + "\n")
            print(f"[{now_s()}] {st:11s} {v['task']} {info}  ({sum(res.values())}/{len(uniq)})", flush=True)
    if res.get("framework"):
        raise FrameworkError(f"批次 {tag} 遇到框架错误,已停(见 {_rel(log)})")
    return {**res, "log": _rel(log)}


# ═══════════════════════════════════════════ decide(§4.3、G2 / G4 / G5、F3 退路)
def tie_dist(cfg) -> float:
    r, m, f = cfg
    return abs(math.log10(r / 0.1)) + abs(math.log10(m)) + (0.5 if f != "barrier" else 0.0)


def choose(table: dict) -> tuple:
    """table:{cfg 元组: 类得分} → (选中的 cfg, 并列集合)。差距在 0.02 以内算并列,取离 (0.1, 1, barrier) 最近的点。"""
    best = max(table.values())
    ties = [c for c, s in table.items() if s >= best - TIE_EPS - 1e-12]
    return min(ties, key=lambda c: (tie_dist(c), c)), ties


def decide() -> dict:
    reg = load_reg()
    if not reg or "cal" not in reg:
        raise SystemExit("先 build-cal 并 run-cal")
    units = {u["uid"]: u for u in reg["cal"]["units"]}
    dec = r2_dec()
    rows = {}
    infra_ex = {}                                                        # §6:重跑 1 次仍是基础设施失败 → 该单元从每个配置的类得分里对称剔除
    for j in jobs_cal(list(units.values())):
        u, cmd, _ = job_cmd(j, units, dec)
        try:
            r = peek_sim(u["task"], u["bias"], cmd)
        except InfraError as e:
            infra_ex.setdefault(j["uid"], []).append({"arm": j["arm"], "cfg": j["cfg"], "err": str(e)})
            continue
        if r is None:
            raise SystemExit(f"校准仿真缺:{u['uid']} {j['arm']} {j['cfg']}(先 run-cal)")
        rows[(j["uid"], j["arm"], None if j["cfg"] is None else tuple(j["cfg"]))] = unit_metrics(u, r, dec)
    if infra_ex:
        print(f"[decide] 基础设施失败剔除的校准单元(所有配置对称剔除):{sorted(infra_ex)}", flush=True)
    units = {uid: u for uid, u in units.items() if uid not in infra_ex}
    empty = [c for c in ("H", "N", "C") if not any(u["b3_class"] == c for u in units.values())]
    if empty:
        raise SystemExit(f"[decide] 剔除基础设施失败后类 {empty} 没有校准单元,停下报告:{sorted(infra_ex)}")
    g4 = {}
    for cls in ("H", "N", "C"):
        us = [uid for uid, u in units.items() if u["b3_class"] == cls]
        val = [rows[(uid, "A", None)]["validity"]["valid"] for uid in us]
        g4[cls] = {"n": len(val), "valid": int(sum(val)), "rate": (sum(val) / len(val)) if val else None}
    g4_ok = all(v["rate"] is not None and v["rate"] >= 0.8 for v in g4.values())
    b3 = {}
    for cls in ("H", "N", "C"):
        us = sorted(uid for uid, u in units.items() if u["b3_class"] == cls)
        cfgs = GRID if cls == "H" else [(0.1, 1.0, "barrier"), (0.3, 1.0, "barrier"), (1.0, 1.0, "barrier")]
        table, binp, full = {}, {}, []
        for cfg in cfgs:
            sc, nb = [], 0
            for uid in us:
                key = (uid, "A", None) if (cls != "H" and abs(cfg[0] - 0.1) < 1e-12) else (uid, "B3", tuple(cfg))
                mt = rows[key]
                sc.append(mt["cal"])
                nb += int(mt["all_pass"])
            table[tuple(cfg)] = float(np.mean(sc))
            binp[tuple(cfg)] = nb
            full.append({"cfg": list(cfg), "score": float(np.mean(sc)), "all_pass": nb, "n": len(us), "unit_scores": dict(zip(us, sc))})
        ch, ties = choose(table)
        b3[cls] = {"chosen": list(ch), "score": table[ch], "ties": [list(t) for t in ties], "table": full,
                   "equals": ("A" if cls != "H" and abs(ch[0] - 0.1) < 1e-12 else
                              "B1" if tuple(ch) == (0.1, 1.0, "quad") else "B2" if tuple(ch) == (0.1, 1.0, "barrier") else None)}
    tp = (reg.get("test") or {}).get("units") or []
    f3 = f3_mode(tp, tuple(b3["H"]["chosen"]), dec) if tp else None
    out = update_decisions_xw({"version": REG_VERSION, "decided_at": now_s(), "gates": {"G4": {"by_class": g4, "ok": g4_ok}},
                               "b3": b3, "F3": f3, "G5": {"need_ref": abs(b3["H"]["chosen"][0] - 0.1) > 1e-12, "done": False},
                               "cal_infra_excluded": infra_ex})
    if not g4_ok:
        print(f"[G4] A 的执行有效率不足 0.8:{g4} → 停下报告", flush=True)
    return out


def f3_mode(test_units: list, cH: tuple, dec: dict) -> dict:
    """F3 退路(§7.2):B3 的 H 类配置在全部 H* 单元上与 B1 或 B2 编译键相同 → F3 的 p 取 F1 / F2 的 p。"""
    hs = [u for u in test_units if u["cls"] == "HS"]
    same = {"B1": True, "B2": True}
    for u in hs:
        k3 = ckey(u["task"], u["bias"], arm_cmd(u, "B3", cH, dec=dec)[0])
        for b in ("B1", "B2"):
            same[b] &= k3 == ckey(u["task"], u["bias"], arm_cmd(u, b, dec=dec)[0])
    mode = "equals_F1" if same["B1"] else ("equals_F2" if same["B2"] else "own")
    return {"mode": mode, "cfg": list(cH), "same_key": same}


# ═══════════════════════════════════════════ selftest(§9.2,离线)
def _ok(cond, msg: str, log: list) -> None:
    log.append(("PASS" if cond else "FAIL", msg))
    if not cond:
        raise AssertionError(msg)


def selftest(quick: bool = False) -> dict:
    """§9.2 的 11 项离线自检(不跑仿真)。整个过程在 R2 写入守卫里运行(#8)。"""
    log: list = []
    rep: dict = {}
    t0 = time.time()
    with r2_write_guard():
        reg = r2_registry()
        dec = r2_dec()
        _ok(reg["meta"]["decisions"] == json.loads(EB.DECISIONS.read_text(encoding="utf-8")), "R2 登记表 meta.decisions == decisions.json", log)
        test = build_test(write=False)
        units = {u["uid"]: u for u in test["units"]}
        # ── #1 A 的 cmd 与 EB.compile_spec 逐字段相同;R2 单元上与 program_once / 起点目录的 cmd.json 相同
        n1, bad1 = 0, []
        for u in test["units"]:
            cmdA, _ = arm_cmd(u, "A", dec=dec)
            if u["cls"] in ("N", "HS", "R", "HR2", "CA"):
                ref, _ = EB.compile_spec(u["task"], {"requirements": u["contract"], "exec": u["exec"]}, dec)
                if "xw" in cmdA or cmdA != ref:                         # 默认容差的单元上 A = R2 正常编译(没有 xw、没有 sigma_scale)
                    bad1.append(f"{u['uid']}: A ≠ EB.compile_spec")
            if u["cls"] not in ("N", "HR2", "CA"):
                continue
            r2c = json.loads((ROOT / u["r2_po_sim"] / "cmd.json").read_text(encoding="utf-8"))
            if cmdA != r2c:
                bad1.append(f"{u['uid']}: A ≠ R2 cmd.json {u['r2_po_sim']}")
            d2 = r2_dir_for(u["task"], u["bias"], cmdA)
            if HOST == EB.LOCAL_HOST and (d2 is None or _rel(d2) != u["r2_po_sim"]):
                bad1.append(f"{u['uid']}: R2 目录映射 {d2} ≠ {u['r2_po_sim']}")
            n1 += 1
        _ok(not bad1 and n1 == test["counts"]["N"] + test["counts"]["HR2"] + test["counts"]["CA"],
            f"#1 A 的 cmd 与 EB.compile_spec 逐字段相同(默认容差单元无 xw);{n1} 个 R2 单元与 R2 cmd.json / 目录映射一致(不符:{bad1[:5]})", log)
        tcA = [arm_cmd(u, "A", dec=dec)[0] for u in test["units"] if u["cls"] == "TC"]
        _ok(all("xw" in c and "sigma" in c["xw"] for c in tcA), "#1 T-conf 上 A 带关节 σ 缩放(xw.sigma),容差进入执行", log)
        # ── #2 各臂项表与 §2.3 公式一致(离线子进程项表)
        ex = st_examples(test)
        tab_print = []
        for name, uid in ex.items():
            u = units[uid]
            for arm, cfg in (("A", None), ("B1", None), ("B2", None), ("AP", None), ("B1m", None), ("B2m", None), ("Adz", None),
                             ("B3", (1.0, 10.0, "barrier")), ("B3", (0.3, 0.3, "quad"))):
                cmd, info = arm_cmd(u, arm, cfg, dec=dec)
                tb = XT.offline_tables(cmd, u["robot"])
                chk = check_table(u, arm, cfg, cmd, tb)
                tab_print.append({"example": name, "uid": uid, "arm": arm, "cfg": cfg, "xw": cmd.get("xw"), "track": chk["track"]})
                _ok(chk["ok"], f"#2 项表 {name} {arm} {cfg or ''}:{chk['msg']}", log)
        rep["tables"] = tab_print
        # ── #3 编译键的等与不等
        k = lambda u, a, cfg=None: ckey(u["task"], u["bias"], arm_cmd(u, a, cfg, dec=dec)[0])     # noqa: E731
        bad3, n3 = [], {"eqA": 0, "eqAP": 0, "HS": 0, "TC": 0}
        for u in test["units"]:
            if u["cls"] in ("N", "CA") or (u["cls"] == "HR2" and u["sub"] == "speed"):
                n3["eqA"] += 1
                if not (k(u, "B1") == k(u, "A") == k(u, "B2")):
                    bad3.append(f"B1 = B2 = A 不成立:{u['uid']}")
            if u["cls"] in ("N", "CA"):
                n3["eqAP"] += 1
                if not (k(u, "AP") == k(u, "B1m") == k(u, "B2m")):
                    bad3.append(f"A\\P = B1⁻ = B2⁻ 不成立:{u['uid']}")
                if k(u, "AP") == k(u, "A"):
                    bad3.append(f"A\\P 应 ≠ A:{u['uid']}")
            if u["cls"] == "HS":
                n3["HS"] += 1
                ok3 = (k(u, "B3", (0.1, 1.0, "quad")) == k(u, "B1") and k(u, "B3", (0.1, 1.0, "barrier")) == k(u, "B2")
                       and len({k(u, "A"), k(u, "B1"), k(u, "B2")}) == 3 and k(u, "B1m") != k(u, "B1") and k(u, "B2m") != k(u, "B2"))
                if not ok3:
                    bad3.append(f"H*:B3 网格点 = B1 / B2,A、B1、B2 互不相同 不成立:{u['uid']}")
        for p in test["tc_pairs"]:
            n3["TC"] += 1
            ui, uii = units[f"TC|{p['pair']}|i"], units[f"TC|{p['pair']}|ii"]
            if not (k(ui, "A") != k(uii, "A") and k(ui, "B1") == k(uii, "B1") and k(ui, "Adz") != k(uii, "Adz")):
                bad3.append(f"T-conf:A(i) ≠ A(ii)、B1(i) = B1(ii) 不成立:{p['pair']}")
        _ok(not bad3, f"#3 编译键:N / C-a / 速度上 B1 = B2 = A({n3['eqA']} 个);N / C-a 上 A\\P = B1⁻ = B2⁻ ≠ A({n3['eqAP']});"
                      f"H* 上 B3(0.1,1,quad) = B1、B3(0.1,1,barrier) = B2、A / B1 / B2 互不相同({n3['HS']});"
                      f"T-conf 上 A(i) ≠ A(ii)、B1(i) = B1(ii)({n3['TC']} 对)。不符:{bad3[:5]}", log)
        # ── #4 compile_spec 包层:表里的项(含 /range)增益被覆盖,其余不变
        rep["t4"] = st_gain_override(log)
        # ── #5 合和 _cost_fn(合成 rollout,CPU)
        if not quick:
            rep["t5"] = st_cost_fn(units[ex["H*"]], dec, log)
        # ── #6 R2 已有仿真跑 EB.evaluate,20 个单元与 labels.program_once.eval 逐值相同
        rep["t6"] = st_eval_replay(reg, log)
        # ── #7 生成的确定性、§3 判据、校准与测试编译键不相交
        rep["t7"] = st_generation(test, dec, log)
        # ── #9 统计
        rep["t9"] = st_stats(log)
        rep["t9b"] = st_device_guard(log)
        # ── #10 入口的四个坑
        rep["t10"] = st_entry_pitfalls(units[ex["N"]], dec, log)
        # ── #11 代价一致逆解在 N 单元上与包装层逆解相同
        if not quick:
            rep["t11"] = st_ik_identity([u for u in test["units"] if u["cls"] == "N" and u["sub"] == "S0"], dec, log)
    # ── #8 写入守卫:正向对照(守卫里写 R2 目录必须被拦;以上全部步骤都在守卫里跑过)
    rep["t8"] = st_write_guard(log)
    rep["log"] = log
    rep["n_pass"] = sum(1 for s, _ in log if s == "PASS")
    rep["wall_s"] = time.time() - t0
    return rep


def st_examples(test: dict) -> dict:
    """selftest #2 的例子单元:N、H*、H-R2 手肘下限、J2 收紧、J1 冲突、J3 offA、T-conf (i)/(ii)、R、H-R2 速度。"""
    U = test["units"]
    pick = lambda f: next(u["uid"] for u in U if f(u))                  # noqa: E731
    return {"N": pick(lambda u: u["cls"] == "N" and u["task"] == "fr3_a" and u["sub"] == "S0"),
            "H*": pick(lambda u: u["cls"] == "HS" and u["task"] == "fr3_a" and u["sub"] == "tilt_upper" and u["meta"]["delta"] == 0.5),
            "H-R2 手肘下限": pick(lambda u: u["cls"] == "HR2" and u["sub"] == "elbow" and u["task"] == "fr3_a" and u["binding"]),
            "J2 收紧": pick(lambda u: u["cls"] == "HR2" and u["family"] == "J2" and u["variant"] == "tighten"),
            "J1 冲突": pick(lambda u: u["cls"] == "CA" and u["family"] == "J1"),
            "J3 offA": pick(lambda u: u["cls"] == "CA" and u["variant"] == "offA"),
            "T-conf (i)": pick(lambda u: u["cls"] == "TC" and u["set"] == "i"),
            "T-conf (ii)": pick(lambda u: u["cls"] == "TC" and u["set"] == "ii"),
            "R": pick(lambda u: u["cls"] == "R"),
            "H-R2 速度": pick(lambda u: u["cls"] == "HR2" and u["sub"] == "speed")}


def expected_rows(u: dict, arm: str, cfg) -> dict:
    """§2.3 的增益公式独立重算:{项 id: (gain 或 None, penalty, 层)},只列契约派生项与测试台 elbow 目标。"""
    P = arm_params(arm, cfg)
    r, m, form = P["r"], P["m"], P["form"]
    eff, _ = EB.effective_items(u["contract"])
    dec = r2_dec()
    soft_planner = set(dec.get("planner_soft") or [])
    out = {}
    if ("elbow", "target") in eff:
        out["elbow"] = (10.0 * 2.0 * r, "quadratic", "soft")
    for q in ("force", "speed", "tilt", "elbow"):
        it = eff.get((q, "bound"))
        if it is None:
            continue
        w = {"force": 3.0, "speed": 3.0, "tilt": 3.0, "elbow": 2.0}[q]
        a = r if q == "elbow" else 1.0
        hard = it["strict"] == "hard"
        g = 10.0 * w * a * (m if hard else 1.0)
        if hard and q not in soft_planner:
            out[f"eb_{q}_bound"] = ((None, "hard", "hard_tier") if form == "tier" else (g, "quadratic", "soft") if form == "quad"
                                    else (g, "hard", "sum_barrier"))
        else:
            out[f"eb_{q}_bound"] = (g, "quadratic", "soft")
    for qj in JQ:
        for cls in ("target", "bound"):
            it = eff.get((qj, cls))
            if it is None:
                continue
            tid = f"eb_{qj}_{it['kind']}"
            hard = cls == "bound" and it["strict"] == "hard"
            g = 10.0 * 2.0 * r * (m if hard else 1.0)
            if hard:
                out[tid] = (None, "hard", "hard_tier") if form == "tier" else (g, "quadratic", "soft") if form == "quad" else (g, "hard", "sum_barrier")
            else:
                out[tid] = (g, "quadratic", "soft")
    return out


def check_table(u: dict, arm: str, cfg, cmd: dict, tb: dict) -> dict:
    """离线项表(子进程同一代码)与 §2.3 公式逐项比较;A_dz 另核对替换项;σ 核对 A 的容差 → σ 规则与 σ0。"""
    exp = expected_rows(u, arm, cfg)
    P = arm_params(arm, cfg)
    track = {t["id"]: t for t in tb["phases"]["track"]}
    msgs = []
    for tid, (g, pen, layer) in exp.items():
        if P["dz"] and (tid == "elbow" or tid.endswith("_target")):
            t = track.get(tid)
            if t is None or t["kind"] != "deadzone":
                msgs.append(f"{tid} 应换成死区")
            continue
        t = track.get(tid)
        if t is None:
            if tid.startswith("eb_q") and tid not in {x["id"] for x in tb["phases"]["settle"]}:
                msgs.append(f"缺项 {tid}")
            continue
        if t["penalty"] != pen or t["layer"] != layer:
            msgs.append(f"{tid} penalty/层 {t['penalty']}/{t['layer']} ≠ {pen}/{layer}")
        if g is not None and abs(t["gain"] - g) > 1e-6 * max(1.0, g):
            msgs.append(f"{tid} 增益 {t['gain']} ≠ {g}")
    eff, _ = EB.effective_items(u["contract"])
    s_exp = {}
    for q, sid, s0 in (("force", "press", 2.0), ("tilt", "ori", 0.03), ("elbow", "elbow", 0.02)):
        it = eff.get((q, "target"))
        if it is None:
            continue
        sc = float(it["tol"]) / float(EB.default_tol(q, it["target"])) if (P["sigmaA"] and not (P["dz"] and q != "force")) else 1.0
        s_exp[sid] = max(s0 * round(sc, 4), {"press": 1.0, "ori": 0.0, "elbow": 0.0}[sid]) if abs(sc - 1.0) > 1e-12 else s0
    for sid, sv in s_exp.items():
        t = track.get(sid)
        if P["dz"] and sid in ("ori", "elbow"):
            continue
        if t is not None and abs(t["sigma"] - sv) > 1e-9:
            msgs.append(f"{sid} σ {t['sigma']} ≠ {sv}")
    for qj in JQ:                                                        # 关节目标:A 的 σ = 0.02 · tol / 0.05,B 臂 σ0 = 0.02
        it = eff.get((qj, "target"))
        if it is None or P["dz"]:
            continue
        sv = r6(Q_SIGMA0 * float(it["tol"]) / Q_TOL0) if P["sigmaA"] else Q_SIGMA0
        t = track.get(f"eb_{qj}_target")
        if t is None or abs(t["sigma"] - sv) > 1e-9:
            msgs.append(f"eb_{qj}_target σ {None if t is None else t['sigma']} ≠ {sv}")
    if P["dz"]:
        if "ori_dz" not in track or track["ori"]["kind"] != "target":
            msgs.append("A_dz 缺 ori_dz / rz 目标")
    for t in tb["phases"].get("go", []) + tb["phases"].get("settle", []):
        if t["id"] == "slow" and t["layer"] != "hard_tier":
            msgs.append("slow 不在 hard 层")
    return {"ok": not msgs, "msg": "; ".join(msgs) or "一致", "track": [{k: t[k] for k in ("id", "penalty", "sigma", "gain", "layer")} for t in tb["phases"]["track"]]}


def st_gain_override(log: list) -> dict:
    from cost_layers.spec import compile_spec as CS
    frames = {"base": (np.eye(3), np.zeros(3))}
    lim = type("L", (), {})()
    lim.q_min, lim.q_max = np.full(7, -3.0), np.full(7, 3.0)
    lim.dq_max, lim.tau_max = np.full(7, 2.0), np.full(7, 80.0)
    spec = {"terms": [{"id": "a", "level": "tcp_motion", "attr": "pos", "frame": "base", "axes": ["x"], "mode": "target+range", "target": 0.5, "lb": 0.4,
                       "ub": 0.6, "sigma": 0.01, "weight": 2.0},
                      {"id": "b", "level": "joint", "attr": "q", "joints": [1], "mode": "range", "lb": -0.5, "ub": 0.5, "sigma": 0.02, "weight": 2.0,
                       "priority": "preference", "penalty": "hard"},
                      {"id": "c", "level": "joint", "attr": "q", "joints": [2], "mode": "target", "target": 0.1, "sigma": 0.02, "weight": 3.0}]}
    comp = CS(spec, frames, lim)
    before = {t.id: t.gain for t in comp.terms}
    n = XT.apply_gain(comp, {"a": 300.0, "b": 7.0})
    after = {t.id: t.gain for t in comp.terms}
    ok = (n == 3 and after["a"] == 300.0 and after["a/range"] == 300.0 and after["b"] == 7.0 and after["c"] == before["c"] == 30.0
          and before["a"] == before["a/range"] == 20.0 and before["b"] == 2.0)
    _ok(ok, f"#4 增益覆盖:<id> 与 <id>/range 都被覆盖,其余不变 {before} → {after}", log)
    _ok(XT.PRIORITY == __import__("cost_layers.spec", fromlist=["PRIORITY"]).PRIORITY, "#4 入口的 PRIORITY 副本 = cost_layers.spec.PRIORITY", log)
    return {"before": before, "after": after}


def st_cost_fn(u: dict, dec: dict, log: list) -> dict:
    """#5:CPU 上建一个真 ClosedLoop,装上 H* 单元 B2 的 track 规格,用 MPPI.rollout 生成合成 rollout;比较原 _cost_fn 与替换版。"""
    import torch
    import cost_layers.sim as SIMM
    from cost_layers import spec as SP
    from cost_layers.config import make_loop
    from cost_layers.cost import rho
    from cost_layers.spec import path_timing
    orig_cost_fn = SIMM.ClosedLoop._cost_fn                              # 原版(offline_setup 装 B2 补丁之前取)
    cmd, _ = arm_cmd(u, "B2", dec=dec)
    res = {}
    with XT.patch_guard():
        mod, PXm, ext, xw, state, rec, (m0, d0, lim0), q_ready, R_t = XT.offline_setup(cmd, u["robot"])
        state["lim"] = lim0
        T_path = path_timing(mod.WP, np.full(len(mod.WP), float(mod.V_TGT)), mod.ACCEL)[2]
        phases = {n: s for n, s, _ in mod.task_specs(q_ready, R_t, T_path)}
        scene, build, _q = mod.setup_robot(u["robot"])
        cl = make_loop("tuned", scene=scene, q_init=q_ready, strict_terms=False, device="cpu",
                       executor_kwargs={"contact_on": 2.0, "contact_off": 1.0})
        cl.extra_frames[mod.SURF] = (np.eye(3), mod.ORIGIN.copy())
        p, R, _ = mod.mj_tcp(cl.m, cl.d, cl.kin.site)
        frames = {"base": (np.eye(3), np.zeros(3)), "tool": (R, p), **cl.extra_frames}
        gen = torch.Generator(device="cpu")
        gen.manual_seed(0)

        def rollouts(tau0):
            kn = cl.mppi.knots[None] + 0.3 * torch.randn(64, *cl.mppi.knots.shape, generator=gen, dtype=cl.mppi.dtype)
            q0 = torch.as_tensor(cl.d.qpos[:7], dtype=cl.mppi.dtype)
            up = torch.zeros(7 + cl.mppi.n_f, dtype=cl.mppi.dtype)
            return cl.mppi.rollout(kn, q0, up, tau0)

        # (a) settle 规格(有 hard 的 slow):sum_ids 里放一个 settle 没有的契约项 → 与原 _cost_fn 逐位相同(slow 仍在 hard 层)
        cl._install(SP.compile_spec(phases["settle"], frames, cl.lim), frames)
        roll = rollouts(0.2)
        _ok(any(t.id == "slow" and t.penalty == "hard" for t in cl.cost_new.terms), "#5 settle 规格里有 hard 的 slow", log)
        J0, Js = orig_cost_fn(cl, dict(roll)), XT.make_cost_fn(xw["sum_ids"])(cl, dict(roll))
        _ok(bool(torch.equal(J0, Js)), "#5 slow 不在 sum_ids:替换版与原 _cost_fn 逐位相同(slow 留在分层的 hard 层)", log)
        # (b) press → track(B2:eb_tilt_bound 仍是 penalty hard,进 sum_ids)
        cl._install(SP.compile_spec(phases["press"], frames, cl.lim), frames)
        comp = SP.compile_spec(phases["track"], frames, cl.lim)
        XT.apply_gain(comp, xw.get("gain") or {})
        cl._install(comp, frames)
        out = {}
        for tau0 in (0.02, 0.2):                                         # 0.02:窗口切换的新旧代价混合;0.2:只有新代价
            roll = rollouts(tau0)
            J0, Je = orig_cost_fn(cl, dict(roll)), XT.make_cost_fn([])(cl, dict(roll))
            out[tau0] = bool(torch.equal(J0, Je))
            _ok(out[tau0], f"#5 sum_ids 为空时替换版与原 _cost_fn 逐位相同(track,tau0={tau0})", log)
        mdl = cl.cost_new
        bar = [t for t in mdl.terms if t.id in xw["sum_ids"]]
        _ok(len(bar) == 1 and bar[0].penalty == "hard" and abs(bar[0].gain - 30.0) < 1e-9,
            f"#5 track 里正好 1 个障碍项 {xw['sum_ids']}(penalty hard,增益 30)", log)
        cl.cost_old = None
        roll = rollouts(0.2)
        rc = mdl.apply_contact(dict(roll))
        H = rc["dq"].shape[1]
        times = rc["tau0"] + rc["dt"] * torch.arange(1, H + 1, dtype=mdl.dt_)
        tot = torch.zeros(rc["dq"].shape[0], dtype=mdl.dt_)
        viol = torch.zeros_like(tot)
        for t in mdl.terms:                                              # 独立手算:障碍项 g·ρ_hard 进和,其余 hard 进 V
            c = rho(mdl.residual(t, mdl.value(t, rc), times) / t.sigma, t.penalty).sum(-1).sum(-1)
            if t.penalty == "hard" and t.id not in xw["sum_ids"]:
                viol = viol + c / 100.0
            else:
                tot = tot + t.gain * c
        f_soft, f_viol = mdl.fixed_cost(rc, split=True)
        S = tot + f_soft
        S = S + (S.max() - S.min() + 1.0) * viol
        J_hand = S + (S.max() - S.min() + 1.0) * f_viol
        J_rep = XT.make_cost_fn(xw["sum_ids"])(cl, dict(roll))
        J_tier = orig_cost_fn(cl, dict(roll))
        close = bool(torch.allclose(J_rep, J_hand, rtol=1e-6, atol=1e-6))
        _ok(close, f"#5 合和版 = Σ 软项 + g·ρ_hard(障碍项)+ (极差+1)·V + 固定硬限最上层(max |差| {float((J_rep - J_hand).abs().max()):.3g})", log)
        # (c) 固定硬限压过一切:把一条样本的固定违反量人为设成 0、其余设成 1,它必须是最小代价(合和版的最上层仍是 F_viol)
        f2 = torch.ones_like(f_viol)
        f2[5] = 0.0
        S2 = tot + f_soft
        S2 = S2 + (S2.max() - S2.min() + 1.0) * viol
        J2 = S2 + (S2.max() - S2.min() + 1.0) * f2
        _ok(int(torch.argmin(J2)) == 5, "#5 固定硬限违反量更小的样本一定更优(最上层)", log)
        res = {"empty_equal": out, "barrier_gain": float(bar[0].gain), "sum_vs_tier_maxdiff": float((J_rep - J_tier).abs().max())}
    return res


def st_eval_replay(reg: dict, log: list) -> dict:
    cs = [c for c in r2_cases(reg) if c["labels"]["program_once"].get("sim")]
    pick = [cs[i] for i in np.linspace(0, len(cs) - 1, 20).astype(int)]
    bad = []
    dec = r2_dec()
    for c in pick:
        po = c["labels"]["program_once"]
        r = EB.load_sim(ROOT / po["sim"])
        ev = EB.evaluate(c["gt"]["spec"]["requirements"], r["series"], c["robot"], dec["extreme"])
        if EB.compact_eval(ev) != po["eval"]:
            bad.append(c["id"])
    _ok(not bad, f"#6 20 个 R2 单元重算 EB.evaluate 与 labels.program_once.eval 逐值相同(不同:{bad})", log)
    return {"n": len(pick), "bad": bad}


def st_generation(test: dict, dec: dict, log: list) -> dict:
    t2 = build_test(write=False)
    strip = lambda o: json.dumps({k: v for k, v in o.items() if k != "created"}, sort_keys=True, default=str)   # noqa: E731
    _ok(strip(test) == strip(t2), "#7 测试集生成确定性(同盐同结果)", log)
    c1 = build_cal(test_keys=test_key_set(test["units"], dec), write=False)
    c2 = build_cal(test_keys=test_key_set(test["units"], dec), write=False)
    _ok(strip(c1) == strip(c2), "#7 校准集生成确定性", log)
    _ok(len(c1["units"]) == 19 and c1["counts"] == {"N": 4, "H": 9, "C": 6}, f"#7 校准集 19 = N 4 + H 9 + C 6({c1['counts']})", log)
    tk = test_key_set(test["units"], dec)
    ck = {ckey(u["task"], u["bias"], arm_cmd(u, "A", dec=dec)[0]) for u in c1["units"]}
    _ok(not (tk & ck), "#7 校准与测试编译键不相交(G3(d))", log)
    hs = [u for u in test["units"] if u["cls"] == "HS"]
    _ok(all(u["g3"]["feasible"] and u["g3"]["no_refuse"] and u["g3"]["binding_A"] for u in hs) and test["g3"]["HS"]["n_clusters"] >= 10,
        f"#7 H*:{len(hs)} 个单元全部满足 G3(a),{test['g3']['HS']['n_clusters']} 簇(丢弃 {len(test['g3']['HS']['dropped'])} 个)", log)
    rr = [u for u in test["units"] if u["cls"] == "R"]
    _ok(len(rr) == 4 and all(u["g3"]["refuse_expected"] for u in rr), f"#7 R:4 个单元 settle 起点离界 > 3σ({[round(u['g3']['z_settle'], 1) for u in rr]})", log)
    pairs = test["tc_pairs"]
    feas = []
    for p in pairs:                                                      # T-conf:(i) 与 (ii) 各自可行、不能同时满足(线性模型)
        s, dq = p["s"], p["dq"]
        fi = dq <= p["tq_L"] + s * TC["te_s"] + 1e-12
        fii = dq <= TC["tq_s"] + s * TC["te_L"] + 1e-12
        both = dq <= TC["tq_s"] + s * TC["te_s"] + 1e-12
        feas.append(fi and fii and not both)
    _ok(all(feas) and len(pairs) == 14, f"#7 T-conf:{len(pairs)} 对(并集规则),每对 (i)、(ii) 各自可行且不能同时满足;逐点规则 {test['g3']['TC']['n_pairs_per_point']} 对", log)
    ca = [u for u in test["units"] if u["cls"] == "CA"]
    conf = []
    for u in ca:                                                         # C-a:冲突经运动学证明(J1 离 E_kin、J3 offA / offB 偏离起点)
        jt = [(rid, it) for rid, it in u["contract"].items() if it["quantity"] in JQ]
        conf.append(len(jt) == 1)
    _ok(len(ca) == 32 and all(conf) and len({u["cluster"] for u in ca}) == 11, f"#7 C-a 32 个单元 11 簇,各带 1 个关节项", log)
    _ok(test["counts"]["N"] == 23 and test["counts"]["HR2"] == 114, f"#7 N 23、H-R2 114({test['counts']})", log)
    hb = test["hr2_binding"]
    _ok((hb["force|True"], hb["force|False"], hb["speed|True"], hb["speed|False"], hb["tilt|True"], hb["tilt|False"], hb["elbow|True"],
         hb["elbow|False"], hb["q|True"], hb["q|False"]) == (13, 21, 13, 16, 7, 11, 11, 4, 9, 9), f"#7 H-R2 绑定 / 松界划分与方案 §1.6 相同 {hb}", log)
    f1 = f3_mode(test["units"], (0.1, 1.0, "quad"), dec)
    f2 = f3_mode(test["units"], (0.1, 1.0, "barrier"), dec)
    fo = f3_mode(test["units"], (0.1, 10.0, "barrier"), dec)
    _ok(f1["mode"] == "equals_F1" and f2["mode"] == "equals_F2" and fo["mode"] == "own", "#7 F3 退路:B3 = B1 / B2 的配置被识别为同键", log)
    return {"counts": test["counts"], "cal_counts": c1["counts"], "hs_dropped": test["g3"]["HS"]["dropped"]}


def cluster_signflip(d_by_cluster: dict) -> dict:
    """§7.2 簇级精确符号翻转(单侧):T = Σ_c d_c,p = #{s ∈ {±1}^C : Σ s_c |d_c| ≥ T} / 2^C(C ≤ 20 时穷举)。"""
    d = np.array([float(v) for _, v in sorted(d_by_cluster.items())])
    C = len(d)
    if C == 0:
        return {"C": 0, "T": float("nan"), "p": float("nan")}
    T = float(d.sum())
    a = np.abs(d)
    if C > 20:
        raise ValueError("簇数 > 20,不穷举")
    signs = np.array(list(itertools.product((1.0, -1.0), repeat=C)))
    tot = signs @ a
    p = float((tot >= T - 1e-12).sum() / len(signs))
    return {"C": C, "T": T, "p": p, "mean": float(d.mean())}


def mcnemar_one_sided(b: int, c: int) -> float:
    """单侧精确 McNemar:P(Bin(b + c, 0.5) ≥ b)(b = A 成 B 败)。"""
    n = b + c
    if n == 0:
        return 1.0
    return float(sum(math.comb(n, i) for i in range(b, n + 1)) / 2 ** n)


def st_stats(log: list) -> dict:
    rng = np.random.default_rng(7)
    for C in (3, 5, 8):
        d = {f"c{i}": float(x) for i, x in enumerate(rng.normal(0.4, 1.0, C))}
        p = cluster_signflip(d)["p"]
        vals = np.array(list(d.values()))
        brute = 0
        for bits in range(2 ** C):
            s = np.array([1.0 if (bits >> i) & 1 else -1.0 for i in range(C)])
            brute += int((s * np.abs(vals)).sum() >= vals.sum() - 1e-12)
        _ok(abs(p - brute / 2 ** C) < 1e-12, f"#9 簇级精确符号翻转与穷举一致(C={C},p={p:.4f})", log)
    _ok(cluster_signflip({f"c{i}": 1.0 for i in range(6)})["p"] == 1 / 64, "#9 6 簇全同号的最小 p = 1/64", log)
    fam = ("F1", "F2", "F3", "F4")
    h = ST.holm({f: p for f, p in zip(fam, (0.01, 0.04, 0.03, 0.2))})
    _ok(list(h["adjusted"]) == list(fam) and abs(h["adjusted"]["F1"] - 0.04) < 1e-12 and h["reject"]["F1"] and not h["reject"]["F2"],
        f"#9 Holm 族固定 m = 4:{h['adjusted']}", log)
    for b, c in ((6, 0), (5, 1), (3, 3), (2, 7)):
        one = mcnemar_one_sided(b, c)
        two = ST.mcnemar_exact(b, c)
        exp2 = min(1.0, 2 * min(mcnemar_one_sided(b, c), mcnemar_one_sided(c, b)))
        _ok(abs(two - exp2) < 1e-12, f"#9 双侧 stats_v3.mcnemar_exact({b},{c}) = 2·min(单侧) = {two:.4f}(单侧 {one:.4f})", log)
    # §4.3 选择规则:差距 ≤ 0.02 算并列,取离 (0.1, 1, barrier) 最近的点
    tab = {c: 0.0 for c in GRID}
    tab[(1.0, 10.0, "quad")] = 0.50
    tab[(0.3, 1.0, "barrier")] = 0.49
    tab[(0.1, 1.0, "quad")] = 0.485
    ch, ties = choose(tab)
    # 距离 = |log10(r/0.1)| + |log10 m| + 0.5·[form ≠ barrier]:(1,10,quad) 2.5、(0.3,1,barrier) 0.477、(0.1,1,quad) 0.5
    _ok(ch == (0.3, 1.0, "barrier") and set(ties) == {(1.0, 10.0, "quad"), (0.3, 1.0, "barrier"), (0.1, 1.0, "quad")},
        f"#9 B3 选择:并列 {sorted(ties)} 里取离 (0.1,1,barrier) 最近的 {ch}(距离 {tie_dist(ch):.3f})", log)
    tab[(0.1, 1.0, "barrier")] = 0.481
    _ok(choose(tab)[0] == (0.1, 1.0, "barrier"), "#9 B3 选择:并列含 (0.1,1,barrier) 时取它(把疑点让给 B)", log)
    _ok(len(GRID) == 18 and tie_dist((0.1, 1.0, "barrier")) == 0.0, "#9 网格 18 个配置", log)
    return {"ok": True}


def st_device_guard(log: list) -> dict:
    """设备守卫(远程规则):白名单、0 / 4 永不、7 只在 16:30 之后、每张卡 ≥ 8 GB 空闲且两次采样稳定(假的显存读数,不 sleep)。"""
    def ff(vals):
        it = iter(vals)
        return lambda x: next(it)
    out = {}
    def tri(name, **kw):
        try:
            device_guard(**kw)
            out[name] = "ok"
        except SystemExit as e:
            out[name] = f"拒绝: {e}"
    tri("5,6 空闲", host="remote-x", cvd="5,6", now=(18, 0), free_fn=ff([20000, 20000, 20000, 20000]))
    tri("0", host="remote-x", cvd="0", now=(18, 0), free_fn=ff([20000, 20000]))
    tri("4,5", host="remote-x", cvd="4,5", now=(18, 0), free_fn=ff([20000] * 4))
    tri("未设置", host="remote-x", cvd="", now=(18, 0), free_fn=ff([]))
    tri("1 空闲不足", host="remote-x", cvd="1", now=(18, 0), free_fn=ff([5000, 5000]))
    tri("2 不稳定", host="remote-x", cvd="2", now=(18, 0), free_fn=ff([20000, 15000]))
    tri("7 早于 16:30", host="remote-x", cvd="7", now=(16, 10), free_fn=ff([20000, 20000]))
    tri("7 之后", host="remote-x", cvd="7", now=(16, 40), free_fn=ff([20000, 20000]))
    tri("本机", host=EB.LOCAL_HOST, cvd=None)
    good = (out["5,6 空闲"] == "ok" and out["7 之后"] == "ok" and out["本机"] == "ok"
            and all(out[k].startswith("拒绝") for k in ("0", "4,5", "未设置", "1 空闲不足", "2 不稳定", "7 早于 16:30")))
    _ok(good, f"#9b 设备守卫:白名单 / 0、4 永不 / 7 的时间 / 每张卡 ≥ 8 GB 且稳定 {out}", log)
    return out


def st_entry_pitfalls(u: dict, dec: dict, log: list) -> dict:
    import ast
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
    src = ENTRY.read_text(encoding="utf-8")
    bad_imp = [x for x in names if x.split(".")[0] in ("edit_breadth", "exec_weighted")] + \
              [m for m in re.findall(r"spec_from_file_location\([^)]*\)", src) if "edit_breadth" in m or "exec_weighted.py" in m]
    _ok(not bad_imp, f"#10 入口没有 import edit_breadth / exec_weighted(AST 扫描;import 了 {sorted(names)})", log)
    # ik = cost:state["lim"] 被设置、退路被记录(用一个总是失败的逆解替身)
    cmd, _ = arm_cmd(u, "A", ik=True, dec=dec)
    with XT.patch_guard():
        mod, PXm, ext, xw, state, rec, (m0, d0, lim0), q_ready, R_t = XT.offline_setup(cmd, u["robot"])
        called = {}
        inner = lambda m, lim, R, q: called.setdefault("inner", {"pre": q})     # noqa: E731
        pc = XT.make_plan_configs_cost(mod, PXm, ext, xw, state, rec, inner, ik_fn=lambda *a, **k: None)
        state["lim"] = None
        out = pc(m0, lim0, R_t, q_ready)
        _ok(state["lim"] is lim0 and rec.get("xw_ik_fallback") == {"failed_at": "pre"} and "inner" in called,
            "#10 ik = cost:先设 state['lim'],逆解失败时调包装层原版并记 xw_ik_fallback", log)
    # fail tail 里的 XWCompileError → 框架错误;只有 ext_result.json → 未完成
    (OUT / "tmp").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="xw_st10_", dir=str(OUT / "tmp")))
    try:
        d1 = tmp / "a"; d1.mkdir()
        CM.atomic_write_json(d1 / "failed.json", {"returncode": 1, "tail": ["Traceback …", "exec_weighted_testbed.XWCompileError: 阶段 track: …"]})
        try:
            load_xw(d1)
            fw = False
        except FrameworkError:
            fw = True
        _ok(fw, "#10 fail tail 里有 XWCompileError → 框架错误", log)
        d2 = tmp / "b"; d2.mkdir()
        CM.atomic_write_json(d2 / "ext_result.json", {"version": "eb2"})
        try:
            load_xw(d2)
            inc = False
        except Incomplete:
            inc = True
        _ok(inc, "#10 只有 ext_result.json 的目录判未完成", log)
        # 基础设施:超时 → 判基础设施失败、改名重跑 1 次;--max-new-sims 预算停(不跑真仿真:子进程换成 sleep)
        LAUNCH_HOOK["fn"] = lambda c, d: [sys.executable, "-c", "import time; time.sleep(5)"]
        LAUNCH_HOOK["timeout"] = 0.5
        saved_sims, saved_infra = globals()["SIMS"], INFRA_LOG["path"]
        globals()["SIMS"] = tmp / "sims"
        INFRA_LOG["path"] = tmp / "infra_events.jsonl"
        SIM_BUDGET.update({"budget": 3, "new": 0})
        try:
            uu = base_unit("fr3_a", s0_contract("fr3_a"))
            cmd_i, _ = arm_cmd(uu, "B2", dec=dec)
            cmd_i = {**cmd_i, "xw": {"gain": {"elbow": 3.0}}}
            got = None
            try:
                run_sim("fr3_a", {}, cmd_i, salt={"selftest": "infra"}, allow_r2=False)
            except InfraError as e:
                got = str(e)
            dd = sim_dir("fr3_a", {}, cmd_i, {"selftest": "infra"})
            _ok(got is not None and (dd / "failed.infra.json").exists() and (dd / "sim.log.try1").exists() and SIM_BUDGET["new"] == 2,
                "#10 超时 → 基础设施失败,改名重跑 1 次后抛 InfraError(新仿真计 2 次)", log)
            SIM_BUDGET.update({"budget": 2, "new": 2})
            try:
                run_sim("fr3_a", {}, {**cmd_i, "xw": {"gain": {"elbow": 4.0}}}, salt={"selftest": "infra"}, allow_r2=False)
                bs = False
            except SimBudgetExceeded:
                bs = True
            _ok(bs, "#10 --max-new-sims 预算用完 → SimBudgetExceeded", log)
        finally:
            LAUNCH_HOOK["fn"] = None
            LAUNCH_HOOK.pop("timeout", None)
            globals()["SIMS"] = saved_sims
            INFRA_LOG["path"] = saved_infra
            SIM_BUDGET.update({"budget": None, "new": 0})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"imports": sorted(names)}


def st_ik_identity(units: list, dec: dict, log: list) -> dict:
    """#11:N 单元(只有手肘目标项)上代价一致逆解的四处位形与包装层 / 测试台逆解逐位相同(只算逆解,CPU)。"""
    out = {}
    for u in units:
        cmdA, _ = arm_cmd(u, "A", dec=dec)
        cmdI, _ = arm_cmd(u, "A", ik=True, dec=dec)
        with XT.patch_guard():
            mod, PXm, ext, xw, state, rec, (m0, d0, lim0), q_ready, R_t = XT.offline_setup(cmdI, u["robot"])
            qa = mod.plan_configs(m0, lim0, R_t, q_ready)
            terms = rec["xw_ik"]["terms"]
        with XT.patch_guard():
            mod2, PXm2, ext2, xw2, state2, rec2, (m2, d2, lim2), q2, R2 = XT.offline_setup(cmdA, u["robot"])
            qb = mod2.plan_configs(m2, lim2, R2, q2)
        same = all(np.array_equal(qa[k], qb[k]) for k in ("pre", "start", "mid", "end"))
        out[u["uid"]] = {"same": same, "k": [t["k"] for t in terms], "fallback": rec.get("xw_ik_fallback")}
        _ok(same and [t["k"] for t in terms] == [5.0] and rec.get("xw_ik_fallback") is None,
            f"#11 代价一致逆解 = 包装层逆解(逐位):{u['uid']}(k = {[t['k'] for t in terms]})", log)
    return out


def st_write_guard(log: list) -> dict:
    probe = EB.OUT / "_xw_guard_probe"
    tries = {"open_w": lambda: open(probe, "w"), "Path.write_text": lambda: probe.write_text("x"), "Path.mkdir": lambda: probe.mkdir(),
             "os.open": lambda: os.open(str(probe), os.O_CREAT | os.O_WRONLY), "os.replace": lambda: os.replace(str(OUT / "x"), str(probe)),
             "np.save": lambda: np.save(str(probe), np.zeros(1)), "mkstemp": lambda: tempfile.mkstemp(dir=str(EB.OUT)),
             "CM.sim_lock": lambda: CM.sim_lock(probe).__enter__(), "CM.atomic_write_text": lambda: CM.atomic_write_text(probe / "a.json", "x")}
    res = {}
    with r2_write_guard():
        for nm, fn in tries.items():
            try:
                fn()
                res[nm] = False
            except R2WriteViolation:
                res[nm] = True
        rd = (EB.OUT / "cases_eb.json").read_bytes()[:10]                # 只读不受影响
    _ok(all(res.values()) and not probe.exists() and len(rd) == 10, f"#8 写入守卫:R2 目录的写操作全部被拦、读不受影响 {res}", log)
    return res


# ═══════════════════════════════════════════ 冒烟(§13;盐 xw-s2,不进分析)
def smoke(items: list, jobs_n: int) -> dict:
    """本机冒烟(同时 ≤ 2 路)。每项写 logs/smoke_<项>.json。#2 通过时写门 r2_bitid(决定能否复用 R2 的 A 仿真)。"""
    test = load_part("test") or build_test(write=False)
    U = {u["uid"]: u for u in test["units"]}
    dec = r2_dec()
    ex = st_examples(test)
    hs = U[ex["H*"]]
    plan = {
        2: [("bitid_A_S0", U["N|fr3_a|S0"], "A", None, False)],
        3: [("B1_HS", hs, "B1", None, False)],
        4: [("B2_HS", hs, "B2", None, False)],
        5: [("B3_1_10_barrier_HS", hs, "B3", (1.0, 10.0, "barrier"), False)],
        6: [("AP_CA", next((u for u in test["units"] if u["cls"] == "CA" and u["task"] == "fr3_a" and u["family"] == "J1"), U[ex["J1 冲突"]]),
             "AP", None, False)],
        7: [("Adz_TC_i", next(u for u in test["units"] if u["cls"] == "TC" and u["task"] == "fr3_a" and u["set"] == "i"), "Adz", None, False)],
        8: [("A_ik_HR2_elbow", next(u for u in test["units"] if u["cls"] == "HR2" and u["task"] == "fr3_a" and u["sub"] == "elbow"
                                    and abs(float(u["notes"].get("offset", 0)) - 0.03) < 1e-9), "A", None, True)],
        9: [("B2_R", next(u for u in test["units"] if u["cls"] == "R" and u["task"] == "iiwa_a" and abs(u["meta"]["g"] - 0.10) < 1e-9), "B2", None, False)],
        10: [("B2_HS_resalt", hs, "B2", None, False)],                   # 同一 cmd、新盐重跑:与 #4 逐位相同(确定性)
        12: [("remote_A_S0", U["N|fr3_a|S0"], "A", None, False), ("remote_B2_HS", hs, "B2", None, False)],   # 远程批次前的入口冒烟
    }
    sweep = None
    if 13 in items:
        items = [i for i in items if i != 13]
        sweep = smoke_sweep(test, dec, jobs_n)
        if not items:
            return {"13:sweep": {"check": sweep["check"]}}
    if 10 in items and 4 not in items:
        items = sorted(set(items) | {4})
    todo = []
    for it in items:
        if it not in plan:
            raise SystemExit(f"冒烟项 {it} 未实现(#2–#10、#12、#13;#11 基础设施见 selftest #10)")
        todo += [(it, *x) for x in plan[it]]
    uniq = {}
    for it, name, u, arm, cfg, ik in todo:
        cmd, info = arm_cmd(u, arm, cfg, 0, ik, dec)
        uniq[(it, name)] = {"task": u["task"], "bias": u["bias"], "cmd": cmd, "u": u, "info": info}
    LOGS.mkdir(parents=True, exist_ok=True)
    results = {}

    def one(key):
        v = uniq[key]
        salt = SMOKE_SALT2 if key[0] == 10 else SMOKE_SALT
        r = run_sim(v["task"], v["bias"], v["cmd"], salt=salt, allow_r2=False)
        return key, r
    with ThreadPoolExecutor(max(1, min(2, int(jobs_n)))) as ex_:
        futs = [ex_.submit(one, k) for k in uniq]
        for f in as_completed(futs):
            try:
                key, r = f.result()
            except Exception as e:                                      # noqa: BLE001
                print(f"[smoke] 失败:{type(e).__name__}: {e}", flush=True)
                raise
            results[key] = r
    rep = {}
    for (it, name), v in uniq.items():
        r = results[(it, name)]
        u = v["u"]
        mt = unit_metrics(u, r, dec)
        xr = r.get("xw_result") or {}
        chk = smoke_check(it, name, u, v["cmd"], r, xr, mt, dec, results)
        rep[f"{it}:{name}"] = {"uid": u["uid"], "dir": r.get("dir"), "xw": v["cmd"].get("xw"), "metrics": {k: mt[k] for k in ("validity", "all_pass", "v", "m", "outcome3")},
                               "check": chk, "refusal_bypassed": xr.get("refusal_bypassed"), "xw_ik_fallback": xr.get("xw_ik_fallback"),
                               "gain_overrides_applied": xr.get("gain_overrides_applied"), "cost_fn_replaced": xr.get("cost_fn_replaced"),
                               "wall_s": (r.get("ext_result") or {}).get("wall_s")}
        CM.atomic_write_json(LOGS / f"smoke_{it}_{name}.json", rep[f"{it}:{name}"], indent=1, default=float)
        print(f"[smoke #{it} {name}] {'通过' if chk['ok'] else '不通过'}:{chk['msg']}", flush=True)
    if sweep is not None:
        rep["13:sweep"] = {"check": sweep["check"]}
    return rep


def smoke_check(it: int, name: str, u: dict, cmd: dict, r: dict, xr: dict, mt: dict, dec: dict, results: dict | None = None) -> dict:
    msgs, ok = [], True
    pt = xr.get("phase_table") or {}
    track = {t["id"]: t for t in pt.get("track", [])}
    if it == 2:
        d2 = ROOT / u["r2_po_sim"]
        A = np.load(ROOT / r["dir"] / "ext_series.npz")
        B = np.load(d2 / "ext_series.npz")
        same = sorted(A.files) == sorted(B.files) and all(np.array_equal(A[k], B[k]) for k in A.files)
        ok &= bool(same)
        msgs.append(f"ext_series.npz 与 R2 {u['r2_po_sim']} 逐位{'相同' if same else '不同'}")
        if same:
            update_decisions_xw({"gates": {"r2_bitid": {"ok": True, "host": HOST, "at": now_s(), "dir": r["dir"], "r2": u["r2_po_sim"],
                                                        "entry_sha16": XT.ENTRY_SHA16}}})
        else:
            update_decisions_xw({"gates": {"r2_bitid": {"ok": False, "host": HOST, "at": now_s(), "dir": r["dir"], "r2": u["r2_po_sim"]}}})
    elif it in (3, 4, 5):
        t = track.get("eb_tilt_bound")
        exp = {3: ("quadratic", "soft", 30.0), 4: ("hard", "sum_barrier", 30.0), 5: ("hard", "sum_barrier", 300.0)}[it]
        good = t is not None and (t["penalty"], t["layer"]) == exp[:2] and abs(t["gain"] - exp[2]) < 1e-9
        ok &= bool(good)
        msgs.append(f"eb_tilt_bound = {None if t is None else (t['penalty'], t['layer'], t['gain'])}(应为 {exp})")
        if it == 5:
            el = track.get("elbow")
            good = el is not None and abs(el["gain"] - 20.0) < 1e-9 and (xr.get("gain_overrides_applied") or 0) > 0
            ok &= bool(good)
            msgs.append(f"elbow 增益 {None if el is None else el['gain']}(应为 20),运行时覆盖 {xr.get('gain_overrides_applied')} 次")
        if it in (4, 5):
            ok &= bool(xr.get("cost_fn_replaced"))
            msgs.append(f"合和代价已替换={xr.get('cost_fn_replaced')};拒收旁路记录 {xr.get('refusal_bypassed')}")
        slow_ok = all(t2["layer"] == "hard_tier" for ph in ("go", "settle", "lift") for t2 in pt.get(ph, []) if t2["id"] == "slow")
        ok &= slow_ok
        msgs.append(f"slow 在 hard 层={slow_ok}")
        ok &= bool(mt["validity"]["valid"])
        msgs.append(f"执行有效={mt['validity']}")
    elif it == 6:
        good = abs(track.get("elbow", {}).get("gain", -1) - 20.0) < 1e-9 and all(abs(t["gain"] - 20.0) < 1e-9 for k, t in track.items() if k.startswith("eb_q"))
        ok &= bool(good)
        msgs.append(f"手肘 / 关节增益 20:{good}")
    elif it == 7:
        good = "ori_dz" in track and track["ori"]["kind"] == "target" and track.get("elbow", {}).get("kind") == "deadzone" and \
            track.get("eb_q1_target", {}).get("kind") == "deadzone"
        ok &= bool(good)
        msgs.append(f"rz 目标 + rx/ry range、手肘 / 关节 range 生效:{good}")
        ok &= bool(mt["validity"]["valid"])
        msgs.append(f"执行有效={mt['validity']}")
    elif it == 8:
        xik = xr.get("xw_ik") or {}
        good = bool(xik.get("terms")) and any(t["id"] == "eb_elbow_bound" and t["hard"] and t["k"] == XT.K_HARD for t in xik["terms"])
        ok &= good
        msgs.append(f"代价一致逆解项 {[(t['id'], t['k']) for t in xik.get('terms', [])]};退路 {xr.get('xw_ik_fallback')}")
        ok &= bool(mt["validity"]["valid"] or mt["validity"]["refused"])
    elif it == 9:
        good = not r.get("refused") and bool(xr.get("refusal_bypassed")) and mt["outcome3"] in ("exec_violate", "exec_ok")
        ok &= good
        msgs.append(f"B2 未被拒、旁路记录 {xr.get('refusal_bypassed')},三分类 {mt['outcome3']},v={mt['v']}")
        ok &= not xr.get("bookkeeping_errors")
        msgs.append(f"记账错误 {xr.get('bookkeeping_errors')}")
    elif it == 10:
        r4 = (results or {}).get((4, "B2_HS"))
        A = np.load(ROOT / r["dir"] / "ext_series.npz")
        B = np.load(ROOT / r4["dir"] / "ext_series.npz") if r4 else None
        same = B is not None and sorted(A.files) == sorted(B.files) and all(np.array_equal(A[k], B[k]) for k in A.files)
        ok &= bool(same)
        msgs.append(f"新盐重跑与 #4 的 ext_series.npz 逐位{'相同' if same else '不同'}({r['dir']} vs {None if r4 is None else r4['dir']})")
    elif it == 12:
        good = (ROOT / r["dir"] / "xw_result.json").exists() and bool(mt["validity"]["valid"])
        ok &= good
        msgs.append(f"完成标记 xw_result.json={'有' if (ROOT / r['dir'] / 'xw_result.json').exists() else '无'};执行有效={mt['validity']};"
                    f"主机 {HOST};CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')}")
    return {"ok": bool(ok), "msg": ";".join(msgs)}


# ───────────────────────────────────────── 冒烟 #13:每类 1 个单元 × 该类会跑的全部臂(同时 ≤ 2 路;盐 xw-s2,不进分析)
SMOKE_B3 = {"H": (0.3, 10.0, "barrier"), "N": (0.3, 1.0, "barrier"), "C": (1.0, 1.0, "barrier")}   # 冒烟用的 B3 网格点(不是选择结果)
SWEEP_PICK = {"N": "N|fr3_b|S0", "HS": "HS|iiwa_a|lower|0.5"}


def sweep_units(test: dict, cal: dict | None) -> dict:
    U = test["units"]
    first = lambda f: next(u for u in U if f(u))                         # noqa: E731
    by = {u["uid"]: u for u in U}
    out = {"N": by[SWEEP_PICK["N"]], "HS": by[SWEEP_PICK["HS"]],
           "HR2": first(lambda u: u["cls"] == "HR2" and u["sub"] == "elbow" and u["binding"] and u["task"].startswith("iiwa")),
           "CA": first(lambda u: u["cls"] == "CA" and u["variant"] == "offA" and u["task"] == "xarm_a"),
           "R": first(lambda u: u["cls"] == "R" and u["task"] == "iiwa_b"),
           "TC": first(lambda u: u["cls"] == "TC" and u["task"] == "iiwa_b" and u["set"] == "ii"),
           "TT": first(lambda u: u["cls"] == "TT" and u["task"] == "xarm_a"),
           "FV": first(lambda u: u["cls"] == "FV" and u["task"] == "xarm_b")}
    if cal:
        out["CAL"] = next(u for u in cal["units"] if u["uid"] == "CAL|H|fr3_b|elbow_lower")
    return out


def smoke_sweep(test: dict, dec: dict, jobs_n: int) -> dict:
    """§13 扩展:每类 1 个单元 × 该类在正式批次会跑的全部臂(jobs_test 的作业,B3 用 SMOKE_B3;种子 0,H* 的 A 另加种子 1;校准取 1 个 H 类单元 ×
    A + 1 个网格点)。逐个仿真核对:完成标记、执行有效性(R 的 A 预期拒收)、xw_result 的运行时项表 = §2.3 公式(空覆盖表按构造 = 包装层)、
    逐维验收与 §6 指标齐全、逆解臂记了逆解项与退路。写 logs/smoke_13_sweep.json。"""
    cal = load_part("cal")
    SU = sweep_units(test, cal)
    dx_s = {"b3": {c: {"chosen": list(v)} for c, v in SMOKE_B3.items()}}
    J = []
    for cls, u in SU.items():
        if cls == "CAL":
            J += [job(u, "A", role="cal"), job(u, "B3", (1.0, 10.0, "barrier"), role="cal")]
            continue
        for j in jobs_test([u], dx_s, None):
            if j["seed"] == 0 or (cls == "HS" and j["arm"] == "A" and j["seed"] == 1):
                J.append(j)
    units = {u["uid"]: u for u in SU.values()}
    uniq, of = dedupe(J, units, dec)
    print(f"[smoke #13] {len(J)} 个作业 → {len(uniq)} 个唯一编译键(按构造相同的臂共享仿真)", flush=True)
    results = {}

    def one(k):
        v = uniq[k]
        return k, run_sim(v["task"], v["bias"], v["cmd"], salt=SMOKE_SALT, allow_r2=False)
    with ThreadPoolExecutor(max(1, min(2, int(jobs_n)))) as ex_:
        for f in as_completed([ex_.submit(one, k) for k in uniq]):
            k, r = f.result()
            results[k] = r
    table, bad = [], []
    for j, k in zip(J, of):
        u = units[j["uid"]]
        r = results[k]
        cmd = uniq[k]["cmd"]
        mt = unit_metrics(u, r, dec)
        xr = r.get("xw_result") or {}
        cls = "CAL" if u["cls"] == "CAL" else u["cls"]
        cfg = None if j["cfg"] is None else tuple(j["cfg"])
        msgs = []
        done = (ROOT / r["dir"] / "xw_result.json").exists()
        if not done:
            msgs.append("缺完成标记")
        exp_refuse = cls == "R" and j["arm"] == "A"
        if exp_refuse:
            if not mt["validity"]["refused"]:
                msgs.append(f"R 的 A 预期拒收,实际 {mt['outcome3']}(G3(c) 预期,不是硬错误)")
        elif not mt["validity"]["valid"]:
            # end_y_err(> 5 mm)/ ik_failed 是 §6 预先登记的执行结果(按最差计),不是框架错误;其余(失败 / 缺序列 / 阶段未采用 / 被拒)才算问题
            if mt["validity"]["why"] in ("end_y_err", "ik_failed"):
                msgs.append(f"情形结果:执行无效({mt['validity']['why']},§6 规则)")
            else:
                msgs.append(f"执行无效:{mt['validity']}")
        if "xw" in cmd:
            pt = xr.get("phase_table")
            if not pt:
                msgs.append("xw_result 没有运行时项表")
            else:
                chk = check_table(u, j["arm"], cfg, cmd, {"phases": pt})
                if not chk["ok"]:
                    msgs.append(f"项表:{chk['msg']}")
        if j["ik"]:
            if not (xr.get("xw_ik") or {}).get("terms"):
                msgs.append("逆解臂没有记逆解项")
        if mt["validity"]["valid"]:
            if mt["eval"] is None or mt["m"] is None:
                msgs.append("缺逐维验收 / m")
            if hard_items(u["contract"]) and mt["v"] is None:
                msgs.append("有 hard 项却没有 v")
        if xr.get("bookkeeping_errors"):
            msgs.append(f"记账错误 {xr['bookkeeping_errors']}")
        hard_err = [m for m in msgs if not m.startswith(("R 的 A 预期拒收", "情形结果"))]
        row = {"cls": cls, "uid": u["uid"], "arm": j["arm"], "cfg": j["cfg"], "seed": j["seed"], "ik": j["ik"], "dir": r.get("dir"),
               "xw": cmd.get("xw"), "outcome3": mt["outcome3"], "valid": mt["validity"]["valid"], "why": mt["validity"]["why"],
               "all_pass": mt["all_pass"], "v": mt["v"], "m": mt["m"], "task_kept": mt["task_kept"],
               "fails": [rid for rid, e in (mt["eval"] or {}).items() if not e.get("ok")],
               "xw_ik_fallback": xr.get("xw_ik_fallback"), "refusal_bypassed": len(xr.get("refusal_bypassed") or []),
               "wall_s": (r.get("ext_result") or {}).get("wall_s"), "issues": msgs, "ok": not hard_err}
        table.append(row)
        if hard_err:
            bad.append(row)
    share = {}
    for k, v in uniq.items():
        if len(v["jobs"]) > 1:
            share[_rel(sim_dir(v["task"], v["bias"], v["cmd"], SMOKE_SALT))] = [f"{x['uid']}:{x['arm']}{'' if x['cfg'] is None else tuple(x['cfg'])}" for x in v["jobs"]]
    rep = {"at": now_s(), "host": HOST, "n_jobs": len(J), "n_sims": len(uniq), "rows": table, "shared_sims": share,
           "check": {"ok": not bad, "msg": f"{len(table)} 个作业 / {len(uniq)} 个仿真;框架问题 {len(bad)} 个:{[(b['uid'], b['arm'], b['issues']) for b in bad][:6]};"
                                          f"情形结果(按 §6 记无效 / 预期拒收){[(x['uid'], x['arm'], x['outcome3'], x['why']) for x in table if x['issues'] and x['ok']]}"}}
    CM.atomic_write_json(LOGS / "smoke_13_sweep.json", rep, indent=1, default=float)
    for row in table:
        print(f"[smoke #13] {row['cls']:4s} {row['arm']:4s} {str(row['cfg'] or ''):22s} s{row['seed']} ik={int(row['ik'])} {row['outcome3']:13s} "
              f"all_pass={int(bool(row['all_pass']))} v={row['v'] if row['v'] is None else round(row['v'], 3)} m={row['m'] if row['m'] is None else round(row['m'], 3)} "
              f"fails={row['fails']} {('OK' + (' ' + str(row['issues']) if row['issues'] else '')) if row['ok'] else 'PROBLEM ' + str(row['issues'])}", flush=True)
    print(f"[smoke #13] {'通过' if not bad else '不通过'}:{rep['check']['msg']}", flush=True)
    return rep


# ═══════════════════════════════════════════ 冻结、状态
def freeze() -> dict:
    reg = load_reg()
    if not reg or "test" not in reg or "cal" not in reg:
        raise SystemExit("先 build-cal / build-test")
    if reg.get("frozen"):
        raise SystemExit("已冻结")
    dx = load_decisions_xw()
    if not dx.get("b3") or not (dx.get("gates") or {}).get("G4", {}).get("ok"):
        raise SystemExit("decisions_xw.json 缺 B3 选择或 G4 不通过")
    if (dx.get("G5") or {}).get("need_ref") and not (dx.get("G5") or {}).get("done"):
        raise SystemExit("G5:B3 的 H 类 r_pref ≠ 0.1,先跑 ref-b3")
    if reg["test"]["g3"]["HS"]["stop"]:
        raise SystemExit("G3:H* 簇数 < 10,停下报告")
    if not ANALYZE.exists():
        raise SystemExit("analyze_exec_weighted.py 不存在")
    dec = r2_dec()
    tk = test_key_set(reg["test"]["units"], dec)
    ck = {ckey(u["task"], u["bias"], arm_cmd(u, "A", dec=dec)[0]) for u in reg["cal"]["units"]}
    if tk & ck:
        raise SystemExit("G3(d):校准与测试编译键相交")
    reg["meta"] = {**(reg.get("meta") or {}), "code_sha": code_shas(), "sha": {"test": sha256_obj(reg["test"]["units"]), "cal": sha256_obj(reg["cal"]["units"]),
                                                                              "decisions": sha256_obj({k: v for k, v in dx.items() if k != "updated_at"})},
                   "g0": g0(strict=True, check_frozen_code=False)}
    reg["frozen"], reg["frozen_at"] = True, now_s()
    CM.atomic_write_json(CASES, reg, indent=1)
    dx["frozen"], dx["frozen_at"] = True, reg["frozen_at"]
    CM.atomic_write_json(DECISIONS, dx, indent=1)
    return reg["meta"]


def load_frozen() -> tuple:
    reg = load_reg()
    if not reg or not reg.get("frozen"):
        raise SystemExit("测试登记表没有冻结(先 freeze)")
    if sha256_obj(reg["test"]["units"]) != reg["meta"]["sha"]["test"] or sha256_obj(reg["cal"]["units"]) != reg["meta"]["sha"]["cal"]:
        raise SystemExit("cases_xw.json 冻结后被改动")
    dx = load_decisions_xw()
    if sha256_obj({k: v for k, v in dx.items() if k not in ("updated_at", "frozen", "frozen_at")}) != reg["meta"]["sha"]["decisions"]:
        raise SystemExit("decisions_xw.json 冻结后被改动")
    return reg, dx


def status() -> None:
    reg = load_reg()
    if not reg:
        print("还没有 cases_xw.json")
        return
    dec = r2_dec()
    dx = load_decisions_xw()
    print(f"cases_xw.json frozen={reg.get('frozen')};门:{json.dumps(dx.get('gates') or {}, ensure_ascii=False)[:300]}")
    for part, jf in (("cal", lambda us: jobs_cal(us)), ("test", lambda us: jobs_test(us, dx, (reg.get("test") or {}).get("sens")))):
        p = reg.get(part)
        if not p:
            continue
        units = {u["uid"]: u for u in p["units"]}
        uniq, _ = dedupe(jf(list(units.values())), units, dec)
        print(f"[{part}] {json.dumps(count_new(uniq), ensure_ascii=False)}")


# ═══════════════════════════════════════════ 主函数
def set_devices(devs: list | None) -> None:
    if devs:
        EB.check_devices(devs)
        DEVICES[:] = devs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("g0")
    s = sub.add_parser("selftest")
    s.add_argument("--quick", action="store_true")
    for nm in ("smoke", "run-cal", "ref-b3", "run"):
        p = sub.add_parser(nm)
        p.add_argument("--jobs", type=int, default=2)
        p.add_argument("--devices", nargs="*", default=None)
        p.add_argument("--max-new-sims", type=int, default=None)
        if nm == "smoke":
            p.add_argument("--items", type=int, nargs="+", required=True)
        if nm == "run":
            p.add_argument("--classes", nargs="*", default=None)
            p.add_argument("--dry-run", action="store_true")
    sub.add_parser("build-cal")
    sub.add_parser("build-test")
    sub.add_parser("decide")
    sub.add_parser("freeze")
    sub.add_parser("status")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.cmd == "g0":
        print(json.dumps(g0(strict=False), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "selftest":
        rep = selftest(quick=a.quick)
        LOGS.mkdir(parents=True, exist_ok=True)
        CM.atomic_write_json(LOGS / "selftest.json", rep, indent=1, default=str)
        for st_, msg in rep["log"]:
            print(f"[{st_}] {msg}")
        print(f"selftest 通过 {rep['n_pass']} 项,用时 {rep['wall_s']:.0f} s;项表见 {_rel(LOGS / 'selftest.json')}")
        return 0
    if a.cmd == "build-test":
        with r2_write_guard():
            t = build_test(write=True)
        print(json.dumps({"counts": t["counts"], "g3": {k: {kk: (len(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()} for k, v in t["g3"].items()},
                          "hr2_binding": t["hr2_binding"]}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "build-cal":
        with r2_write_guard():
            c = build_cal(write=True)
        print(json.dumps({"counts": c["counts"], "units": [u["uid"] for u in c["units"]]}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "decide":
        print(json.dumps(decide(), ensure_ascii=False, indent=1, default=float)[:4000])
        return 0
    if a.cmd == "freeze":
        print(json.dumps(freeze(), ensure_ascii=False, indent=1, default=float))
        return 0
    if a.cmd == "status":
        status()
        return 0
    # —— 运行类命令:G0 + 设备守卫 + manifest
    g = g0(strict=True)
    device_guard()
    set_devices(a.devices)
    SIM_BUDGET["budget"] = a.max_new_sims
    write_manifest(DEVICES, {"argv": sys.argv[1:], "g0_ok": g["ok"], "entry_sha16": XT.ENTRY_SHA16})
    dec = r2_dec()
    if a.cmd == "smoke":
        if a.jobs > 2:
            raise SystemExit("冒烟同时最多 2 路仿真")
        rep = smoke(a.items, a.jobs)
        print(json.dumps({k: v["check"] for k, v in rep.items()}, ensure_ascii=False, indent=1))
        return 0 if all(v["check"]["ok"] for v in rep.values()) else 1
    if a.cmd == "run-cal":
        p = load_part("cal")
        if not p:
            raise SystemExit("先 build-cal")
        units = {u["uid"]: u for u in p["units"]}
        uniq, _ = dedupe(jobs_cal(list(units.values())), units, dec)
        print(json.dumps(count_new(uniq), ensure_ascii=False))
        print(json.dumps(run_batch(uniq, a.jobs, tag="cal"), ensure_ascii=False))
        return 0
    if a.cmd == "ref-b3":
        dx = load_decisions_xw()
        tp = load_part("test")
        s0u = [u for u in tp["units"] if u["cls"] == "N" and u["sub"] == "S0"]
        J = jobs_ref(dx, s0u)
        if not J:
            update_decisions_xw({"G5": {"need_ref": False, "done": True, "F3_units": "all_HS"}})
            print("B3 的 H 类 r_pref = 0.1:不需要无界参照")
            return 0
        units = {u["uid"]: u for u in s0u}
        uniq, of = dedupe(J, units, dec)
        print(json.dumps(run_batch(uniq, a.jobs, tag="ref_b3"), ensure_ascii=False))
        ref = {}
        for j in J:
            u, cmd, _ = job_cmd(j, units, dec)
            r = peek_sim(u["task"], u["bias"], cmd)
            S = r.get("series") if r else None
            ref[u["task"]] = None if S is None else {"min": float(S["tilt"][S["on"]].min()), "max": float(S["tilt"][S["on"]].max())}
        cells = []
        for u in tp["units"]:
            if u["cls"] != "HS" or ref.get(u["task"]) is None:
                continue
            b = u["meta"]["bound"]
            bind3 = (b < ref[u["task"]]["max"]) if u["sub"] == "tilt_upper" else (b > ref[u["task"]]["min"])
            if bind3:
                cells.append(u["uid"])
        ncl = len({tp_u["cluster"] for tp_u in tp["units"] if tp_u["uid"] in set(cells)})
        f3 = dx.get("F3") or {}
        if f3.get("mode") == "own" and ncl < 8:
            f3 = {**f3, "mode": "descriptive", "why": f"B3 绑定簇 {ncl} < 8"}
        update_decisions_xw({"G5": {"need_ref": True, "done": True, "ref_stats": ref, "F3_units": cells, "n_clusters": ncl}, "F3": f3})
        return 0
    if a.cmd == "run":
        reg, dx = load_frozen()
        units = {u["uid"]: u for u in reg["test"]["units"]}
        J = jobs_test(list(units.values()), dx, reg["test"].get("sens"), set(a.classes) if a.classes else None)
        uniq, _ = dedupe(J, units, dec)
        print(json.dumps(count_new(uniq), ensure_ascii=False))
        if a.dry_run:
            return 0
        print(json.dumps(run_batch(uniq, a.jobs, tag="run"), ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
