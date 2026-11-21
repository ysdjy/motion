# 消融实验 A 重新统计(restat_A.py 生成)

- full: 75 个实例,与 full 相同: True
- flat: 75 个实例,与 full 相同: True
- flat_diag: 75 个实例,与 full 相同: True
- llm_l1: 75 个实例,与 full 相同: True
- no_diag: 75 个实例,与 full 相同: True
- no_A: 75 个实例,与 full 相同: True

| 条件 | 成功 | 成功率 | 调用/例 | 总 token/例 | 费用/例 ($) | 大模型等待/例 (s) | 真实耗时/例 (s) | 仿真时钟/例 (s) | 真实耗时合计 (s) | 代码版本数 |
|---|---|---|---|---|---|---|---|---|---|---|
| full | 66/75 | 88.0% | 1.07 | 6693 | 0.0027 | 38.7 | 75.7 | 20.7 | 5680 | 7 |
| flat | 34/75 | 45.3% | 1.19 | 10749 | 0.0041 | 55.6 | 91.1 | 17.6 | 6831 | 4 |
| flat_diag | 36/75 | 48.0% | 1.12 | 9944 | 0.0037 | 59.1 | 90.5 | 17.5 | 6785 | 4 |
| llm_l1 | 68/75 | 90.7% | 1.68 | 8578 | 0.0039 | 69.0 | 120.5 | 26.0 | 9036 | 5 |
| no_diag | 65/75 | 86.7% | 1.09 | 6338 | 0.0027 | 59.8 | 100.5 | 20.8 | 7538 | 6 |
| no_A(参考) | 67/75 | 89.3% | 0.96 | 4855 | 0.0020 | 34.2 | 69.0 | 19.9 | 5172 | 7 |

## 按族的成功数

| 条件 | comp | n121 | strategy | disturb | solver |
|---|---|---|---|---|---|
| full | 21 | 12 | 13 | 14 | 6 |
| flat | 4 | 1 | 12 | 13 | 4 |
| flat_diag | 5 | 1 | 14 | 12 | 4 |
| llm_l1 | 21 | 12 | 14 | 15 | 6 |
| no_diag | 21 | 12 | 11 | 15 | 6 |
| no_A | 21 | 11 | 14 | 15 | 6 |

## 代码版本分布(prov.code)

- full: 21 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 19 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 8 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 8 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=f4922cd3a21f;pms=20ee6b40e4ff; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=ef4dfc5d96cc;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=f4922cd3a21f;pms=d3c2d112a2e3; 5 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91
- flat: 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 18 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91
- flat_diag: 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 17 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 8 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91
- llm_l1: 26 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 23 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 18 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 1 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=f484ff970ba4
- no_diag: 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 25 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 10 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=ef4dfc5d96cc;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 1 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=f484ff970ba4
- no_A: 21 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=7710687fae12; 20 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=a70cc137f84a;pms=3cd64d01d032; 12 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=f4922cd3a21f;pms=20ee6b40e4ff; 8 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 7 个 ← cost_layers=b5a4f51b16fd;exp_sweep=cdb674261930;exp_xemb=ef4dfc5d96cc;pms=c43ef2cefd91; 5 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=e9ae4d1d0c51;pms=c43ef2cefd91; 2 个 ← cost_layers=b5a4f51b16fd;exp_sweep=dcc1f3b95db4;exp_xemb=f4922cd3a21f;pms=d3c2d112a2e3

注:输入 / 输出 token 没有分开存档(tokens_in / tokens_out 列留空),见 README。
