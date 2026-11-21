#!/usr/bin/env python3
"""实验 A(11-08):HMR 消融。等 lv2(PID 参数)结束后,6 个条件 × 8 个族 × 种子 0–2,6 个并行进程分到本机两张卡。
每个任务是一次 exp_levels.py run 调用(结果文件已存在就跳过,可重复启动续跑)。"""
import itertools
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
wait_pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
NPAR = int(os.environ.get("A_NPAR", 6))
CONDS = ["full", "flat", "flat_diag", "llm_l1", "no_A", "no_diag"]
FAMS = ["comp", "n121", "strategy", "infeasible", "localopt", "solver", "disturb", "base"]
SEEDS = [0, 1, 2]

while wait_pid is not None:
    try:
        os.kill(wait_pid, 0)
        time.sleep(60)
    except ProcessLookupError:
        break

jobs = [(s, f, c) for s, f, c in itertools.product(SEEDS, FAMS, CONDS)]       # 先跑完一个种子的全部条件:中途停下也有配对的结果
log_dir = ROOT / "logs_hmr" / "lvA"
log_dir.mkdir(parents=True, exist_ok=True)


def run(ij):
    i, (s, f, c) = ij
    dev = f"cuda:{i % 2}"
    env = {**os.environ, "MUJOCO_GL": "egl"}
    cmd = [str(ROOT / ".venv/bin/python"), "pms/exp_levels.py", "run", "--mode", "llm", "--model", "oc:deepseek-v4.1-flash",
           "--cond", c, "--families", f, "--seeds", str(s), "--tag", "lvA", "--device", dev]
    t0 = time.time()
    with open(log_dir / f"{f}_{c}_s{s}.log", "w") as fh:
        rc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    print(f"[{i + 1}/{len(jobs)}] {f} {c} s{s} rc={rc} {time.time() - t0:.0f}s", flush=True)


with ThreadPoolExecutor(NPAR) as ex:
    list(ex.map(run, enumerate(jobs)))
print("ALLDONE", flush=True)
