#!/usr/bin/env python3
"""R-XW 确认性检验 F1(B1 − A,终点 v)逐单元导出 + 复算均值。只读 analysis_xw.json / cases_xw.json。

v 的定义(exec_weighted.py unit_metrics + edit_breadth.py eval_item):
  对每个硬约束(HS 族每单元恰好一个:工具倾角 tilt 的单侧上界 17 个 / 下界 16 个),
  在「on」(接触)窗口内取原始序列(decisions.extreme = raw,未平滑)的峰值:上界取 max,下界取 min;
  margin = 上界 − max(或 min − 下界);v = max(0, −margin) / Δ,Δ_tilt = 1°,截到 [0, 3]。单位即「度」。
  无效执行 / 无序列记 3。
F1:每单元先对 3 个种子取 v 均值,单元差 = B1 − A,再按簇(任务 × 方向,12 簇)平均,最后对簇等权平均。
用法:python3 restat_xw_f1.py <analysis_xw.json> <cases_xw.json> <输出目录>
"""
import ast, csv, json, os, sys, collections, statistics as S

a = json.load(open(sys.argv[1])); cases = json.load(open(sys.argv[2])); out = sys.argv[3]
os.makedirs(out, exist_ok=True)
units = {u["uid"]: u for u in cases["test"]["units"] if u.get("family") == "HS"}
def m(r):
    x = r["m"]
    return x if isinstance(x, dict) else ast.literal_eval(x)
rec = []
for r in a["rows"]:
    if r["cls"] != "HS" or r["role"] != "main":
        continue
    mm = m(r); u = units[r["uid"]]
    hard = [it for it in u["contract"].values() if it.get("strict") == "hard"][0]
    rec.append({"uid": r["uid"], "cluster": r["cluster"], "task": r["task"], "robot": u["robot"], "arm": r["arm"], "seed": int(r["seed"]),
                "bound_side": "upper" if "upper" in hard else "lower", "bound_deg": hard.get("upper", hard.get("lower")),
                "v_deg": mm.get("v"), "hard_ok": mm.get("hard_ok"), "all_pass": mm.get("all_pass"), "valid": mm["validity"]["valid"], "sim_dir": r["dir"]})
with open(os.path.join(out, "xw_HS_per_run.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, list(rec[0])); w.writeheader(); w.writerows(sorted(rec, key=lambda x: (x["arm"], x["uid"], x["seed"])))
# 复算 F1
vs = collections.defaultdict(list)
for x in rec:
    if x["arm"] in ("A", "B1") and x["v_deg"] is not None:
        vs[(x["uid"], x["arm"])].append(x["v_deg"])
du = {uid: S.mean(vs[(uid, "B1")]) - S.mean(vs[(uid, "A")]) for uid in units if (uid, "A") in vs and (uid, "B1") in vs}
cl = collections.defaultdict(list)
for uid, d in du.items():
    cl[units[uid]["cluster"]].append(d)
dc = {c: S.mean(v) for c, v in cl.items()}
lines = [f"HS 单元 {len(du)} 个,簇 {len(dc)} 个;每单元种子数 A/B1 = {sorted({len(v) for v in vs.values()})}",
         f"F1 复算:簇均值差的均值 = {S.mean(dc.values()):+.4f} °(结果文件里为 {a['confirmatory']['F1']['mean']:+.4f})", "", "按簇(B1 − A,°):"]
lines += [f"  {c}: {v:+.4f}" for c, v in sorted(dc.items())]
for side in ("upper", "lower"):
    sub = [d for uid, d in du.items() if ("upper" in [it for it in units[uid]["contract"].values() if it.get("strict") == "hard"][0]) == (side == "upper")]
    lines.append(f"{side} 界单元 {len(sub)} 个:单元差均值 {S.mean(sub):+.4f} °")
open(os.path.join(out, "xw_F1_recheck.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
