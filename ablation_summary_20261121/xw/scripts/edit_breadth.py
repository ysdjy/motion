#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 最小编辑广度实验框架(plan_edit_breadth.md v2;2026-10-25 新建,只新建文件,不改任何冻结 / 他人文件)。

检验:用户一句话提出 v3 从没测过的修改 —— 容差改宽 / 改窄、新增硬上下限、软 ↔ 硬、加一项、删一项、关节范围 / 关节目标 ——
大模型能否把它写进规格 v4 里正确的字段、正确的值与语义、正确的软硬标记,不碰其余要求;执行能否满足新契约;硬约束是否守住。
仅仿真;按压族(冻结快照测试台 + 包装层 exp_repair/press_ext_testbed.py);大模型只用 gemini-3.8-flash、gemini-4-argon
(gemini-3.5-flash-lite 可选、只描述);deepseek 一律拒绝。

━━━ 设计要点(详见方案;这里只列实现时定下的取舍)
1. 快照:按 press_ablate_hint.py 第 72–110 行的做法从 exp_repair_frozen_v3/ 加载 press_repair_v3(P3)、press_repair(PR)、common、
   run_repair(不 import press_ablate_hint);P3.TESTBED 换成 exp_xemb_frozen_v3/iiwa_press.py 后重算 CODE_VER,必须 = a6c026990e;
   HARNESS_VER = e6deaf0841、rule_v3 = 414734318e39b751。线上 common.py / cost_layers 七个模块 + llm.py 的 sha16 = 冻结值(G0,运行类命令拦)。
   本文件之前已 import common / run_repair / press_repair* 就拒绝运行。
2. 规格 v4:{"requirements": {id: 项}, "exec": {四个补偿}}。项 = target(target + tol)或上下限(upper / lower / range + strict soft|hard)。
   target 项一律 soft(写 hard 记 invalid_hard_target、按 soft 执行);每个量最多一项 target、一项界;同量同类两项 → 执行 hard 的那项
   (同严时取交集 = 更紧的),记 duplicate,计分时这一处改动算写错;force 与 tilt 的 target 必须存在,否则 spec_invalid(按执行失败)。
   target 项不写 tol 时补缺省容差(记 tol_defaulted;系统提示写明了这条规则)。
3. 补丁(§2.6):id → null 删项;已有 id 字段级合并(字段 null = 去掉该字段;界类项没写 kind 但改了 lower/upper 时按字段重推 kind);
   新 id 新建,不完整丢弃记 invalid_item;数值接受 {"value": x} / {"target": x};exec 缺字段沿用上一轮并限幅;修复轮写的 requirements
   不应用,记 repair_req_attempt;JSON 解析失败 → 规格不变、parse_failed。
4. 编译(§2.5):命令 F / V / tilt_deg / elbow_y 沿用 v3 make_cmd 的取整与执行层下限;ext 里所有数值按 r_q 取整(force 0.01 N、
   speed 0.1 mm/s、tilt 0.1°、elbow 0.001 m、q 0.002 rad),取整后的 ext 原样写进 cmd.json 并进缓存键;cmd.acc 固定 = 任务原始目标
   (R2 的验收全由框架从逐样本序列算)。没有 speed 项 → V = 缺省速度(decisions.json 的 D2,缺省 50 mm/s);没有 elbow 项 → ext.elbow =
   false、elbow_y 固定为任务原始值(elbow_comp 闲置)。path 的项只验收。所以「只改容差 / 只删 path」与起点编译成同一个键、命中起点仿真。
5. 评估(§2.2):target → 窗口均值,|均值 − target| ≤ tol;soft 界 → p95 / p05;hard 界 → max / min(D1 可改成 25 ms 滑动平均后的极值)。
   窗口:target 的 force / speed / path 用 mid,其余 target 用 on;界一律 on,只有 speed 的下界用 mid。逐样本序列来自包装层
   ext_series.npz(与测试台 accept_eval 逐位相同);关节角 = log["q"][idx]。冻结 v3 仿真可从 log.npz 事后重算关节验收(frozen_series)。
   边界标记:余量 < max(0.1·尺度, 2·SD_rep),尺度 = target 的 tol 或界的 Δ(force 1 N、speed 4 mm/s、tilt 1°、elbow 0.01 m、path 1 mm、q 0.05 rad)。
6. 登记表(§3):540 例 = B0 18 + T 180 + H 126 + AD 108 + J 108;模板 = (族, 变体, 说法, 起点),是 §8 的聚类单位;每情形
   seeded_rng("eb2", 情形 id, attempt, 阶段) 抽值(阶段 "p" 在起点仿真之前、"f" 在之后,执行顺序不影响结果);界先从网格抽、再按说法取整,
   真值由显示的数反算;句式(TEMPLATES)与词面审计白名单随登记表冻结。词面审计:去白名单后取连续 3 个汉字,转述层任一编辑句与系统提示
   共有片段即不通过(提示词对应层用加了 硬约束 / 软约束 / 上限 / 下限 / 要求项 的白名单,同样要求不共有)。
7. 标签(§4):起点 → 契约变化 → 程序一次(gt 规格 + 起点 exec;编译相同直接复用起点仿真)→ 搜索 ≤ 4 次;类别 C1 > C2 > C4 > C3,
   记 decided_by;不可达分已证明(合同内矛盾 / 限幅 / 运动学包络)与未证明;D-elbow 含糊时保留、类别记 SE(副作用单列)。
8. 计分(§7):gt 改动清单逐项(按 (quantity, target|界) 匹配,不看 id);数值 |v − gt| ≤ max(0.01·|gt|, r_q);克力说法另要求
   v ∈ [gf·0.0098 − 0.005, gf·0.00981 + 0.005](g = 10 的换算算错);strict、kind、tol;未改动项全部保持;多出的项算写错。
9. 冻结(§4.4):freeze 把 gt / 标签 / 模板 / 扫描文件 / 决策文件的 sha256 写进 meta.sha;读表时重算,不一致 → RegistryTampered,episode 拒绝运行;
   每集记 framework 哈希(本文件 + 包装层 + 系统提示)与登记表 sha,不一致拒绝复用(StaleEpisode)。
10. 设备(§9.2):--devices;主机名不是本机(SPRL6201012107U)且 CUDA_VISIBLE_DEVICES 未设或含 7 → 拒绝;manifest_<host>.json 记物理卡号与空闲显存。
11. 2026-10-25 冒烟时发现(只算逆解,草稿区 r1r2/eb/ik_reach.py):关节项的零空间拉力能把 q1 拉动约 0.25–0.3 rad(手肘随之出容差),
    所以方案 §12 #4 的「区间离当前 q1 ≥ 0.08 rad 必被拒」不成立 —— 逆解会把 q1 拉进去;被拒冒烟与先导 P6 改用 q1 最大值 + 0.60 rad。
    iiwa 的 q4 由尖端位姿锁定(逆解拉不动),是更稳的被拒探针。冒烟里 q1 soft 相容范围 + 删手肘时 q1 跑出范围(preference 权重太弱),属门 D5 的输入。
12. 冒烟(--smoke-tag)的新仿真预算:--max-new-sims;超了的回合记 budget_stop(不算情形结果),标签停在搜索时记 smoke_budget_stop。
13. 2026-10-25 实现审查(第二轮)后的改动(方案 v3 文末记录):contract_only = 编译不变且起点满足完整 gt 契约(另存 compile_unchanged);
    J3 偏移 B = E_kin 外 0.13、J1 冲突取整后再证明;包装层逆解退路(ik_fallback / ik_failed);基础设施失败改名重跑 1 次后抛 InfraError;
    门决定接到 design_cells(a_speed_tasks / a_elbow_tasks / dropped_variants + 补格)、先导 P2b / P9s、planner_softened;J1 / J2 收紧区间
    按点核对 E_exec(含平移退路);标签阶段丢弃自动重抽;系统提示加术语一行、被拒规则改写;声明成功要求编辑轮写对;运动学证明的采样复核
    (kin_confirm);H2 的 X 取在显示网格上;J4 距离 0.06–0.10;S0-res 最多 8 次;真正的割线;D-rep 删手肘保留为 SE;读表核对系统提示 sha。
    冒烟命令:build --stage label --registry <冒烟表> --smoke-tag <t> --allow-undecided(没有 decisions.json 时用 DEFAULTS)。

━━━ 命令(都在项目根目录运行;仿真类命令需要 MUJOCO_GL=egl)
    .venv/bin/python exp_repair/edit_breadth.py g0                                  # 版本门 + 设备守卫(不跑仿真)
    .venv/bin/python exp_repair/edit_breadth.py selftest                            # 离线单元测试(补丁 / 编译 / 评估 / 计分 / 程序参照 /
                                                                                    #   词面审计 / 抽样确定性 / 冻结篡改 / 设备守卫),不跑仿真、不调大模型
    .venv/bin/python exp_repair/edit_breadth.py audit                               # 词面审计(系统提示 × 全部登记句式;含人为塞入的违规句)
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py sim-check --what g0 --task fr3_a --devices cuda:0 --smoke-tag s1
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py sim-check --what map|refuse ...        # 冒烟 #4 的执行映射 / 被拒
    .venv/bin/python exp_repair/edit_breadth.py joint-check --dir <仿真目录>         # 冒烟 #3:ext_series 的 q 与 log.npz 重算逐位相同;冻结 v3 仿真只算关节验收
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py pilot --parts P1 P2 P3 ... --jobs 6 --devices cuda:0 cuda:1
    .venv/bin/python exp_repair/edit_breadth.py decide                              # 门 D1–D6 → results/exp_edit_breadth/pilot/decisions.json
    .venv/bin/python exp_repair/edit_breadth.py kin-scan --tasks fr3_a [--reduced]  # 运动学扫描(只算逆解)→ results/exp_edit_breadth/kin/<task>.json
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py build --stage starts|draw|label --jobs 6 --devices cuda:0 cuda:1
    .venv/bin/python exp_repair/edit_breadth.py draw --provisional --out <file>     # 不跑仿真的抽样(起点统计量按 provisional 规则近似),确定性检查用
    .venv/bin/python exp_repair/edit_breadth.py subset --src <draw 结果> --cases <id …> --out <file>   # 冒烟登记表(挑几个情形,不改内容)
    .venv/bin/python exp_repair/edit_breadth.py freeze [--registry <file>] [--allow-provisional]
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py label-one --registry <file> --case <id> --devices cuda:0 [--smoke-tag t]
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py run --models gemini-3.8-flash gemini-4-argon --jobs 6 --devices cuda:0 cuda:1
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py episode --registry <file> --case <id> --model gemini-3.8-flash --smoke-tag t --max-new-sims 1
    .venv/bin/python exp_repair/edit_breadth.py prog-ref [--registry <file>]        # 程序参照 episode(由标签生成,不跑新仿真)
    MUJOCO_GL=egl .venv/bin/python exp_repair/edit_breadth.py sigma-replay --jobs 6 # §6.3 次要分析(容差同时驱动规划器 σ)
    .venv/bin/python exp_repair/edit_breadth.py status
远程(3090):先 source ~/fcl_setup/env.sh,再 export CUDA_VISIBLE_DEVICES=<从 1,2,3,5,6 里选的空闲卡>,--devices cuda:0 …
输出只在 results/exp_edit_breadth/{pilot, kin, sims, episodes, logs}/ 与 cases_eb.json。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ═══════════════════════════════════════════ 第一件事:从快照加载按压框架(在 import 任何 exp_repair 模块之前)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SNAP = ROOT / "exp_repair_frozen_v3"
SNAP_TESTBED = ROOT / "exp_xemb_frozen_v3" / "iiwa_press.py"
for _m in ("common", "run_repair", "press_repair", "press_repair_v3", "stats_v3", "analyze_v3"):
    if _m in sys.modules:
        raise SystemExit(f"[R2] {_m} 在加载快照之前已被 import({getattr(sys.modules[_m], '__file__', '?')}),拒绝运行")
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SNAP))
_spec = importlib.util.spec_from_file_location("press_repair_v3", SNAP / "press_repair_v3.py")
P3 = importlib.util.module_from_spec(_spec)
sys.modules["press_repair_v3"] = P3
_spec.loader.exec_module(P3)
PR = P3.PR
import common as CM                                                      # noqa: E402  快照
from run_repair import LLMDown, ask_retry, llm_rec                       # noqa: E402  快照
_pxs = importlib.util.spec_from_file_location("press_ext_testbed", HERE / "press_ext_testbed.py")
PX = importlib.util.module_from_spec(_pxs)
sys.modules["press_ext_testbed"] = PX
_pxs.loader.exec_module(PX)
import numpy as np                                                       # noqa: E402

# ═══════════════════════════════════════════ 冻结值与线上文件(plan_supplement §0.1;与 press_ablate_hint 相同的数)
FROZEN = {"code": "a6c026990e", "harness": "e6deaf0841", "rule_v3": "414734318e39b751"}
ONLINE_STRICT = {"exp_repair/common.py": "3ec1d51192d94103",
                 "cost_layers/__init__.py": "47450208fb7f8340", "cost_layers/config.py": "f8ddd900002e909b",
                 "cost_layers/cost.py": "29fd55cbf42ad99b", "cost_layers/mppi.py": "88ff6099c908fb71",
                 "cost_layers/robot.py": "7d95c9a4686a0e3f", "cost_layers/sim.py": "d192aade8376165b",
                 "cost_layers/spec.py": "2270b218f1ae1cd0", "cost_layers/llm.py": "27e219ef3ac5a0e0"}
ONLINE_REPORT = {"exp_xemb/iiwa_press.py": "653ad3a27580c4b1"}
LOCAL_HOST = "SPRL6201012107U"
ALLOWED_REMOTE_GPUS = {"1", "2", "3", "5", "6"}
MODELS = ["gemini-3.8-flash", "gemini-4-argon", "gemini-3.5-flash-lite"]
STRONG = ["gemini-3.8-flash", "gemini-4-argon"]
TEMPERATURE, ROUNDS = 0.7, 3

OUT = ROOT / "results" / "exp_edit_breadth"
PILOT, KIN, SIMS, EPS, LOGS = OUT / "pilot", OUT / "kin", OUT / "sims", OUT / "episodes", OUT / "logs"
REG_PATH = OUT / "cases_eb.json"
DECISIONS = PILOT / "decisions.json"
PY = str(ROOT / ".venv" / "bin" / "python")
WRAPPER = HERE / "press_ext_testbed.py"
KEY_V = "eb2"


def sha16(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def sha256_obj(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=float).encode("utf-8")).hexdigest()


def _rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


# ═══════════════════════════════════════════ G0:快照版本 + 线上文件 + 设备守卫
def snapshot_asserts() -> dict:
    out = {"P3": P3.__file__, "PR": PR.__file__, "common": CM.__file__, "run_repair": sys.modules["run_repair"].__file__}
    for k_, f in out.items():
        if not str(Path(f).resolve()).startswith(str(SNAP.resolve())):
            raise SystemExit(f"[R2] {k_} 不是从快照加载的:{f}")
    if sha16(SNAP_TESTBED) != PX.SNAP_SHA16:
        raise SystemExit(f"[R2] 快照测试台 sha16 {sha16(SNAP_TESTBED)} ≠ {PX.SNAP_SHA16}")
    P3.TESTBED = SNAP_TESTBED
    P3.CODE_VER = CM.code_version(*P3.code_files())
    got = {"code": P3.CODE_VER, "harness": P3.HARNESS_VER, "rule_v3": P3.rule_v3_sha()}
    bad = {k_: (got[k_], v) for k_, v in FROZEN.items() if got[k_] != v}
    if bad:
        raise SystemExit(f"[R2] 快照版本 ≠ 冻结值:{bad}")
    if P3.ALLOW_CODE_DRIFT or P3.RETRY_FAILED:
        raise SystemExit("[R2] P3.ALLOW_CODE_DRIFT / RETRY_FAILED 必须是 False")
    out.update({"testbed": _rel(SNAP_TESTBED), "testbed_sha16": PX.SNAP_SHA16, **got})
    return out


def online_reading(expect: dict | None = None) -> dict:
    expect = ONLINE_STRICT if expect is None else expect
    st = {k_: (sha16(ROOT / k_) if (ROOT / k_).exists() else None) for k_ in expect}
    rp = {k_: (sha16(ROOT / k_) if (ROOT / k_).exists() else None) for k_ in ONLINE_REPORT}
    return {"strict": st, "strict_ok": {k_: st[k_] == v for k_, v in expect.items()}, "report_only": rp}


def g0(strict: bool = True, expect: dict | None = None) -> dict:
    rd = online_reading(expect)
    bad = [k_ for k_, ok in rd["strict_ok"].items() if not ok]
    rd["ok"] = not bad
    if bad:
        msg = f"[R2] 线上文件与冻结值不同:{ {k_: rd['strict'][k_] for k_ in bad} }"
        if strict:
            raise SystemExit(msg)
        print("[警告] " + msg, flush=True)
    return rd


SNAP_CHECKS = snapshot_asserts()


def device_guard(host: str | None = None, cvd: str | None = "__env__") -> dict:
    """远程主机上 CUDA_VISIBLE_DEVICES 必须显式设置且不含物理卡 7(§9.2;本机不限制)。"""
    host = socket.gethostname() if host is None else host
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES") if cvd == "__env__" else cvd
    if host != LOCAL_HOST:
        ids = [x.strip() for x in (cvd or "").split(",") if x.strip()]
        if cvd is None or not ids:
            raise SystemExit(f"[R2] 远程主机 {host}:CUDA_VISIBLE_DEVICES 未设置。先 source ~/fcl_setup/env.sh,再 export CUDA_VISIBLE_DEVICES=<1,2,3,5,6 中的空闲卡>")
        if "7" in ids:
            raise SystemExit(f"[R2] 远程主机 {host}:CUDA_VISIBLE_DEVICES={cvd} 含 7,拒绝运行(只用 1,2,3,5,6)")
        bad = [x for x in ids if x not in ALLOWED_REMOTE_GPUS]
        if bad:                                                           # 审查 R2 第 14 条:白名单
            raise SystemExit(f"[R2] 远程主机 {host}:CUDA_VISIBLE_DEVICES={cvd} 含白名单 1,2,3,5,6 以外的卡 {bad}")
    return {"host": host, "cuda_visible_devices": cvd}


def check_devices(devices: list, cvd: str | None = "__env__") -> None:
    """--devices 的 cuda:k 必须是 cuda:<整数>,且设置了 CUDA_VISIBLE_DEVICES 时 k < 可见卡数(审查 R2 第 14 条)。"""
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES") if cvd == "__env__" else cvd
    ids = [x.strip() for x in (cvd or "").split(",") if x.strip()]
    for d in devices or []:
        m = re.fullmatch(r"cuda:(\d+)", str(d))
        if not m:
            raise SystemExit(f"[R2] --devices 只接受 cuda:<k>:{d}")
        if ids and int(m.group(1)) >= len(ids):
            raise SystemExit(f"[R2] --devices {d} 超出 CUDA_VISIBLE_DEVICES={cvd}(只有 {len(ids)} 张可见卡)")


def gpu_manifest(devices: list) -> dict:
    info = {"host": socket.gethostname(), "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"), "devices": devices,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.free,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
        info["gpus"] = [dict(zip(["index", "name", "free_mib", "total_mib"], [x.strip() for x in r.split(",")])) for r in q]
    except Exception as e:                                               # noqa: BLE001
        info["gpus_error"] = f"{type(e).__name__}: {e}"
    return info


def write_manifest(devices: list, extra: dict | None = None) -> None:
    f = OUT / f"manifest_{socket.gethostname()}.json"
    with CM.file_lock(OUT / ".manifest.lock"):
        old = CM.read_json_retry(f) if f.exists() else {"events": []}
        old["events"].append({**gpu_manifest(devices), **(extra or {})})
        CM.atomic_write_json(f, old, indent=1)


# ═══════════════════════════════════════════ 量、单位、取整、缺省值
TASKS = P3.TASKS                                                         # fr3_a … xarm_b:{"robot", force, speed, tilt, elbow}
A_TASKS = ["fr3_a", "iiwa_a", "xarm_a"]
ALL_TASKS = list(TASKS)
DIMS5 = ["force", "speed", "tilt", "elbow", "path"]
JQ = [f"q{j}" for j in range(1, 8)]
QTYS = DIMS5 + JQ
EXEC_KEYS = list(PR.EXEC_KEYS)
COMP_OF = dict(PR.COMP_OF)                                               # force→force_comp …(path、关节角没有补偿)
COMP_LIM = dict(PR.COMP_LIM)
UNIT = {"force": "N", "speed": "mm/s", "tilt": "°", "elbow": "m", "path": "mm", **{q: "rad" for q in JQ}}
DISP_PER_SI = {"force": 1.0, "speed": 1000.0, "tilt": 180.0 / math.pi, "elbow": 1.0, "path": 1000.0}
R_Q = {"force": 0.01, "speed": 0.1, "tilt": 0.1, "elbow": 0.001, "path": 0.1, **{q: 0.002 for q in JQ}}
DEC = {"force": 2, "speed": 2, "tilt": 2, "elbow": 3, "path": 2, **{q: 3 for q in JQ}}
DELTA = {"force": 1.0, "speed": 4.0, "tilt": 1.0, "elbow": 0.01, "path": 1.0, **{q: 0.05 for q in JQ}}
QZH = {"force": "压力(桌面法向)", "speed": "滑动速度", "tilt": "工具离竖直的角度", "elbow": "手肘(第 4 连杆原点)基座 y", "path": "路径横向偏差",
       **{f"q{j}": f"关节 {j} 角度" for j in range(1, 8)}}
SD_REP = {"fr3": {"force": 0.071, "speed": 0.155, "tilt": 0.226, "elbow": 0.0046},     # results.md §6.1 E3a 合并重复 SD
          "iiwa": {"force": 0.058, "speed": 0.172, "tilt": 0.129, "elbow": 0.0043},
          "xarm7": {"force": 0.080, "speed": 0.151, "tilt": 0.248, "elbow": 0.0045}}
GF = 0.00980665
JOINT_TOL = 0.05
OFFB_GAP = 0.13                                                          # J3 偏移 B:E_kin 边界外 = tol 0.05 + 证明余量 0.05 + 取整余量 0.03
FLOOR = {"force": 0.5, "speed": 2.0}
DEFAULTS = {"default_speed": 50.0, "extreme": "raw", "planner_soft": [], "joint_weight": 2.0, "joint_priority": "preference",
            "force_offsets": [-1.0, -0.5, 0.5, 1.5], "speed_offsets": [-3.0, -1.0, 1.0, 3.0], "tilt_deltas": [-0.5, 0.5, 1.5],
            "elbow_offsets": [-0.02, 0.01, 0.03], "j4_dist": [0.06, 0.10], "a_elbow_tasks": ALL_TASKS, "a_speed_tasks": ALL_TASKS,
            "dropped_variants": [], "decided": False, "d6_stage": 0}
# 门 D6 的变体(审查 R2 第 5 条):某个量的 hard 项在起点满足的界上走不完滑动 → 先在规划器里改 soft(planner_soft,合同仍按 hard),
# 改后仍不行 → 去掉这些 (族, 变体),配额平均分给同族其余变体(design_cells 里补 idx = 1, 2, … 的情形)。
D6_VARIANTS = {"force": [["H1", "force_upper"], ["H1-rep", "force_upper"]], "speed": [["H1", "speed_upper"], ["H1-rep", "speed_upper"]],
               "tilt": [["H1", "tilt_window"]], "elbow": [["H1", "elbow_lower"]], "q": [["J2", "compat"], ["J2", "tighten"]]}
D6_LABELS = {"force": ["force_hard+1.5"], "speed": ["speed_hard+1"], "tilt": ["tilt_hard+1"], "elbow": ["elbow_hard+1", "elbow_hard_pos"], "q": ["q1_hard_compat"]}


def load_decisions() -> dict:
    d = dict(DEFAULTS)
    if DECISIONS.exists():
        d.update(CM.read_json_retry(DECISIONS))
    return d


def default_tol(q: str, target: float) -> float:
    if q in JQ:
        return JOINT_TOL
    return {"force": max(1.0, 0.2 * target), "speed": 0.2 * target, "tilt": 3.0, "elbow": 0.04, "path": 3.0}[q]


def rq(q: str, v: float) -> float:
    r = R_Q[q]
    return round(round(float(v) / r) * r, 6)


def targets_of(task: str) -> dict:
    T = TASKS[task]
    return {"force": T["force"], "speed": T["speed"], "tilt": T["tilt"], "elbow": T["elbow"], "path": 0.0}


def zero_exec() -> dict:
    return {k: 0.0 for k in EXEC_KEYS}


def clamp_comp(k: str, v: float) -> float:
    return float(min(max(float(v), -COMP_LIM[k]), COMP_LIM[k]))


def gstr(v: float, nd: int = 6) -> str:
    s = f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ═══════════════════════════════════════════ 规格 v4:项、补丁、重复项、编译
KINDS = ("target", "upper", "lower", "range")


class ItemError(ValueError):
    pass


class SpecInvalid(ValueError):
    pass


def kind_class(kind: str) -> str:
    return "target" if kind == "target" else "bound"


def item_key(it: dict) -> tuple:
    return (it["quantity"], kind_class(it["kind"]))


def _num(v) -> float:
    if isinstance(v, dict):
        for k_ in ("value", "target", "v"):
            if k_ in v:
                return _num(v[k_])
        raise ItemError(f"嵌套值里没有 value / target: {v}")
    if isinstance(v, bool) or v is None:
        raise ItemError(f"不是数: {v!r}")
    x = float(v)
    if not math.isfinite(x):
        raise ItemError(f"不是有限数: {v!r}")
    return x


def infer_kind(raw: dict) -> str | None:
    if raw.get("target") is not None:
        return "target"
    lo, hi = raw.get("lower") is not None, raw.get("upper") is not None
    return "range" if (lo and hi) else ("upper" if hi else ("lower" if lo else None))


def normalize_item(raw: dict) -> tuple:
    """规范化一个要求项 → (项, 标记列表);不完整 / 不合法抛 ItemError。规范形:target {quantity, kind, target, tol};
    界 {quantity, kind, lower?, upper?, strict}。与 kind 无关的字段丢掉(记 extra_fields_dropped)。"""
    if not isinstance(raw, dict):
        raise ItemError(f"要求项应为对象: {raw!r}")
    flags = []
    q = raw.get("quantity")
    if q not in QTYS:
        raise ItemError(f"quantity 不认识: {q!r}")
    kind = raw.get("kind")
    if kind is None:
        kind = infer_kind(raw)
        flags.append("kind_inferred")
    if kind not in KINDS:
        raise ItemError(f"kind 不合法: {kind!r}")
    strict = raw.get("strict", "soft")
    if strict not in ("soft", "hard"):
        raise ItemError(f"strict 只能是 soft / hard: {strict!r}")
    if kind == "target":
        if raw.get("target") is None:
            raise ItemError("target 项缺 target")
        out = {"quantity": q, "kind": "target", "target": _num(raw["target"])}
        if raw.get("tol") is None:
            out["tol"] = round(default_tol(q, out["target"]), 6)
            flags.append("tol_defaulted")
        else:
            out["tol"] = _num(raw["tol"])
        if not out["tol"] > 0:
            raise ItemError("tol 必须 > 0")
        if strict == "hard":
            flags.append("invalid_hard_target")
        extra = set(raw) - {"quantity", "kind", "target", "tol", "strict"}
    else:
        out = {"quantity": q, "kind": kind, "strict": strict}
        if kind in ("lower", "range"):
            if raw.get("lower") is None:
                raise ItemError(f"{kind} 项缺 lower")
            out["lower"] = _num(raw["lower"])
        if kind in ("upper", "range"):
            if raw.get("upper") is None:
                raise ItemError(f"{kind} 项缺 upper")
            out["upper"] = _num(raw["upper"])
        if kind == "range" and not out["lower"] < out["upper"]:
            raise ItemError("range 的 lower 必须小于 upper")
        extra = set(raw) - {"quantity", "kind", "lower", "upper", "strict"}
        extra -= {f for f in ("lower", "upper") if raw.get(f) is None}
    if extra:
        flags.append("extra_fields_dropped")
    return out, flags


def effective_items(reqs: dict) -> tuple:
    """同量同类多项时按 §2.1 合并:界 → hard 优先,同严取交集(更紧);target → tol 更小者(并列取 id 排序第一)。
    返回 ({(q, 类): 项}, [重复记录])。"""
    groups: dict = {}
    for rid in sorted(reqs):
        it = reqs[rid]
        groups.setdefault(item_key(it), []).append((rid, it))
    eff, dups = {}, []
    for key, L in groups.items():
        if len(L) == 1:
            eff[key] = L[0][1]
            continue
        if key[1] == "target":
            rid, it = min(L, key=lambda x: (x[1]["tol"], x[0]))
            eff[key] = it
            dups.append({"key": list(key), "ids": [x[0] for x in L], "chosen": rid})
            continue
        hard = [x for x in L if x[1]["strict"] == "hard"]
        pool = hard or L
        lo = [x[1]["lower"] for x in pool if "lower" in x[1]]
        hi = [x[1]["upper"] for x in pool if "upper" in x[1]]
        m = {"quantity": key[0], "strict": pool[0][1]["strict"]}
        if lo:
            m["lower"] = max(lo)
        if hi:
            m["upper"] = min(hi)
        m["kind"] = "range" if (lo and hi) else ("upper" if hi else "lower")
        eff[key] = m
        dups.append({"key": list(key), "ids": [x[0] for x in L], "chosen": "hard" if hard else "intersection"})
    return eff, dups


def spec_issues(reqs: dict) -> list:
    eff, _ = effective_items(reqs)
    out = [f"缺 {q} 的 target 项" for q in ("force", "tilt") if (q, "target") not in eff]
    for (q, c), it in eff.items():
        if c == "bound" and "lower" in it and "upper" in it and not it["lower"] < it["upper"]:
            out.append(f"{q} 的界合并后为空")
    return out


def parse_reply(text: str):
    if not isinstance(text, str):
        return None
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        obj = json.loads(text[a:b + 1])
    except Exception:                                                    # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) else None


def apply_patch(spec: dict, obj, round_kind: str) -> tuple:
    """§2.6 补丁 → (新规格, info)。obj = parse_reply 的结果(None = 解析失败)。round_kind:"edit" 或 "repair"。"""
    info = {"parse_failed": obj is None, "invalid_items": [], "added": [], "deleted": [], "modified": [], "delete_missing": [],
            "repair_req_attempt": False, "item_flags": {}, "infeasible": [], "changed": None, "reason": None, "exec_missing": True}
    new = {"requirements": copy.deepcopy(spec["requirements"]), "exec": dict(spec["exec"])}
    if obj is None:
        return new, info
    info["changed"], info["reason"] = obj.get("changed"), obj.get("reason")
    R = obj.get("requirements")
    if round_kind == "repair":
        if isinstance(R, dict) and R:
            info["repair_req_attempt"] = True
    elif isinstance(R, dict):
        reqs = new["requirements"]
        for rid, v in R.items():
            rid = str(rid)
            if v is None:
                if rid in reqs:
                    del reqs[rid]
                    info["deleted"].append(rid)
                else:
                    info["delete_missing"].append(rid)
                continue
            if not isinstance(v, dict):
                info["invalid_items"].append({"id": rid, "why": "不是对象"})
                continue
            if rid in reqs:
                old = reqs[rid]
                merged = dict(old)
                for f, x in v.items():
                    if x is None:
                        merged.pop(f, None)
                    else:
                        merged[f] = x
                if "kind" not in v and kind_class(old["kind"]) == "bound" and any(f in v for f in ("lower", "upper")):
                    merged.pop("kind", None)                             # 只改了界的字段:按现有字段重推 kind(例 range → upper)
                if "kind" not in v and old["kind"] == "target" and "target" not in merged:
                    merged.pop("kind", None)
                try:
                    it, fl = normalize_item(merged)
                except (ItemError, TypeError, ValueError) as e:
                    info["invalid_items"].append({"id": rid, "why": str(e)})
                    continue
                if it != old:
                    reqs[rid] = it
                    info["modified"].append(rid)
                if fl:
                    info["item_flags"][rid] = fl
            else:
                try:
                    it, fl = normalize_item(v)
                except (ItemError, TypeError, ValueError) as e:
                    info["invalid_items"].append({"id": rid, "why": str(e)})
                    continue
                reqs[rid] = it
                info["added"].append(rid)
                if fl:
                    info["item_flags"][rid] = fl
    elif R is not None:
        info["invalid_items"].append({"id": "*", "why": "requirements 不是对象"})
    e = obj.get("exec") if isinstance(obj.get("exec"), dict) else {}
    info["exec_missing"] = not e
    for k_ in EXEC_KEYS:
        v = spec["exec"][k_]
        if k_ in e:
            try:
                v = _num(e[k_])
            except (ItemError, TypeError, ValueError):
                v = spec["exec"][k_]
        new["exec"][k_] = clamp_comp(k_, v)
    inf = obj.get("infeasible")
    if isinstance(inf, list):
        info["infeasible"] = [{"id": str(x.get("id")), "achievable": x.get("achievable")} for x in inf if isinstance(x, dict) and x.get("id") is not None]
    return new, info


def compile_spec(task: str, spec: dict, dec: dict | None = None, opts: dict | None = None, sigma_scale: dict | None = None) -> tuple:
    """规格 v4 → (测试台 cmd(含取整后的 ext), info)。规格不完整抛 SpecInvalid。opts:测试台 v3 可选键(重复实验用)。"""
    dec = load_decisions() if dec is None else dec
    reqs, ex = spec["requirements"], spec["exec"]
    issues = spec_issues(reqs)
    if issues:
        raise SpecInvalid("; ".join(issues))
    eff, dups = effective_items(reqs)
    tg0 = targets_of(task)
    inert = []
    Ft = eff[("force", "target")]["target"]
    F = round(Ft + ex["force_comp"], 3)
    clipped = {"F": F < FLOOR["force"]}
    F = max(F, FLOOR["force"])
    if ("speed", "target") in eff:
        V = round((eff[("speed", "target")]["target"] + ex["speed_comp"]) / 1000.0, 5)
        clipped["V"] = V < 0.002
        V = max(V, 0.002)
    else:
        V = round(float(dec["default_speed"]) / 1000.0, 5)
        clipped["V"] = False
        inert.append("speed_comp")
    tilt_deg = round(eff[("tilt", "target")]["target"] + ex["tilt_comp"], 3)
    ext: dict = {}
    if ("elbow", "target") in eff:
        elbow_y = round(eff[("elbow", "target")]["target"] + ex["elbow_comp"], 4)
    else:
        elbow_y = round(tg0["elbow"], 4)
        ext["elbow"] = False
        inert.append("elbow_comp")
    soft_planner = set(dec.get("planner_soft") or [])
    softened = []                                                        # 门 D6 退路:hard 项在规划器里按 soft 编(合同仍按 hard 判)
    bounds = []
    for q in ("force", "speed", "tilt", "elbow"):
        it = eff.get((q, "bound"))
        if it is None:
            continue
        pen = "hard" if (it["strict"] == "hard" and q not in soft_planner) else "quadratic"
        if it["strict"] == "hard" and q in soft_planner:
            softened.append(q)
        bounds.append({"q": q, "lb": None if "lower" not in it else rq(q, it["lower"]), "ub": None if "upper" not in it else rq(q, it["upper"]),
                       "penalty": pen})
    if bounds:
        ext["bounds"] = bounds
    joints = []
    for q in JQ:
        j = int(q[1:])
        for cls in ("target", "bound"):
            it = eff.get((q, cls))
            if it is None:
                continue
            r = {"j": j, "mode": it["kind"], "weight": float(dec["joint_weight"]), "priority": dec["joint_priority"]}
            if cls == "target":
                r.update({"target": rq(q, it["target"]), "penalty": "quadratic"})
            else:
                r["penalty"] = "hard" if (it["strict"] == "hard" and "q" not in soft_planner) else "quadratic"
                if it["strict"] == "hard" and "q" in soft_planner:
                    softened.append(q)
                if "lower" in it:
                    r["lb"] = rq(q, it["lower"])
                if "upper" in it:
                    r["ub"] = rq(q, it["upper"])
            joints.append(r)
    if joints:
        ext["joints"] = joints
    if sigma_scale:
        ext["sigma_scale"] = {k_: round(float(v), 4) for k_, v in sorted(sigma_scale.items())}
    ext = PX.validate_ext(ext)
    cmd = {"F": F, "V": V, "tilt_deg": tilt_deg, "elbow_y": elbow_y,
           "acc": {"force": tg0["force"], "speed": tg0["speed"] / 1000.0, "tilt_deg": tg0["tilt"], "elbow": tg0["elbow"]}}
    if ext:
        cmd["ext"] = ext
    for k_, v_ in (opts or {}).items():
        if v_ is not None:
            cmd[k_] = v_
    return cmd, {"clipped": clipped, "inert_comps": inert, "duplicates": dups, "planner_softened": sorted(set(softened))}


def base_spec(task: str, drop: tuple = ()) -> dict:
    tg = targets_of(task)
    reqs = {q: {"quantity": q, "kind": "target", "target": tg[q], "tol": round(default_tol(q, tg[q]), 6)} for q in DIMS5 if q not in drop}
    return {"requirements": reqs, "exec": zero_exec()}


# ═══════════════════════════════════════════ 仿真(缓存 + 子进程)
DEVICES = [os.environ.get("PRESS_DEVICE", "cuda:0")]
_dev_lock, _dev_n = threading.Lock(), [0]
SIM_BUDGET = {"budget": None, "new": 0, "lock": threading.Lock()}


class SimBudgetExceeded(RuntimeError):
    pass


class InfraError(RuntimeError):
    pass


def next_device() -> str:
    with _dev_lock:
        d = DEVICES[_dev_n[0] % len(DEVICES)]
        _dev_n[0] += 1
    return d


def bias_args(nb: dict) -> list:
    pa = []
    if nb["force_gain"] != 1.0:
        pa += ["--force-gain", repr(nb["force_gain"])]
    if nb["v_err"] != 1.0:
        pa += ["--v-err", repr(nb["v_err"])]
    if nb["tilt_err"] != 0.0:
        pa += ["--tilt-err", repr(nb["tilt_err"])]
    for k_, flag in (("force_offset", "--force-offset"), ("v_offset", "--v-offset"), ("elbow_err", "--elbow-err")):
        if nb.get(k_):
            pa += [flag, repr(nb[k_])]
    if "v_pow" in nb:
        pa += ["--v-pow", repr(nb["v_pow"]), "--v-pow-ref", repr(nb["v_pow_ref"])]
    if "force_pow" in nb:
        pa += ["--force-pow", repr(nb["force_pow"]), "--force-pow-ref", repr(nb["force_pow_ref"])]
    return pa


def sim_key(task: str, bias: dict | None, cmd: dict, extra: dict | None = None) -> tuple:
    key = {"v": KEY_V, "wrapper": PX.WRAPPER_SHA16, "testbed": PX.SNAP_SHA16, "code": P3.CODE_VER, "sim_args": P3.SIM_ARGS,
           "robot": TASKS[task]["robot"], "bias": P3.norm_bias(bias), "cmd": cmd, "accept_series": True}
    if extra:
        key["extra"] = extra
    ks = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return ks, hashlib.sha1(ks.encode("utf-8")).hexdigest()[:16]


def sim_dir(task: str, bias: dict | None, cmd: dict, extra: dict | None = None, prefix: str | None = None) -> Path:
    return SIMS / f"{prefix or task}_{sim_key(task, bias, cmd, extra)[1]}"


INFRA_RE = re.compile(r"CUDA out of memory|out of memory|CUDA error|CUDA_ERROR|cudaError|CUBLAS_STATUS|Killed|SIGKILL|MemoryError", re.I)


def is_infra_failure(d: Path) -> bool:
    """基础设施失败(同 R1 §9.7):sim.log / failed.json 里有 OOM、CUDA 报错、被杀,或超时 / 返回码 −9 / 137。"""
    txt = ""
    for nm in ("sim.log", "failed.json"):
        if (Path(d) / nm).exists():
            txt += (Path(d) / nm).read_text(encoding="utf-8", errors="replace")[-20000:]
    fj = {}
    try:
        fj = json.loads((Path(d) / "failed.json").read_text(encoding="utf-8")) if (Path(d) / "failed.json").exists() else {}
    except Exception:                                                    # noqa: BLE001
        pass
    return bool(INFRA_RE.search(txt)) or fj.get("returncode") in ("timeout", -9, 137)


def infra_log(ev: dict) -> None:
    p = OUT / "infra_events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with CM.file_lock(OUT / ".infra.lock"):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": socket.gethostname(), **ev}, ensure_ascii=False) + "\n")


def run_sim(task: str, bias: dict | None, cmd: dict, extra: dict | None = None, prefix: str | None = None, readonly: bool = False) -> dict:
    """跑(或读缓存)一次包装层仿真。完成标记 = ext_result.json;失败写 failed.json,不重跑(各臂共用)。
    WrapperCompileError / ExtFormatError → InfraError(框架错误,不是情形结果)。readonly 时缺缓存就抛错。
    基础设施失败(审查 R2 第 4 条,同 R1 §9.7):failed.json 改名 failed.infra.json、sim.log 改名 sim.log.try1,重跑 1 次;仍失败 →
    记 infra_events.jsonl 并抛 InfraError(调用方不写这个标签 / 这一集,之后补跑)。之前运行留下的基础设施失败按「还没重跑过」处理。"""
    ks, h = sim_key(task, bias, cmd, extra)
    d = SIMS / f"{prefix or task}_{h}"
    nb = P3.norm_bias(bias)

    def launch():
        with SIM_BUDGET["lock"]:
            if SIM_BUDGET["budget"] is not None and SIM_BUDGET["new"] >= SIM_BUDGET["budget"]:
                raise SimBudgetExceeded(f"新仿真预算 {SIM_BUDGET['budget']} 已用完(要跑 {_rel(d)})")
            SIM_BUDGET["new"] += 1
        CM.atomic_write_text(d / "cmd.json", json.dumps(cmd, ensure_ascii=False))
        CM.atomic_write_text(d / "key.json", ks)
        c = [PY, str(WRAPPER), "run", "--robot", TASKS[task]["robot"], "--device", next_device(), "--cmd", str(d / "cmd.json"), "--out", str(d),
             *P3.SIM_ARGS, *bias_args(nb), "--accept-series"]
        rc = None
        try:
            with open(d / "sim.log", "w", encoding="utf-8") as lf:
                rc = subprocess.run(c, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, env={**os.environ, "MUJOCO_GL": "egl"}, timeout=1800).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
        if not (d / "ext_result.json").exists():
            tail = (d / "sim.log").read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if (d / "sim.log").exists() else []
            CM.atomic_write_json(d / "failed.json", {"returncode": rc, "tail": tail, "argv": c[1:]}, indent=1)

    def retire_infra():
        (d / "failed.json").replace(d / "failed.infra.json")
        if (d / "sim.log").exists():
            (d / "sim.log").replace(d / "sim.log.try1")

    with CM.sim_lock(d):
        done = (d / "ext_result.json").exists()
        failed = (d / "failed.json").exists() and not done
        if failed and is_infra_failure(d):
            if (d / "failed.infra.json").exists():
                infra_log({"dir": _rel(d), "event": "infra_fail_cached"})
                raise InfraError(f"{_rel(d)}:缓存里是重试过的基础设施失败")
            retire_infra()
            failed = False
        if not done and not failed:
            if readonly:
                raise InfraError(f"只读模式下缺仿真缓存:{_rel(d)}")
            launch()
            if not (d / "ext_result.json").exists() and is_infra_failure(d):
                if (d / "failed.infra.json").exists():
                    infra_log({"dir": _rel(d), "event": "infra_fail"})
                    raise InfraError(f"{_rel(d)}:重跑 1 次后仍是基础设施失败")
                retire_infra()
                infra_log({"dir": _rel(d), "event": "infra_retry"})
                launch()
                if not (d / "ext_result.json").exists() and is_infra_failure(d):
                    infra_log({"dir": _rel(d), "event": "infra_fail"})
                    raise InfraError(f"{_rel(d)}:重跑 1 次后仍是基础设施失败")
    return load_sim(d)


def load_sim(d: Path) -> dict:
    d = Path(d)
    rel = _rel(d)
    if (d / "failed.json").exists() and not (d / "ext_result.json").exists():
        fj = CM.read_json_retry(d / "failed.json")
        tail = "\n".join(fj.get("tail") or [])
        if "WrapperCompileError" in tail or "ExtFormatError" in tail:
            raise InfraError(f"{rel}: 包装层编译错误(框架 bug,不是情形结果):{tail[-400:]}")
        if is_infra_failure(d):                                          # 审查 R2 第 4 条:基础设施失败永远不当作情形结果
            raise InfraError(f"{rel}: 基础设施失败(OOM / CUDA / 被杀 / 超时)")
        return {"dir": rel, "ok": False, "failed": True, "refused": False, "series": None, "ext_result": None, "fail_tail": fj.get("tail")}
    J = CM.read_json_retry(d / "ext_result.json")
    S = load_series(d) if J.get("series_file") else None
    return {"dir": rel, "ok": True, "failed": False, "refused": bool(J.get("refused")), "series": S, "ext_result": J,
            "all_phases_accepted": J.get("all_phases_accepted"), "end_y_err_mm": J.get("end_y_err_mm"), "ik_fallback": J.get("ik_fallback"),
            "ik_failed": bool(J.get("ik_failed"))}


def load_series(d: Path) -> dict:
    """ext_series.npz → 显示单位:force N、speed mm/s、tilt °、elbow m、path mm、q rad;on / mid 掩码。"""
    Z = np.load(Path(d) / "ext_series.npz")
    S = {"t": Z["t"], "on": Z["on"].astype(bool), "mid": Z["mid"].astype(bool), "q": Z["q"].astype(np.float64)}
    for q in DIMS5:
        S[q] = Z[q].astype(np.float64) * DISP_PER_SI[q]
    return S


def frozen_series(d: Path) -> dict:
    """冻结 v3 仿真(log.npz 每 5 个取 1 = 验收网格)事后重建:t、on / mid 掩码(marks.track + task.T_path_s)、q(N × 7)。
    log.npz 没有速度,所以只用于关节验收与核对。"""
    d = ROOT / d if not Path(d).is_absolute() else Path(d)
    L = np.load(d / "log.npz")
    J = CM.read_json_retry(d / "result.json")
    t = L["t"]
    t0, T = J["marks"]["track"][0], J["task"]["T_path_s"]
    return {"t": t, "on": (t >= t0) & (t <= t0 + T), "mid": (t >= t0 + 0.5) & (t <= t0 + T - 0.5), "q": L["q"].astype(np.float64)}


# ═══════════════════════════════════════════ 评估(§2.2)
def item_window(it: dict, side: str | None = None) -> str:
    q = it["quantity"]
    if it["kind"] == "target":
        return "mid" if q in ("force", "speed", "path") else "on"
    return "mid" if (q == "speed" and side == "lower") else "on"


def series_of(S: dict, q: str):
    return S["q"][:, int(q[1:]) - 1] if q in JQ else S[q]


def _ma(x: np.ndarray, n: int = 5) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same")


def boundary_scale(it: dict, robot: str | None) -> float:
    q = it["quantity"]
    sd = (SD_REP.get(robot or "", {}) or {}).get(q, 0.0)
    base = it["tol"] if it["kind"] == "target" else DELTA[q]
    return max(0.1 * base, 2.0 * sd)


def eval_item(it: dict, S: dict | None, robot: str | None = None, extreme: str = "raw") -> dict:
    if S is None:
        return {"ok": False, "kind": it["kind"], "quantity": it["quantity"], "value": None, "why": "no_series"}
    x = series_of(S, it["quantity"])
    if it["kind"] == "target":
        w = item_window(it)
        m = S[w]
        if not m.any():
            return {"ok": False, "kind": "target", "quantity": it["quantity"], "value": None, "why": f"empty_{w}"}
        v = float(np.mean(x[m]))
        dev = v - it["target"]
        margin = it["tol"] - abs(dev)
        return {"ok": bool(abs(dev) <= it["tol"] + 1e-9), "kind": "target", "quantity": it["quantity"], "value": v, "dev": dev, "margin": margin,
                "window": w, "boundary": bool(margin < boundary_scale(it, robot))}
    out = {"kind": it["kind"], "quantity": it["quantity"], "strict": it["strict"], "sides": {}}
    ok_all, bnd = True, False
    for side in ("lower", "upper"):
        if side not in it:
            continue
        w = item_window(it, side)
        m = S[w]
        if not m.any():
            out["sides"][side] = {"stat": None, "ok": False, "window": w}
            ok_all = False
            continue
        xs = _ma(x) if (it["strict"] == "hard" and extreme == "ma25") else x
        if it["strict"] == "hard":
            stat = float(np.max(xs[m])) if side == "upper" else float(np.min(xs[m]))
            sname = "max" if side == "upper" else "min"
        else:
            stat = float(np.percentile(x[m], 95)) if side == "upper" else float(np.percentile(x[m], 5))
            sname = "p95" if side == "upper" else "p05"
        margin = (it["upper"] - stat) if side == "upper" else (stat - it["lower"])
        ok = bool(margin >= -1e-9)
        ok_all &= ok
        b = bool(abs(margin) < boundary_scale(it, robot))
        bnd |= b
        out["sides"][side] = {"stat": stat, "stat_name": sname, "margin": margin, "ok": ok, "window": w, "boundary": b}
    out.update({"ok": bool(ok_all), "boundary": bnd, "hard_violation": bool(it["strict"] == "hard" and not ok_all)})
    return out


def evaluate(reqs: dict, S: dict | None, robot: str | None = None, extreme: str = "raw") -> dict:
    return {rid: eval_item(it, S, robot, extreme) for rid, it in sorted(reqs.items())}


def all_ok(ev: dict | None) -> bool:
    return bool(ev) and all(v["ok"] for v in ev.values())


def compact_eval(ev: dict) -> dict:
    out = {}
    for rid, v in ev.items():
        if v["kind"] == "target":
            out[rid] = {"ok": v["ok"], "value": None if v.get("value") is None else round(v["value"], 6), "boundary": v.get("boundary")}
        else:
            out[rid] = {"ok": v["ok"], "boundary": v.get("boundary"),
                        "stats": {s: (None if x.get("stat") is None else round(x["stat"], 6)) for s, x in (v.get("sides") or {}).items()}}
    return out


def start_stats(S: dict) -> dict:
    """起点统计量(显示单位):各量在 on / mid 窗口的 mean / p05 / p95 / min / max;关节角在 on 窗口。"""
    out = {}
    for q in DIMS5 + JQ:
        x = series_of(S, q)
        out[q] = {}
        for w in ("on", "mid"):
            m = S[w]
            if not m.any():
                continue
            xx = x[m]
            out[q][w] = {"mean": float(xx.mean()), "p05": float(np.percentile(xx, 5)), "p95": float(np.percentile(xx, 95)),
                         "min": float(xx.min()), "max": float(xx.max())}
            if q in JQ and w == "on":                                    # 审查 R2 第 6 条:三处(滑动段起点 / 中点 / 终点)的关节角,收紧区间按点核对 E_exec
                out[q][w]["pts"] = {"start": float(xx[0]), "mid": float(xx[len(xx) // 2]), "end": float(xx[-1])}
    return out


# ═══════════════════════════════════════════ 系统提示、规格视图、回报
SYSTEM_PROMPT_TMPL = """你负责一台机械臂「压住桌面沿一条直线滑 10 cm」这一动作的规格。规格由两部分组成:requirements(用户的要求,也是验收标准)与 exec(执行侧补偿)。

## 量与单位
- force:桌面法向力,N。
- speed:工具尖端的速率,mm/s。
- tilt:工具轴偏离铅垂线的夹角,°。
- elbow:第 4 连杆原点的 y 坐标(基座坐标系),m。
- path:尖端偏离那条直线的横向距离,mm。
- q1–q7:各关节角,rad。q1 = 基座绕竖直轴转动,q4 = 肘关节;三台机械臂的零位与正负方向各不相同,数值以执行回报为准。

## requirements 的写法
requirements 是对象:键为条目 id(自取的短名),值为一条要求。
- 目标型:{{"quantity": 量, "kind": "target", "target": 数, "tol": 数}}。判据:时间窗内的均值与 target 之差的绝对值 ≤ tol。tol 缺省时按下面的缺省值。
- 界型:kind 为 "upper"(写 upper)、"lower"(写 lower)或 "range"(两者都写),再写 "strict": "soft" 或 "hard"(缺省 soft)。
  · soft:上界比较时间窗内的 95% 分位数,下界比较 5% 分位数;约 5% 的采样落在界外也判为满足。
  · hard:时间窗内每个采样都须在界内,即比较最大值 / 最小值。
- 同一个量至多一条目标型、一条界型;目标型不区分 soft / hard。force 与 tilt 必须各有一条目标型。
- 术语:「要求项」= requirements 里的一个条目;「上限」/「下限」= 界型的 upper / lower;「软约束」= strict 为 soft 的界型条目,「硬约束」= strict 为 hard 的界型条目。
- 时间窗:mid = 滑动段掐头去尾各 0.5 s;on = 整个滑动段(从起步到抵达终点)。目标型里 force、speed、path 用 mid,tilt、elbow、关节角用 on;界型一律用 on,唯独 speed 的下界用 mid(起步与停下时速率必经过 0)。
- 缺省 tol:force 为 max(1, 0.2 × target) N,speed 为 0.2 × target,tilt 3°,elbow 0.04 m,path 3 mm,关节角 0.05 rad。tol 是条目里存着的数,改 target 不会自动改 tol。
- 规格里没有 speed 的目标型时,滑动按缺省速率 {default_speed} mm/s 执行。
- 示例(id 与数值仅示意写法):
  "path_band": {{"quantity": "path", "kind": "range", "lower": -1.5, "upper": 1.5, "strict": "soft"}}
  "q6_cap": {{"quantity": "q6", "kind": "upper", "upper": 1.9, "strict": "hard"}}
  "q7": {{"quantity": "q7", "kind": "target", "target": 0.3, "tol": 0.05}}

## 规格如何被执行
- 下发的指令 = target + 补偿。补偿共四个:force_comp(N;压力指令最小 0.5 N)、speed_comp(mm/s;速率指令最小 2 mm/s)、tilt_comp(°;正值 = 离铅垂线更远)、elbow_comp(m;加在 elbow 的 target 上。elbow 由零空间偏好实现,不一定完全跟上)。限幅:force ±6 N、speed ±30 mm/s、tilt ±20°、elbow ±0.15 m。
- 对应的目标型条目不存在时,该补偿不起作用。关节角与 path 没有补偿:关节角条目交给规划器与逆解,path 只用于验收。
- 界型条目与关节角条目直接交给规划器;hard 界在规划时优先于所有非 hard 条目。关节角条目在定位(逆解出起始位形)时也会把关节往要求那边拉,拉不动就只交给规划器。关节角或 tilt 的 hard 界在定位之后、开始执行的那一刻仍在界外超过约 3 个 sigma(关节约 0.06 rad,tilt 约 3.4°)时,规划器拒收整份规格、本轮不执行。

## 输出
只输出一个 JSON:{{"requirements": {{"<id>": {{字段…}} 或 null, …}}, "exec": {{"force_comp": 数, "speed_comp": 数, "tilt_comp": 数, "elbow_comp": 数}}, "changed": ["本轮改动的 id 或补偿名"], "reason": "一两句话", "infeasible": [{{"id": "<条目 id>", "achievable": 数}}]}}
- requirements 里只写有改动的条目:已有 id 中写出的字段覆盖旧值,未写的字段照旧,字段写 null 表示删去这个字段;整条写 null 表示删除该条目;新 id 表示新增条目。未出现的 id 不变。
- exec 里未写的补偿沿用上一轮。
- requirements 只由用户决定:用户提出改动的那一轮,严格按用户的话改 requirements(同轮也可调 exec);此后各修复轮只调 exec,写进 requirements 也不生效。
- 若判断某个条目无论怎样调补偿都达不到,写 infeasible(条目 id 与估计能达到的值),意为放弃这些条目、结束修复;确有把握时才用。"""


def system_prompt(dec: dict | None = None) -> str:
    dec = load_decisions() if dec is None else dec
    return SYSTEM_PROMPT_TMPL.format(default_speed=gstr(dec["default_speed"]))


def framework_version(dec: dict | None = None) -> str:
    h = hashlib.sha256()
    h.update(Path(__file__).read_bytes())
    h.update(WRAPPER.read_bytes())
    h.update(system_prompt(dec).encode("utf-8"))
    return h.hexdigest()[:16]


def fmt(q: str, v) -> str:
    return "无" if v is None else f"{v:.{DEC[q]}f}"


def fmts(q: str, v) -> str:
    return "无" if v is None else f"{v:+.{DEC[q]}f}"


def spec_view(spec: dict) -> str:
    return json.dumps({"requirements": spec["requirements"], "exec": spec["exec"]}, ensure_ascii=False, sort_keys=True)


def intent_text() -> str:
    return "任务:压住桌面沿直线滑 10 cm(滑动段从起步到抵达终点)。下面是当前规格与最近一次执行的检查结果。"


def joint_summary(S: dict | None) -> str:
    if S is None or not S["on"].any():
        return "关节角:无实测值。"
    q = S["q"][S["on"]]
    return "关节角(滑动段 on 窗口,rad):" + ";".join(f"q{j + 1} 均值 {q[:, j].mean():.3f} [{q[:, j].min():.3f}, {q[:, j].max():.3f}]" for j in range(7))


REJ_RE = re.compile(r"hard 项 (\S+) 的当前值 \[([^\]]*)\]")


def refusal_text(reason: str | None, spec: dict) -> str:
    """§2.3 回报原文:点名要求项 id。逆解在退路下也失败(ik_failed,理论上不会出现)时点名关节角条目。"""
    if (reason or "").startswith("ik_failed"):
        rid = next((k_ for k_, it in sorted(spec["requirements"].items()) if it["quantity"] in JQ), "?")
        return f"执行被拒:按这份规格算不出起始位形(要求项 {rid} 与按压姿态在逆解里冲突),这一轮没有执行。"
    m = REJ_RE.search(reason or "")
    rid, val, unit = "?", "?", ""
    if m:
        term, vals = m.group(1), m.group(2)
        x = float(vals.split(",")[0])
        q = None
        if term.startswith("eb_q"):
            q = "q" + term[4]
        elif term.startswith("eb_tilt"):
            q, x = "tilt", math.degrees(x)
        for k_, it in sorted(spec["requirements"].items()):
            if q is not None and it["quantity"] == q and kind_class(it["kind"]) == "bound":
                rid = k_
                break
        if q is not None:
            val, unit = fmt(q, x), UNIT[q]
    return f"执行被拒:要求项 {rid}(hard)在开始执行时的当前值 {val} {unit} 已在界外,规划器不接受这份规格,这一轮没有执行。"


def report_lines(spec: dict, ev: dict) -> list:
    L = []
    for rid, it in sorted(spec["requirements"].items()):
        q, u, e = it["quantity"], UNIT[it["quantity"]], ev[rid]
        if it["kind"] == "target":
            L.append(f"- {rid}({QZH[q]}):目标 {fmt(q, it['target'])} {u},容差 ±{gstr(it['tol'])} {u},实测均值 {fmt(q, e.get('value'))} {u},"
                     f"偏差 {fmts(q, e.get('dev'))} {u} → {'达标' if e['ok'] else '未达标'}")
            continue
        parts = []
        for side, word in (("lower", "下界"), ("upper", "上界")):
            if side not in it:
                continue
            s = (e.get("sides") or {}).get(side) or {}
            parts.append(f"{word} {fmt(q, it[side])} {u},实测 {s.get('stat_name', '')} {fmt(q, s.get('stat'))} {u},余量 {fmts(q, s.get('margin'))} {u}")
        tag = "达标" if e["ok"] else ("未达标(硬约束越界)" if it["strict"] == "hard" else "未达标")
        L.append(f"- {rid}({QZH[q]},{it['strict']}):" + ";".join(parts) + f" → {tag}")
    return L


def feedback(spec: dict, ev: dict | None, S: dict | None, seq: list, *, refused: str | None = None, invalid: str | None = None,
             full: bool = False) -> str:
    """当前这一轮的回报。full = 编辑轮(也给全部实测值);修复轮全部达标时只说达标。"""
    if invalid is not None:
        return f"规格不完整({invalid}),这一轮没有执行。"
    if refused is not None:
        return refused
    if S is None:
        return "执行后检查:这次执行没有完成,没有任何实测值。"
    if all_ok(ev) and not full:
        return "执行后检查:全部要求都达到了。"
    L = ["执行后检查(逐项):"] + report_lines(spec, ev) + [joint_summary(S)]
    hist = [r for r in seq if r.get("executed")]
    if len(hist) >= 2:
        L.append("历史(各轮补偿 → 实测均值):")
        for rid, it in sorted(spec["requirements"].items()):
            if it["kind"] != "target" or ev[rid]["ok"] or it["quantity"] not in COMP_OF:
                continue
            k_ = COMP_OF[it["quantity"]]
            pts = []
            for r in hist:
                v = ((r.get("self_eval") or {}).get(rid) or {}).get("value")
                pts.append(f"第{r['round']}轮 {k_}={r['exec'][k_]:.3g} → {'无' if v is None else round(v, 3)}")
            L.append(f"- {rid}:" + ";".join(pts))
    return "\n".join(L)


def history_lines(seq: list) -> list:
    L = []
    for r in seq[:-1]:
        ev = r.get("self_eval") or {}
        if r.get("refused"):
            res = "执行被拒"
        elif r.get("spec_invalid"):
            res = "规格不完整,未执行"
        elif not ev or all(v.get("value") is None and not v.get("sides") for v in ev.values()):
            res = "没有实测值"
        else:
            res = ", ".join(f"{rid}{'✓' if v['ok'] else '✗'}" for rid, v in sorted(ev.items()))
        L.append(f"第 {r['round']} 轮:{json.dumps(r['exec'], ensure_ascii=False)} → {res}")
    return L


# ═══════════════════════════════════════════ 句式(§3.3,随登记表冻结)与词面审计
QN = {"force": "压力", "speed": "滑动速度", "tilt": "工具离竖直的角度", "elbow": "手肘的基座 y"}
QN_T = {**QN, "elbow": "手肘的基座 y "}                                    # T 族句式「{qn}放宽一些」里 y 后面要空一格
UN = {"force": "N", "speed": "mm/s", "tilt": "°", "elbow": "m"}
TEMPLATES = {
    ("T1", "abs"): "{qn}放宽一些:平均下来差 {v} {u} 以内都可以接受,其他要求不变。",
    ("T1", "rel"): "{qn}放宽一些:能接受的偏差放到现在的 {r} 倍,其他要求不变。",
    ("T1", "unit"): "{qn}放宽一些:平均下来差 {v} {u} 以内都可以接受,其他要求不变。",
    ("T2", "abs"): "{qn}收紧一些:平均下来差 {v} {u} 以内才算合格,其他要求不变。",
    ("T2", "rel"): "{qn}收紧一些:能接受的偏差缩到现在的 {p}%,其他要求不变。",
    ("T2", "unit"): "{qn}收紧一些:平均下来差 {v} {u} 以内才算合格,其他要求不变。",
    ("H1force", "abs"): "滑动的时候,压力一刻也不许高过 {v} {u},其他要求不变。",
    ("H1force", "rel"): "滑动的时候,压力一刻也不许比要求的压力高出 {p}% 以上,其他要求不变。",
    ("H1force", "unit"): "滑动的时候,压力一刻也不许高过 {v} {u},其他要求不变。",
    ("H1speed", "abs"): "滑动的时候,速度哪怕一瞬间也不能快过 {v} {u},其他要求不变。",
    ("H1speed", "rel"): "滑动的时候,速度哪怕一瞬间也不能比要求的速度快 {p}% 以上,其他要求不变。",
    ("H1speed", "unit"): "滑动的时候,速度哪怕一瞬间也不能快过 {v} {u},其他要求不变。",
    ("H1tilt", "abs"): "滑动全程,工具离竖直的角度必须一直待在 {a}{u} 到 {b}{u} 之间,其他要求不变。",
    ("H1tilt", "rel"): "滑动全程,工具离竖直的角度必须一直待在要求角度的 ±{x}° 之内,其他要求不变。",
    ("H1tilt", "unit"): "滑动全程,工具离竖直的角度必须一直待在 {a} {u} 到 {b} {u} 之间,其他要求不变。",
    ("H1elbow", "abs"): "滑动全程,手肘的基座 y 一次都不能低于 {v} {u},其他要求不变。",
    ("H1elbow", "rel"): "滑动全程,手肘一次都不能比要求的位置低 {x} cm 以上,其他要求不变。",
    ("H1elbow", "rel_neg"): "滑动全程,手肘必须一直比要求的位置高出至少 {x} cm,其他要求不变。",
    ("H1elbow", "unit"): "滑动全程,手肘的基座 y 一次都不能低于 {v} {u},其他要求不变。",
    ("H2", "direct"): "把{qn}上限那一项从软约束改成硬约束,其他要求不变。",
    ("H2", "implicit"): "{qn}那个上限现在一下都不能超了,其他要求不变。",
    ("H2", "reason"): "桌面换成玻璃了,{qn}那个上限得严格守住,其他要求不变。",
    ("H3", "direct"): "把{qn}上限那一项从硬约束改成软约束,其他要求不变。",
    ("H3", "implicit"): "{qn}那个上限偶尔冒过去一点也行,大部分时间守住就好,其他要求不变。",
    ("H3", "reason"): "换成木桌了,{qn}那个上限不用卡那么死,其他要求不变。",
    ("Aelbow", "abs"): "另外,手肘请放在基座 y = {v} m 附近,其他要求不变。",
    ("Aelbow", "unit"): "另外,手肘请放在基座 y = {v} mm 附近,其他要求不变。",
    ("Aelbow", "tol"): "另外,手肘请放在基座 y = {v} m,前后差 {t} cm 以内都行,其他要求不变。",
    ("Aspeed", "abs"): "另外,滑动速度请保持在 {v} mm/s 左右,其他要求不变。",
    ("Aspeed", "unit"): "另外,滑动速度请保持在 {v} cm/s 左右,其他要求不变。",
    ("Aspeed", "tol"): "另外,滑动速度请保持在 {v} mm/s,快慢差 {t} mm/s 以内都行,其他要求不变。",
    ("D", "direct"): "去掉{obj}这个要求项,其他要求不变。",              # 提示词对应层:用系统提示里定义的「要求项」(审查 R2 第 7 条)
    ("Delbow", "implicit"): "手肘放哪都行,其他要求不变。",
    ("Dpath", "implicit"): "直线走偏一点也无所谓了,其他要求不变。",
    ("Dforce_hard", "implicit"): "压力高一点也没事了,其他要求不变。",
    ("Dq1_range", "implicit"): "关节 1 转到哪都行,其他要求不变。",
    ("Delbow", "reason"): "旁边的障碍挪走了,手肘位置无所谓了,其他要求不变。",
    ("Dpath", "reason"): "这次只是试压,走得直不直无所谓了,其他要求不变。",
    ("Dforce_hard", "reason"): "换了更结实的桌子,压力那个上限用不着了,其他要求不变。",
    ("Dq1_range", "reason"): "线缆重新走过了,关节 1 不用再限制了,其他要求不变。",
    ("J1", "abs"): "关节 1 尽量待在 {lo} 到 {hi} rad 之间,稍微出去一会儿可以,其他要求不变。",
    ("J1", "unit"): "关节 1 尽量待在 {lo}° 到 {hi}° 之间,稍微出去一会儿可以,其他要求不变。",
    ("J1", "rel"): "关节 1 尽量待在现在的平均角度{span}之间,稍微出去一会儿可以,其他要求不变。",
    ("J2", "abs"): "关节 1 一刻也不许离开 {lo} 到 {hi} rad 这个区间,其他要求不变。",
    ("J2", "unit"): "关节 1 一刻也不许离开 {lo}° 到 {hi}° 这个区间,其他要求不变。",
    ("J2", "rel"): "关节 1 一刻也不许离开现在的平均角度{span}这个区间,其他要求不变。",
    ("J34", "abs"): "关节 {j} 请保持在 {v} rad 左右,其他要求不变。",
    ("J34", "unit"): "关节 {j} 请保持在 {v}° 左右,其他要求不变。",
    ("J34", "rel"): "关节 {j} 比现在的平均角度{dirw} {d} rad,其他要求不变。",
}
D_OBJ = {"elbow": "手肘位置", "path": "路径偏差", "force_hard": "压力上限", "q1_range": "关节 1 范围"}
AUDIT_WHITELIST = ["其他要求不变", "工具离竖直的角度", "工具离竖直的倾角", "手肘的基座", "滑动速度", "压力", "速度", "倾角", "手肘", "关节", "克力"]
AUDIT_WHITELIST_PROMPT = ["硬约束", "软约束", "上限", "下限", "要求项"]
PLANTED_VIOLATION = "压力别超过界型条目给的数,其他要求不变。"        # 冒烟 #14:与系统提示共有「界型条」等片段,审计必须拒绝


def _is_han(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def han_trigrams(text: str, whitelist: list) -> set:
    for w in sorted(whitelist, key=len, reverse=True):
        text = text.replace(w, "|")
    grams, run = set(), []
    for ch in text + "|":
        if _is_han(ch):
            run.append(ch)
            continue
        for i in range(len(run) - 2):
            grams.add("".join(run[i:i + 3]))
        run = []
    return grams


def lexical_audit(prompt: str, sentences: list) -> dict:
    """sentences: [(文本, 层)];层 = "paraphrase" / "prompt_word"。去白名单后取连续 3 个汉字,与系统提示共有片段 → 违规。"""
    P_base, P_ext = han_trigrams(prompt, AUDIT_WHITELIST), han_trigrams(prompt, AUDIT_WHITELIST + AUDIT_WHITELIST_PROMPT)
    viol = []
    for text, layer in sentences:
        wl = AUDIT_WHITELIST + (AUDIT_WHITELIST_PROMPT if layer == "prompt_word" else [])
        g = han_trigrams(text, wl)
        common = sorted(g & (P_ext if layer == "prompt_word" else P_base))
        if common:
            viol.append({"text": text, "layer": layer, "shared": common})
    return {"ok": not viol, "n_sentences": len(sentences), "violations": viol}


def template_layer(fam: str, phrasing: str) -> str:
    return "prompt_word" if (fam in ("H2", "H3", "D", "D-rep") and phrasing == "direct") else "paraphrase"


def all_template_sentences() -> list:
    """审计用:把每个句式的占位符换成代表性的数,得到全部登记句式(B0 用 v3 冻结句式的代表句)。"""
    out = []
    for (fam, ph), tpl in TEMPLATES.items():
        layer = "prompt_word" if (fam in ("H2", "H3", "D") and ph == "direct") else "paraphrase"
        for qd in (["force", "speed", "tilt", "elbow"] if "{qn}" in tpl else [None]):
            kw = {"qn": QN.get(qd, ""), "v": "1.5", "u": UN.get(qd or "force", "N"), "r": "2", "p": "50", "a": "14", "b": "16", "x": "1.5",
                  "t": "3", "obj": "", "lo": "0.80", "hi": "0.90", "span": "往小 0.10 rad 到往小 0.04 rad ", "j": "4", "dirw": "大", "d": "0.10"}
            if fam == "D":
                for o in D_OBJ.values():
                    out.append((tpl.format(**{**kw, "obj": o}), layer))
                break
            out.append((tpl.format(**kw), layer))
    for dim, cur, raws in (("tilt", 15.0, (20.0, 10.0)), ("elbow", 0.10, (0.20, 0.02))):   # B0:v3 冻结句式(P3.edit_text),往两个方向
        for ph in ("absolute", "relative", "unit"):
            for raw in raws:
                out.append((P3.edit_text(dim, ph, cur, raw)[0], "paraphrase"))
    return out


# ═══════════════════════════════════════════ 情形设计(§3.1):族 × 变体 × 说法 × 任务 × 起点
FAMILY_GROUP = {"B0": "B0", "T1": "T", "T2a": "T", "T2b": "T", "H1": "H", "H1-rep": "H", "H2": "H", "H3": "H",
                "A": "AD", "A-rep": "AD", "D": "AD", "D-rep": "AD", "J1": "J", "J2": "J", "J3": "J", "J4": "J"}
PH_NUM = ["abs", "rel", "unit"]
PH_SEM = ["direct", "implicit", "reason"]
PH_ADD = ["abs", "unit", "tol"]
DESIGN = [  # (族, 变体, 说法表, 任务, 起点类型)
    *[("B0", d, ["absolute", "relative", "unit"], A_TASKS, "S0") for d in ("tilt", "elbow")],
    *[("T1", d, PH_NUM, A_TASKS, "S0") for d in ("force", "speed", "tilt", "elbow")],
    *[("T2a", d, PH_NUM, ALL_TASKS, "S0") for d in ("force", "speed", "tilt", "elbow")],
    *[("T2b", d, PH_NUM, ALL_TASKS, "S0-res") for d in ("force", "speed", "tilt", "elbow")],
    *[("H1", v, PH_NUM, ALL_TASKS, "S0") for v in ("force_upper", "speed_upper", "tilt_window", "elbow_lower")],
    *[("H1-rep", v, PH_NUM, A_TASKS, "S0-rep") for v in ("force_upper", "speed_upper")],
    *[("H2", v, PH_SEM, A_TASKS, "S1-soft") for v in ("force_upper", "speed_upper")],
    *[("H3", v, PH_SEM, A_TASKS, "S1-hard") for v in ("force_upper", "speed_upper")],
    ("A", "elbow", PH_ADD, ALL_TASKS, "S-noElbow"), ("A", "speed", PH_ADD, ALL_TASKS, "S-noSpeed"),
    ("A-rep", "speed", PH_ADD, A_TASKS, "S-noSpeed-rep"),
    ("D", "elbow", PH_SEM, ALL_TASKS, "S0"), ("D", "path", PH_SEM, ALL_TASKS, "S0"),
    ("D", "force_hard", PH_SEM, A_TASKS, "S1-hard"), ("D", "q1_range", PH_SEM, A_TASKS, "SJ"),
    ("D-rep", "elbow", PH_SEM, A_TASKS, "S0-rep2"),
    *[("J1", v, ["abs", "unit", "rel"], ALL_TASKS, "S0") for v in ("compat", "tighten", "conflict")],
    *[("J2", v, ["abs", "unit", "rel"], A_TASKS, "S0") for v in ("compat", "tighten")],
    *[("J3", v, ["abs", "unit", "rel"], A_TASKS, "S0") for v in ("offA", "offB")],
    ("J4", "q1", ["abs", "unit", "rel"], ALL_TASKS, "S0"),
]
MAX_ATTEMPTS = 4
MAX_ATTEMPTS_BY_START = {"S0-res": 8}                                    # 审查 R2 第 16 条:T2b 残差带窄,多给几次(按格报告尝试 / 丢弃数)


def max_attempts(start_type: str) -> int:
    return MAX_ATTEMPTS_BY_START.get(start_type, MAX_ATTEMPTS)


def design_cells(dec: dict | None = None) -> list:
    """按 DESIGN 与门决定生成格子(审查 R2 第 5 条):A-speed / A-rep 只用 dec["a_speed_tasks"](D2),A-elbow 只用 dec["a_elbow_tasks"](D3);
    dec["dropped_variants"](D6 第二步)里的 (族, 变体) 去掉,它们的格数平均补给同族其余变体(idx = 1, 2, … 的额外情形,按固定顺序轮流)。"""
    dec = load_decisions() if dec is None else dec
    dropped = {tuple(x) for x in (dec.get("dropped_variants") or [])}
    out, lost = [], {}
    for fam, var, phs, tasks, st in DESIGN:
        if fam in ("A", "A-rep") and var == "speed":
            tasks = [t for t in tasks if t in (dec.get("a_speed_tasks") or [])]
        if fam == "A" and var == "elbow":
            tasks = [t for t in tasks if t in (dec.get("a_elbow_tasks") or [])]
        for task in tasks:
            for ph in phs:
                c = {"family": fam, "variant": var, "phrasing": ph, "task": task, "start_type": st, "idx": 0,
                     "template": f"{fam}|{var}|{ph}|{st}", "group": FAMILY_GROUP[fam], "layer": template_layer(fam, ph)}
                if (fam, var) in dropped:
                    lost[fam] = lost.get(fam, 0) + 1
                    continue
                out.append(c)
    for fam, n in sorted(lost.items()):                                   # 配额补给同族其余变体
        pool = sorted([c for c in out if c["family"] == fam and c["idx"] == 0], key=lambda c: (c["variant"], c["task"], c["phrasing"]))
        if not pool:
            continue
        k = 0
        while k < n:
            base = pool[k % len(pool)]
            out.append({**base, "idx": 1 + k // len(pool), "realloc_from_dropped": True})
            k += 1
    return out


def cell_id(c: dict) -> str:
    return CM.case_id(c["task"], f"{c['family']}-{c['variant']}-{c['phrasing']}", int(c.get("idx", 0)))


def cell_of_case(case: dict) -> dict:
    return {"family": case["family"], "variant": case["variant"], "phrasing": case["phrasing"], "task": case["task"], "start_type": case["start_type"],
            "idx": int(case["id"].split("|")[-1]), "template": case["template"], "group": case["group"], "layer": case["layer"]}


# ───────────────────────────────────────── 起点统计量的来源
def base_start_specs(task: str, dec: dict) -> dict:
    return {"S0": base_spec(task), "S-noElbow": base_spec(task, drop=("elbow",)), "S-noSpeed": base_spec(task, drop=("speed",))}


def provisional_stats(task: str) -> dict:
    """不跑仿真时的近似起点统计量(只用于 draw --provisional 的确定性检查,不能冻结):有包装层 S0 仿真就用它;
    否则用冻结 v3 的 S0 起点仿真(log.npz):force = Fz_true、tilt、q 逐样本;speed = 位置差分;path = 尖端 x;elbow 只有验收均值。"""
    dec = load_decisions()
    cmd, _ = compile_spec(task, base_spec(task), dec)
    for f in sorted(SIMS.glob(f"{task}_*/ext_result.json")) if SIMS.exists() else []:      # 任何同 cmd、无偏差的包装层 S0(含冒烟盐的)
        k = CM.read_json_retry(f.parent / "key.json")
        if k.get("cmd") == cmd and k.get("bias") == P3.norm_bias({}):
            S = load_sim(f.parent)["series"]
            if S is not None:
                return {"source": _rel(f.parent), "provisional": False, **start_stats(S)}
    reg = CM.read_json_retry(ROOT / "results/exp_repair_v3/press/cases_v3.json")
    fd = next(c["labels"]["sims"]["start"] for c in reg["cases"] if c["case_type"] == "edit" and c["task"] == task and c["params"]["start"] == "standard")
    L = np.load(ROOT / fd / "log.npz")
    J = CM.read_json_retry(ROOT / fd / "result.json")
    FS = frozen_series(fd)
    t = FS["t"]
    p = L["p"]
    sp = np.concatenate([[0.0], np.linalg.norm(np.diff(p, axis=0), axis=1) / np.maximum(np.diff(t), 1e-9)]) * 1000.0
    el = float(J["accept"]["elbow"]["value"])
    S = {"t": t, "on": FS["on"], "mid": FS["mid"], "q": FS["q"], "force": L["Fz_true"].astype(np.float64), "speed": sp, "tilt": L["tilt"].astype(np.float64),
         "elbow": np.full(len(t), el), "path": (p[:, 0] - 0.5) * 1000.0}
    return {"source": fd, "provisional": True, **start_stats(S)}


# ───────────────────────────────────────── 抽样工具
def logu(rng, lo: float, hi: float) -> float:
    return float(math.exp(math.log(lo) + rng.random() * (math.log(hi) - math.log(lo))))


def pick(rng, L: list):
    return L[min(len(L) - 1, int(rng.random() * len(L)))]


def round_step(v: float, step: float) -> float:
    return round(round(v / step) * step, 6)


def floor_f(robot: str, d: str) -> float:
    k = 3.0 if d == "elbow" else 4.0
    return max(k * SD_REP[robot][d], {"force": 0.05, "speed": 0.1, "tilt": 0.1, "elbow": 0.001}[d])


def target_dev(stats: dict, q: str, tg: float) -> float:
    w = "mid" if q in ("force", "speed", "path") else "on"
    return stats[q][w]["mean"] - tg


def tol_text(d: str, ph: str, raw: float, kind: str) -> tuple:
    """容差句的数:abs → 显示精度取整;unit → 另一单位;返回 (显示串, 单位串, 真值, 显示的数)。kind = "T1"(放宽,粗精度)/ "T2"(收紧)。"""
    if ph == "abs":
        step = ({"force": 0.1, "speed": 1.0, "tilt": 1.0, "elbow": 0.01} if kind == "T1" else {"force": 0.05, "speed": 0.1, "tilt": 0.1, "elbow": 0.001})[d]
        v = max(round_step(raw, step), step)
        return gstr(v), UN[d], v, v
    if d == "force":
        gf = max(int(round(raw / GF / 10.0) * 10), 10)
        return str(gf), "克力", gf * GF, gf
    if d == "speed":
        step = 0.1 if kind == "T1" else 0.01
        cms = max(round_step(raw / 10.0, step), step)
        return gstr(cms), "cm/s", round(cms * 10.0, 6), cms
    if d == "tilt":
        rad = max(round(math.radians(raw), 3), 0.001)
        return f"{rad:.3f}", "rad", math.degrees(rad), rad
    mm = max(int(round(raw * 1000.0)), 1)
    return str(mm), "mm", mm / 1000.0, mm


def gt_change(op: str, key: tuple, rid: str, fields: dict, accept: dict | None = None) -> dict:
    return {"op": op, "key": list(key), "id": rid, "fields": fields, "accept": accept or {}}


def gf_accept(gf: int) -> list:
    return [gf * 0.0098 - 0.005, gf * 0.00981 + 0.005]


# ───────────────────────────────────────── 第一阶段:起点参数(起点仿真之前)
def start_params(c: dict, rng, base: dict, dec: dict) -> dict:
    """返回 {"spec", "exec", "bias", "params"};base = 该任务 S0 / S-noElbow / S-noSpeed 的统计量(provisional 或包装层仿真)。"""
    task, fam, var, st = c["task"], c["family"], c["variant"], c["start_type"]
    robot, tg = TASKS[task]["robot"], targets_of(task)
    s0 = base["S0"]
    P: dict = {}
    if st in ("S0", "S-noElbow", "S-noSpeed"):
        spec = base_spec(task, drop={"S0": (), "S-noElbow": ("elbow",), "S-noSpeed": ("speed",)}[st])
        return {"spec": spec, "exec": zero_exec(), "bias": {}, "params": P}
    if st == "S0-res":                                                      # T2b:被收紧维的隐藏偏差 + 理想补偿 + 残差偏移
        d = var
        pb = P3.draw_bias(rng, d, tg)
        f, old = floor_f(robot, d), default_tol(d, tg[d])
        lo, hi = 2.0 * f, 0.8 * old
        if lo >= hi:
            return {"discard": "no_residual_band"}
        r0 = lo + (0.35 + 0.3 * rng.random()) * (hi - lo)                 # 审查 R2 第 16 条:瞄准残差带中部(带很窄时少出带)
        sgn = -1.0 if rng.random() < 0.5 else 1.0
        dbase = target_dev(s0, d, tg[d])
        k_ = COMP_OF[d]
        if d == "force":
            comp = (tg[d] + sgn * r0 - dbase) / pb["k_f"] - tg[d]          # 实现 ≈ k_f × 命令(force_gain = 1/k_f;见 P3.ideal_exec)
        elif d == "speed":
            comp = (tg[d] + sgn * r0 - dbase) / pb["k_v"] - tg[d]
        elif d == "tilt":
            comp = sgn * r0 - dbase - pb["tilt_err"]
        else:
            comp = sgn * r0 - dbase - pb["elbow_err"]
        ex = zero_exec()
        ex[k_] = clamp_comp(k_, round(comp, 4))
        P.update({"bias_params": {k2: v for k2, v in pb.items() if k2 != "bias"}, "r0_design": r0, "r0_sign": sgn, "dbase": dbase, "floor": f})
        return {"spec": base_spec(task), "exec": ex, "bias": pb["bias"], "params": P}
    if st in ("S0-rep", "S-noSpeed-rep", "S0-rep2"):
        dims = {"S0-rep": ["force" if var == "force_upper" else "speed"], "S-noSpeed-rep": ["force"], "S0-rep2": ["elbow", "force"]}[st]
        p: dict = {}
        for d in dims:
            pb = P3.draw_bias(rng, d, tg)
            p.update({k2: v for k2, v in pb.items() if k2 != "bias"})
        bias = P3.bias_of(p)
        ex = P3.ideal_exec(p, tg)
        P["bias_params"] = p
        spec = base_spec(task, drop=("speed",) if st == "S-noSpeed-rep" else ())
        return {"spec": spec, "exec": ex, "bias": bias, "params": P}
    q = "force" if var.startswith("force") else "speed"
    if st == "S1-soft":                                                     # H2:soft 上限 X,一半在 p95–max 之间,一半在 max 之上
        on = s0[q]["on"]
        half = "between" if rng.random() < 0.5 else "above"
        u = rng.random()
        step = 0.1 if q == "force" else 1.0
        if half == "between":                                            # 审查 R2 第 11 条:在显示网格上取 [ceil(p95), floor(max)] 内的点,没有就重抽
            g_lo, g_hi = math.ceil(on["p95"] / step - 1e-9), math.floor(on["max"] / step + 1e-9)
            if g_lo > g_hi:
                return {"discard": "h2_between_empty"}
            X = round((g_lo + min(int(u * (g_hi - g_lo + 1)), g_hi - g_lo)) * step, 6)
        else:
            X = round(math.ceil((on["max"] + (0.1 + 0.9 * u) * DELTA[q]) / step - 1e-9) * step, 6)
        spec = base_spec(task)
        spec["requirements"][f"{q}_limit"] = {"quantity": q, "kind": "upper", "upper": X, "strict": "soft"}
        P.update({"X": X, "half": half})
        return {"spec": spec, "exec": zero_exec(), "bias": {}, "params": P}
    if st == "S1-hard":                                                     # H3 / D-force_hard:hard 上限 = 起点 on 最大值 + 0.5Δ
        on = s0[q]["on"]
        step = 0.1 if q == "force" else 1.0
        X = round(math.ceil((on["max"] + 0.5 * DELTA[q]) / step) * step, 6)
        spec = base_spec(task)
        spec["requirements"][f"{q}_limit"] = {"quantity": q, "kind": "upper", "upper": X, "strict": "hard"}
        P["X"] = X
        return {"spec": spec, "exec": zero_exec(), "bias": {}, "params": P}
    if st == "SJ":                                                          # D-q1_range:S0 + q1 soft 相容范围
        on = s0["q1"]["on"]
        lo, hi = math.floor((on["min"] - 0.05) * 100) / 100, math.ceil((on["max"] + 0.05) * 100) / 100
        spec = base_spec(task)
        spec["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(lo, 6), "upper": round(hi, 6), "strict": "soft"}
        return {"spec": spec, "exec": zero_exec(), "bias": {}, "params": P}
    raise ValueError(f"未知起点 {st}")


# ───────────────────────────────────────── 第二阶段:编辑句、真值、标准答案(起点仿真之后)
def tighten_interval(st_stats: dict, kin: dict | None, ua: float, us: float) -> dict:
    """J1 / J2「收紧可行」的 q1 区间(审查 R2 第 6 条):宽 w = 起点滑动段 q1 扫过的范围 + 0.04(区间必须装得下整条轨迹),
    离起点均值 a ∈ [0.01, 0.03](不含均值);方向取 E_exec 余量大的一侧。可行性:起点、中点、终点三处的 q1 统一平移 s 之后
    都落在 [lo, hi] ∩ E_exec(该点) 里,s 的可行区间长度 ≥ 0.01 rad;不满足 → feasible = False(抽样时重抽)。没有扫描文件 → feasible = None。"""
    on = st_stats["q1"]["on"]
    pts = on.get("pts")
    sweep = float(on["max"] - on["min"])
    w = sweep + 0.04
    a = 0.01 + 0.02 * ua
    ex = (kin or {}).get("exec") or {}
    env_u = (ex.get("union") or {}).get("q1")
    side = (1.0 if (env_u[1] - on["mean"]) >= (on["mean"] - env_u[0]) else -1.0) if env_u else (1.0 if us < 0.5 else -1.0)
    lo, hi = (on["mean"] + a, on["mean"] + a + w) if side > 0 else (on["mean"] - a - w, on["mean"] - a)
    out = {"lo": lo, "hi": hi, "side": side, "a": a, "w": w, "sweep": sweep, "feasible": None, "shift": None, "rule": "exclude_mean"}
    pp = ex.get("per_point")

    def shift_room(lo_, hi_):
        smin, smax = -math.inf, math.inf
        for n in ("start", "mid", "end"):
            e_lo, e_hi = pp[n]["q1"]
            smin = max(smin, max(lo_, e_lo) - pts[n])
            smax = min(smax, min(hi_, e_hi) - pts[n])
        return [smin, smax]
    if pp and pts:
        out["shift"] = shift_room(lo, hi)
        out["feasible"] = bool(out["shift"][1] - out["shift"][0] >= 0.01)
        if not out["feasible"]:
            # 退路(2026-10-25 冒烟发现:iiwa_a 的 E_exec 平移余量 ≈ 0.07 rad,小于「不含均值」所需的半个扫过范围 + a):
            # 区间宽度不变、以平移 δ ∈ [0.04, 0.06] 后的轨迹为中心(起点轨迹的远端越界 δ − 0.02 ≥ 0.02 rad,仍需改执行),方向取余量大的一侧
            dl = 0.04 + 0.02 * ua
            best = None
            for sd in (1.0, -1.0):
                lo2, hi2 = on["min"] + sd * dl - 0.02, on["max"] + sd * dl + 0.02
                sh = shift_room(lo2, hi2)
                if sh[1] - sh[0] >= 0.01 and (best is None or sh[1] - sh[0] > best[2][1] - best[2][0]):
                    best = (lo2, hi2, sh, sd)
            if best is not None:
                out.update({"lo": best[0], "hi": best[1], "shift": best[2], "side": best[3], "delta": dl, "feasible": True, "rule": "shift_partial"})
    return out


def kin_env(task: str) -> dict | None:
    f = KIN / f"{task}.json"
    return CM.read_json_retry(f) if f.exists() else None


def finalize(c: dict, rng, st_stats: dict, start: dict, dec: dict, kin: dict | None) -> dict:
    """返回 {"text", "shown", "truth", "gt_spec", "changes", "accept_alt", "notes"} 或 {"discard": 原因}。"""
    task, fam, var, ph = c["task"], c["family"], c["variant"], c["phrasing"]
    robot, tg = TASKS[task]["robot"], targets_of(task)
    spec0 = start["spec"]
    gt = copy.deepcopy(spec0)
    R = gt["requirements"]
    notes: dict = {}
    if fam == "B0":
        p = P3.edit_draw(task, var, ph, "standard")(rng, 0)
        R[var]["target"] = float(p["new_value"])
        return {"text": p["text"], "shown": p["shown"], "truth": p["new_value"], "gt_spec": gt,
                "changes": [gt_change("modify", (var, "target"), var, {"target": p["new_value"]})], "accept_alt": []}
    if fam in ("T1", "T2a", "T2b"):
        d = var
        old = spec0["requirements"][d]["tol"]
        kind = "T1" if fam == "T1" else "T2"
        acc = {}
        if fam == "T1":
            r = pick(rng, [1.5, 2.0, 2.5, 3.0])
            raw = old * r
            notes["r"] = r
        else:
            f = floor_f(robot, d)
            if fam == "T2a":
                d0 = abs(target_dev(st_stats, d, tg[d]))
                lo, hi = max(f, 1.3 * d0 + 2.0 * SD_REP[robot][d]), 0.7 * old
                notes.update({"d0": d0, "floor": f})
            else:
                r0 = abs(target_dev(st_stats, d, tg[d]))
                if st_stats.get("proxy_for") == "S0-res":                      # provisional 抽样:没有 S0-res 起点仿真,用设计残差代替(只用于确定性检查)
                    r0 = start["params"]["r0_design"]
                lo, hi = f, r0 / 1.5
                notes.update({"r0": r0, "floor": f})
            if not lo < hi:
                return {"discard": "no_room"}
            raw = logu(rng, lo, hi)
            notes["range"] = [lo, hi]
        if ph == "rel":
            if fam == "T1":
                r = notes["r"]
                text = TEMPLATES[("T1", "rel")].format(qn=QN_T[d], r=gstr(r))
                truth, shown = round(old * r, 6), r
            else:
                pct = int(round(raw / old * 100.0 / 5.0) * 5)
                pct = min(max(pct, 5), 95)
                text = TEMPLATES[("T2", "rel")].format(qn=QN_T[d], p=pct)
                truth, shown = round(old * pct / 100.0, 6), pct
        else:
            vs, us, truth, shown = tol_text(d, ph, raw, kind)
            text = TEMPLATES[(kind, ph)].format(qn=QN_T[d], v=vs, u=us).replace(" °", "°")
            if us == "克力":
                acc["tol"] = gf_accept(shown)
        R[d]["tol"] = truth
        return {"text": text, "shown": shown, "truth": truth, "gt_spec": gt, "notes": notes,
                "changes": [gt_change("modify", (d, "target"), d, {"tol": truth}, acc)], "accept_alt": []}
    if fam in ("H1", "H1-rep"):
        q = var.split("_")[0]
        on = st_stats[q]["on"]
        acc = {}
        if q in ("force", "speed"):
            offs = dec["force_offsets"] if q == "force" else dec["speed_offsets"]
            o = pick(rng, offs)
            raw = on["max"] + o
            notes.update({"offset": o, "M": on["max"]})
            tmpl = "H1force" if q == "force" else "H1speed"
            if ph == "abs":
                v = round_step(raw, 0.1 if q == "force" else 1.0)
                text, truth, shown = TEMPLATES[(tmpl, "abs")].format(v=gstr(v), u=UN[q]), v, v
            elif ph == "rel":
                pct = max(int(round((raw / tg[q] - 1.0) * 100.0 / 5.0) * 5), 5)
                text, truth, shown = TEMPLATES[(tmpl, "rel")].format(p=pct), round(tg[q] * (1 + pct / 100.0), 6), pct
            elif q == "force":
                gf = int(round(raw / GF / 10.0) * 10)
                text, truth, shown = TEMPLATES[(tmpl, "unit")].format(v=gf, u="克力"), gf * GF, gf
                acc["upper"] = gf_accept(gf)
            else:
                cms = round_step(raw / 10.0, 0.1)
                text, truth, shown = TEMPLATES[(tmpl, "unit")].format(v=gstr(cms), u="cm/s"), round(cms * 10.0, 6), cms
            item = {"quantity": q, "kind": "upper", "upper": truth, "strict": "hard"}
        elif q == "tilt":
            dl = pick(rng, dec["tilt_deltas"])
            a, b = on["min"] - dl, on["max"] + dl
            if b - a < 0.3:
                mid_, a, b = 0.5 * (a + b), 0.5 * (a + b) - 0.15, 0.5 * (a + b) + 0.15
                notes["delta_clamped"] = True
            notes.update({"delta": dl, "min": on["min"], "max": on["max"]})
            if ph == "abs":
                a_, b_ = round_step(a, 0.1), round_step(b, 0.1)
                text, truth, shown = TEMPLATES[("H1tilt", "abs")].format(a=gstr(a_), b=gstr(b_), u="°"), [a_, b_], [a_, b_]
            elif ph == "rel":
                half = math.ceil(max(tg["tilt"] - on["min"], on["max"] - tg["tilt"]) * 2.0) / 2.0
                x = max(half + dl, 0.5)
                text, truth, shown = TEMPLATES[("H1tilt", "rel")].format(x=gstr(x)), [tg["tilt"] - x, tg["tilt"] + x], x
            else:
                ra, rb = round(math.radians(a), 3), round(math.radians(b), 3)
                text, truth, shown = TEMPLATES[("H1tilt", "unit")].format(a=f"{ra:.3f}", b=f"{rb:.3f}", u="rad"), [math.degrees(ra), math.degrees(rb)], [ra, rb]
            item = {"quantity": "tilt", "kind": "range", "lower": round(truth[0], 6), "upper": round(truth[1], 6), "strict": "hard"}
        else:
            o = pick(rng, dec["elbow_offsets"])
            raw = on["min"] + o
            notes.update({"offset": o, "min": on["min"]})
            if ph == "abs":
                v = round(raw, 3)
                text, truth, shown = TEMPLATES[("H1elbow", "abs")].format(v=f"{v:.3f}", u="m"), v, v
            elif ph == "rel":
                xcm = int(round((tg["elbow"] - raw) * 100.0)) or (-1 if raw > tg["elbow"] else 1)
                if xcm > 0:
                    text, truth = TEMPLATES[("H1elbow", "rel")].format(x=xcm), round(tg["elbow"] - xcm / 100.0, 6)
                else:
                    text, truth = TEMPLATES[("H1elbow", "rel_neg")].format(x=-xcm), round(tg["elbow"] - xcm / 100.0, 6)
                shown = xcm
            else:
                mm = int(round(raw * 1000.0))
                text, truth, shown = TEMPLATES[("H1elbow", "unit")].format(v=mm, u="mm"), mm / 1000.0, mm
            item = {"quantity": "elbow", "kind": "lower", "lower": truth, "strict": "hard"}
        rid = f"{q}_hard"
        R[rid] = item
        return {"text": text, "shown": shown, "truth": truth, "gt_spec": gt, "notes": notes,
                "changes": [gt_change("add", (q, "bound"), rid, dict(item), acc)], "accept_alt": []}
    if fam in ("H2", "H3"):
        q = var.split("_")[0]
        rid = f"{q}_limit"
        new_strict = "hard" if fam == "H2" else "soft"
        R[rid]["strict"] = new_strict
        text = TEMPLATES[(fam, ph)].format(qn=QN[q])
        return {"text": text, "shown": None, "truth": new_strict, "gt_spec": gt,
                "changes": [gt_change("modify", (q, "bound"), rid, {"strict": new_strict})], "accept_alt": []}
    if fam in ("A", "A-rep"):
        q = var
        tval = tg[q]
        tol = default_tol(q, tval)
        if q == "elbow":
            if ph == "abs":
                text, shown = TEMPLATES[("Aelbow", "abs")].format(v=f"{tval:.2f}"), tval
            elif ph == "unit":
                text, shown = TEMPLATES[("Aelbow", "unit")].format(v=int(round(tval * 1000))), int(round(tval * 1000))
            else:
                tol = 0.03
                text, shown = TEMPLATES[("Aelbow", "tol")].format(v=f"{tval:.2f}", t=3), tval
        else:
            if ph == "abs":
                text, shown = TEMPLATES[("Aspeed", "abs")].format(v=gstr(tval)), tval
            elif ph == "unit":
                text, shown = TEMPLATES[("Aspeed", "unit")].format(v=gstr(tval / 10.0)), tval / 10.0
            else:
                tol = 3.0 if tval >= 20.0 else 2.0                          # 与缺省容差(0.2 × 目标)不同,才区分得出「写了容差」
                text, shown = TEMPLATES[("Aspeed", "tol")].format(v=gstr(tval), t=gstr(tol)), tval
        item = {"quantity": q, "kind": "target", "target": tval, "tol": round(tol, 6)}
        R[q] = item
        return {"text": text, "shown": shown, "truth": [tval, tol], "gt_spec": gt,
                "changes": [gt_change("add", (q, "target"), q, dict(item))], "accept_alt": []}
    if fam in ("D", "D-rep"):
        obj = var
        rid = {"elbow": "elbow", "path": "path", "force_hard": "force_limit", "q1_range": "q1_range"}[obj]
        key = item_key(spec0["requirements"][rid])
        del R[rid]
        if ph == "direct":
            text = TEMPLATES[("D", "direct")].format(obj=D_OBJ[obj])
        else:
            text = TEMPLATES[(f"D{obj}", ph)]
        alt = ["elbow_comp_inert_change_ok"] if fam == "D-rep" else []
        return {"text": text, "shown": None, "truth": "delete", "gt_spec": gt, "changes": [gt_change("delete", key, rid, {})], "accept_alt": alt}
    if fam in ("J1", "J2"):
        on = st_stats["q1"]["on"]
        m_disp = round(on["mean"], 3)
        if var == "compat":
            lo, hi = on["min"] - 0.05, on["max"] + 0.05
        elif var == "tighten":
            iv = tighten_interval(st_stats, kin, rng.random(), rng.random())
            notes["tighten"] = {k_: iv.get(k_) for k_ in ("side", "a", "w", "sweep", "shift", "feasible", "rule", "delta")}
            if iv["feasible"] is None:
                notes["kin_missing"] = True
            elif not iv["feasible"]:
                return {"discard": "tighten_outside_E_exec"}
            lo, hi = iv["lo"], iv["hi"]
        else:
            k_env = ((kin or {}).get("kin") or {}).get("union", {}).get("q1")
            side = 1.0 if rng.random() < 0.5 else -1.0
            if k_env:
                lo, hi = (k_env[1] + 0.08, k_env[1] + 0.14) if side > 0 else (k_env[0] - 0.14, k_env[0] - 0.08)
                notes["E_kin_q1"] = k_env
            else:
                lo, hi = (on["max"] + 0.6, on["max"] + 0.66) if side > 0 else (on["min"] - 0.66, on["min"] - 0.6)
                notes["kin_missing"] = True
        strict = "soft" if fam == "J1" else "hard"
        if ph == "abs":
            lo_, hi_ = round(lo, 2), round(hi, 2)
            text, truth, shown = TEMPLATES[(fam, "abs")].format(lo=f"{lo_:.2f}", hi=f"{hi_:.2f}"), [lo_, hi_], [lo_, hi_]
        elif ph == "unit":
            dl, dh = round(math.degrees(lo), 1), round(math.degrees(hi), 1)
            text, truth, shown = TEMPLATES[(fam, "unit")].format(lo=gstr(dl), hi=gstr(dh)), [math.radians(dl), math.radians(dh)], [dl, dh]
        else:
            a, b = round(lo - m_disp, 2) or -0.01, round(hi - m_disp, 2) or 0.01
            w_ = lambda x: f"往{'大' if x > 0 else '小'} {abs(x):.2f} rad"
            span = f"{w_(a)} 到{w_(b)} "
            text, truth, shown = TEMPLATES[(fam, "rel")].format(span=span), [m_disp + a, m_disp + b], [a, b]
            notes["mean_shown"] = m_disp
        item = {"quantity": "q1", "kind": "range", "lower": round(truth[0], 6), "upper": round(truth[1], 6), "strict": strict}
        if fam == "J1" and var == "conflict" and kin is not None and kin_proof(item, kin) is None:   # 审查 R2 第 2 条:取整之后仍须可证明
            return {"discard": "conflict_not_proven_after_rounding"}
        R["q1_range"] = item
        alt = ["declare_q1_or_elbow"] if (fam == "J1" and var == "conflict") else []
        return {"text": text, "shown": shown, "truth": truth, "gt_spec": gt, "notes": notes,
                "changes": [gt_change("add", ("q1", "bound"), "q1_range", dict(item))], "accept_alt": alt}
    if fam in ("J3", "J4"):
        j = 4 if fam == "J3" else 1
        qj = f"q{j}"
        on = st_stats[qj]["on"]
        m_disp = round(on["mean"], 3)
        side = 1.0 if rng.random() < 0.5 else -1.0
        if fam == "J3" and var == "offA":
            raw = on["mean"] + side * 0.15
        elif fam == "J3":
            k_env = ((kin or {}).get("kin") or {}).get("union", {}).get(qj)
            if k_env:                                                    # 审查 R2 第 2 条:界外 tol + 余量 + 取整余量(0.05 + 0.05 + 0.03)
                raw = k_env[1] + OFFB_GAP if side > 0 else k_env[0] - OFFB_GAP
                notes["E_kin_q4"] = k_env
            else:
                raw = on["mean"] + side * 0.6
                notes["kin_missing"] = True
        else:
            lo_d, hi_d = dec["j4_dist"]
            ex_env = ((kin or {}).get("exec") or {}).get("union", {}).get(qj)
            dist = lo_d + rng.random() * (hi_d - lo_d)
            if ex_env:
                side = 1.0 if (ex_env[1] - on["mean"]) >= (on["mean"] - ex_env[0]) else -1.0
                notes["E_exec_q1"] = ex_env
            else:
                notes["kin_missing"] = True
            raw = on["mean"] + side * dist
            notes["dist"] = dist
            notes["dist_lt_tol"] = bool(dist < JOINT_TOL)                 # 审查 R2 第 13 条:距离 < 容差的单报
            if ex_env and not (ex_env[0] + 0.01 <= raw <= ex_env[1] - 0.01):
                return {"discard": "j4_outside_E_exec"}
        if ph == "abs":
            v = round(raw, 2)
            text, truth, shown = TEMPLATES[("J34", "abs")].format(j=j, v=f"{v:.2f}"), v, v
        elif ph == "unit":
            dg = round(math.degrees(raw), 1)
            text, truth, shown = TEMPLATES[("J34", "unit")].format(j=j, v=gstr(dg)), math.radians(dg), dg
        else:
            dd = round(raw - m_disp, 2) or (0.01 * side)
            text = TEMPLATES[("J34", "rel")].format(j=j, dirw="大" if dd > 0 else "小", d=f"{abs(dd):.2f}")
            truth, shown = round(m_disp + dd, 6), dd
            notes["mean_shown"] = m_disp
        item = {"quantity": qj, "kind": "target", "target": round(truth, 6), "tol": JOINT_TOL}
        if fam == "J3" and var == "offB" and kin is not None and kin_proof(item, kin) is None:   # 审查 R2 第 2 条:取整之后仍须可证明
            return {"discard": "offB_not_proven_after_rounding"}
        R[qj] = item
        return {"text": text, "shown": shown, "truth": truth, "gt_spec": gt, "notes": notes,
                "changes": [gt_change("add", (qj, "target"), qj, dict(item))], "accept_alt": []}
    raise ValueError(f"未知族 {fam}")


def make_case(c: dict, idx: int, attempt: int, base: dict, dec: dict, start_stats_fn, kin: dict | None) -> dict:
    """抽一个情形(两阶段)。start_stats_fn(case_dict, start) → 起点统计量(包装层仿真或 provisional);返回情形或 {"discard": …}。"""
    cid = CM.case_id(c["task"], f"{c['family']}-{c['variant']}-{c['phrasing']}", idx)
    rp = CM.seeded_rng("eb2", cid, attempt, "p")
    st = start_params(c, rp, base, dec)
    if "discard" in st:
        return {"id": cid, "discard": st["discard"], "attempt": attempt}
    case = {"id": cid, "task": c["task"], "robot": TASKS[c["task"]]["robot"], "family": c["family"], "group": c["group"], "variant": c["variant"],
            "phrasing": c["phrasing"], "layer": c["layer"], "template": c["template"], "start_type": c["start_type"], "attempt": attempt,
            "start": {"spec": st["spec"], "exec": st["exec"], "bias": st["bias"], "params": st["params"]}}
    sstats = start_stats_fn(case, case["start"])
    if isinstance(sstats, dict) and sstats.get("discard"):
        return {"id": cid, "discard": sstats["discard"], "attempt": attempt}
    case["start"]["stats_source"] = sstats.get("source")
    case["provisional"] = bool(sstats.get("provisional"))
    rf = CM.seeded_rng("eb2", cid, attempt, "f")
    fin = finalize(case, rf, sstats, case["start"], dec, kin)
    if "discard" in fin:
        return {"id": cid, "discard": fin["discard"], "attempt": attempt}
    case["edit"] = {"text": fin["text"], "shown": fin["shown"], "truth": fin["truth"], "notes": fin.get("notes") or {}}
    case["gt"] = {"spec": fin["gt_spec"], "changes": fin["changes"], "accept_alt": fin["accept_alt"]}
    return case


def draw_registry(start_stats_fn, base_of, dec: dict, cells: list | None = None, tag: str = "") -> dict:
    """按 DESIGN 抽全部情形(每格 1 个情形;每个情形最多 MAX_ATTEMPTS 次尝试)。start_stats_fn 决定起点统计量来源。"""
    cells = design_cells(dec) if cells is None else cells
    cases, discards, attempts_by_cell, got_cells = [], {}, {}, set()
    for c in cells:
        base = base_of(c["task"])
        kin = kin_env(c["task"])
        got = None
        ck = c["template"] + "|" + c["task"] + f"|{int(c.get('idx', 0))}"
        for a in range(max_attempts(c["start_type"])):
            r = make_case(c, int(c.get("idx", 0)), a, base, dec, start_stats_fn, kin)
            attempts_by_cell[ck] = a + 1
            if "discard" in r:
                discards.setdefault(ck, []).append({"attempt": a, "why": r["discard"], "stage": "draw"})
                continue
            got = r
            break
        if got is not None:
            cases.append(got)
            got_cells.add(ck)
    return {"version": KEY_V, "frozen": False, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag,
            "meta": {"templates": {f"{k[0]}|{k[1]}": v for k, v in TEMPLATES.items()}, "audit_whitelist": AUDIT_WHITELIST,
                     "audit_whitelist_prompt": AUDIT_WHITELIST_PROMPT, "decisions": dec, "system_prompt_sha16": hashlib.sha256(system_prompt(dec).encode()).hexdigest()[:16],
                     "design": [list(x[:2]) + [x[2], x[3], x[4]] for x in DESIGN], "n_cells": len(cells)},
            "cases": cases, "discards": discards, "attempts_by_cell": attempts_by_cell, "cells_lost": sorted(set(attempts_by_cell) - got_cells)}


# ═══════════════════════════════════════════ 运动学扫描(§4.3,只算逆解)
def kin_scan(task: str, reduced: bool = False) -> dict:
    """每个任务:滑动直线起点 / 中点 / 终点 × 倾角(目标 ± 容差,5 档)× 手肘目标(目标 ± 容差,5 档),
    E_exec:方位角与绕轴转角取执行器的值;E_kin:方位角 24 档 × 绕轴转角 12 档(reduced:3 × 2,只作代码路径检查)。
    只保留实际手肘在 目标 ± 容差 内的解;记录 q1、q3、q4、手肘 y 的逐点范围与并集,以及 E_exec 上 dq1 / d手肘 的斜率。"""
    mod = PX.load_testbed()
    import mujoco
    robot = TASKS[task]["robot"]
    tg = targets_of(task)
    scene, build, q_ready = mod.setup_robot(robot)
    m, d, lim = build()
    site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "attachment_site")
    d.qpos[:7] = q_ready
    mujoco.mj_forward(m, d)
    _, R_r, _ = mod.mj_tcp(m, d, site)
    V = mod.vertical_R(R_r)
    tilts = np.linspace(tg["tilt"] - 3.0, tg["tilt"] + 3.0, 5)
    elbows = np.linspace(tg["elbow"] - 0.04, tg["elbow"] + 0.04, 5)
    L = 0.10
    pts = {"start": np.array([0.0, -L / 2]), "mid": np.array([0.0, 0.0]), "end": np.array([0.0, L / 2])}
    c3 = lambda w: mod.ORIGIN + np.array([w[0], w[1], mod.TIP_R])

    def Rz(a):
        ca, sa = math.cos(a), math.sin(a)
        return np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])

    def solve(R_t, ely):
        q, sol = q_ready.copy(), {}
        pre = mod.ORIGIN + np.array([pts["start"][0], pts["start"][1], mod.TIP_R + mod.HOVER])
        q = PX.ik_ext(mod, m, site, lim, pre, R_t, q, elbow_y=ely)
        if q is None:
            return None
        for name in ("start", "mid", "end"):
            q = PX.ik_ext(mod, m, site, lim, c3(pts[name]), R_t, q, elbow_y=ely)
            if q is None:
                return None
            e_y = mod.elbow_y_of(m, q)
            if abs(e_y - tg["elbow"]) > 0.04 + 1e-9:
                return None
            sol[name] = {"q": q.copy(), "elbow": e_y}
        return sol

    def scan(azs, rolls):
        env = {n: {k: [math.inf, -math.inf] for k in ("q1", "q3", "q4", "elbow")} for n in pts}
        n_ok, n_all, samples = 0, 0, []
        for az in azs:
            for ro in rolls:
                for tl in tilts:
                    R_t = Rz(az) @ mod.Ry(math.radians(tl)) @ V @ Rz(ro)
                    for ely in elbows:
                        n_all += 1
                        s = solve(R_t, float(ely))
                        if s is None:
                            continue
                        n_ok += 1
                        for n, v in s.items():
                            for k, x in (("q1", v["q"][0]), ("q3", v["q"][2]), ("q4", v["q"][3]), ("elbow", v["elbow"])):
                                env[n][k][0], env[n][k][1] = min(env[n][k][0], float(x)), max(env[n][k][1], float(x))
                        samples.append((float(ely), float(s["mid"]["q"][0]), float(s["mid"]["elbow"])))
        union = {k: [min(env[n][k][0] for n in pts), max(env[n][k][1] for n in pts)] for k in ("q1", "q3", "q4", "elbow")}
        return {"per_point": env, "union": union, "n_ok": n_ok, "n_all": n_all, "samples": samples}

    t0 = time.time()
    ex = scan([0.0], [0.0])
    sl = None
    if len(ex["samples"]) >= 2:
        e_act = np.array([s[2] for s in ex["samples"]])
        q1s = np.array([s[1] for s in ex["samples"]])
        if e_act.std() > 1e-6:
            sl = float(np.polyfit(e_act, q1s, 1)[0])
    ex["slope_q1_per_elbow"] = sl
    nz, nr = (3, 2) if reduced else (24, 12)
    kn = scan(list(np.linspace(0, 2 * math.pi, nz, endpoint=False)), list(np.linspace(0, 2 * math.pi, nr, endpoint=False)))
    out = {"task": task, "robot": robot, "reduced": reduced, "grid": {"tilts": tilts.tolist(), "elbows": elbows.tolist(), "az": nz, "roll": nr},
           "exec": {k: v for k, v in ex.items() if k != "samples"}, "kin": {k: v for k, v in kn.items() if k != "samples"},
           "wall_s": time.time() - t0, "testbed_sha16": PX.SNAP_SHA16, "wrapper_sha16": PX.WRAPPER_SHA16}
    return out


def kin_proof(it: dict, kin: dict | None) -> dict | None:
    """运动学不可达证明:关节角 / 手肘要求与 E_kin 相距 ≥ 余量(关节 0.05 rad、手肘 0.01 m)。界型:三个点都与该点包络分离;target:与并集分离。"""
    if kin is None:
        return None
    q = it["quantity"]
    k = q if q in ("q1", "q3", "q4") else ("elbow" if q == "elbow" else None)
    if k is None:
        return None
    mg = 0.01 if k == "elbow" else 0.05
    K = kin["kin"]

    def gap(lo, hi, env):
        return max(lo - env[1], env[0] - hi)
    if it["kind"] == "target":
        g = gap(it["target"] - it["tol"], it["target"] + it["tol"], K["union"][k])
        return {"kind": "kinematic", "gap": g, "margin": mg} if g >= mg else None
    lo, hi = it.get("lower", -math.inf), it.get("upper", math.inf)
    gaps = [gap(lo, hi, K["per_point"][n][k]) for n in ("start", "mid", "end")]
    return {"kind": "kinematic", "gaps": gaps, "margin": mg} if min(gaps) >= mg else None


def kin_confirm(task: str, it: dict, dec: dict, n: int = 240, seed: int = 20261025) -> dict:
    """运动学证明的采样复核(审查 R2 第 15 条):随机起点(关节限位内均匀)× 随机方位角 / 绕轴转角 / 倾角(目标 ± 容差)/ 手肘目标(± 容差),
    逆解链(起点上方 → 起点 → 中点 → 终点)同时把要求的关节角拉向要求;任一条链在三处都满足要求、手肘在容差内 → found = True(证明不成立)。
    只对已证明(C3p / C4p)的运动学情形跑;固定种子,确定性。"""
    mod = PX.load_testbed()
    import mujoco
    robot = TASKS[task]["robot"]
    tg = targets_of(task)
    scene, build, q_ready = mod.setup_robot(robot)
    m, d, lim = build()
    site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "attachment_site")
    d.qpos[:7] = q_ready
    mujoco.mj_forward(m, d)
    _, R_r, _ = mod.mj_tcp(m, d, site)
    V = mod.vertical_R(R_r)
    q = it["quantity"]
    j = int(q[1:]) if q in JQ else None
    jt = None
    if j is not None:
        jt = ({"j": j, "mode": "target", "target": it["target"]} if it["kind"] == "target"
              else {"j": j, "mode": "range", "lb": it.get("lower", -math.inf), "ub": it.get("upper", math.inf)})

    def sat(qv, ely_act):
        if j is not None:
            x = qv[j - 1]
            if it["kind"] == "target":
                return abs(x - it["target"]) <= it["tol"]
            return it.get("lower", -math.inf) <= x <= it.get("upper", math.inf)
        if q == "elbow":
            return (it.get("lower", -math.inf) <= ely_act <= it.get("upper", math.inf)) if it["kind"] != "target" else abs(ely_act - it["target"]) <= it["tol"]
        return False

    def Rz(a):
        ca, sa = math.cos(a), math.sin(a)
        return np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
    rng = np.random.default_rng(seed)
    L = 0.10
    pts = [np.array([0.0, -L / 2, mod.TIP_R + mod.HOVER]), np.array([0.0, -L / 2, mod.TIP_R]), np.array([0.0, 0.0, mod.TIP_R]), np.array([0.0, L / 2, mod.TIP_R])]
    t0, n_ok = time.time(), 0
    for _ in range(n):
        az, ro = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
        tl = tg["tilt"] + rng.uniform(-3.0, 3.0)
        ely = tg["elbow"] + rng.uniform(-0.04, 0.04)
        R_t = Rz(az) @ mod.Ry(math.radians(tl)) @ V @ Rz(ro)
        qv = lim.q_min + 0.05 + rng.random(7) * (lim.q_max - lim.q_min - 0.1)
        good = True
        for k, pt in enumerate(pts):
            qv = PX.ik_ext(mod, m, site, lim, mod.ORIGIN + pt, R_t, qv, elbow_y=ely, joints=[jt] if jt else ())
            if qv is None:
                good = False
                break
            e_y = mod.elbow_y_of(m, qv)
            if k > 0 and (abs(e_y - tg["elbow"]) > 0.04 + 1e-9 or not sat(qv, e_y)):
                good = False
                break
        if good:
            return {"found": True, "n_tried": _ + 1, "n_ik_ok": n_ok, "wall_s": time.time() - t0, "example": {"az": az, "roll": ro, "tilt": tl, "q": qv.tolist()}}
        n_ok += int(qv is not None)
    return {"found": False, "n_tried": n, "wall_s": time.time() - t0}


def contract_proof(reqs: dict) -> dict | None:
    """合同内矛盾:同量 hard 上界 < target − tol,或 hard 下界 > target + tol(均值 ≤ 最大值 ≤ 上界;窗口嵌套成立)。"""
    eff, _ = effective_items(reqs)
    for (q, c), b in eff.items():
        if c != "bound" or b["strict"] != "hard" or (q, "target") not in eff:
            continue
        t = eff[(q, "target")]
        if "upper" in b and b["upper"] < t["target"] - t["tol"]:
            return {"kind": "contract", "quantity": q, "detail": f"hard upper {b['upper']} < target − tol {t['target'] - t['tol']}"}
        if "lower" in b and b["lower"] > t["target"] + t["tol"]:
            return {"kind": "contract", "quantity": q, "detail": f"hard lower {b['lower']} > target + tol {t['target'] + t['tol']}"}
    return None


# ═══════════════════════════════════════════ 标签(§4.2)
def changed_keys(case: dict) -> set:
    return {tuple(ch["key"]) for ch in case["gt"]["changes"] if ch["op"] != "delete"}


def contract_only(case: dict, dec: dict) -> bool:
    """编译结果不变(只改验收)。注意:「只改合同」类(contract_only 标签)还要求起点仿真满足完整的 gt 契约,见 label_case(审查 R2 第 1 条)。"""
    c0, _ = compile_spec(case["task"], {**case["start"]["spec"], "exec": case["start"]["exec"]}, dec)
    c1, _ = compile_spec(case["task"], {**case["gt"]["spec"], "exec": case["start"]["exec"]}, dec)
    return c0 == c1


SECANT = {"secant": True}                                                # 搜索表里的占位:按前两次尝试的 (补偿, 偏差) 做割线


def program_ref_spec(case: dict) -> dict:
    """程序参照的编辑轮:gt 规格 + 起点 exec(§6.1)。"""
    return {"requirements": copy.deepcopy(case["gt"]["spec"]["requirements"]), "exec": dict(case["start"]["exec"])}


def search_candidates(case: dict, ev_prog: dict, dec: dict, kin: dict | None) -> list:
    """§4.2 搜索表:返回至多 4 个 exec(按顺序试);SECANT 占位在 label_case 里按前两次尝试计算(审查 R2 第 17(a) 条,方案原文「再割线」)。"""
    fam, var, task = case["family"], case["variant"], case["task"]
    tg = targets_of(task)
    ex0 = dict(case["start"]["exec"])
    gt = case["gt"]["spec"]["requirements"]
    out = []

    def with_(**kw):
        e = dict(ex0)
        for k_, v in kw.items():
            e[k_] = clamp_comp(k_, round(v, 4))
        return e
    bp = (case["start"]["params"] or {}).get("bias_params")
    if case["start_type"] in ("S0-res", "S0-rep", "S0-rep2", "S-noSpeed-rep") and bp:
        out.append(P3.ideal_exec(bp, tg))
    if fam in ("T2a", "T2b", "B0", "A", "A-rep"):
        d = var if fam != "A-rep" else "speed"
        e = ev_prog.get(d) or {}
        if d in COMP_OF and e.get("dev") is not None:
            k_ = COMP_OF[d]
            out.append(with_(**{k_: ex0[k_] - e["dev"]}))
            out.append(dict(SECANT, dim=d))
    elif fam in ("H1", "H1-rep", "H2"):
        q = var.split("_")[0]
        if q in ("force", "speed"):
            t = gt[q]["tol"]
            out += [with_(**{COMP_OF[q]: ex0[COMP_OF[q]] - 0.5 * t}), with_(**{COMP_OF[q]: ex0[COMP_OF[q]] - 0.9 * t})]
        elif q == "tilt":
            b = gt["tilt_hard"]
            cen = 0.5 * (b["lower"] + b["upper"])
            e = ev_prog.get("tilt") or {}
            if e.get("value") is not None:
                out += [with_(tilt_comp=ex0["tilt_comp"] + (cen - e["value"])), with_(tilt_comp=ex0["tilt_comp"] + 1.5 * (cen - e["value"]))]
        else:
            lb = gt["elbow_hard"]["lower"]
            out += [with_(elbow_comp=lb + 0.01 - tg["elbow"]), with_(elbow_comp=lb + 0.02 - tg["elbow"])]
    elif fam in ("J1", "J2"):
        it = gt["q1_range"]
        cen = 0.5 * (it["lower"] + it["upper"])
        sl = ((kin or {}).get("exec") or {}).get("slope_q1_per_elbow")
        m1 = (case.get("labels") or {}).get("start_q1_mean")
        tol_e = 0.04
        if sl and m1 is not None:
            s = 1.0 if (cen - m1) * sl > 0 else -1.0
            out += [with_(elbow_comp=s * 0.5 * tol_e), with_(elbow_comp=s * 0.9 * tol_e)]
        else:
            out += [with_(elbow_comp=0.9 * tol_e), with_(elbow_comp=-0.9 * tol_e)]
    elif fam in ("J3", "J4"):
        out += [with_(elbow_comp=0.9 * 0.04), with_(elbow_comp=-0.9 * 0.04), with_(tilt_comp=0.9 * 3.0), with_(tilt_comp=-0.9 * 3.0)]
    uniq, seen = [], set()
    for e in out:
        k_ = json.dumps(e, sort_keys=True)
        if k_ not in seen and e != ex0:
            seen.add(k_)
            uniq.append(e)
    return uniq[:4]


def _secant_exec(case: dict, d: str, hist: list) -> dict | None:
    """割线:hist = [(exec, 完整 eval)](程序一次在前);用最后两次在 d 维 target 项上的 (补偿, 偏差) 求下一个补偿。"""
    k_ = COMP_OF[d]
    pts = []
    for ex, ev in hist:
        e = ev.get(d) or {}
        if e.get("dev") is not None:
            pts.append((float(ex[k_]), float(e["dev"])))
    if len(pts) < 2:
        return None
    (c0, d0), (c1, d1) = pts[-2], pts[-1]
    c2 = c1 - d1 * (c1 - c0) / (d1 - d0) if abs(d1 - d0) > 1e-9 else c1 - d1
    e = dict(hist[-1][0])
    e[k_] = clamp_comp(k_, round(c2, 4))
    return e


def label_case(case: dict, dec: dict, extra: dict | None = None, kin: dict | None = None) -> dict:
    """§4.2 标签。返回 labels(写进情形);起点不满足自己的契约 → {"discard": "start_fails"}。基础设施失败 → InfraError 往上抛(不写标签)。"""
    task, robot = case["task"], case["robot"]
    ext_kw = {"extra": extra} if extra else {}
    sspec = {**case["start"]["spec"], "exec": case["start"]["exec"]}
    cmd0, ci0 = compile_spec(task, sspec, dec)
    r0 = run_sim(task, case["start"]["bias"], cmd0, **ext_kw)
    if r0["series"] is None:
        return {"discard": "start_exec_failed", "sims": {"start": r0["dir"]}}
    ev0 = evaluate(case["start"]["spec"]["requirements"], r0["series"], robot, dec["extreme"])
    sst = start_stats(r0["series"])
    lab = {"sims": {"start": r0["dir"]}, "start_eval": compact_eval(ev0), "start_stats": sst,
           "start_q1_mean": float(r0["series"]["q"][r0["series"]["on"], 0].mean()), "start_planner_softened": ci0.get("planner_softened")}
    if case["start_type"] == "S1-soft":                                    # 审查 R2 第 11 条:实际落在哪一半(按 S1-soft 起点仿真)
        q = "force" if case["variant"].startswith("force") else "speed"
        X, on = case["start"]["params"]["X"], sst[q]["on"]
        lab["h2_half_realised"] = "between" if on["p95"] <= X < on["max"] else ("above" if X >= on["max"] else "below_p95")
    if not all_ok(ev0):
        return {**lab, "discard": "start_fails"}
    gtR = case["gt"]["spec"]["requirements"]
    gt0 = evaluate(gtR, r0["series"], robot, dec["extreme"])
    lab["gt_on_start"] = compact_eval(gt0)
    lab["compile_unchanged"] = contract_only(case, dec)
    lab["contract_only"] = bool(lab["compile_unchanged"] and all_ok(gt0))  # 审查 R2 第 1 条:只改合同 = 编译不变且起点已满足完整 gt 契约
    attempts, hist = [], []
    pspec = program_ref_spec(case)
    cmd1, ci1 = compile_spec(task, pspec, dec)
    r1 = r0 if cmd1 == cmd0 else run_sim(task, case["start"]["bias"], cmd1, **ext_kw)
    ev1 = evaluate(gtR, r1["series"], robot, dec["extreme"])
    attempts.append({"name": "program_once", "exec": pspec["exec"], "sim": r1["dir"], "refused": r1["refused"], "eval": compact_eval(ev1),
                     "ok": all_ok(ev1) and not r1["refused"], "planner_softened": ci1.get("planner_softened"), "ik_fallback": r1.get("ik_fallback"),
                     "ik_failed": r1.get("ik_failed")})
    hist.append((pspec["exec"], ev1))
    lab["program_once"] = attempts[0]
    cat, by = None, None
    if attempts[0]["ok"]:
        cat, by = "C1", "program_once"
    else:
        cands = search_candidates({**case, "labels": lab}, ev1, dec, kin)
        for i, ex in enumerate(cands, 1):
            if isinstance(ex, dict) and ex.get("secant"):
                ex = _secant_exec(case, ex["dim"], hist)
                if ex is None:
                    continue
            cmdk, cik = compile_spec(task, {"requirements": gtR, "exec": ex}, dec)
            try:
                rk = run_sim(task, case["start"]["bias"], cmdk, **ext_kw)
            except SimBudgetExceeded as e:                                 # 只在冒烟(--max-new-sims)时出现:不打类别,记下停在哪
                lab.update({"attempts": attempts, "category": None, "decided_by": "smoke_budget_stop", "budget_stop": str(e)})
                return lab
            evk = evaluate(gtR, rk["series"], robot, dec["extreme"])
            ok = all_ok(evk) and not rk["refused"]
            attempts.append({"name": f"search_{i}", "exec": ex, "sim": rk["dir"], "refused": rk["refused"], "eval": compact_eval(evk), "ok": ok,
                             "planner_softened": cik.get("planner_softened"), "ik_fallback": rk.get("ik_fallback"), "ik_failed": rk.get("ik_failed")})
            hist.append((ex, evk))
            if ok:
                cat, by = "C2", f"search_{i}"
                lab["oracle_exec"] = ex
                break
    if cat is None:
        if all(a["refused"] for a in attempts):
            cat, by = "C4", "all_refused"
        else:
            # 「干净」= 不达标的只有被编辑 / 新增的项,或可接受声明里的项(J1 冲突:q1 范围或手肘,§3.3 替代答案;2026-10-25 冒烟发现
            # iiwa_a 的 J1 冲突每次执行都是手肘跟着出容差,按旧判据 4 次都判「含糊」被丢)
            ck = changed_keys(case) | {tuple(k) for k in acceptable_declare(case)}
            clean = [a for a in attempts if not a["refused"] and a["eval"]
                     and all(v["ok"] for rid, v in a["eval"].items() if item_key(gtR[rid]) not in ck)]
            if clean:
                cat, by = "C3", clean[0]["name"]
            elif case["family"] in ("D", "D-rep") and case["variant"] == "elbow":   # 审查 R2 第 17(b) 条:D-rep 删手肘与 D-elbow 同样保留
                cat, by = "SE", "side_effect_kept"
            else:
                return {**lab, "attempts": attempts, "discard": "ambiguous"}
    proof = None
    if cat in ("C3", "C4"):
        proof = contract_proof(gtR)
        if proof is None:
            for ch in case["gt"]["changes"]:
                if ch["op"] != "delete":
                    proof = kin_proof(gtR[ch["id"]], kin)
                    if proof:
                        conf = kin_confirm(task, gtR[ch["id"]], dec) if kin is not None else None   # 审查 R2 第 15 条:多起点采样逆解复核
                        proof["confirm"] = conf
                        if conf is not None and conf.get("found"):
                            proof = None                                  # 采样找到了满足要求的位形:证明不成立 → 未证明
                    if proof:
                        break
        cat = cat + ("p" if proof else "u")
    dec_att = next(a for a in attempts if a["name"] == by) if by in [a["name"] for a in attempts] else attempts[-1]
    bnd = any(v.get("boundary") for v in (dec_att.get("eval") or {}).values())
    lab.update({"category": cat, "decided_by": by, "proof": proof, "attempts": attempts, "boundary": bnd,
                "planner_softened": sorted({q for a in attempts for q in (a.get("planner_softened") or [])}),
                "acceptable_declare": acceptable_declare(case) if cat in ("C3p", "C4p", "C3u", "C4u") else []})
    return lab


def acceptable_declare(case: dict) -> list:
    """可接受的不可达声明(按 (quantity, 类) 匹配)。J1 冲突:q1 范围项或 elbow 项任一。"""
    keys = [list(k) for k in sorted(changed_keys(case))]
    if "declare_q1_or_elbow" in case["gt"]["accept_alt"]:
        keys.append(["elbow", "target"])
    return keys


# ═══════════════════════════════════════════ 登记表:读写、冻结、篡改检查
class RegistryTampered(RuntimeError):
    pass


class StaleEpisode(RuntimeError):
    pass


def block_shas(reg: dict) -> dict:
    cs = sorted(reg["cases"], key=lambda c: c["id"])
    files = {}
    for t in ALL_TASKS:
        f = KIN / f"{t}.json"
        files[f"kin/{t}.json"] = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
    files["pilot/decisions.json"] = hashlib.sha256(DECISIONS.read_bytes()).hexdigest() if DECISIONS.exists() else None
    return {"gt": sha256_obj([(c["id"], c["gt"], c["edit"], c["start"]) for c in cs]),
            "labels": sha256_obj([(c["id"], c.get("labels")) for c in cs]),
            "templates": sha256_obj({"templates": reg["meta"].get("templates"), "whitelist": reg["meta"].get("audit_whitelist"),
                                     "design": reg["meta"].get("design")}),
            "files": files}


def freeze_registry(path: Path, allow_provisional: bool = False) -> dict:
    reg = CM.read_json_retry(path)
    if reg.get("frozen"):
        raise SystemExit(f"{path} 已冻结")
    if not allow_provisional and any(c.get("provisional") for c in reg["cases"]):
        raise SystemExit("登记表含 provisional 情形(起点统计量不是包装层仿真),不能冻结为正式表")
    reg["meta"]["sha"] = block_shas(reg)
    reg["frozen"], reg["frozen_at"] = True, time.strftime("%Y-%m-%dT%H:%M:%S")
    CM.atomic_write_json(path, reg, indent=1)
    return reg["meta"]["sha"]


def load_registry(path: Path, need_frozen: bool = True) -> dict:
    reg = CM.read_json_retry(path)
    if need_frozen:
        if not reg.get("frozen"):
            raise RegistryTampered(f"{path} 没有冻结")
        now, then = block_shas(reg), reg["meta"].get("sha") or {}
        bad = [k for k in ("gt", "labels", "templates") if now[k] != then.get(k)]
        bad += [f"files:{f}" for f, h in (then.get("files") or {}).items() if now["files"].get(f) != h]
        if bad:
            raise RegistryTampered(f"{path} 冻结后被改动:{bad}")
        dec = reg["meta"].get("decisions") or {}
        sp = system_prompt(dec)
        if reg["meta"].get("system_prompt_sha16") != hashlib.sha256(sp.encode()).hexdigest()[:16]:   # 审查 R2 第 17(e) 条
            raise RegistryTampered(f"{path}:登记表记的系统提示 sha {reg['meta'].get('system_prompt_sha16')} ≠ 当前系统提示(审计已过期,重建登记表)")
        au = lexical_audit(sp, [(c["edit"]["text"], c["layer"]) for c in reg["cases"]])
        if not au["ok"]:
            raise RegistryTampered(f"{path}:当前系统提示下词面审计不通过:{au['violations'][:3]}")
    reg["_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return reg


# ═══════════════════════════════════════════ 计分(§7)
def _close(q: str, v, gt: float, acc: list | None = None) -> bool:
    if v is None:
        return False
    if acc:
        return acc[0] - 1e-9 <= v <= acc[1] + 1e-9
    return abs(v - gt) <= max(0.01 * abs(gt), R_Q[q]) + 1e-9


def _same_item(q: str, a: dict, b: dict) -> bool:
    if a["kind"] != b["kind"]:
        return False
    for f in ("target", "tol", "lower", "upper"):
        if (f in a) != (f in b):
            return False
        if f in a and not _close(q, a[f], b[f]):
            return False
    return a.get("strict", "soft") == b.get("strict", "soft") or a["kind"] == "target"


def score_spec(case: dict, llm_spec: dict, info: dict) -> dict:
    """gt 改动清单逐项对照 + 未改动项保持 + 多出的项。返回字段级结果与 spec_correct。"""
    start = case["start"]["spec"]["requirements"]
    gt = case["gt"]["spec"]["requirements"]
    Lg: dict = {}
    for rid, it in sorted(llm_spec["requirements"].items()):
        Lg.setdefault(item_key(it), []).append((rid, it))
    res = {"changes": [], "preserve": {}, "extra": [], "parse_failed": bool(info.get("parse_failed"))}
    ck = set()
    for ch in case["gt"]["changes"]:
        key = tuple(ch["key"])
        ck.add(key)
        items = Lg.get(key, [])
        r = {"op": ch["op"], "key": list(key), "n_items": len(items), "fields": {}}
        if ch["op"] == "delete":
            r["ok"] = not items
        elif len(items) != 1:
            r["ok"] = False
            r["why"] = "missing" if not items else "duplicate"
        else:
            it, g = items[0][1], gt[ch["id"]]
            q = key[0]
            r["fields"]["kind"] = it["kind"] == g["kind"]
            for f in ("target", "tol", "lower", "upper"):
                if f in g:
                    r["fields"][f] = _close(q, it.get(f), g[f], (ch.get("accept") or {}).get(f))
            if g["kind"] != "target":
                r["fields"]["strict"] = it.get("strict") == g["strict"]
            r["ok"] = all(r["fields"].values())
            r["llm_item"] = it
        res["changes"].append(r)
    for rid, st in sorted(start.items()):
        key = item_key(st)
        if key in ck:
            continue
        items = Lg.get(key, [])
        res["preserve"][rid] = bool(len(items) == 1 and _same_item(key[0], items[0][1], st))
    start_keys = {item_key(it) for it in start.values()}
    add_keys = {tuple(ch["key"]) for ch in case["gt"]["changes"] if ch["op"] == "add"}
    for key, items in Lg.items():
        if key not in start_keys and key not in add_keys:
            res["extra"] += [rid for rid, _ in items]
    res["changes_ok"] = all(r["ok"] for r in res["changes"])
    res["preserve_all"] = all(res["preserve"].values())
    res["strict_errors"] = [r["key"] for r in res["changes"] if r["fields"].get("strict") is False]
    res["spec_correct"] = bool(res["changes_ok"] and res["preserve_all"] and not res["extra"] and not res["parse_failed"]
                               and not spec_issues(llm_spec["requirements"]))
    return res


def score_exec(case: dict, new_spec: dict) -> dict:
    """编辑轮的 exec 改动:有效补偿(新规格里对应 target 存在)/ 闲置补偿;在用补偿保持(T2b 的被编辑维除外)。"""
    ex0, ex1 = case["start"]["exec"], new_spec["exec"]
    eff_new = {item_key(it) for it in new_spec["requirements"].values()}
    eff_start = {item_key(it) for it in case["start"]["spec"]["requirements"].values()}
    eff_gt = {item_key(it) for it in case["gt"]["spec"]["requirements"].values()}
    dim_of = {v: k for k, v in COMP_OF.items()}
    changed = [k for k in EXEC_KEYS if abs(ex1[k] - ex0[k]) > 1e-9]
    effective = [k for k in changed if (dim_of[k], "target") in eff_new]
    inert = [k for k in changed if k not in effective]
    skip = {COMP_OF[case["variant"]]} if case["family"] == "T2b" else set()
    in_use = [k for k in EXEC_KEYS if abs(ex0[k]) > 1e-9 and (dim_of[k], "target") in eff_start and (dim_of[k], "target") in eff_gt and k not in skip]
    return {"changed": changed, "effective_changed": effective, "inert_exec_change": inert, "in_use": in_use,
            "in_use_preserved": all(abs(ex1[k] - ex0[k]) <= 1e-9 for k in in_use) if in_use else None}


def declared_keys(decl: list, spec: dict) -> list:
    out = []
    for x in decl:
        it = spec["requirements"].get(x["id"])
        out.append(list(item_key(it)) if it else ["?", x["id"]])
    return out


# ═══════════════════════════════════════════ episode(大模型臂;§2.8、§7)
def get_llm(model: str, temperature: float):
    if model.lower().startswith("deepseek"):
        raise SystemExit("[R2] deepseek 一律拒绝(余额已用完,方案也不用)")
    from cost_layers.llm import make_llm
    return make_llm(model, timeout_s=180.0, temperature=temperature)


def episode_tag(case: dict, model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", case["id"]) + "_" + re.sub(r"[^A-Za-z0-9]+", "-", model)


def exec_round(case: dict, spec: dict, dec: dict, extra: dict | None) -> dict:
    """编译 + 仿真 + 双重评估(gt 契约 / 自己的规格)。规格不完整 → 不仿真。冒烟的新仿真预算用完 → budget_stop(不算情形结果)。"""
    task, robot = case["task"], case["robot"]
    try:
        cmd, cinfo = compile_spec(task, spec, dec)
    except SpecInvalid as e:
        return {"spec_invalid": str(e), "executed": False, "refused": False, "S": None}
    try:
        r = run_sim(task, case["start"]["bias"], cmd, **({"extra": extra} if extra else {}))
    except SimBudgetExceeded as e:
        return {"budget_stop": str(e), "executed": False, "refused": False, "S": None, "cmd": cmd}
    S = r["series"]
    ev_t = evaluate(case["gt"]["spec"]["requirements"], S, robot, dec["extreme"])
    ev_s = evaluate(spec["requirements"], S, robot, dec["extreme"])
    return {"sim": r["dir"], "refused": r["refused"], "refused_reason": (r.get("ext_result") or {}).get("refused_reason"), "executed": S is not None,
            "S": S, "eval": ev_t, "self_eval": ev_s, "cmd": cmd, "compile": cinfo, "all_phases_accepted": r.get("all_phases_accepted"),
            "planner_softened": cinfo.get("planner_softened"), "ik_fallback": r.get("ik_fallback"), "ik_failed": r.get("ik_failed")}


def run_episode(case: dict, model: str, args, reg: dict, eps_dir: Path, extra: dict | None = None) -> dict:
    dec = reg["meta"]["decisions"]
    tag = episode_tag(case, model)
    f_out = eps_dir / f"{tag}.json"
    fv = framework_version(dec)
    if f_out.exists() and not getattr(args, "force", False):
        e = CM.read_json_retry(f_out)
        if e.get("framework_version") != fv or e.get("registry_sha256") != reg["_sha256"] or e.get("code_version") != P3.CODE_VER:
            raise StaleEpisode(f"{f_out.name}: 框架 / 登记表 / 仿真代码版本与当前不同")
        return e
    llm = get_llm(model, TEMPERATURE)
    system = system_prompt(dec)
    lab = case.get("labels") or {}
    spec0 = {"requirements": copy.deepcopy(case["start"]["spec"]["requirements"]), "exec": dict(case["start"]["exec"])}
    r0 = exec_round(case, spec0, dec, extra)
    if lab.get("sims", {}).get("start") and r0.get("sim") != lab["sims"]["start"]:
        raise StaleEpisode(f"{case['id']}: 起点仿真 {r0.get('sim')} ≠ 标签 {lab['sims']['start']}")
    rounds = [{"round": 0, "kind": "start", "exec": spec0["exec"], "spec": spec0, "sim": r0.get("sim"), "executed": r0["executed"],
               "eval": compact_eval(r0["eval"]), "self_eval_full": None}]
    txt = case["edit"]["text"]
    user = (intent_text() + "\n\n当前规格:" + spec_view(spec0) + "\n" + feedback(spec0, r0["self_eval"], r0["S"], [], full=True)
            + f"\n\n用户追加要求:{txt}\n请按这句话改规格(requirements 只写改动的条目;格式见说明)。")
    t0 = time.time()
    reply = ask_retry(llm, system, user)
    obj = parse_reply(reply["text"])
    spec1, info = apply_patch(spec0, obj, "edit")
    sc = score_spec(case, spec1, info)
    se = score_exec(case, spec1)
    declared = info["infeasible"]
    rec = {"round": 1, "kind": "edit", "instruction": txt, "spec": spec1, "exec": spec1["exec"], "patch_info": info, "spec_score": sc, "exec_score": se,
           "llm": {**llm_rec(user, reply), "usage": reply.get("usage")}, "prompt_size": CM.prompt_size(user, system, reply.get("usage")),
           "wall_s": time.time() - t0}
    cur = {"S": r0["S"], "eval": r0["eval"]}
    if declared:
        rec.update({"declared": declared, "declared_keys": declared_keys(declared, spec1), "executed": False})
        rounds.append(rec)
    else:
        r1 = exec_round(case, spec1, dec, extra)
        rec.update({"sim": r1.get("sim"), "refused": r1["refused"], "spec_invalid": r1.get("spec_invalid"), "executed": r1["executed"],
                    "budget_stop": r1.get("budget_stop"), "planner_softened": r1.get("planner_softened"), "ik_fallback": r1.get("ik_fallback"),
                    "eval": compact_eval(r1["eval"]) if r1.get("eval") else None, "self_eval": r1.get("self_eval"),
                    "self_eval_c": compact_eval(r1["self_eval"]) if r1.get("self_eval") else None, "cmd": r1.get("cmd")})
        rounds.append(rec)
        cur = r1
        spec = spec1
        while (len(rounds) - 2 < args.rounds and not cur.get("budget_stop")
               and not (cur.get("self_eval") and all_ok(cur["self_eval"]) and not cur.get("refused"))):
            seq = rounds[1:]
            refused_txt = refusal_text(cur.get("refused_reason"), spec) if cur.get("refused") else None
            fb = feedback(spec, cur.get("self_eval"), cur.get("S"), seq, refused=refused_txt, invalid=cur.get("spec_invalid"))
            hist = history_lines(seq)
            user = (intent_text() + f"\n用户追加要求:{txt}\n" + ("之前的尝试:\n" + "\n".join(hist) + "\n\n" if hist else "")
                    + "当前规格:" + spec_view(spec) + "\n" + fb + "\n\n请只改执行侧字段(exec),让执行结果达到规格里的全部要求。")
            t0 = time.time()
            reply = ask_retry(llm, system, user)
            obj = parse_reply(reply["text"])
            spec_n, info_n = apply_patch(spec, obj, "repair")
            recn = {"round": len(rounds), "kind": "repair", "spec": spec_n, "exec": spec_n["exec"], "patch_info": info_n,
                    "llm": {**llm_rec(user, reply), "usage": reply.get("usage")}, "prompt_size": CM.prompt_size(user, system, reply.get("usage")),
                    "wall_s": time.time() - t0}
            if info_n["infeasible"]:
                declared = info_n["infeasible"]
                recn.update({"kind": "infeasible", "declared": declared, "declared_keys": declared_keys(declared, spec_n), "executed": False})
                rounds.append(recn)
                break
            rn = exec_round(case, spec_n, dec, extra)
            recn.update({"sim": rn.get("sim"), "refused": rn["refused"], "spec_invalid": rn.get("spec_invalid"), "executed": rn["executed"],
                         "budget_stop": rn.get("budget_stop"), "planner_softened": rn.get("planner_softened"), "ik_fallback": rn.get("ik_fallback"),
                         "eval": compact_eval(rn["eval"]) if rn.get("eval") else None, "self_eval": rn.get("self_eval"),
                         "self_eval_c": compact_eval(rn["self_eval"]) if rn.get("self_eval") else None, "cmd": rn.get("cmd")})
            rounds.append(recn)
            cur, spec = rn, spec_n
    last_eval = cur.get("eval")
    gt_ok = bool(last_eval) and all_ok(last_eval)
    cat = lab.get("category")
    success = gt_ok and not declared
    decl_ok = None
    decl_round = next((r["round"] for r in rounds if r.get("declared")), None)
    if declared and cat in ("C3p", "C4p"):
        acc = [tuple(k) for k in lab.get("acceptable_declare") or []]
        dk = [tuple(k) for k in declared_keys(declared, rounds[-1]["spec"])]
        gtR = case["gt"]["spec"]["requirements"]
        others_ok = bool(last_eval) and all(v["ok"] for rid, v in last_eval.items() if item_key(gtR[rid]) not in set(acc))
        # 审查 R2 第 8 条:声明只有在被声明的要求项本身写对(编辑轮规格字段级写对)时才算成功
        decl_ok = bool(dk) and all(k in acc for k in dk) and others_ok and bool(rounds[1]["spec_score"]["spec_correct"])
        success = success or decl_ok
    for r in rounds:                                                       # self_eval 全量只留在内存里;落盘用 compact
        r.pop("self_eval", None)
    first = rounds[1]
    res = {"tag": tag, "case_id": case["id"], "model": model, "temperature": TEMPERATURE, "framework_version": fv, "registry_sha256": reg["_sha256"],
           "code_version": P3.CODE_VER, "wrapper_sha16": PX.WRAPPER_SHA16, "system_prompt_sha16": hashlib.sha256(system.encode()).hexdigest()[:16],
           "family": case["family"], "group": case["group"], "variant": case["variant"], "phrasing": case["phrasing"], "layer": case["layer"],
           "template": case["template"], "task": case["task"], "robot": case["robot"], "category": cat, "contract_only": lab.get("contract_only"),
           "turn_budget": 1 + int(args.rounds), "spec_correct": first["spec_score"]["spec_correct"], "spec_score": first["spec_score"],
           "exec_score": first["exec_score"], "one_shot": bool(first.get("eval") and all(v["ok"] for v in first["eval"].values()) and not first.get("declared")),
           "declared_infeasible": declared, "declare_ok": decl_ok, "declared_in_edit_round": decl_round == 1 if declared else None,
           "unproven_declared": bool(declared and cat in ("C3u", "C4u")),
           "planner_softened": sorted({q for r in rounds for q in (r.get("planner_softened") or [])}),
           "ik_fallback_rounds": sum(1 for r in rounds if r.get("ik_fallback")),
           "success": bool(success), "n_rounds": len(rounds) - 1,
           "spec_self_ok_last": bool(rounds[-1].get("self_eval_c") and all(v["ok"] for v in rounds[-1]["self_eval_c"].values())),
           "rounds": rounds, "extra": extra, "smoke_budget_stop": any(r.get("budget_stop") for r in rounds),
           "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    res["self_deceived"] = bool(rounds[-1].get("self_eval_c") and all(v["ok"] for v in rounds[-1]["self_eval_c"].values()) and not gt_ok)
    CM.atomic_write_json(f_out, res, indent=1, default=float)
    print(f"[{tag}] 规格写对={res['spec_correct']} 一次到位={res['one_shot']} 成功={res['success']} 回合 {res['n_rounds']} 类别 {cat}", flush=True)
    return res


def prog_ref_episode(case: dict) -> dict:
    """程序参照(§6.1):编辑轮 = gt 规格 + 起点 exec,只跑这一轮 = 标签的 program_once,不额外仿真。"""
    lab = case.get("labels") or {}
    po = lab.get("program_once") or {}
    return {"case_id": case["id"], "arm": "program", "family": case["family"], "group": case["group"], "variant": case["variant"],
            "phrasing": case["phrasing"], "template": case["template"], "task": case["task"], "category": lab.get("category"),
            "contract_only": lab.get("contract_only"), "spec_correct": True, "one_shot": bool(po.get("ok")), "sim": po.get("sim"), "eval": po.get("eval")}


# ═══════════════════════════════════════════ 先导(§9.3)与决策门
def pilot_jobs(parts: list, dec: dict) -> list:
    """返回 [(part, task, label, spec, bias, opts)]。P4–P7、P9 的界依赖 P1 统计量,P1 没跑完时跳过并提示。"""
    jobs = []
    p1 = {}
    for t in ALL_TASKS:
        cmd, _ = compile_spec(t, base_spec(t), dec)
        d = sim_dir(t, {}, cmd, prefix="pilot")
        if (d / "ext_result.json").exists():
            S = load_sim(d)["series"]
            if S is not None:
                p1[t] = start_stats(S)
    for part in parts:
        if part == "P1":
            jobs += [(part, t, "S0", base_spec(t), {}, None) for t in ALL_TASKS]
        elif part == "P2":
            jobs += [(part, t, "S-noSpeed", base_spec(t, drop=("speed",)), {}, None) for t in ALL_TASKS]
        elif part == "P2b":                                                # 门 D2 的 30 mm/s 复查(run_pilot 用 default_speed = 30 编译)
            jobs += [(part, t, "S-noSpeed30", base_spec(t, drop=("speed",)), {}, None) for t in ALL_TASKS]
        elif part == "P3":
            jobs += [(part, t, "S-noElbow", base_spec(t, drop=("elbow",)), {}, None) for t in ALL_TASKS]
        elif part == "P8":
            for t in ("fr3_a", "iiwa_b"):
                for s in (1, 2):
                    jobs.append((part, t, f"rep{s}", base_spec(t), {}, {"mppi_seed": s, "q_jitter": 0.02, "jitter_seed": s}))
        elif part == "P10":
            for t in ("fr3_a",):
                sp = base_spec(t)
                sp["requirements"]["tilt_lb"] = {"quantity": "tilt", "kind": "lower", "lower": 12.0, "strict": "soft"}
                jobs.append((part, t, "tilt_lower", sp, {}, None))
                sp = base_spec(t)
                sp["requirements"]["speed_lb"] = {"quantity": "speed", "kind": "lower", "lower": 10.0, "strict": "soft"}
                jobs.append((part, t, "speed_lower", sp, {}, None))
        elif part in ("P4", "P5", "P6", "P7", "P9", "P9s"):
            for t in (ALL_TASKS if part in ("P4", "P6") else A_TASKS):
                if t not in p1:
                    print(f"[pilot] {part} {t}:P1 统计量缺失,先跑 P1", flush=True)
                    continue
                st = p1[t]
                if part == "P4":
                    for o in (-0.5, 0.5, 1.5):
                        sp = base_spec(t)
                        sp["requirements"]["force_hard"] = {"quantity": "force", "kind": "upper", "upper": round(st["force"]["on"]["max"] + o, 2), "strict": "hard"}
                        jobs.append((part, t, f"force_hard{o:+g}", sp, {}, None))
                        if t in A_TASKS:
                            sp2 = copy.deepcopy(sp)
                            sp2["requirements"]["force_hard"]["strict"] = "soft"
                            jobs.append((part, t, f"force_soft{o:+g}", sp2, {}, None))
                elif part in ("P5", "P9"):
                    offs = ((-1.0, 1.0) if part == "P5" else (1.0,))
                    for o in offs:
                        sp = base_spec(t)
                        sp["requirements"]["speed_hard"] = {"quantity": "speed", "kind": "upper", "upper": round(st["speed"]["on"]["max"] + o * 2, 1), "strict": "hard"}
                        jobs.append((part, t, f"speed_hard{o:+g}", sp, {}, None))
                        sp = base_spec(t)
                        a_, b_ = st["tilt"]["on"]["min"] - 0.5 * o, st["tilt"]["on"]["max"] + 0.5 * o
                        if b_ - a_ < 0.3:                                  # 2026-10-25 正式前修正:起点倾角范围 < 1° 时 δ = −0.5 给出空窗口(SpecInvalid,先导崩溃);
                            c_ = 0.5 * (a_ + b_)                           # 改用与 finalize(H1 tilt)相同的规则:宽 < 0.3° 时以中心取 0.3° 宽
                            a_, b_ = c_ - 0.15, c_ + 0.15
                        sp["requirements"]["tilt_hard"] = {"quantity": "tilt", "kind": "range", "lower": round(a_, 1), "upper": round(b_, 1), "strict": "hard"}
                        jobs.append((part, t, f"tilt_hard{o:+g}", sp, {}, None))
                        sp = base_spec(t)
                        sp["requirements"]["elbow_hard"] = {"quantity": "elbow", "kind": "lower", "lower": round(st["elbow"]["on"]["min"] - 0.01 * o, 3), "strict": "hard"}
                        jobs.append((part, t, f"elbow_hard{o:+g}", sp, {}, None))
                    if part == "P9":
                        sp = base_spec(t)
                        sp["requirements"]["elbow_hard"] = {"quantity": "elbow", "kind": "lower", "lower": round(st["elbow"]["on"]["min"] + 0.01, 3), "strict": "hard"}
                        jobs.append((part, t, "elbow_hard_pos", sp, {}, None))
                        q1 = st["q1"]["on"]
                        sp = base_spec(t)
                        sp["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(q1["min"] - 0.05, 2), "upper": round(q1["max"] + 0.05, 2), "strict": "hard"}
                        jobs.append((part, t, "q1_hard_compat", sp, {}, None))
                elif part == "P9s":                                          # 门 D6 第二步:planner_soft 里的量在同样的界上按规划器 soft 重跑
                    for q in dec.get("planner_soft") or []:
                        for lab_ in D6_LABELS[q]:
                            sp = d6_spec(t, st, lab_)
                            jobs.append((part, t, lab_ + "|planner_soft", sp, {}, None))
                elif part == "P6":
                    # 审查 R2 第 6 条:收紧可行区间按新规则(宽 = 起点扫过范围 + 0.04,离起点均值 0.01–0.03,三处都落在 E_exec 里),
                    # soft × 6 个任务、hard × 3 个任务(A 组)
                    for strict in (("soft", "hard") if t in A_TASKS else ("soft",)):
                        sp = base_spec(t)
                        iv = tighten_interval(st, kin_env(t), 0.5, 0.5)
                        sp["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(iv["lo"], 2), "upper": round(iv["hi"], 2), "strict": strict}
                        jobs.append((part, t, f"q1_{strict}_tight", sp, {}, None))
                    if t == "iiwa_a":                                      # 被拒:逆解的零空间拉力能把 q1 拉动约 0.25–0.3 rad,所以放在 max + 0.60(见 sim_check refuse)
                        q1 = st["q1"]["on"]                                # 2026-10-25 正式前修正:原来这里引用了未定义的 q1(UnboundLocalError)
                        sp = base_spec(t)
                        sp["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(q1["max"] + 0.60, 2), "upper": round(q1["max"] + 0.66, 2), "strict": "hard"}
                        jobs.append((part, t, "q1_hard_refuse", sp, {}, None))
                elif part == "P7":
                    q4, q1 = st["q4"]["on"], st["q1"]["on"]
                    sp = base_spec(t)
                    sp["requirements"]["q4"] = {"quantity": "q4", "kind": "target", "target": round(q4["mean"] + 0.15, 3), "tol": JOINT_TOL}
                    jobs.append((part, t, "q4_offA", sp, {}, None))
                    sp = base_spec(t)
                    sp["requirements"]["q1"] = {"quantity": "q1", "kind": "target", "target": round(q1["mean"] + 0.05, 3), "tol": JOINT_TOL}
                    jobs.append((part, t, "q1_j4", sp, {}, None))
    return jobs


def d6_spec(t: str, st: dict, label: str) -> dict:
    """门 D6 用的规格(P4 / P9 / P9s 共用,保证同一个界;审查 R2 第 5 条)。st = 该任务 P1 起点统计量。"""
    sp = base_spec(t)
    R = sp["requirements"]
    if label.startswith("force_hard"):
        o = float(label[len("force_hard"):])
        R["force_hard"] = {"quantity": "force", "kind": "upper", "upper": round(st["force"]["on"]["max"] + o, 2), "strict": "hard"}
    elif label.startswith("speed_hard"):
        o = float(label[len("speed_hard"):])
        R["speed_hard"] = {"quantity": "speed", "kind": "upper", "upper": round(st["speed"]["on"]["max"] + o * 2, 1), "strict": "hard"}
    elif label.startswith("tilt_hard"):
        o = float(label[len("tilt_hard"):])
        R["tilt_hard"] = {"quantity": "tilt", "kind": "range", "lower": round(st["tilt"]["on"]["min"] - 0.5 * o, 1),
                          "upper": round(st["tilt"]["on"]["max"] + 0.5 * o, 1), "strict": "hard"}
    elif label == "elbow_hard_pos":
        R["elbow_hard"] = {"quantity": "elbow", "kind": "lower", "lower": round(st["elbow"]["on"]["min"] + 0.01, 3), "strict": "hard"}
    elif label.startswith("elbow_hard"):
        o = float(label[len("elbow_hard"):])
        R["elbow_hard"] = {"quantity": "elbow", "kind": "lower", "lower": round(st["elbow"]["on"]["min"] - 0.01 * o, 3), "strict": "hard"}
    elif label == "q1_hard_compat":
        q1 = st["q1"]["on"]
        R["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(q1["min"] - 0.05, 2), "upper": round(q1["max"] + 0.05, 2), "strict": "hard"}
    else:
        raise ValueError(f"未知 D6 标签 {label}")
    return sp


def d6_pass(r: dict | None) -> bool:
    """门 D6 的通过判据:滑动走完(全部阶段被采用、没有被拒、|end_y_err| ≤ 5 mm)且未编辑的要求都达标(others_ok;不看被加的 hard 项本身)。"""
    return bool(r and r.get("all_phases_accepted") and not r.get("refused") and abs(r.get("end_y_err_mm") or 99.0) <= 5.0 and r.get("others_ok"))


def run_pilot(parts: list, jobs_n: int) -> None:
    dec = load_decisions()
    jobs = pilot_jobs(parts, dec)
    PILOT.mkdir(parents=True, exist_ok=True)
    out = []

    def one(j):
        part, t, label, sp, bias, opts = j
        dj = {**dec, "default_speed": 30.0} if part == "P2b" else dec
        cmd, cinfo = compile_spec(t, sp, dj, opts=opts)
        r = run_sim(t, bias, cmd, prefix="pilot")
        ev = evaluate(sp["requirements"], r["series"], TASKS[t]["robot"], dec["extreme"])
        others = {rid: v for rid, v in ev.items() if rid in DIMS5}                # 未编辑的要求(基础规格的 5 项)
        return {"part": part, "task": t, "label": label, "sim": r["dir"], "refused": r["refused"], "all_phases_accepted": r.get("all_phases_accepted"),
                "end_y_err_mm": r.get("end_y_err_mm"), "eval": compact_eval(ev), "all_ok": all_ok(ev), "others_ok": all_ok(others),
                "planner_softened": cinfo.get("planner_softened"), "ik_fallback": r.get("ik_fallback"),
                "stats": start_stats(r["series"]) if r["series"] is not None else None, "spec": sp}
    with ThreadPoolExecutor(jobs_n) as ex:
        for f in as_completed([ex.submit(one, j) for j in jobs]):
            r = f.result()
            out.append(r)
            print(f"[pilot {r['part']} {r['task']} {r['label']}] 全部达标={r['all_ok']} 被拒={r['refused']} 阶段全采用={r['all_phases_accepted']}", flush=True)
    f = PILOT / "pilot_runs.jsonl"
    with CM.file_lock(PILOT / ".pilot.lock"):
        with open(f, "a", encoding="utf-8") as fh:
            for r in out:
                fh.write(json.dumps(r, ensure_ascii=False, default=float) + "\n")


def decide() -> dict:
    """门 D1–D6(§9.3),由 pilot_runs.jsonl 计算;写 decisions.json(之后冻结,登记表 meta 记它的 sha)。
    审查 R2 第 5 条:D2 在 50 mm/s 不足 5/6 时读 P2b(30 mm/s),没跑 P2b 就停;D6 分两步 —— 第一步把走不完的量放进 planner_soft
    并要求跑 P9s(decided = false),第二步读 P9s,仍走不完的量把对应 (族, 变体) 写进 dropped_variants。"""
    runs = [json.loads(x) for x in (PILOT / "pilot_runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    by = {}
    for r in runs:
        by[(r["part"], r["task"], r["label"])] = r                     # 同键多次:取最后一次
    old = CM.read_json_retry(DECISIONS) if DECISIONS.exists() else {}
    dec = dict(DEFAULTS)
    why = {}
    # D1:P8 重复里 on 窗口力最大值的 SD > 0.5 × Δ(1 N)→ 25 ms 滑动平均
    sds = []
    for t in ("fr3_a", "iiwa_b"):
        xs = [((by.get(("P1", t, "S0")) or {}).get("stats") or {}).get("force", {}).get("on", {}).get("max")]
        xs += [((by.get(("P8", t, f"rep{s}")) or {}).get("stats") or {}).get("force", {}).get("on", {}).get("max") for s in (1, 2)]
        xs = [x for x in xs if x is not None]
        if len(xs) >= 2:
            sds.append(float(np.std(xs, ddof=1)))
    dec["extreme"] = "ma25" if (sds and max(sds) > 0.5 * DELTA["force"]) else "raw"
    why["D1"] = {"force_max_rep_sd": sds}
    # D2:S-noSpeed 在 ≥ 5/6 任务上其余要求全部达标 → 50 mm/s;否则 30 mm/s(P2b,同一判据);两者都不行 → 不做 A-speed
    ok50 = [t for t in ALL_TASKS if (by.get(("P2", t, "S-noSpeed")) or {}).get("all_ok")]
    if len(ok50) >= 5:
        dec["default_speed"], dec["a_speed_tasks"] = 50.0, ok50
    else:
        have30 = [t for t in ALL_TASKS if ("P2b", t, "S-noSpeed30") in by]
        if len(have30) < len(ALL_TASKS):
            raise SystemExit(f"D2:50 mm/s 下只有 {len(ok50)}/6 个任务达标,先跑 pilot --parts P2b(30 mm/s)再 decide")
        ok30 = [t for t in ALL_TASKS if by[("P2b", t, "S-noSpeed30")].get("all_ok")]
        if len(ok30) >= 5:
            dec["default_speed"], dec["a_speed_tasks"] = 30.0, ok30
        else:
            dec["default_speed"], dec["a_speed_tasks"] = 50.0, []
    why["D2"] = {"ok_tasks_at_50": ok50, "chosen": dec["default_speed"], "a_speed_tasks": dec["a_speed_tasks"]}
    # D3:S-noElbow 其余要求达标的任务做 A-elbow
    dec["a_elbow_tasks"] = [t for t in ALL_TASKS if (by.get(("P3", t, "S-noElbow")) or {}).get("all_ok")]
    why["D3"] = {"a_elbow_tasks": dec["a_elbow_tasks"]}
    # D5:P6 收紧可行 q1 soft 情形里 q1 完全不动(均值变化 < 0.005 rad)→ weight 4 / task
    moved = []
    for t in ALL_TASKS:
        a, b = by.get(("P1", t, "S0")), by.get(("P6", t, "q1_soft_tight"))
        if a and b and a.get("stats") and b.get("stats"):
            moved.append(abs(b["stats"]["q1"]["on"]["mean"] - a["stats"]["q1"]["on"]["mean"]))
    if moved and max(moved) < 0.005:
        dec["joint_weight"], dec["joint_priority"] = 4.0, "task"
    why["D5"] = {"q1_moved": moved}
    # D6 第一步:每个 hard 变体在起点满足的界上(以及 elbow 下限正偏移)走完滑动 + 未编辑要求达标;不过 → planner_soft
    soft, d6 = [], {}
    for q, labs in D6_LABELS.items():
        rs = [r for (p_, t, l_), r in by.items() if p_ in ("P4", "P9") and l_ in labs]
        bad = [f"{r['task']}:{r['label']}" for r in rs if not d6_pass(r)]
        d6[q] = {"n": len(rs), "fail": bad}
        if not rs:
            raise SystemExit(f"D6:{q} 没有先导结果({labs}),先跑 P4 / P9")
        if bad:
            soft.append(q)
    dec["planner_soft"] = soft
    dec["d6_stage"] = 1
    dec["dropped_variants"] = []
    pending = []
    if soft:
        # 第二步:P9s(planner_soft 下重跑同样的界)
        rs2 = {q: [r for (p_, t, l_), r in by.items() if p_ == "P9s" and l_.split("|")[0] in D6_LABELS[q]] for q in soft}
        pending = [q for q in soft if not rs2[q] or set(old.get("planner_soft") or []) != set(soft)]
        if not pending:
            for q in soft:
                bad2 = [f"{r['task']}:{r['label']}" for r in rs2[q] if not d6_pass(r)]
                d6[q]["fail_planner_soft"] = bad2
                if bad2:
                    dec["dropped_variants"] += D6_VARIANTS[q]
            dec["d6_stage"] = 2
    why["D6"] = {**d6, "planner_soft": soft, "pending_P9s": pending, "dropped_variants": dec["dropped_variants"]}
    dec["decided"] = not pending
    dec["why"] = why
    dec["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    PILOT.mkdir(parents=True, exist_ok=True)
    CM.atomic_write_json(DECISIONS, dec, indent=1)
    if pending:
        print(f"[decide] D6:{pending} 走不完滑动,已写 planner_soft;先跑 pilot --parts P9s 再 decide(decided = false,build 会拒绝)", flush=True)
    return dec


# ═══════════════════════════════════════════ 登记表构建(正式):起点仿真 → 抽值 → 审计 → 标签
def build(stage: str, jobs_n: int, path: Path = REG_PATH, extra: dict | None = None, cells: list | None = None, allow_undecided: bool = False) -> None:
    """allow_undecided 只给冒烟(--smoke-tag 必须同时给):没有 decisions.json 时用 DEFAULTS;登记表里的 decisions 仍按表内的值。"""
    dec = load_decisions()
    if stage == "label" and path.exists():
        dec = (CM.read_json_retry(path).get("meta") or {}).get("decisions") or dec
    if not dec.get("decided") and not (allow_undecided and extra):
        raise SystemExit("先跑先导并 decide(decisions.json 里 decided = true);冒烟可加 --smoke-tag … --allow-undecided")
    base_cache: dict = {}

    def base_of(task):
        if task not in base_cache:
            sts = {}
            for k, sp in base_start_specs(task, dec).items():
                cmd, _ = compile_spec(task, sp, dec)
                r = run_sim(task, {}, cmd, **({"extra": extra} if extra else {}))
                if r["series"] is None:
                    raise InfraError(f"{task} {k} 起点仿真失败")
                sts[k] = start_stats(r["series"])
            base_cache[task] = sts
        return base_cache[task]

    def stats_fn(case, start):
        cmd, _ = compile_spec(case["task"], {**start["spec"], "exec": start["exec"]}, dec)
        r = run_sim(case["task"], start["bias"], cmd, **({"extra": extra} if extra else {}))
        if r["series"] is None:
            return {"discard": "start_exec_failed"}
        ev = evaluate(start["spec"]["requirements"], r["series"], case["robot"], dec["extreme"])
        if not all_ok(ev):
            return {"discard": "start_fails"}
        if case["start_type"] == "S0-res":
            d = case["variant"]
            r0 = abs(target_dev(start_stats(r["series"]), d, targets_of(case["task"])[d]))
            f = start["params"]["floor"]
            if not 2.0 * f <= r0 <= 0.8 * default_tol(d, targets_of(case["task"])[d]):
                return {"discard": "r0_out_of_band"}
        return {"source": r["dir"], "provisional": False, **start_stats(r["series"])}
    if stage in ("starts", "draw"):
        for t in ALL_TASKS:
            base_of(t)
        if stage == "starts":
            return
        reg = draw_registry(stats_fn, base_of, dec, cells=cells)
        au = lexical_audit(system_prompt(dec), [(c["edit"]["text"], c["layer"]) for c in reg["cases"]])
        reg["meta"]["audit"] = au
        if not au["ok"]:
            raise SystemExit(f"词面审计不通过:{au['violations'][:5]}")
        CM.atomic_write_json(path, reg, indent=1, default=float)
        print(f"[build] 抽到 {len(reg['cases'])} 个情形 → {_rel(path)}", flush=True)
        return
    if stage == "label":
        reg = CM.read_json_retry(path)
        if reg.get("frozen"):
            raise SystemExit("已冻结")
        todo = [c for c in reg["cases"] if not c.get("labels") or (c["labels"].get("discard") and not c["labels"].get("redraw_exhausted"))]

        def one(c):
            """审查 R2 第 6 条:标签阶段的丢弃(含糊 / 起点不达标 …)按同一格的下一次尝试重抽并重新打标签,直到成功或用完尝试次数,
            使 §3.1 的配额成立;每次丢弃记进 reg["discards"]。基础设施失败往上抛(这个情形不写,之后补跑)。"""
            cur = c
            lab = label_case(cur, dec, extra, kin_env(cur["task"])) if not (cur.get("labels") or {}).get("discard") else cur["labels"]
            log = []
            cell = cell_of_case(cur)
            att = int(cur.get("attempt", 0))
            while lab.get("discard"):
                log.append({"attempt": att, "why": lab["discard"], "stage": "label"})
                att += 1
                if att >= max_attempts(cell["start_type"]):
                    lab = {**lab, "redraw_exhausted": True, "redraw_last_attempt": att - 1}
                    break
                nc = make_case(cell, cell["idx"], att, base_of(cell["task"]), dec, stats_fn, kin_env(cell["task"]))
                if "discard" in nc:
                    lab = {"discard": nc["discard"]}
                    continue
                cur = nc
                lab = label_case(cur, dec, extra, kin_env(cur["task"]))
            cur = dict(cur)
            cur["labels"] = lab
            return c["id"], cur, log
        cnt = {"labelled": 0, "discard_final": 0, "infra": 0, "redrawn": 0}
        with ThreadPoolExecutor(jobs_n) as ex:
            futs = {ex.submit(one, c): c["id"] for c in todo}
            for f in as_completed(futs):
                try:
                    cid, newc, log = f.result()
                except InfraError as e:
                    cnt["infra"] += 1
                    print(f"[label {futs[f]}] 基础设施失败,这个情形先不写,之后补跑:{e}", flush=True)
                    continue
                i = next(k for k, x in enumerate(reg["cases"]) if x["id"] == cid)
                reg["cases"][i] = newc
                if log:
                    cnt["redrawn"] += 1
                    key = newc["template"] + "|" + newc["task"] + "|" + str(int(cid.split("|")[-1]))
                    reg.setdefault("discards", {}).setdefault(key, []).extend(log)
                lab = newc["labels"]
                cnt["discard_final" if lab.get("discard") else "labelled"] += 1
                print(f"[label {cid}] {lab.get('category') or lab.get('discard')}(尝试 {newc.get('attempt')})", flush=True)
        reg["label_counts"] = cnt
        CM.atomic_write_json(path, reg, indent=1, default=float)
        print(f"[build label] {cnt}", flush=True)
        return
    raise SystemExit(f"未知 stage {stage}")


# ═══════════════════════════════════════════ §6.3 次要分析:σ 随容差缩放
SIGMA_ID = {"force": "press", "tilt": "ori", "elbow": "elbow"}


def sigma_replay(path: Path, jobs_n: int, eps_dir: Path = EPS / "main") -> None:   # 正式 episode 在 episodes/main/(2026-10-25 正式前修正:原缺省 EPS 读不到大模型规格)
    reg = load_registry(path)
    dec = reg["meta"]["decisions"]
    items = []
    for c in reg["cases"]:
        if c["family"] not in ("T1", "T2a", "T2b") or c["variant"] == "speed" or not c.get("labels"):
            continue
        old = c["start"]["spec"]["requirements"][c["variant"]]["tol"]
        items.append((c, "program", program_ref_spec(c), old))
        for f in sorted(eps_dir.glob(f"{episode_tag(c, 'X').rsplit('_', 1)[0]}_*.json")):
            e = CM.read_json_retry(f)
            if e.get("model") in STRONG and len(e["rounds"]) > 1 and e["rounds"][1].get("spec"):
                items.append((c, e["model"], e["rounds"][1]["spec"], old))
    out = []

    def one(it):
        c, arm, spec, old = it
        d = c["variant"]
        new = next((x["tol"] for x in spec["requirements"].values() if x["quantity"] == d and x["kind"] == "target"), old)
        try:
            cmd, _ = compile_spec(c["task"], spec, dec, sigma_scale={SIGMA_ID[d]: new / old})
        except SpecInvalid:
            return {"case_id": c["id"], "arm": arm, "spec_invalid": True}
        r = run_sim(c["task"], c["start"]["bias"], cmd)
        ev = evaluate(c["gt"]["spec"]["requirements"], r["series"], c["robot"], dec["extreme"])
        return {"case_id": c["id"], "arm": arm, "scale": new / old, "sim": r["dir"], "ok": all_ok(ev), "eval": compact_eval(ev)}
    with ThreadPoolExecutor(jobs_n) as ex:
        for f in as_completed([ex.submit(one, it) for it in items]):
            out.append(f.result())
    LOGS.mkdir(parents=True, exist_ok=True)
    CM.atomic_write_json(LOGS / "sigma_replay.json", out, indent=1, default=float)


# ═══════════════════════════════════════════ 离线自检(冒烟 #2、#5、#6、#7、#9、#14 与计分 / 程序参照 / 抽样确定性)
def _fake_series(n: int = 400, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 0.005
    on = (t >= 0.2) & (t <= 1.8)
    mid = (t >= 0.7) & (t <= 1.3)
    S = {"t": t, "on": on, "mid": mid, "q": np.tile(np.array([0.9, 0.3, 0.0, -2.1, 0.0, 2.0, 0.8]), (n, 1)) + 0.01 * rng.standard_normal((n, 7))}
    S["force"] = 4.0 + 0.3 * rng.standard_normal(n)
    S["force"][on & ~mid] += 1.5
    S["speed"] = 20.0 + 0.5 * rng.standard_normal(n)
    S["speed"][~mid] = 3.0
    S["tilt"] = 15.0 + 0.2 * rng.standard_normal(n)
    S["elbow"] = 0.1 + 0.002 * rng.standard_normal(n)
    S["path"] = 0.1 * rng.standard_normal(n)
    return S


def selftest() -> dict:
    res, fails = {}, []

    def chk(name, cond, detail=None):
        res[name] = bool(cond)
        if not cond:
            fails.append((name, detail))
    dec = dict(DEFAULTS)
    task = "fr3_a"
    s0 = base_spec(task)
    # —— #5 补丁解析
    sp, info = apply_patch(s0, {"requirements": {"elbow": None}}, "edit")
    chk("patch_delete", "elbow" not in sp["requirements"] and info["deleted"] == ["elbow"])
    sp, info = apply_patch(s0, {"requirements": {"force": {"tol": 2.0}}}, "edit")
    chk("patch_field_merge", sp["requirements"]["force"] == {"quantity": "force", "kind": "target", "target": 4.0, "tol": 2.0})
    s1 = copy.deepcopy(s0)
    s1["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": 0.8, "upper": 1.0, "strict": "soft"}
    sp, info = apply_patch(s1, {"requirements": {"q1_range": {"lower": None}}}, "edit")
    chk("patch_field_null_reinfer", sp["requirements"]["q1_range"] == {"quantity": "q1", "kind": "upper", "upper": 1.0, "strict": "soft"}, sp["requirements"]["q1_range"])
    sp, info = apply_patch(s0, {"requirements": {"x": {"quantity": "force", "kind": "upper"}}}, "edit")
    chk("patch_new_incomplete", "x" not in sp["requirements"] and info["invalid_items"] and info["invalid_items"][0]["id"] == "x")
    sp, info = apply_patch(s0, {"requirements": {"fh": {"quantity": "force", "kind": "upper", "upper": 6.0, "strict": "hard"},
                                                 "fs": {"quantity": "force", "kind": "upper", "upper": 5.0, "strict": "soft"}}}, "edit")
    eff, dups = effective_items(sp["requirements"])
    chk("dup_diff_strict_hard_wins", eff[("force", "bound")]["upper"] == 6.0 and eff[("force", "bound")]["strict"] == "hard" and dups)
    sp, info = apply_patch(s0, {"requirements": {"a": {"quantity": "speed", "kind": "upper", "upper": 30.0, "strict": "soft"},
                                                 "b": {"quantity": "speed", "kind": "range", "lower": 5.0, "upper": 25.0, "strict": "soft"}}}, "edit")
    eff, dups = effective_items(sp["requirements"])
    chk("dup_same_strict_intersection", eff[("speed", "bound")] == {"quantity": "speed", "strict": "soft", "lower": 5.0, "upper": 25.0, "kind": "range"}, eff[("speed", "bound")])
    sp, info = apply_patch(s0, {"requirements": {"force": {"strict": "hard"}}}, "edit")
    chk("target_hard_flag", "invalid_hard_target" in info["item_flags"].get("force", []) and sp["requirements"]["force"]["kind"] == "target")
    sp, info = apply_patch(s0, {"requirements": {"q4": {"quantity": "q4", "target": {"value": -2.0}}}, "exec": {"force_comp": {"value": 0.5}}}, "edit")
    chk("nested_numbers", sp["requirements"]["q4"]["target"] == -2.0 and sp["requirements"]["q4"]["tol"] == JOINT_TOL and sp["exec"]["force_comp"] == 0.5)
    sp, info = apply_patch(s0, parse_reply("not json {"), "edit")
    chk("parse_failed", info["parse_failed"] and sp == s0)
    sp, info = apply_patch(s0, {"requirements": {"force": {"tol": 9.0}}, "exec": {"tilt_comp": 99}}, "repair")
    chk("repair_req_ignored", info["repair_req_attempt"] and sp["requirements"] == s0["requirements"] and sp["exec"]["tilt_comp"] == 20.0)
    sp, _ = apply_patch(s0, {"requirements": {"force": None}}, "edit")
    chk("spec_invalid_no_force", bool(spec_issues(sp["requirements"])))
    try:
        compile_spec(task, sp, dec)
        chk("compile_rejects_invalid", False)
    except SpecInvalid:
        chk("compile_rejects_invalid", True)
    # —— #6 编译确定性与缓存命中
    c0, _ = compile_spec(task, s0, dec)
    chk("s0_cmd_equals_v3", {k: v for k, v in c0.items()} == P3.make_cmd(targets_of(task), zero_exec())[0], c0)
    sA, _ = apply_patch(s0, {"requirements": {"force": {"tol": 1.7}}}, "edit")
    chk("tol_only_same_key", compile_spec(task, sA, dec)[0] == c0)
    sB, _ = apply_patch(s0, {"requirements": {"path": None}}, "edit")
    chk("delete_path_same_key", compile_spec(task, sB, dec)[0] == c0)
    e1 = copy.deepcopy(s0)
    e1["requirements"]["zz"] = {"quantity": "force", "kind": "upper", "upper": 6.501, "strict": "hard"}
    e2 = copy.deepcopy(s0)
    e2["requirements"] = dict(reversed(list(e2["requirements"].items())))
    e2["requirements"]["cap"] = {"strict": "hard", "upper": 6.4996, "kind": "upper", "quantity": "force"}
    k1, k2 = compile_spec(task, e1, dec)[0], compile_spec(task, e2, dec)[0]
    chk("equiv_specs_same_key", sim_key(task, {}, k1)[1] == sim_key(task, {}, k2)[1] and k1["ext"]["bounds"][0]["ub"] == 6.5, (k1, k2))
    chk("ext_is_validated", PX.validate_ext(k1["ext"]) == k1["ext"])
    sN, _ = apply_patch(s0, {"requirements": {"elbow": None, "speed": None}, "exec": {"elbow_comp": 0.05, "speed_comp": 3.0}}, "edit")
    cN, iN = compile_spec(task, sN, dec)
    chk("inert_comps", cN["ext"] == {"elbow": False} and cN["V"] == 0.05 and cN["elbow_y"] == 0.1 and set(iN["inert_comps"]) == {"speed_comp", "elbow_comp"}, cN)
    sL = copy.deepcopy(s0)
    sL["requirements"]["tl"] = {"quantity": "tilt", "kind": "lower", "lower": 12.04, "strict": "soft"}
    sL["requirements"]["sl"] = {"quantity": "speed", "kind": "lower", "lower": 10.0, "strict": "hard"}
    cL, _ = compile_spec(task, sL, dec)
    bt = {b["q"]: PX.bound_term(b, "surface:table") for b in cL["ext"]["bounds"]}
    chk("lower_bound_compile", bt["tilt"]["mode"] == "range" and abs(bt["tilt"]["ub"] - math.pi) < 1e-12 and bt["speed"]["mode"] == "range"
        and bt["speed"]["ub"] == PX.SPEED_CAP and abs(bt["tilt"]["lb"] - math.radians(12.0)) < 1e-12 and bt["speed"]["penalty"] == "hard", bt)
    # —— #7 评估器(合成序列手算)
    S = _fake_series()
    ev = evaluate({"f": {"quantity": "force", "kind": "target", "target": 4.0, "tol": 1.0},
                   "fu": {"quantity": "force", "kind": "upper", "upper": 6.0, "strict": "hard"},
                   "fs": {"quantity": "force", "kind": "upper", "upper": 6.0, "strict": "soft"},
                   "sl": {"quantity": "speed", "kind": "lower", "lower": 15.0, "strict": "hard"},
                   "q4": {"quantity": "q4", "kind": "target", "target": -2.1, "tol": 0.05}}, S, "fr3")
    chk("eval_target_mid", abs(ev["f"]["value"] - S["force"][S["mid"]].mean()) < 1e-12 and ev["f"]["window"] == "mid")
    chk("eval_hard_on_max", abs(ev["fu"]["sides"]["upper"]["stat"] - S["force"][S["on"]].max()) < 1e-12)
    chk("eval_soft_on_p95", abs(ev["fs"]["sides"]["upper"]["stat"] - np.percentile(S["force"][S["on"]], 95)) < 1e-12)
    chk("eval_speed_lower_mid", ev["sl"]["sides"]["lower"]["window"] == "mid" and ev["sl"]["ok"] and abs(ev["sl"]["sides"]["lower"]["stat"] - S["speed"][S["mid"]].min()) < 1e-12)
    chk("eval_joint_on_mean", abs(ev["q4"]["value"] - S["q"][S["on"], 3].mean()) < 1e-12 and ev["q4"]["window"] == "on")
    evb = eval_item({"quantity": "force", "kind": "target", "target": float(S["force"][S["mid"]].mean()) + 0.98, "tol": 1.0}, S, "fr3")
    chk("eval_boundary_flag", evb["ok"] and evb["boundary"])
    # —— 计分 + 程序参照
    s_h2 = copy.deepcopy(s0)
    s_h2["requirements"]["force_limit"] = {"quantity": "force", "kind": "upper", "upper": 6.2, "strict": "soft"}
    gt_h2 = copy.deepcopy(s_h2)
    gt_h2["requirements"]["force_limit"]["strict"] = "hard"
    case = {"task": task, "family": "H2", "variant": "force_upper", "start": {"spec": s_h2, "exec": zero_exec()},
            "gt": {"spec": gt_h2, "changes": [gt_change("modify", ("force", "bound"), "force_limit", {"strict": "hard"})], "accept_alt": []}}
    good, gi = apply_patch(s_h2, {"requirements": {"force_limit": {"strict": "hard"}}}, "edit")
    chk("score_h2_correct", score_spec(case, good, gi)["spec_correct"])
    dupd, di = apply_patch(s_h2, {"requirements": {"force_cap2": {"quantity": "force", "kind": "upper", "upper": 6.2, "strict": "hard"}}}, "edit")
    chk("score_h2_duplicate_wrong", not score_spec(case, dupd, di)["spec_correct"])
    wrong, wi = apply_patch(s_h2, {"requirements": {"force_limit": {"strict": "hard"}, "tilt": {"tol": 4.0}}}, "edit")
    sw = score_spec(case, wrong, wi)
    chk("score_preservation_fail", sw["changes_ok"] and not sw["preserve"]["tilt"] and not sw["spec_correct"])
    extra_, ei = apply_patch(s_h2, {"requirements": {"force_limit": {"strict": "hard"}, "q2": {"quantity": "q2", "target": 0.3}}}, "edit")
    chk("score_extra_item", score_spec(case, extra_, ei)["extra"] == ["q2"])
    gfcase = {"task": task, "family": "T1", "variant": "force", "start": {"spec": s0, "exec": zero_exec()},
              "gt": {"spec": None, "changes": [gt_change("modify", ("force", "target"), "force", {"tol": 200 * GF}, {"tol": gf_accept(200)})], "accept_alt": []}}
    g2 = copy.deepcopy(s0)
    g2["requirements"]["force"]["tol"] = round(200 * GF, 6)
    gfcase["gt"]["spec"] = g2
    for v, want in ((1.961, True), (1.96, True), (2.0, False)):
        sp, si = apply_patch(s0, {"requirements": {"force": {"tol": v}}}, "edit")
        chk(f"score_gf_{v}", score_spec(gfcase, sp, si)["spec_correct"] == want)
    pr = program_ref_spec(case)
    pc, _ = compile_spec(task, pr, dec)
    chk("program_ref_applies_gt", pr["requirements"] == gt_h2["requirements"] and pr["exec"] == zero_exec()
        and pc["ext"]["bounds"] == [{"q": "force", "lb": None, "ub": 6.2, "penalty": "hard"}], pc)
    chk("program_ref_scores_correct", score_spec(case, pr, {"parse_failed": False})["spec_correct"])
    # —— #14 词面审计(含人为违规句)
    au = lexical_audit(system_prompt(dec), all_template_sentences())
    chk("lexical_audit_templates", au["ok"], au["violations"][:6])
    au2 = lexical_audit(system_prompt(dec), [(PLANTED_VIOLATION, "paraphrase")])
    chk("lexical_audit_planted_rejected", not au2["ok"], au2)
    # —— #2 设备守卫与版本门篡改
    try:
        device_guard("sprl-server1", "5,6,7")
        chk("guard_remote_7", False)
    except SystemExit:
        chk("guard_remote_7", True)
    try:
        device_guard("sprl-server1", None)
        chk("guard_remote_unset", False)
    except SystemExit:
        chk("guard_remote_unset", True)
    chk("guard_remote_ok", device_guard("sprl-server1", "1,2")["cuda_visible_devices"] == "1,2")
    try:
        device_guard("sprl-server1", "0,1")
        chk("guard_remote_whitelist", False)
    except SystemExit:
        chk("guard_remote_whitelist", True)
    try:
        check_devices(["cuda:2"], "5,6")
        chk("devices_within_cvd", False)
    except SystemExit:
        chk("devices_within_cvd", True)
    # —— 审查 R2 第 5 条:门决定接到情形生成
    d2 = {**dec, "a_speed_tasks": ["fr3_a", "iiwa_a"], "a_elbow_tasks": ALL_TASKS[:5], "dropped_variants": [["H1", "elbow_lower"]]}
    cells = design_cells(d2)
    n_as = sum(1 for c in cells if c["family"] in ("A", "A-rep") and c["variant"] == "speed")
    n_h1 = sum(1 for c in cells if c["family"] == "H1")
    chk("design_gates_filter", n_as == 3 * 2 + 3 * 2 and not any(c["family"] == "H1" and c["variant"] == "elbow_lower" for c in cells)
        and n_h1 == 72 and sum(1 for c in cells if c["family"] == "A" and c["variant"] == "elbow") == 15, (n_as, n_h1))
    chk("design_default_540", len(design_cells(dec)) == 540, len(design_cells(dec)))
    ids = [cell_id(c) for c in cells]
    chk("design_realloc_unique_ids", len(ids) == len(set(ids)))
    # —— 门 D6:d6_spec 与先导 P4 / P9 的规格逐字相同
    fst = {q: {"on": {"max": 6.0, "min": 0.05, "mean": 0.9, "p95": 5.5}} for q in DIMS5}
    fst["tilt"]["on"].update({"min": 14.0, "max": 16.0})
    fst["q1"] = {"on": {"min": 0.88, "max": 0.94, "mean": 0.91}}
    sp_a = d6_spec("fr3_a", fst, "force_hard+1.5")["requirements"]["force_hard"]
    sp_b = d6_spec("fr3_a", fst, "speed_hard+1")["requirements"]["speed_hard"]
    chk("d6_spec_matches_pilot", sp_a == {"quantity": "force", "kind": "upper", "upper": round(6.0 + 1.5, 2), "strict": "hard"}
        and sp_b["upper"] == round(6.0 + 2.0, 1) and d6_spec("fr3_a", fst, "q1_hard_compat")["requirements"]["q1_range"]["lower"] == 0.83)
    soft_dec = {**dec, "planner_soft": ["force", "q"]}
    sp_h = base_spec(task)
    sp_h["requirements"]["fh"] = {"quantity": "force", "kind": "upper", "upper": 7.0, "strict": "hard"}
    sp_h["requirements"]["q1r"] = {"quantity": "q1", "kind": "range", "lower": 0.8, "upper": 1.0, "strict": "hard"}
    ch, ih = compile_spec(task, sp_h, soft_dec)
    chk("planner_softened_recorded", ih["planner_softened"] == ["force", "q1"] and ch["ext"]["bounds"][0]["penalty"] == "quadratic"
        and ch["ext"]["joints"][0]["penalty"] == "quadratic", ih)
    # —— 审查 R2 第 6 条:收紧区间按点核对 E_exec
    stq = {"q1": {"on": {"min": 0.88, "max": 0.94, "mean": 0.91, "pts": {"start": 0.88, "mid": 0.91, "end": 0.94}}}}
    kin_ok = {"exec": {"union": {"q1": [0.6, 1.1]}, "per_point": {n: {"q1": [0.6, 1.1]} for n in ("start", "mid", "end")}}}
    kin_bad = {"exec": {"union": {"q1": [0.85, 0.97]}, "per_point": {n: {"q1": [0.85, 0.97]} for n in ("start", "mid", "end")}}}
    iv1, iv2 = tighten_interval(stq, kin_ok, 0.5, 0.5), tighten_interval(stq, kin_bad, 0.5, 0.5)
    chk("tighten_interval", iv1["feasible"] and abs((iv1["hi"] - iv1["lo"]) - (0.06 + 0.04)) < 1e-12 and not (iv1["lo"] <= 0.91 <= iv1["hi"])
        and iv2["feasible"] is False and tighten_interval(stq, None, 0.5, 0.5)["feasible"] is None, (iv1, iv2))
    # —— 审查 R2 第 2 条:J3 偏移 B 取整后仍可证明
    kin_q4 = {"kin": {"union": {"q4": [-2.3, -2.0]}}}
    item_b = {"quantity": "q4", "kind": "target", "target": round(-2.0 + OFFB_GAP, 2), "tol": JOINT_TOL}
    # —— 审查 R2 第 17(a) 条:割线
    hs = [({**zero_exec(), "speed_comp": 0.0}, {"speed": {"dev": 2.0}}), ({**zero_exec(), "speed_comp": -2.0}, {"speed": {"dev": 0.5}})]
    se_ = _secant_exec({"start": {"exec": zero_exec()}}, "speed", hs)
    chk("secant_exec", se_ is not None and abs(se_["speed_comp"] - round(-2.0 - 0.5 * (-2.0) / (0.5 - 2.0), 4)) < 1e-9, se_)
    # —— 审查 R2 第 4 条:基础设施失败识别
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        Path(td, "sim.log").write_text("...\nRuntimeError: CUDA out of memory. Tried to allocate\n", encoding="utf-8")
        Path(td, "failed.json").write_text(json.dumps({"returncode": 1, "tail": []}), encoding="utf-8")
        inf1 = is_infra_failure(Path(td))
        Path(td, "sim.log").write_text("Traceback ... ValueError: spec\n", encoding="utf-8")
        inf2 = is_infra_failure(Path(td))
        Path(td, "failed.json").write_text(json.dumps({"returncode": "timeout", "tail": []}), encoding="utf-8")
        inf3 = is_infra_failure(Path(td))
    chk("infra_detect", inf1 and not inf2 and inf3, (inf1, inf2, inf3))
    chk("offB_proven_after_rounding", kin_proof(item_b, kin_q4) is not None and kin_proof({**item_b, "target": -2.0 + 0.09}, kin_q4) is None)
    chk("guard_local_ok", device_guard(LOCAL_HOST, None)["host"] == LOCAL_HOST)
    try:
        g0(True, {**ONLINE_STRICT, "cost_layers/spec.py": "0000000000000000"})
        chk("g0_tamper_refuses", False)
    except SystemExit:
        chk("g0_tamper_refuses", True)
    chk("g0_ok", g0(True)["ok"])
    return {"ok": not fails, "n": len(res), "fails": fails, "results": res}


# ═══════════════════════════════════════════ 冒烟用的单项仿真检查(#1、#3、#4)
def joint_check(d: Path, frozen_dir: str | None = None) -> dict:
    """#3:ext_series 的 q 与 log.npz 重算逐位相同;on 掩码由 marks.track + T_path_s 重建后相同;另给关节验收(q1–q7 on 均值 / 极值)。"""
    d = ROOT / d if not Path(d).is_absolute() else Path(d)
    out = {}
    if (d / "ext_series.npz").exists():
        Z = np.load(d / "ext_series.npz")
        L = np.load(d / "log.npz")
        J = CM.read_json_retry(d / "result.json")
        t0, T = J["marks"]["track"][0], J["task"]["T_path_s"]
        on_re = (L["t"] >= t0) & (L["t"] <= t0 + T)
        out.update({"q_bitwise": bool(np.array_equal(Z["q"], L["q"])), "t_bitwise": bool(np.array_equal(Z["t"], L["t"])),
                    "on_rebuilt_equal": bool(np.array_equal(Z["on"].astype(bool), on_re))})
        q_on = Z["q"][Z["on"]]
        out["joint_accept_from_series"] = {f"q{j + 1}": {"mean": float(q_on[:, j].mean()), "min": float(q_on[:, j].min()), "max": float(q_on[:, j].max())} for j in range(7)}
        FS = frozen_series(d)
        out["joint_accept_from_log"] = {f"q{j + 1}": {"mean": float(FS["q"][FS["on"], j].mean()), "min": float(FS["q"][FS["on"], j].min()),
                                                      "max": float(FS["q"][FS["on"], j].max())} for j in range(7)}
        out["joint_accept_equal"] = out["joint_accept_from_series"] == out["joint_accept_from_log"]
        acc = J["accept"]
        S = load_series(d)
        out["series_mean_equals_accept"] = {k: bool(abs(float(np.mean(Z[k][Z['mid' if k in ('force', 'speed', 'path') else 'on'].astype(bool)])) - acc[k]["value"]) <= 1e-6 * max(1.0, abs(acc[k]["value"])))
                                            for k in DIMS5}
        _ = S
    if frozen_dir:
        FS = frozen_series(frozen_dir)
        q_on = FS["q"][FS["on"]]
        out["frozen_joint_accept"] = {"dir": frozen_dir, **{f"q{j + 1}": {"mean": float(q_on[:, j].mean()), "min": float(q_on[:, j].min()),
                                                                         "max": float(q_on[:, j].max())} for j in range(7)}}
    return out


def sim_check(what: str, task: str, tag: str) -> dict:
    dec = load_decisions()
    extra = {"smoke": tag}
    out = {"what": what, "task": task, "tag": tag}
    if what == "g0":                                                       # #1:空 ext 的包装层 S0 与直接调用快照测试台(冻结 v3 同 cmd 仿真)比
        cmd, _ = compile_spec(task, base_spec(task), dec)
        r = run_sim(task, {}, cmd, extra=extra)
        J = CM.read_json_retry(ROOT / r["dir"] / "result.json")
        reg = CM.read_json_retry(ROOT / "results/exp_repair_v3/press/cases_v3.json")
        fd = next(c["labels"]["sims"]["start"] for c in reg["cases"] if c["case_type"] == "edit" and c["task"] == task and c["params"]["start"] == "standard")
        F = CM.read_json_retry(ROOT / fd / "result.json")
        out.update({"wrapper_dir": r["dir"], "frozen_dir": fd, "frozen_device": F.get("device"), "wrapper_device": J.get("device"),
                    "accept_bitwise_equal_frozen": {k: J["accept"][k]["value"] == F["accept"][k]["value"] for k in DIMS5},
                    "accept_wrapper": {k: J["accept"][k]["value"] for k in DIMS5}, "accept_frozen": {k: F["accept"][k]["value"] for k in DIMS5},
                    "log_q_bitwise_equal_frozen": bool(np.array_equal(np.load(ROOT / r["dir"] / "log.npz")["q"], np.load(ROOT / fd / "log.npz")["q"])),
                    "joint": joint_check(ROOT / r["dir"], fd)})
        ev = evaluate(base_spec(task)["requirements"], r["series"], TASKS[task]["robot"])
        out["r2_eval_matches_testbed"] = {k: bool(abs(ev[k]["value"] - J["accept"][k]["value"] * DISP_PER_SI[k]) <= 1e-6 * max(1.0, abs(ev[k]["value"]))) for k in DIMS5}
        return out
    if what == "map":                                                      # #4(合并成一次):删 elbow + force hard 上限 + tilt soft 下限 + speed soft 下限 + q1 soft 范围
        st = provisional_stats(task)
        sp = base_spec(task, drop=("elbow",))
        q1 = st["q1"]["on"]
        sp["requirements"].update({
            "force_hard": {"quantity": "force", "kind": "upper", "upper": round(st["force"]["on"]["max"] + 1.5, 1), "strict": "hard"},
            "tilt_lb": {"quantity": "tilt", "kind": "lower", "lower": round(st["tilt"]["on"]["min"] - 1.0, 1), "strict": "soft"},
            "speed_lb": {"quantity": "speed", "kind": "lower", "lower": 10.0, "strict": "soft"},
            "q1_range": {"quantity": "q1", "kind": "range", "lower": round(q1["min"] - 0.05, 2), "upper": round(q1["max"] + 0.05, 2), "strict": "soft"}})
        cmd, _ = compile_spec(task, sp, dec)
        r = run_sim(task, {}, cmd, extra=extra)
        ev = evaluate(sp["requirements"], r["series"], TASKS[task]["robot"])
        J = r["ext_result"] or {}
        out.update({"dir": r["dir"], "ext": cmd.get("ext"), "windows": J.get("windows"), "marks": J.get("marks"), "refused": r["refused"],
                    "all_phases_accepted": r.get("all_phases_accepted"), "end_y_err_mm": r.get("end_y_err_mm"), "phase_terms": J.get("phase_terms"),
                    "ik_elbow_y": (J.get("ik") or {}).get("elbow_y"), "eval": compact_eval(ev), "stats_source": st.get("source")})
        return out
    if what == "refuse":                                                   # #4:q1 hard 范围在逆解够不着的地方 → 必须 SpecRejected
        # 2026-10-25 只算逆解的核对(草稿区 r1r2/eb/ik_reach.py):关节项的零空间拉力能把 q1 拉动约 0.25–0.3 rad(代价是手肘出容差),
        # 所以「离当前 q1 ≥ 0.08 rad」的区间会被逆解拉进去、不会被拒;冒烟改用滑动段 q1 最大值 + 0.60 rad(逆解后仍差 0.27–0.40 rad)。
        st = provisional_stats(task)
        q1 = st["q1"]["on"]
        sp = base_spec(task)
        sp["requirements"]["q1_range"] = {"quantity": "q1", "kind": "range", "lower": round(q1["max"] + 0.60, 2), "upper": round(q1["max"] + 0.66, 2), "strict": "hard"}
        cmd, _ = compile_spec(task, sp, dec)
        r = run_sim(task, {}, cmd, extra=extra)
        J = r["ext_result"] or {}
        out.update({"dir": r["dir"], "ext": cmd.get("ext"), "refused": r["refused"], "refused_phase": J.get("refused_phase"),
                    "refused_reason": J.get("refused_reason"), "windows": J.get("windows"), "report_text": refusal_text(J.get("refused_reason"), sp),
                    "stats_source": st.get("source")})
        return out
    raise SystemExit(f"未知 --what {what}")


# ═══════════════════════════════════════════ CLI
def set_devices(devs: list | None) -> None:
    if devs:
        check_devices(devs)
        DEVICES[:] = list(devs)


def status() -> None:
    print(f"输出目录 {_rel(OUT)}")
    for p in (DECISIONS, REG_PATH):
        print(f"  {_rel(p)}: {'有' if p.exists() else '无'}")
    n_s = len(list(SIMS.glob("*/ext_result.json"))) if SIMS.exists() else 0
    n_f = len(list(SIMS.glob("*/failed.json"))) if SIMS.exists() else 0
    n_e = len(list(EPS.rglob("*.json"))) if EPS.exists() else 0
    print(f"  仿真 完成 {n_s} / 失败 {n_f};episode {n_e}")
    if REG_PATH.exists():
        reg = CM.read_json_retry(REG_PATH)
        from collections import Counter
        print(f"  登记表 {len(reg['cases'])} 例,冻结={reg.get('frozen')};类别 {dict(Counter((c.get('labels') or {}).get('category') for c in reg['cases']))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("g0")
    sub.add_parser("selftest")
    sub.add_parser("audit")
    sub.add_parser("status")
    s = sub.add_parser("sim-check")
    s.add_argument("--what", choices=["g0", "map", "refuse"], required=True)
    s.add_argument("--task", default="fr3_a")
    s.add_argument("--smoke-tag", required=True)
    s.add_argument("--devices", nargs="+")
    s.add_argument("--max-new-sims", type=int, default=1)
    s = sub.add_parser("joint-check")
    s.add_argument("--dir", required=True)
    s.add_argument("--frozen-dir")
    s = sub.add_parser("pilot")
    s.add_argument("--parts", nargs="+", required=True)
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--devices", nargs="+")
    sub.add_parser("decide")
    s = sub.add_parser("kin-scan")
    s.add_argument("--tasks", nargs="+", default=ALL_TASKS)
    s.add_argument("--reduced", action="store_true")
    s.add_argument("--out-dir", default=None)
    s = sub.add_parser("build")
    s.add_argument("--stage", choices=["starts", "draw", "label"], required=True)
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--devices", nargs="+")
    s.add_argument("--registry", default=str(REG_PATH))
    s.add_argument("--smoke-tag", default=None, help="冒烟:仿真键加盐 {smoke: tag},不与正式仿真共用")
    s.add_argument("--allow-undecided", action="store_true", help="只给冒烟:没有 decisions.json 时用 DEFAULTS")
    s.add_argument("--max-new-sims", type=int, default=None)
    s = sub.add_parser("draw")
    s.add_argument("--provisional", action="store_true", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("subset")
    s.add_argument("--src", required=True)
    s.add_argument("--cases", nargs="+", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("freeze")
    s.add_argument("--registry", default=str(REG_PATH))
    s.add_argument("--allow-provisional", action="store_true")
    s = sub.add_parser("label-one")
    s.add_argument("--registry", required=True)
    s.add_argument("--case", required=True)
    s.add_argument("--devices", nargs="+")
    s.add_argument("--smoke-tag")
    s.add_argument("--max-new-sims", type=int, default=None)
    s = sub.add_parser("episode")
    s.add_argument("--registry", required=True)
    s.add_argument("--case", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--smoke-tag")
    s.add_argument("--max-new-sims", type=int, default=None)
    s.add_argument("--devices", nargs="+")
    s.add_argument("--rounds", type=int, default=ROUNDS)
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("run")
    s.add_argument("--models", nargs="+", default=STRONG)
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--devices", nargs="+")
    s.add_argument("--registry", default=str(REG_PATH))
    s.add_argument("--rounds", type=int, default=ROUNDS)
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("prog-ref")
    s.add_argument("--registry", default=str(REG_PATH))
    s.add_argument("--out", default=None, help="缺省 episodes/program_ref.json;冒烟写别处")
    s = sub.add_parser("sigma-replay")
    s.add_argument("--registry", default=str(REG_PATH))
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--devices", nargs="+")
    a = ap.parse_args()
    if a.cmd == "g0":
        print(json.dumps({"snapshot": SNAP_CHECKS, "online": g0(True), "device": device_guard()}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "selftest":
        r = selftest()
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return 0 if r["ok"] else 1
    if a.cmd == "audit":
        sp = system_prompt()
        au = lexical_audit(sp, all_template_sentences())
        au2 = lexical_audit(sp, [(PLANTED_VIOLATION, "paraphrase")])
        print(json.dumps({"templates": au, "planted": au2}, ensure_ascii=False, indent=1))
        return 0 if (au["ok"] and not au2["ok"]) else 1
    if a.cmd == "status":
        status()
        return 0
    if a.cmd == "joint-check":
        print(json.dumps(joint_check(Path(a.dir), a.frozen_dir), ensure_ascii=False, indent=1, default=float))
        return 0
    if a.cmd == "kin-scan":
        od = Path(a.out_dir) if a.out_dir else KIN
        od.mkdir(parents=True, exist_ok=True)
        for t in a.tasks:
            r = kin_scan(t, reduced=a.reduced)
            CM.atomic_write_json(od / f"{t}.json", r, indent=1, default=float)
            print(f"[kin {t}] exec {r['exec']['n_ok']}/{r['exec']['n_all']} kin {r['kin']['n_ok']}/{r['kin']['n_all']} {r['wall_s']:.0f} s → {_rel(od / (t + '.json'))}", flush=True)
        return 0
    if a.cmd == "draw":
        dec = load_decisions()
        pst: dict = {}

        def base_of(task):
            if task not in pst:
                ps = provisional_stats(task)
                pst[task] = {"S0": ps, "S-noElbow": ps, "S-noSpeed": ps}
            return pst[task]
        reg = draw_registry(lambda case, start: {**base_of(case["task"])["S0"], "provisional": True, "proxy_for": case["start_type"]}, base_of, dec,
                            tag="provisional")
        reg["meta"]["provisional"] = True
        reg["meta"]["audit"] = lexical_audit(system_prompt(dec), [(c["edit"]["text"], c["layer"]) for c in reg["cases"]])
        CM.atomic_write_json(Path(a.out), reg, indent=1, default=float)
        print(json.dumps({"n_cases": len(reg["cases"]), "n_discard_cells": len(reg["discards"]), "audit_ok": reg["meta"]["audit"]["ok"],
                          "gt_sha": block_shas(reg)["gt"], "templates_sha": block_shas(reg)["templates"]}, ensure_ascii=False))
        return 0
    if a.cmd == "freeze":
        print(json.dumps(freeze_registry(Path(a.registry), a.allow_provisional), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "subset":                                                  # 冒烟登记表:从 draw 结果里挑几个情形(不改情形内容)
        src = CM.read_json_retry(Path(a.src))
        keep = [c for c in src["cases"] if c["id"] in set(a.cases)]
        miss = sorted(set(a.cases) - {c["id"] for c in keep})
        if miss:
            raise SystemExit(f"draw 结果里没有 {miss}")
        reg = {**{k: v for k, v in src.items() if k != "cases"}, "cases": keep, "frozen": False, "tag": f"subset:{a.src}"}
        reg["meta"] = {**src["meta"], "subset_of": a.src, "subset_sha256_src": hashlib.sha256(Path(a.src).read_bytes()).hexdigest()}
        CM.atomic_write_json(Path(a.out), reg, indent=1, default=float)
        print(f"{len(keep)} 个情形 → {a.out}")
        return 0
    # —— 下面都是会跑仿真 / 调大模型的命令:G0 拦
    g0(True)
    set_devices(getattr(a, "devices", None))
    device_guard()
    if getattr(a, "max_new_sims", None) is not None:
        SIM_BUDGET["budget"] = int(a.max_new_sims)
    if a.cmd == "sim-check":
        write_manifest(DEVICES, {"cmd": f"sim-check {a.what}"})
        r = sim_check(a.what, a.task, a.smoke_tag)
        LOGS.mkdir(parents=True, exist_ok=True)
        CM.atomic_write_json(LOGS / f"sim_check_{a.what}_{a.task}_{a.smoke_tag}.json", r, indent=1, default=float)
        print(json.dumps(r, ensure_ascii=False, indent=1, default=float))
        return 0
    if a.cmd == "pilot":
        write_manifest(DEVICES, {"cmd": "pilot", "parts": a.parts})
        run_pilot(a.parts, a.jobs)
        return 0
    if a.cmd == "decide":
        print(json.dumps(decide(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "build":
        if a.allow_undecided and not a.smoke_tag:
            raise SystemExit("--allow-undecided 只能和 --smoke-tag 一起用")
        write_manifest(DEVICES, {"cmd": f"build {a.stage}", "smoke_tag": a.smoke_tag})
        build(a.stage, a.jobs, Path(a.registry), extra={"smoke": a.smoke_tag} if a.smoke_tag else None, allow_undecided=a.allow_undecided)
        return 0
    if a.cmd == "label-one":
        reg = CM.read_json_retry(Path(a.registry))
        c = next(x for x in reg["cases"] if x["id"] == a.case)
        lab = label_case(c, reg["meta"]["decisions"], {"smoke": a.smoke_tag} if a.smoke_tag else None, kin_env(c["task"]))
        c["labels"] = lab
        CM.atomic_write_json(Path(a.registry), reg, indent=1, default=float)
        print(json.dumps({k: v for k, v in lab.items() if k not in ("start_stats",)}, ensure_ascii=False, indent=1, default=float))
        return 0
    if a.cmd == "episode":
        reg = load_registry(Path(a.registry))
        c = next(x for x in reg["cases"] if x["id"] == a.case)
        eps_dir = EPS / (f"smoke_{a.smoke_tag}" if a.smoke_tag else "main")
        e = run_episode(c, a.model, a, reg, eps_dir, {"smoke": a.smoke_tag} if a.smoke_tag else None)
        print(json.dumps({k: e[k] for k in ("tag", "spec_correct", "one_shot", "success", "n_rounds", "category", "spec_score", "exec_score")},
                         ensure_ascii=False, indent=1, default=float))
        return 0
    if a.cmd == "run":
        reg = load_registry(Path(a.registry))
        write_manifest(DEVICES, {"cmd": "run", "models": a.models})
        if any(m.lower().startswith("deepseek") for m in a.models):
            raise SystemExit("[R2] deepseek 一律拒绝")
        jobs = [(c, m) for c in reg["cases"] for m in a.models if (c.get("labels") or {}).get("category")]
        jobs.sort(key=lambda j: CM.stable_hash("eb2_order", j[0]["id"], j[1]))  # 固定种子交错排队(两个模型同批)
        cnt = {"done": 0, "llm_down": 0, "infra": 0, "stale": 0, "error": 0}
        with ThreadPoolExecutor(a.jobs) as ex:
            futs = {ex.submit(run_episode, c, m, a, reg, EPS / "main"): (c["id"], m) for c, m in jobs}
            for f in as_completed(futs):
                try:
                    f.result()
                    cnt["done"] += 1
                except LLMDown as e:
                    cnt["llm_down"] += 1
                    print(f"[大模型无回复,本集未写结果,之后重跑补上] {futs[f]} {e}", flush=True)
                except InfraError as e:
                    cnt["infra"] += 1
                    print(f"[基础设施失败,本集未写,之后补跑] {futs[f]} {e}", flush=True)
                except StaleEpisode as e:
                    cnt["stale"] += 1
                    print(f"[已有 episode 版本不符,未覆盖(--force 重跑)] {futs[f]} {e}", flush=True)
                except Exception as e:                                   # noqa: BLE001
                    import traceback
                    cnt["error"] += 1
                    print(f"[失败] {futs[f]} {type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}", flush=True)
        write_manifest(DEVICES, {"cmd": "run-finished", "models": a.models, "counts": cnt})
        print(json.dumps(cnt, ensure_ascii=False), flush=True)
        return 0
    if a.cmd == "prog-ref":
        reg = load_registry(Path(a.registry))
        out = [prog_ref_episode(c) for c in reg["cases"] if (c.get("labels") or {}).get("category")]
        dst = Path(a.out) if a.out else EPS / "program_ref.json"
        CM.atomic_write_json(dst, out, indent=1, default=float)
        print(f"程序参照 {len(out)} 集 → {_rel(dst)}")
        return 0
    if a.cmd == "sigma-replay":
        sigma_replay(Path(a.registry), a.jobs)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
