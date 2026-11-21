#!/usr/bin/env python3
"""消融实验 A(lvA)逐实例重新统计。只读 levels/*.json,不改原文件。

75 个实例 = comp 21 + n121 18 + strategy 15 + disturb 15 + solver 6(25 探针 × 种子 0–2)。
五个论文条件:full / flat / flat_diag / llm_l1 / no_diag(另附 no_A 供参考)。

输出列:
  final_pass      最终全部达标
  llm_calls       成功返回的大模型调用数(失败另计 llm_errors)
  tokens_total    输入 + 输出 token(结果文件只存了和,输入 / 输出拆分不可得)
  cost_usd        OpenCode 返回的 list_cost 累计
  llm_wait_s      L1b + L2 调用耗时之和(含网络重试退避)
  wall_s          整次运行真实耗时(time.time(),含等大模型)= 结果文件里的 sim_s
  sim_clock_s     仿真时钟时长 = stages 最后一项的 t1(大模型调用时仿真暂停,不含等待)
  code_version    prov.code 拼成的版本串,用于检查是否同一份代码

用法:python3 restat_A.py <levels 目录> <输出目录>
"""
import csv, glob, json, os, sys, collections

FAMS = {"comp": 21, "n121": 18, "strategy": 15, "disturb": 15, "solver": 6}
CONDS = ["full", "flat", "flat_diag", "llm_l1", "no_diag", "no_A"]
PAPER = CONDS[:5]

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
rows = []
for f in sorted(glob.glob(os.path.join(src, "*.json"))):
    d = json.load(open(f))
    if d.get("family") not in FAMS or d.get("cond") not in CONDS:
        continue
    L = d.get("llm") or {}
    st = d.get("stages") or []
    code = d.get("prov", {}).get("code", {})
    rows.append({"probe": d["probe"], "family": d["family"], "seed": d["seed"], "cond": d["cond"],
                 "final_pass": int(bool(d.get("final_pass"))), "llm_calls": L.get("calls", 0), "llm_errors": L.get("errors", 0),
                 "tokens_total": L.get("tokens", 0), "tokens_in": "", "tokens_out": "", "cost_usd": L.get("cost_usd", 0.0),
                 "llm_wait_s": L.get("latency_s", 0.0), "wall_s": d.get("sim_s"),
                 "sim_clock_s": round(max((s.get("t1") or 0) for s in st), 2) if st else "",
                 "n_L1b": len(d.get("repairs") or []), "n_L2": len(d.get("replans") or []),
                 "level_path": ">".join(d.get("level_path") or []), "aborted": int(bool(d.get("aborted"))),
                 "code_version": ";".join(f"{k}={v}" for k, v in sorted(code.items())), "file": os.path.basename(f)})

keys = list(rows[0])
with open(os.path.join(out, "lvA_per_instance.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, keys); w.writeheader(); w.writerows(sorted(rows, key=lambda r: (CONDS.index(r["cond"]), r["family"], r["probe"], r["seed"])))

# 检查:每个条件是否恰好覆盖同一组 75 个实例
inst = collections.defaultdict(set)
for r in rows:
    inst[r["cond"]].add((r["family"], r["probe"], r["seed"]))
ref = inst["full"]
lines = ["# 消融实验 A 重新统计(restat_A.py 生成)", ""]
for c in CONDS:
    lines.append(f"- {c}: {len(inst[c])} 个实例,与 full 相同: {inst[c] == ref}")
lines += ["", "| 条件 | 成功 | 成功率 | 调用/例 | 总 token/例 | 费用/例 ($) | 大模型等待/例 (s) | 真实耗时/例 (s) | 仿真时钟/例 (s) | 真实耗时合计 (s) | 代码版本数 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
for c in CONDS:
    rs = [r for r in rows if r["cond"] == c]; n = len(rs)
    m = lambda k: sum(float(r[k] or 0) for r in rs) / n
    lines.append(f"| {c}{'' if c in PAPER else '(参考)'} | {sum(r['final_pass'] for r in rs)}/{n} | {100*sum(r['final_pass'] for r in rs)/n:.1f}% | "
                 f"{m('llm_calls'):.2f} | {m('tokens_total'):.0f} | {m('cost_usd'):.4f} | {m('llm_wait_s'):.1f} | {m('wall_s'):.1f} | {m('sim_clock_s'):.1f} | "
                 f"{sum(float(r['wall_s'] or 0) for r in rs):.0f} | {len({r['code_version'] for r in rs})} |")
lines += ["", "## 按族的成功数", "", "| 条件 | " + " | ".join(FAMS) + " |", "|---" * (len(FAMS) + 1) + "|"]
for c in CONDS:
    lines.append(f"| {c} | " + " | ".join(str(sum(r['final_pass'] for r in rows if r['cond'] == c and r['family'] == f)) for f in FAMS) + " |")
lines += ["", "## 代码版本分布(prov.code)", ""]
for c in CONDS:
    cnt = collections.Counter(r["code_version"] for r in rows if r["cond"] == c)
    lines.append(f"- {c}: " + "; ".join(f"{v} 个 ← {k}" for k, v in cnt.most_common()))
lines += ["", "注:输入 / 输出 token 没有分开存档(tokens_in / tokens_out 列留空),见 README。"]
open(os.path.join(out, "lvA_summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
