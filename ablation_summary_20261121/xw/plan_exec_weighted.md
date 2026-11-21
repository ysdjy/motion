# 执行层消融:逐维规格 vs 加权代价(R-XW)实验方案

- 版本:2026-10-26 v2.1(v1 按两份方案审查修订,见 §15;v2 → v2.1 按代码审查修订并加「运行」一节,见 §15a;v1 原文 `plan_exec_weighted_20261026_v1_before_review.md`,v2 原文 `plan_exec_weighted_20261026_v2_before_run.md`)。冒烟已跑(本机,不进分析);正式批次由等待驱动启动。
- 依附:`plan.md`(v3.1);R2 `plan_edit_breadth.md`(冻结登记表、包装层、验收定义、门 D6);E6 `plan_e6_whitebox.md`(加权渲染 r2);`plan_supplement.md` §0(冻结、标注、统计口径)。
- 本文件里的数有三类:(a) 2026-10-26 对冻结代码与冻结数据的只读核对(注明文件与行号;v2 新增的核对脚本在 scratchpad 的 `xw_rev2/`:`hcells.py`、`cacells.py`、`cb_swivel.py`、`power2.py`、`power3.py`);(b) 设计时计算(功效、二次模型,写明假设);(c) 审查人的只读核对(标「审查 B 核对」)。
- **设计时已知的结果**:R2 的 N、H、C-a 单元上 A 的执行结果(R2 登记表 `labels.program_once`)在设计时已知(§1.6)。确认族是在看过这一列之后定的。所以 H 的确认性检验改用新建的、A 结果未知的单元(§3.2);C-a 的检验(F4)以已知的 A 列为条件(§7.4)。
- 路径相对项目根 `projects/franka_cost_layers/`。

## 0. 目的与边界

- 要回答审查意见 C007(工作流转述:容差与硬约束的价值从没在执行中展示过)和「本方法只是 CoRAL 的增量」的风险。做法:同一个 MPPI 执行器、同一批任务、同一份契约,只换「契约 → 代价」的编译方式,所有臂都用原契约逐维验收:
  - A = 本文逐维规格的正常编译(目标、容差 → σ、硬界进分层的 hard 层并带起点拒收、优先级档位);
  - B = 加权代价(CoRAL / L2R 风格):E6 r2 的渲染原样,即目标附近的加权罚项,权重 = 档位常数 × 基础权重,没有容差,硬性最多写成和里的障碍项,单层。B3 在校准集上调权。
- 口径(记忆 `rss2027-paper-framing`):这是本方法的消融,不是与 L2R / CoRAL 系统的正面对比。B 只取「加权和」这种表示;论文里写「加权代价消融」。
- 规格全部由程序从契约生成,不调大模型,不花 API,只做仿真。
- **决定设计的结构事实**(§1.7、§2.5):在这个执行器上,把档位折进权重的加权代价(B1)在所有软项上与 A 是同一个代价函数。两者只在三处不同:
  1. 契约 hard 项:A 放进分层的 hard 层,起点在界外 3σ 以上时拒收;B 写成和里的二次项(B1)或障碍项(B2)。
  2. 容差:A 的 σ 随容差缩放,只在容差不是默认值时生效;B 用固定的 σ0。
  3. 档位:只有加权代价不按档位设权(B1⁻、B3 的部分网格点)时才不同。
  所以每类单元只检验一个字段:H*(新建倾角硬界)检验硬语义;T 检验容差;C-a 检验档位,对照是不带档位的加权代价;N 上 A、B1、B2 按构造相同,只用来量其他臂的副作用。
- 能回答:在这个执行器上,硬语义、容差、档位进入代价后,对原契约的逐维达标、硬限违反、任务维保持有没有可测作用;调过权重的加权代价能不能追平。回答不了:换一个执行器(例如带真硬约束的 QP)会怎样;大模型能不能写对这些字段(那是 R2 / E6 的问题)。

## 1. 代码侦察:决定设计的事实

### 1.1 规格怎样编译成代价项(`cost_layers/spec.py`、`cost.py`)

- 每个原子项编译成 Term:kind ∈ {target, deadzone},σ,gain = PRIORITY[priority] · weight(task 10、preference 1;spec.py 44),penalty ∈ {quadratic, huber, hard}。weight 截到 [0.1, 10],超出只告警(spec.py 213–215)。target 写 hard 时 target 部分按 quadratic(spec.py 475–477)。range / upper / lower 编成死区,残差 relu(x − ub) + relu(lb − x)(cost.py 296–307)。target+range = 一个 target 项加一个同 σ、同 gain、id 带 `/range` 后缀的死区项(spec.py 473–483)。Term 是可写的 dataclass。
- 单项代价 c = g · Σ_t ρ(r / σ),ρ_quad = z²,ρ_hard = 10z² + 100·1[z ≠ 0](cost.py 49–55)。

### 1.2 分层(`sim.py` 469–491;`config.TUNED_LOOP["tiered"] = True`)

- `spec_cost(split=True)`:非 hard 项按 g · ρ 进 soft;hard 项的违反量 V = Σ_t (0.1z² + 1[z ≠ 0]),不乘增益(cost.py 309–330)。S = soft + F_soft;S ← S + (range_K(S) + 1) · V;J = S + (range_K(S) + 1) · F_viol(固定硬限:关节限位、关节速度 / 加速度、工作空间、TCP 速度、接近速度、挡板)。一批样本里 hard 违反量更小的样本一定更优。
- `tiered=False` 会把固定硬限也压成单层,改的不只是表示,所以不用。

### 1.3 硬项的另外两处语义

- 拒收:测试台以 `strict_terms=True` 建闭环。位置类 hard 死区项(pos / pos_ball / ori / ori_cone / q)在规格生效时已在界外 3σ 以上 → SpecRejected(sim.py 445–454)。判据看的是 `t.penalty == "hard"`,所以 B2 的障碍项若沿用 penalty = hard 也会触发拒收,B 臂必须旁路(§9.1)。手肘(link_pos)、速度、力的 hard 项不会被拒。
- 力的 hard 上限不保证实现值:执行器力环积分追 F_des,F_des 只来自力的 target(spec.py 454–455);规划器的 hard 项只影响前馈与运动(R2 §2.3)。

### 1.4 容差在执行里的位置

- R2 的正常编译:容差只用于验收。目标项的 σ 是测试台 / 包装层常数:press 2.0 N、ori 0.03 rad(rx、ry、rz 整姿态目标)、elbow 0.02 m、line 0.003 m、关节 0.02 rad;速度由路径配时决定,没有 σ。
- R2 §6.3 预先登记的「容差同时驱动规划器」规则 σ′ = σ0 · tol / tol0 已在包装层实现(`ext.sigma_scale`,只对 press / ori / elbow,press 下限 1.0 N)。R2 用它重放了 132 个情形(`results/exp_edit_breadth/logs/sigma_replay.json`,program 臂),只有 4 个结果变了:3 个 T1 力情形放宽到 3 倍后由过变不过,1 个 T2b 倾角收紧到 0.4 倍后由不过变过(只读核对)。这说明容差 → σ 在这个执行器上的执行作用小。
- 死区只来自 range / upper / lower 与 target+range。target+range 在容差内仍保留完整的 target 二次项,只在容差外多加一项罚,所以它是「容差外加罚」,不是「容差内放松」。真正的死区要去掉 target 项。这个执行器上能做纯死区的只有三类:倾角(ori 的 range 可以带 R_target,spec.py 271–278)、手肘、关节。力不行:去掉 target 就没有 F_des,力环积分停掉,等于换了执行器。路径不行:profile "path" 只接受 pos 的 target(spec.py 366–368)。速度在规划器里没有目标项。
- 对外接口 `api/robot_control_api.py` 把 tolerance 直接当 σ(`to_engine_dict`,279 行);接口文档 22–26 行说「偏差不超过容差,控制系统……不会再为它牺牲别的项」,与实现不符(§14 D3)。
- 主臂 A 用「R2 正常编译 + R2 §6.3 的容差 → σ 规则」,在默认容差下与 R2 编译逐位相同。死区作为次要臂 A_dz(纯死区,§2.3)。**在 N、H、C 类的默认容差下,A 的容差完全不进入执行;容差只在 T 类上进入执行。** 论文里不用「容差死区」这个说法描述 A。PI 若要以死区为主臂,冻结前改(§14 D0)。

### 1.5 R2 测试台怎样加硬界、关节项,怎样验收

- 包装层 `exp_repair/press_ext_testbed.py`(sha16 8c670b2347b752e5,冻结,只 import):上下限项只加在 track 阶段(force:tcp_force z,σ 1.0 N,w 3,task;speed:speed upper / range,σ 0.002 m/s,w 3,task,下限编成 [lb, 0.25];tilt:ori_cone,σ 0.02 rad,w 3,task;elbow:link_pos y,σ 0.02 m,w 2,preference)。关节项 σ 0.02 rad,w 2,preference,settle 到 lift 全程生效。逆解在零空间以增益 5 同时拉手肘目标与关节目标(range 拉到区间内最近点;`ik_ext`、`joint_goal`),不收敛时整条链退回不拉关节(`ik_fallback`)。逆解只读目标值,不读权重、容差、硬标记。
- 门 D6(`results/exp_edit_breadth/pilot/decisions.json`,sha16 67c09c4eb9218a00):hard 速度上限放进规划器分层时,3/3 个任务走不完滑动,所以 `planner_soft = ["speed"]`,hard 速度界在规划器里按 soft 死区执行,合同仍按 hard 判。**v2 把 D6 当执行器层的规则,所有臂一致适用**:速度界在规划器里一律 ρ_quad(§2.1)。
- 验收(`edit_breadth.eval_item`,820–860 行):target → 窗口均值,|均值 − target| ≤ tol(force / speed / path 用 mid 窗口,tilt / elbow / q 用 on 窗口);soft 界 → p95 / p05;hard 界 → on 窗口 max / min(speed 下限用 mid)。逐样本序列取包装层的 `ext_series.npz`,关节角 = `log["q"][idx]`。本实验原样 import。

### 1.6 已知的 A 列(R2 `labels.program_once`,只读核对,`xw_rev2/hcells.py`、`cacells.py`)

单元按 (任务, 契约, 起点 exec, 隐藏偏差) 去重。「松界」= 界不比 A 自己无界起点(S0 / S0-rep / S1-soft 起点仿真)的 on 窗口统计量更紧(上界 ≥ 起点 max、下界 ≤ 起点 min、区间包住起点范围);否则「绑定」。H 的界本来就是按这些起点统计量加偏移定的(`start.stats_source`)。

| 子类 | 单元 | 松界:A 达标 | 绑定:A 达标 | 备注 |
|---|---|---|---|---|
| 力上限(H1 / H1-rep / H2) | 34 | 21/21 | 0/13 | 力环追 F_des |
| 速度上限 | 29 | 16/16 | 13/13 | D6:规划器 soft |
| 倾角硬窗口(H1) | 18 | 11/11 | 3/7 | 绑定达标的 3 个:iiwa_a、iiwa_b、xarm_b 的 δ = −0.5 |
| 手肘下限(H1) | 15 | 4/4 | 0/11 | 绑定单元上 A 的手肘 min 与起点 min 相同,违反量 ≈ 偏移(+0.01 → 0.93–1.05 Δ;+0.03 → 2.77–3.35 Δ):hard 层没有移动手肘 |
| 硬 q1 范围(J2) | 18 | 9/9 | 3/9 | 绑定达标的 3 个都是 xarm_a 收紧(同一契约的三种说法) |
| C-a(J1 冲突 14 + J3 offA 9 + offB 9) | 32 | 按优先级满足 29/32 | | 不过的 3 个是 J3 offB,都有 `ik_fallback`(pre 处失败)且倾角不达标 |
| N(S0 6 + B0 17) | 23 | 全部达标 23/23 | | |

- H 的程序一次没有拒收,也没有 `ik_fallback`。
- 推论:在 R2 的 H 单元上,A 占优的二值不一致对只可能出现在 A 达标的单元上。松界上 A 全部达标,B 若不达标只能是 B 的副作用;绑定且非力、非速度的 27 个单元里 A 只过 6 个(分属 4 个 (任务, 变体) 簇)。最好情形(6 对全部 A 占优、0 对反向)的单侧精确 McNemar p = 1/64 = 0.016,按簇是 1/16。所以 R2 的 H 单元不能承担二值终点的确认性检验(§8)。
- 位形主要由逆解定位决定:E4 滑动中途改手肘目标 0/12 有可测效果;R2 门 D5 收紧的 soft q1 让 q1 均值最多移动 0.056 rad;上表的手肘行是同一现象。

### 1.7 加权代价 r2 与测试台的项(决定 B1 的形式)

- E6 r2 渲染(`exp_repair/audit_wb.py` 13、418–424 行):`PI_TASK, PI_PREF = 10.0, 1.0`;每项权重 `W_* = PI_* × 基础权重`;`quad(z) = z²`,`barrier(z) = 10z² + 100·(z > 0)`;罚函数按契约的 strictness 选(hard → barrier)。基础权重来自测试台:force 3、speed / path 5(同属 line 项)、tilt 4、elbow 2、safety 1。
- 测试台 track 阶段的项(`exp_xemb_frozen_v3/iiwa_press.py` 299–326 行):line w 5 task(增益 50)、press w 3 task(30)、ori w 4 task(40)、elbow w 2 preference(2)、hold_depth w 2 task(20)。slow(自由段速度 ≤ 0.25 m/s,hard)只在 go / settle / lift。
- 所以 r2 的权重就是 A 的增益 π · w。v1 把档位去掉(B1 = 10 · w),等于把偏好项相对任务项放大 10 倍:手肘从 2 变成 20,对力的 30;在 N、C-a 上 v1 的 B1 与 A\P(π 一律 10)逐项相同。v2 改为 r2 原样(§2.3)。

### 1.8 实现钩子(不改冻结文件;审查 B 已对照代码核实)

- `iiwa_press.run()` 按模块全局名调用 `plan_configs` / `task_specs` / `accept_eval`(494、539、628 行);`sim._start_window` 调用模块全局的 `compile_spec`(sim.py 23、354 行);`step_window` 每次规划都传 `self._cost_fn`(709 行);`apply_cmd` 忽略未知键,`PX.validate_ext` 只检查 `cmd["ext"]`,所以新臂的配置放在顶层 `cmd["xw"]` 是安全的。
- `PX.main()` 调用模块全局的 `PX.install`(press_ext_testbed.py 416 行),所以子进程可以先把 `PX.install` 换成「先调原版、再打 xw 补丁」的版本,再原样调 `PX.main()`;这样 `state["lim"]` 等包装层状态都在。
- R2 的 216 个 program_once 仿真目录在本机都完整(审查 B 核对);远程 sprl1 上没有 R2 的登记表、kin、decisions 与仿真(审查 B 核对,§9.4)。

### 1.9 v1 的 C-b 为什么删掉(CPU 逆解探针)

- v1 的 C-b 设想:硬 q1 范围放在 E_exec 之外、E_kin 之内,冲突对象是测试台钉住方位角的整姿态 ori 项。
- 审查 B 的探针(R_t 固定、手肘拉向目标):g = 0.03 / 0.05 / 0.08 时 q1 只差区间 0.02–0.05 rad,手肘被拉出容差;g = 0.3 时 q1 仍能到 1.16–1.29,超过 E_exec 上界 1.076。
- 本次探针(`xw_rev2/cb_swivel.py`,R_t 固定、不拉手肘、把 q1 拉向 E_kin 外 0.5 rad):iiwa_a 的 q1 到了 0.69–0.86(E_kin 逐点上界 0.50–0.54)和 −0.30(下界 0.195–0.213);iiwa_b 到了 0.72–0.90 和 −0.23;fr3、xarm 在这么远的目标下位姿不收敛。
- 结论:扫描文件的 E_exec / E_kin 都以手肘网格 [0.06, 0.14] m 为条件。姿态固定时 q1 受手肘约束,不受 ori 约束,所以 C-b 的硬 q1 冲突的是手肘偏好,与 J2 收紧、C-a 重复;g = 0.08 时起点离界只有 1.2–2.5σ,A 也不会拒收。C-b 删掉,改用 iiwa q4 的拒收演示(§3.5)。

## 2. 臂与代价形式

### 2.1 各臂相同的部分

- 执行器:快照测试台 `exp_xemb_frozen_v3/iiwa_press.py`(sha16 653ad3a27580c4b1)+ 包装层 + config "tuned";MPPI 种子 0(确认性单元另跑 1、2,经 `cmd["mppi_seed"]`;种子 0 不写这个键,与 R2 的 cmd 相同)。
- 契约 → 命令:`EB.compile_spec(task, spec, dec)`(R2 冻结函数,dec = decisions.json)。exec 补偿与隐藏偏差取 R2 情形的起点值。
- **D6 执行器规则**:dec 的 `planner_soft = ["speed"]` 对所有臂生效:速度界在规划器里一律 ρ_quad,合同仍按 hard 判。
- 逆解定位(主分析):包装层 `plan_configs`,各臂逐位相同。代价一致逆解是预先登记的次要分析(§2.4)。
- 测试台脚手架项(qgo、above、xy、up 各 w 4 task;hold_depth w 2 task)各臂相同。**slow 在所有臂都留在 hard 层**,单一加权和只作用于契约派生的项(`eb_*_bound`、`eb_q*`)。
- 固定硬限(§1.2)在所有臂都是最上层。
- 验收:原契约,`EB.evaluate`,同一窗口与统计量。

### 2.2 记号与两种窗口代价

规格项 i 的残差 r_i(t)(target:x − x*;死区:relu(x − ub) + relu(lb − x)),尺度 σ_i,罚函数 ρ_i,增益 g_i,z_i = r_i / σ_i。ℋ_c = 契约 hard 项(速度界按 D6 不算),ℋ_s = 脚手架 hard 项(slow)。V(ℋ) = Σ_{i∈ℋ} Σ_t (0.1z_i² + 1[z_i ≠ 0])。

- **分层**(A、A\P、A_dz):S = Σ_{i∉ℋ_c∪ℋ_s} g_i Σ_t ρ_i(z_i) + F_soft;S ← S + (range_K S + 1) · V(ℋ_c ∪ ℋ_s);J = S + (range_K S + 1) · F_viol。这就是现有的 `_cost_fn`。
- **合和**(B1、B2、B3、B1⁻、B2⁻):ℋ_c 的项从 hard 层移进 S,按 g_i Σ_t ρ_i 计(B1:ρ_quad;B2:ρ_hard;B3 按网格);ℋ_s 留在 hard 层:S = Σ_{i∉ℋ_s} g_i Σ_t ρ_i(z_i) + F_soft;S ← S + (range_K S + 1) · V(ℋ_s);J = S + (range_K S + 1) · F_viol。
- ℋ_c 为空时两式相同(B1 把契约 hard 项改成 quadratic 后 ℋ_c 为空,不需要替换 `_cost_fn`)。

### 2.3 臂

增益公式(所有臂):g_i = 10 · w_i · a_i · b_i。w_i 是测试台 / 包装层的基础权重(press 3、line 5、ori 4、elbow 目标 2;界项 force / speed / tilt 3、elbow 2;关节 2)。a_i = r_pref,若该项的契约档位是 preference(手肘目标、手肘界、全部关节项),否则 1。b_i = m_b,若该项是契约 hard 界(ext.bounds 里 hard 的项、hard 的关节 range / upper / lower;速度界也算,但罚函数按 D6 恒为 ρ_quad),否则 1。soft 的关节范围、关节目标、soft 界不是「界项」:b = 1,恒为 ρ_quad。

| 臂 | 角色 | r_pref | m_b | 契约 hard 项 | σ | 拒收 | 与 A 只差 |
|---|---|---|---|---|---|---|---|
| **A** | 本文(主) | 0.1 | 1 | 分层的 hard 层 | σ0 · tol / tol0(force:press σ0 2.0 N,tol0 = max(1, 0.2F),下限 1.0 N;tilt:ori σ0 0.03 rad,三轴同缩,tol0 3°;elbow σ0 0.02 m,tol0 0.04;q σ0 0.02 rad,tol0 0.05);path、speed 不缩 | 有 | — |
| **B1** | 加权(主;E6 r2 原样,二次) | 0.1 | 1 | ρ_quad,进和 | σ0 | 无 | 硬语义、拒收、容差 |
| **B2** | 加权 + 障碍(主;E6 r2 原样) | 0.1 | 1 | ρ_hard,进和 | σ0 | 无 | 分层、拒收、容差 |
| **B3** | 按类调权(主) | 网格 | 网格 | 网格:ρ_quad 或 ρ_hard,进和 | σ0 | 无 | 权重(校准集上选,§4) |
| A\P | 归因:去档位 | 1 | 1 | 同 A | 同 A | 有 | 档位 |
| B1⁻ / B2⁻ | 加权去档位(PI 原话的字面读法;描述) | 1 | 1 | ρ_quad / ρ_hard,进和 | σ0 | 无 | 档位 + 硬语义 |
| A_dz | 次要:纯死区 | 0.1 | 1 | 同 A | 倾角:ori 换成 rz 的 target(σ0)+ rx、ry 的 range [−tol/√2, +tol/√2](相对 R_t 的旋转向量,内接于容差锥,σ 0.03 rad);手肘、关节:target 换成 range [x* ± tol];force、line 的 target 不变 | 有 | 容差内放松 |

- A 与 B1 / B2 的增益相同,所以 B1 / B2 不需要覆盖增益;A\P 只是把偏好项的 priority 改成 task。只有 B3 的 m_b = 10、r_pref = 1 等超出 weight 截断的组合要在编译后覆盖 Term.gain(§9.1)。
- B3 = (0.1, 1, quad) 就是 B1,(0.1, 1, barrier) 就是 B2。v1 的「去档位」B1 / B2 降为描述用的 B1⁻ / B2⁻;在 N、C-a 上它们与 A\P 编译相同,共用仿真。
- A\H(只去硬层)在 v2 里就是 B1:没有 hard 项时分层与合和相同,所以不再单列。A\T(只去容差)在 T 类上就是 B1。
- 例(selftest #2 打印核对):J2 收紧单元(hard q1 范围,preference):A 进 hard 层;B1 增益 2、ρ_quad;B2 增益 2、ρ_hard;B3(r, m, f) 增益 10 · 2 · r · m、罚函数 f。H1 手肘下限单元:手肘界同时是 preference 和 hard,增益 10 · 2 · r_pref · m_b。J1 冲突单元(soft q1 范围):各臂增益 10 · 2 · r_pref、ρ_quad,form 与 m_b 都不作用。

### 2.4 代价一致逆解(预先登记的次要分析)

主分析的逆解不读档位、硬性、容差,而位形主要由逆解决定(§1.6),所以主分析在位形类(手肘界、q 界、T-conf)上偏向无差异(§12 #2)。次要分析把逆解改成读这些字段:

- 零空间目标 Σ_i k_i J_iᵀ (goal_i − x_i)。soft 位形项(手肘目标、关节目标 / 范围、B 臂里的界项):k_i = 5 · κ_i / max_j κ_j,κ_i = g_i · c_i / σ_i²,c_i = 1(ρ_quad)或 10(ρ_hard 进和时的二次系数)。A 的 hard 位形项(分层)goal = 区间内最近点,k = 50(最大 soft 增益的 10 倍,近似 hard 层)。range 项的 goal 都是区间内最近点。
- 默认容差下 A 与 B1 的手肘、关节项 κ 相同,归一化后都是 5,与包装层逆解相同(selftest #11 在 N 单元上核对逆解位形)。
- 不收敛时退回包装层逆解,记 `xw_ik_fallback`。
- 用在:R2 的手肘绑定 11 + q1 绑定 9 单元上的 A、B1、B2;T-conf 的 A 与 B1。倾角界不进逆解(R_t 固定),C-a 上 A 与 A\P 的 κ 比值都是 1,与包装层相同,都不跑。

### 2.5 按构造相同的格

编译键相同(§2.6)的臂共享一次仿真;分析里标「按构造相同」,不当证据。

| 类 | B1 vs A | B2 vs A | A\P、B1⁻、B2⁻ | B3 vs A |
|---|---|---|---|---|
| N | 相同 | 相同 | 三者相同 | N 类配置 r_pref = 0.1 时相同 |
| H*(新建倾角界) | 不同(硬语义) | 不同(分层 / 拒收 vs 障碍) | A\P 不跑;B1⁻ ≠ B2⁻ | 选到 (0.1, 1, quad) 时 = B1,(0.1, 1, barrier) 时 = B2 |
| H-R2 力、倾角、手肘、q | 不同 | 不同 | 不跑 | 同上 |
| H-R2 速度 | 相同(D6) | 相同(D6) | 不跑 | m_b = 1 且 r_pref = 0.1 时相同 |
| C-a | 相同 | 相同 | 三者相同 | C 类配置 r_pref = 0.1 时相同 |
| R 拒收演示 | 不同 | 不同 | 不跑 | 不跑 |
| T-conf / T-tight / FV | 不同(容差;= A\T) | = B1 | 不跑 | 不跑 |
| T-conf 一对里的 (i)、(ii) | B1 两套相同,共用一次仿真 | | | |

### 2.6 编译键与缓存

- 父进程按臂把编译结果写成规范化的覆盖表 `cmd["xw"]`,只记与 `EB.compile_spec` 默认不同的东西:`pen`(项 id → quadratic / hard)、`gain`(项 id → 增益,只记与 π · w 不同的)、`sigma`(只记与默认不同的)、`replace`(A_dz 的替换项)、`sum_ids`(从 hard 层移进和的契约项)、`refuse: false`(只在仍有位置类 hard 项时写)、`ik: "cost"`。空表就不写 `cmd["xw"]`,子进程与包装层逐位相同。
- 这样「按构造相同」由键直接体现:N 上 B1、B2 与 A 都是空表;A\P、B1⁻、B2⁻ 在 N / C-a 上都是 `gain = {elbow: 20, q*: 20}`;速度单元上 B2 的障碍按 D6 改回 quadratic,也是空表。selftest #3 断言这些相等与不等。
- 键 = {"v": "xw1", xw 入口 sha、包装层 sha、测试台 sha、`P3.CODE_VER`、`P3.SIM_ARGS`、robot、bias、cmd(含 ext、mppi_seed、xw)、hostname}。仿真目录 `results/exp_exec_weighted/sims/<hostname>/<task>_<hash>`。跨机器不逐位一致,同一单元的全部臂在同一台机器上跑;分析时同一单元各臂主机不同就拒绝。
- 复用 R2:本机、种子 0、空覆盖表的 A,直接用 `EB.load_sim` 只读 R2 的 program_once 目录(不加锁、不写),前提是冒烟 #2 逐位相同。R2 用 `v = "eb2"` 和自己的目录,不会和本实验的键冲突。

## 3. 情形类别

### 3.0 单元与聚类

单元 = 去重后的 (任务, 契约, 起点 exec, 隐藏偏差)。聚类单位 = (任务, 变体)。任务 = fr3_a / fr3_b / iiwa_a / iiwa_b / xarm_a / xarm_b。

| 类 | 来源 | 单元 | 簇 | 角色 | 终点 |
|---|---|---|---|---|---|
| N 无字段差异 | R2(S0 6 + B0 17) | 23 | — | 副作用基线(A\P、B3、A_dz) | 全部达标 |
| **H* 倾角单侧硬界** | 新建 | 36 | 12 | **F1–F3** | 硬界违反量 |
| H-R2 | R2(力 34、速度 29、倾角 18、手肘 15、q1 18) | 114 | — | 描述;绑定 / 松界分开报 | 全部达标、违反量 |
| **C-a 位形偏好 vs 任务维** | R2(J1 冲突 14、J3 18) | 32 | 11 | **F4** | 任务维最差余量 |
| R 拒收演示 | 新建 | 4 | — | 描述(按构造) | 三分类结果 |
| T-conf | 新建 | 14 对 / 28 | — | 描述(按对) | 一对两套都过 |
| T-tight / FV | 新建 | 8 / 6 | — | 描述 | 逐维 |

### 3.1 N(23)

每个任务的 S0 契约(5 个 target,默认容差)+ R2 B0 的 gt 契约。没有 hard 项、没有位形项。A、B1、B2 按构造相同;N 只用来报告 A\P、B3、A_dz 相对 A 的副作用,也作为 H-R2 松界单元上 B 副作用的对照。n = 23 只能给区间(差值区间约 ±0.15–0.2),不构成无差异的证据。

### 3.2 H* 新建的倾角单侧硬界(36,确认性)

- 为什么新建:R2 的 H 单元 A 结果已知,而且绑定单元上 A 几乎做不到(§1.6);力环使力上限不经规划器;手肘被逆解钉住。倾角是规划器直接控制的量(ori 项与 ori_cone 界都在 track 阶段的代价里),硬层在这里才有机会作用。
- 规则:取每个任务 S0 起点仿真(R2 缓存,例如 `sims/fr3_a_946b2e6a83c1a7a3`)的倾角 on 窗口 min / max。上限 ub = round_0.1(max − δ),下限 lb = round_0.1(min + δ),δ ∈ {0.25, 0.5, 0.75}°;契约 = S0 契约 + 一项 `{"quantity": "tilt", "kind": "upper" | "lower", "strict": "hard"}`。6 任务 × 2 方向 × 3 个 δ = 36,簇 = (任务, 方向) 12 个。
- 起点 on 窗口(只读核对):fr3_a [13.96, 16.26]、fr3_b [8.56, 10.82]、iiwa_a [14.85, 15.58]、iiwa_b [9.65, 10.67]、xarm_a [16.23, 16.82]、xarm_b [10.68, 11.45]°。双侧收窄的窗口在 4 个任务上宽度不足 0.3°,所以只用单侧界。
- 对称性:A、B1、B2 在无界的 S0 契约上编译相同(§2.5),所以「按 A 的起点统计量锚定」对这三个臂是同一条轨迹,36 个单元对三者都绑定。B3 若在 H 类选到 r_pref ≠ 0.1,先跑 B3 自己的 6 个无界参照(S0 契约用 B3 的 H 类配置编译),F3 只用对 A 和 B3 都绑定的单元。
- 生成时核对(门 G3):契约可行(界离目标 ≤ 1.5°,目标容差 3°);track 开始时倾角离界 < 3σ(σ 0.02 rad = 1.15°),A 预计不拒收;取整后不同 δ 的界互不相同,与 R2 契约、校准契约的编译键都不相交。
- 这 36 个单元上 A 的结果在设计时未知。

### 3.3 H-R2(114,描述)

R2 冻结登记表(`results/exp_edit_breadth/cases_eb.json`,sha16 019e5f5458704f73,只读)的 H1 / H1-rep / H2 / J2 契约,按 §1.6 分绑定 / 松界报告:B1、B2(全部 85 个非速度单元)、B3(51 个倾角 / 手肘 / q 单元)。松界单元是 B 副作用的对照(B1 / B2 在无界起点上与 A 相同,预期全部达标);绑定单元报二值达标与违反量;手肘、q 的绑定单元另跑代价一致逆解(§2.4)。速度 29 个按构造 A = B1 = B2,只报 B3。

### 3.4 C-a(32,F4)

J1 冲突(soft q1 范围,离 E_kin ≥ 0.05 rad;R2 判「含糊」并丢弃的 3 个 xarm_a 不用)14 个,J3 关节 4 目标 offA / offB 18 个。q 项都是 preference。契约不可能全部满足,按契约优先级,正确的执行是 q 项让步、task 档的 force / speed / tilt / path 守住。A 与 B1、B2 按构造相同(没有 hard 项、默认容差、档位折进权重),所以 C-a 检验的是档位本身:A vs A\P(= B1⁻ = B2⁻)。B3 在 C 类选到 r_pref = 0.1 时也与 A 相同。

### 3.5 R 拒收演示(4,描述,按构造)

iiwa 的 q4 由尖端位姿锁定(`edit_breadth.py` 文档第 11 条;kin 文件里 iiwa_a / iiwa_b 的 q4 逐点上界 E_exec = E_kin = −1.545 / −1.623 rad)。契约 = S0 + hard q4 范围 [上界 + g, 上界 + g + 0.10],g ∈ {0.10, 0.20} rad,iiwa_a、iiwa_b 各两个。预期:A 在 settle 拒收(起点离界 ≥ 5σ),B1 / B2 执行且越界。只用来展示「拒收(安全失败)/ 执行且越界」两列,不进任何检验。

### 3.6 T 容差决定执行(描述)

**T-conf(14 对 / 28 单元)**:q1 目标与手肘目标同为 preference,二者在 E_exec 内近似线性相关,q1 ≈ q1⁰ + s · Δe,s 取 kin 文件的 `slope_q1_per_elbow`。
- 容差:te_s = 0.015 m、te_L = 0.04 m、tq_s = 0.03 rad、tq_L = tq_s + s · (te_L − te_s)。界:b0 = tq_s + s · te_s,b1 = tq_s + s · te_L。Δq ∈ {b0 + 0.25(b1 − b0), b0 + 0.5(b1 − b0), b0 + 0.75(b1 − b0)}。q1 目标 = 起点 q1 均值 ∓ Δq,方向取 E_exec 余量大的一侧。
- **包络规则定为并集**(E_exec 三个点的 q1 范围之并,离边界 ≥ 0.02 rad):验收看的是 on 窗口均值,不要求每个点都能到。按此重算(只读核对,与审查 B 一致):fr3_a 3、fr3_b 3、iiwa_a 1、iiwa_b 2、xarm_a 2、xarm_b 3,共 14 对;逐点规则只剩 7 对,作为敏感性子集报告。
- 每个 Δq 配两套容差:(i) 手肘紧 te_s、q1 宽 tq_L;(ii) 手肘宽 te_L、q1 紧 tq_s。在 E_exec 内没有一个执行同时满足 (i) 与 (ii),但各自可行。B1 不读容差,(i)、(ii) 共用一次仿真,每对至多过 1 个。
- **分析单位是对**,终点「两套都过」。B 在结构上是 0,所以不做 McNemar,只报 A、A_dz 的两套都过率(Wilson 区间)与机理量:A 的 on 窗口手肘均值在 (ii) 与 (i) 之间的移动 ē(ii) − ē(i),与二次模型预测 D_pred 之比(B1 按构造为 0)。包装层逆解与代价一致逆解两套都报。
- 二次模型(只用于解读):规划器近似最小化 κ_e δe² + κ_q (Δq − s δe)²,κ = g / σ²,δe* = κ_q s Δq / (κ_e + κ_q s²)。fr3_a、Δq = 0.177:A(i) δe* ≈ 0.009 m、A(ii) ≈ 0.033 m,两套都过;B1 两套都是 ≈ 0.032 m,只过 (ii)。R2 的 σ 重放只改变了 4/132 个结果(§1.4),预计实际移动远小于预测。
- 解读口径:T-conf 的冲突只存在于执行层(方位角放开后 q1 与手肘解耦:fr3_a 的 E_kin q1 为 [−1.99, 1.53],E_exec 为 [0.59, 1.08]),写成「执行层冲突 / 构造演示」。按容差归一化设权(w ∝ 1 / tol²)的加权代价在软项上与 A 相同,所以 T-conf 能说明的是「容差信息进入了代价」,不是加权表示原理上做不到。

**T-tight(8)**:只取起点偏差高于噪声地板(4 · SD_rep)的维:xarm_a 倾角(偏差 1.63°;新容差 1.0°、1.3°)、xarm_b 倾角(1.20°;1.0°)、fr3_a / iiwa_a 力(0.24 / 0.21 N;0.15 N,A 的 press σ 会被 1.0 N 下限截住)、iiwa_a / iiwa_b 手肘(0.014 m;0.010 m)。

**FV(6)**:每任务 V = 40 mm/s(容差 ±20%),力容差收紧到默认的 0.5 倍,看力与速度能否经规划器折中。

**为什么冲突类只有位形**:力由力环积分追 F_des,速度由路径配时决定,两者都不靠规划器权重折中;起点路径横向偏差 0.1–0.75 mm,远小于 3 mm 容差。PI 点名的力 vs 速度、倾角 vs 路径两类在本执行器上构造不出来,只留 FV 探索;这是对 PI 批准范围的偏离,列为 §14 D4。

## 4. 校准集与 B3

### 4.1 校准集(19 单元,与测试集不相交,盐 "xw-cal")

- N 4:按 B0 规则在 fr3_b / iiwa_a / xarm_b / iiwa_b 上重抽倾角或手肘目标(值与测试 B0 不同)。
- H 9:倾角单侧硬界 δ ∈ {0.4, 0.6}°(fr3_a 上 0.4、fr3_b 下 0.6、iiwa_a 上 0.6、iiwa_b 下 0.4、xarm_a 下 0.6、xarm_b 上 0.4);力上限 −0.75 N(xarm_b);手肘下限 +0.02 m(fr3_b);hard q1 收紧型区间(iiwa_b,R2 `tighten_interval` 规则)。取整后若与测试契约同键,δ 改为 δ − 0.05。
- C 6:J1 冲突型 soft q1 范围,离 E_kin 0.08 rad(fr3_b、iiwa_b、xarm_b);J3 offA 型 q4 目标(fr3_b、iiwa_b、xarm_b)。
- 速度单元不进校准(D6 规则下 B 臂的速度界只受 m_b 影响,单元太少,在并列很多时会左右选择)。T 不进校准(B3 的网格同比例缩放手肘与 q 项,改变不了 T-conf 的结构上限)。
- 核对:校准单元的编译键不出现在测试集。

### 4.2 网格(预先登记,18 个配置)

r_pref ∈ {0.1, 0.3, 1} × m_b ∈ {0.3, 1, 10} × form ∈ {quad, barrier}。增益按 §2.3 公式;form 只作用于契约 hard 界(速度界恒为 ρ_quad)。没有契约 hard 项的单元上 m_b 与 form 不起作用,只有 3 个有效配置,其中 r_pref = 0.1 与 A 相同。目标项之间的比例(press : line : ori = 3 : 5 : 4)是测试台调好的,不调。

### 4.3 选择规则(按类,可部署)

- 类别只从契约结构读出:有契约 hard 项 → H 类;否则有位形项(关节项、soft 手肘界)→ C 类;否则 N 类。每类在自己的校准单元上各选一个配置;测试时按单元的类用对应配置。
- 校准分是连续量:单元得分 s = 计分项里最小的归一化余量(target:(tol − |均值 − target|) / tol;hard 界:到界的有符号距离 / Δ,界内为正),截到 [−3, 1];H、N 类计全部项,C 类计 task 档 target 项。类得分 = 该类单元 s 的均值。二值达标数作次级。
- 取类得分最大的配置;差距在 0.02 以内算并列,并列时取离 (0.1, 1, barrier) 最近的点(距离 = |log10(r_pref / 0.1)| + |log10 m_b| + 0.5 · [form ≠ barrier]),把疑点让给 B。
- 结果在测试登记表冻结之前写进 `decisions_xw.json`。

### 4.4 灵敏度与上界

- 校准集上全部配置的全表(每类)。
- 测试子集(H* 12 个单元,每簇 1 个;N 6;C-a 6)上跑 H 类在选中 r_pref 下**全部 6 个** (m_b, form) 配置(实现按 3 × 2 全积生成;与主作业同键的点由缓存共享:选中 r_pref = 0.1 时 B1、B2 与选中点已跑,新增 ≤ 4 个 / 单元;r_pref ≠ 0.1 时新增 5 个 / 单元。2026-10-26 代码审查 #7 后改写,原文「另外 4 个」),以及 N / C 类的另外 2 个 r_pref:各配置的终点、校准排名与测试排名的 Kendall τ。
- 同一子集上逐单元事后最好配置 B_oracle:只作上界,不可部署。T-conf 不做 B_oracle(网格改变不了它的结构上限)。

## 5. 预先登记的预期(以已知的 A 列为条件)

| 类 / 子类 | 比较 | 预期 | 依据 |
|---|---|---|---|
| N | A = B1 = B2 | 按构造相同 | §2.5 |
| N | A\P、B3、A_dz vs A | 副作用描述;A 23/23 已知 | A\P 把手肘增益抬到 20 |
| H* 倾角单侧界 | A vs B1(F1) | v_A < v_B1 | 硬层按字典序压倾角瞬态;B1 只有增益 30 的二次死区(0.5° 的违反只贡献约 5.8 / 步,ori 目标增益 40) |
| H* | A vs B2(F2) | 差值小,方向 A ≤ B2;可能等价 | 障碍 30 · (10z² + 100) 已经很强 |
| H* | A vs B3(F3) | 选到 barrier 或 m_b ≥ 1 时接近 F2 | |
| H* | B1⁻、B2⁻ | 描述 | 档位去掉后手肘增益 20 |
| H-R2 倾角绑定 7 | A vs B1 / B2 | 二值上 A 占优只可能在 A 达标的 3 个上;违反量方向同 H* | §1.6 |
| H-R2 手肘绑定 11 | 全部比较 | 无差异 | A 的 hard 层没有移动手肘;B 的界更弱,也移不动 |
| H-R2 手肘绑定 11(代价一致逆解) | A vs B1 | v_A < v_B1;A ≈ B2 | 逆解读硬界后 A 把手肘拉向下限,B1 折中 |
| H-R2 q1 绑定 9 | A vs B1 / B2 | 无差异或很小 | 各臂逆解相同地把 q1 拉进区间;A 3/9 |
| H-R2 松界 24 | B vs A | B1 / B2 基本全部达标 | 无界起点上与 A 相同 |
| H-R2 力 34 | A vs B1 / B2 | 无差异 | 力环追 F_des;A 绑定 0/13 |
| H-R2 速度 29 | A = B1 = B2 | 按构造相同 | D6 |
| C-a | A vs A\P(F4) | A > A\P(任务维余量) | A\P 的手肘 / 关节增益 20,接近 press 30;A 已知 29/32 |
| C-a | A vs B1 / B2 | 按构造相同 | 档位折进权重 |
| C-a | A vs B3 | C 类选到 r_pref = 0.1 时按构造相同;否则同 A\P 方向 | |
| R | A vs B | A 拒收(安全失败),B 执行且越界 | 按构造 |
| T-conf | A | 两套都过的对很少 | σ 重放 4/132;位形由逆解定 |
| T-conf | A_dz vs A | A_dz 两套都过更多 | 纯死区在容差内不罚 |
| T-conf | B1 | 每对至多过 1 个 | 按构造 |
| T-tight、FV | — | 不预设方向 | 描述 |

结果的读法:
- F1 显著、F2 不显著且等价检验成立(§7.3):作用来自「知道哪些项是硬的」;把硬性写成障碍项的加权代价也能做到,分层本身没有额外作用。
- F1、F2 都显著:分层 / 拒收本身有作用。
- F1 不显著:这个执行器在倾角界上没有用上硬标记;C007 在本执行器上的回答是否定的,相关主张只能落在验收定义上。
- F4 显著:档位(等价于权重比 10)保护任务维。B1 / B2 在 C-a 上与 A 相同,所以这一条只说明优先级信息进入代价有执行作用,不说明加权表示做不到。
- B3 与 B_oracle 的读法见 §12 #4。

## 6. 指标

- 逐维达标:`EB.eval_item`。全部达标:契约内所有项达标。按优先级满足:全部 hard 项达标,且全部 task 档 target 项(force、speed、tilt、path)达标。
- **硬界违反量** v:on 窗口 max / min 超出界的量 / Δ(Δ:force 1 N、speed 4 mm/s、tilt 1°、elbow 0.01 m、q 0.05 rad),界内为 0,截到 [0, 3]。描述性的违反率与违反量只在已执行的单元上算。
- **任务维最差余量** m:task 档 4 个 target 项的 (tol − |均值 − target|) / tol 取最小,截到 [−3, 1]。
- **三分类结果**:执行且达标 / 拒收 / 执行且越界;另报「安全且有用」= 执行且全部达标。违反率不把拒收计为「没违反」,不作头条数字。
- 确认性终点里的无效执行与拒收:无效执行(5 个阶段没全部采用、没有逐样本序列、|end_y_err| > 5 mm、`ik_failed`)和拒收,v 记 3、m 记 −3(对该臂最差,不奖励拒收);另做剔除这些单元的敏感性分析。
- 高优先级维保持比例:达标的 task 档 target 项数 / 4。
- 权重灵敏度:§4.4。边界标记(`EB.boundary_scale`)。换种子翻转率(确认性单元的 3 个种子)。
- 基础设施失败(OOM / CUDA / 被杀 / 超时):重跑 1 次;仍失败则该单元的整组配对剔除并披露。

## 7. 统计

### 7.1 口径

- 各臂在同一单元上配对(同一台机器)。确认性单元(H* 36、C-a 32)上,检验涉及的臂都跑种子 0、1、2,单元值取 3 个种子的均值;其余单元只跑种子 0。
- 主检验尊重聚类:簇 = (任务, 变体),对簇均值做精确符号翻转。单元级符号翻转(蒙特卡洛 10⁶ 次)作敏感性;按任务聚类(6 簇,最小可达 p = 1/64)只作描述。三台机器在推断上 n = 3,机器层面只描述。
- 比率给 Wilson 区间;差值给簇 bootstrap 95% 区间。工具用快照 `exp_repair_frozen_v3/stats_v3.py`(`wilson_ci`、`mcnemar_paired`、`holm`、`cluster_bootstrap`、`paired_signflip_test`);簇级精确符号翻转新写,selftest 与穷举对照。

### 7.2 【补充·预先登记】确认性族(Holm,m = 4,α = 0.05,单侧,簇级精确符号翻转)

| 检验 | 单元(簇) | 比较 | 终点 | 方向 |
|---|---|---|---|---|
| F1 | H*(36,12) | A vs B1 | 硬界违反量 v | v_B1 − v_A > 0 |
| F2 | H*(36,12) | A vs B2 | v | v_B2 − v_A > 0 |
| F3 | H* 中对 A、B3 都绑定的单元 | A vs B3 | v | v_B3 − v_A > 0 |
| F4 | C-a(32,11) | A vs A\P | 任务维最差余量 m | m_A − m_A\P > 0 |

- 统计量 T = Σ_c d_c(d_c = 簇内单元差值的均值),p = #{s ∈ {±1}^C : Σ_c s_c |d_c| ≥ T} / 2^C。
- 族固定为 4 个检验,不随结果改变。F3 的退路(冻结前写进 decisions):B3 的 H 类配置在全部 H* 单元上与 B1 或 B2 编译键相同 → F3 的 p 取 F1 或 F2 的 p(同一批数据;Holm 在任意依赖下仍控制族错误率);对 B3 绑定的簇少于 8 个 → F3 改为描述,按 p = 1 计入。
- 二值终点(全部达标、硬界达标)在这些单元上作描述:R2 单元的计算表明二值不一致对太少,承担不了确认性检验(§8)。

### 7.3 【描述】

- H*:二值达标(配对精确 McNemar 与差值区间)、三分类结果、B1⁻ / B2⁻、等价检验:A vs B2 的簇均值差在 ±0.10 Δ(倾角 0.1°)内,用两个单侧符号翻转检验各取 α = 0.05(TOST)。只有 TOST 成立时才写「A ≈ B2」,否则只写「没有检出差异(差值 95% 区间 […])」。
- H-R2 各子类(绑定 / 松界分开)、速度子集、力子集;N 的副作用(双侧精确 McNemar、差值区间);C-a 上的 B3;代价一致逆解(配对符号翻转,不进 Holm);A_dz;T-conf(按对);T-tight;FV;R;B_oracle;灵敏度表;换种子翻转率。

### 7.4 条件推断与已知的 A 列

- R2 单元(N、H-R2、C-a)上 A 的结果在确认族确定之前已观察到(§1.6);F4 与全部 R2 单元上的推断以此为条件。F1–F3 用新建的 H* 单元,A 的结果在设计时未知。
- H-R2、C-a 是 R2 冻结契约在新执行条件下的重执行,推断以这些情形为条件,不是独立情形上的复现。

## 8. 功效

- **二值终点为什么不作确认性**:R2 绑定单元上 A 只过 6/27(§1.6),A 占优的不一致对最多 6 个,最好情形的单侧精确 p = 1/64 = 0.016,高于 Holm 最严一级 0.0125;按簇只有 4 簇,最小 p = 1/16。审查 A 在 n = 85、力子类无差异、其余 p10 0.10 / p01 0.03 的设定下复算 v1 的 F1 功效为 0.06(Holm 最严)/ 0.21(α = 0.05)。
- **簇级精确符号翻转**(`xw_rev2/power3.py`;假设簇均值差服从 N(δ, 1),δ 是标准化效应,3000 次模拟;不是预测):

| 簇数 | α | δ = 0.5 | 0.8 | 1.0 | 1.2 |
|---|---|---|---|---|---|
| 12(F1、F2、F3) | 0.0125(Holm 最严) | 0.23 | 0.59 | 0.78 | 0.91 |
| 12 | 0.05 | 0.49 | 0.83 | 0.95 | 0.99 |
| 11(F4) | 0.0125 | 0.22 | 0.52 | 0.73 | 0.88 |
| 11 | 0.05 | 0.47 | 0.78 | 0.91 | 0.98 |

- 换算参照:A 在 R2 倾角绑定单元上的违反量是 0–0.50 Δ(簇间 SD 远小于手肘子类)。δ = 1 大致对应「B1 在多数簇上比 A 多违反约一个簇间 SD」。效应 δ ≈ 0.5 测不出。
- T-conf:14 对,Wilson 区间宽约 ±0.25;N:n = 23,差值区间约 ±0.15–0.2。都只报区间。
- 功效计算在实现时并入 `analyze_exec_weighted.py power`。

## 9. 实现计划

### 9.1 新文件(只新建;冻结文件与他人文件只 import)

**`exp_repair/exec_weighted_testbed.py`(子进程入口,自包含,不 import `edit_breadth` / `exec_weighted`)**
- 按路径加载包装层(核对 sha16 8c670b2347b752e5)与测试台(`PX.load_testbed()`,核对 653ad3a27580c4b1);读 `--cmd` 的 `cmd["xw"]`。没有 `xw` 时直接 `PX.main()`,逐位等于包装层。
- 有 `xw` 时把 `PX.install` 换成 `install_xw(mod, ext, state)`:先调原版 `PX.install`(包装层的 `plan_configs` / `task_specs` / `accept_eval` / `_install` 照常装上,`state["lim"]` 照常设置),再打补丁:
  1. 包 `mod.task_specs`(包装层版本的外层):按 `xw.pen` 改契约项的 penalty,按 `xw.sigma` 改 σ(A 的关节 σ 缩放),按 `xw.replace` 换 A_dz 的项,按偏好 → task 改 priority(A\P、B1⁻、B2⁻);改完逐阶段用 `spec.compile_spec` 预编译,有 rejected_terms 或整份不通过 → `XWCompileError`(框架错误,不是情形结果)。
  2. `xw.gain` 非空时包 `cost_layers.sim.compile_spec`(模块全局):编译后按表覆盖 Term.gain,`<id>` 与 `<id>/range` 都映射。
  3. `xw.sum_ids` 非空时替换 `ClosedLoop._cost_fn`:逐项用公开的 `CostModel.value` / `residual` 与 `cost.rho` 计算,`sum_ids` 里的 hard 项按 g · ρ_hard 进 soft,其余 hard 项(slow)进 V,固定硬限在最上层;窗口切换的 50 ms 混合照原式。
  4. `xw.refuse == false` 时在包装层的 `_install` 外再包一层,编译期间临时 `strict_terms = False`(包装层已保证没有 rejected_terms)。
  5. `xw.ik == "cost"` 时包 `mod.plan_configs`(包装层版本):先 `state["lim"] = lim`,跑 §2.4 的逆解链;失败就调包装层原版并记 `xw_ik_fallback`。
- `PX.main()` 原样运行,`PX.write_outputs` 写 `ext_result.json`、`ext_series.npz`;之后原子写 `xw_result.json`(xw 配置、各阶段每项实际的 penalty / σ / gain / 层、三个 sha、是否旁路过拒收、逆解退路)。**只有 `xw_result.json` 存在才算完成**;只有 `ext_result.json` 的目录按未完成处理。IKFailed 路径同样补写 `xw_result.json`。

**`exp_repair/exec_weighted.py`(框架)**
- 第一件事按 R2 的方式 import `edit_breadth`,只用它的纯函数:`compile_spec`、`evaluate` / `eval_item`、`load_series`、`load_sim`(只读)、`TASKS`、`targets_of`、`default_tol`、`bias_args`、`load_decisions`、`gpu_manifest`(只返回 dict)、`tighten_interval`。**不用** `EB.run_sim` / `sim_dir` / `infra_log` / `write_manifest` / `device_guard`:它们写 `results/exp_edit_breadth/`(`sim_lock` 会 mkdir 并建 `.lock`),`ALLOWED_REMOTE_GPUS` 也不含 7。
- 自己的 `run_sim` / `sim_dir` / `infra_log` / `write_manifest` / `device_guard`,根目录 `results/exp_exec_weighted/`;远程 GPU 白名单 {1, 2, 3, 5, 6, 7},7 只在 16:30 之后且空闲显存 ≥ 8 GB 时可用,永远不用 0 / 4;`CUDA_VISIBLE_DEVICES` 必须显式设置。
- 失败判定:fail tail 里有 `WrapperCompileError`、`ExtFormatError` 或 `XWCompileError` → 框架错误;基础设施失败重跑 1 次;子进程超时 1800 s;`--max-new-sims` 预算。
- 功能:G0(`EB.ONLINE_STRICT` 的 9 个文件 = `common.py` + cost_layers 8 个模块含 `llm.py`;包装层、测试台、`edit_breadth.py` d65f1c1cc7775903、`cases_eb.json` 019e5f5458704f73、`decisions.json` 67c09c4eb9218a00、`kin/*.json` = R2 登记表 meta.sha;冻结后再加本实验三个文件的 sha);`build-cal` / `build-test`(读 R2 登记表、去重、H* / R / T-conf 生成与核对,`seeded_rng("xw2", …)`);`arm_cmd(unit, arm, cfg, seed)` 生成规范化的 `cmd["xw"]`;缓存(§2.6);子命令 `g0` / `selftest` / `smoke` / `run-cal` / `decide` / `ref-b3` / `freeze` / `run` / `status`。
- 输出只写 `results/exp_exec_weighted/{cases_xw.json, decisions_xw.json, sims/<host>/, logs/, manifest_<host>.json, infra_events.jsonl, analysis_xw.*}`。

**`exp_repair/analyze_exec_weighted.py`**:读冻结登记表与仿真结果,`EB.evaluate` 逐维验收,§6 的终点、§7 的检验与区间、灵敏度表、按构造相同格的标注、功效 → `results/exp_exec_weighted/analysis_xw.{md,json}`。

### 9.2 离线自检(`selftest`,不跑仿真)

1. A 的 cmd 与 `EB.compile_spec` 逐字段相同;R2 单元上与 R2 program_once 目录里的 `cmd.json` 相同(复用映射的依据)。
2. 各臂各阶段的 penalty / σ / gain / 层表与 §2.3 公式一致,覆盖 N、H*、H-R2 手肘、J2 收紧、J1、J3、T-conf (i)/(ii)、R 各一例,打印成表。
3. 编译键:N、C-a、速度单元上 B1 = B2 = A;N、C-a 上 A\P = B1⁻ = B2⁻;H* 上 B3(0.1, 1, quad) = B1、B3(0.1, 1, barrier) = B2;H* 上 B1 ≠ B2 ≠ A;T-conf 上 A(i) ≠ A(ii)、B1(i) = B1(ii)。
4. `compile_spec` 包层:表里的项(含 `/range`)增益被覆盖,其余不变。
5. 合和 `_cost_fn` 在合成 rollout 上:`sum_ids` 的项按 g · ρ_hard 进和;slow 仍在 hard 层;固定硬限压过一切;`sum_ids` 为空时与原 `_cost_fn` 数值相同。
6. 用 R2 已有仿真的 `ext_series.npz` 跑 `EB.evaluate`,20 个单元与登记表 `labels.program_once.eval` 逐值相同。
7. H* / R / T-conf / 校准集生成的确定性(同盐同结果)、§3 的判据、校准与测试编译键不相交。
8. 写入守卫:monkeypatch `open` / `os.open` / `os.mkdir` / `Path.mkdir` / `os.replace`,在 build-test、分析(读 R2 目录)与 selftest 本身运行期间,任何指向 `results/exp_edit_breadth/` 的写操作都报错。
9. 簇级精确符号翻转与穷举一致;Holm 族固定 m = 4;单侧 McNemar 与 `stats_v3.mcnemar_exact` 的关系。
10. 入口的四个坑:`ik = "cost"` 设置 `state["lim"]` 并记退路;fail tail 里的 `XWCompileError` 判框架错误;入口文件没有 import `edit_breadth` / `exec_weighted`(AST 扫描);只有 `ext_result.json` 的目录判未完成。
11. 代价一致逆解在 N 单元上的逆解位形与包装层逆解相同(只算逆解,CPU)。

### 9.3 不改的文件

`cost_layers/*`、`exp_xemb/*`、`exp_xemb_frozen_v3/*`、`exp_repair_frozen_v3/*`、`exp_repair/press_ext_testbed.py`、`exp_repair/edit_breadth.py`、`exp_repair/audit_wb.py`、`results/exp_edit_breadth/**`,以及其他正在运行的实验文件(`repair_style*`、`edit_breadth*`、`hard_repair*`、`rules_hg*`、`exp_ft/*`、`run_v3_deepseek.py`)。/home1 是 NTFS:改文件用 Edit 或 Python 写回,不用 `sed -i` / `cp -p`;改本实验已写好的文件前先用 `shutil.copyfile` 备份为 `<名>_<日期>_before_<事由>.py`(`copy2` 的 copystat 在 NTFS 上可能失败)。

### 9.4 远程运行前提(审查 B 核对)

- sprl1 `~/fcl` 的代码与本机一致(edit_breadth d65f1c1c、包装层 8c670b23、测试台 653ad3a2、cost_layers 8 个、common 3ec1d511),但没有 `results/exp_edit_breadth/{cases_eb.json, pilot/decisions.json, kin/*.json}`,也没有 R2 仿真。
- 做法:build-test 在本机做(要读 R2 起点仿真)→ freeze → 只 rsync 新文件 `exp_repair/exec_weighted*.py`、`analyze_exec_weighted.py`、`results/exp_exec_weighted/{cases_xw.json, decisions_xw.json}` 与 R2 的登记表、kin、decisions 三类文件 → 远程跑 G0 → 远程 1–2 次 xw 入口冒烟(EGL + LD_PRELOAD 路径重定向)→ 批次。hg2 运行期间绝不整树同步(`hard_repair.py` 本机仍在改)。回传时排除 `manifest*.json` 与 `*.lock`。
- 远程跑就不能复用 R2 的 A 仿真,按全额预算(§10.1)。

## 10. 计算量与日程

### 10.1 仿真次数(上限 2,000)

| 部分 | 内容 | 新仿真(B3 各类都与 A / B1 / B2 不同时的上限) |
|---|---|---|
| 冒烟 | §13(本机 15 + 远程 2) | 17 |
| 校准 | A 19;B3 网格:H 9 × 18、N 4 × 2、C 6 × 2 | 201 |
| N | A\P 23、A_dz 23、B3 23(A、B1、B2 复用 / 按构造) | 69 |
| H* | A、B1、B2 × 36 × 3 种子 324;B3 108;B1⁻ / B2⁻ 72;B3 无界参照 6 | 510 |
| H-R2 | B1、B2 × 85(非速度)170;B3 × 51;速度上 B3 29 | 250 |
| C-a | A 种子 1、2 64;A\P × 3 种子 96;B3 32;A_dz 32 | 224 |
| R | A、B1、B2 × 4 | 12 |
| T | T-conf:A 28、B1 14、A_dz 28、逆解 A 28 + B1 14;T-tight:A、B1、A_dz × 8;FV:A、B1 × 6 | 148 |
| 代价一致逆解 | H-R2 手肘 11 + q 9 × A、B1、B2 | 60 |
| 灵敏度子集 + B_oracle | H* 12 × 至多 5 = 60(选中 r_pref = 0.1 时 ≤ 48);N 6、C-a 6 × 至多 2 个未跑的 r_pref = 24 | ≤ 84 |
| 合计 | | ≈ 1,560(本机,复用 R2 的 A 仿真 169 次);远程不复用 ≈ 1,730 |

B3 选到与 A / B1 / B2 相同的配置时,约省 250 次。

### 10.2 墙钟

- R2 的 1,367 次仿真:循环 wall_s 中位 33 s(p90 41),端到端(cmd.json 到 ext_result.json)中位 40 s(p90 48),本机 6 路负载下(审查 B 核对);本机满负载约 66 s(记忆)。
- 本机 6 路:1,560 × 40 s / 6 ≈ 2.9 h;满负载 ≈ 4.8 h。
- 远程:18:00 后实际可用 GPU 5、6、7(GPU 1–3 当时被别人占满且 100% 利用,只在显存稳定时用,会更慢);约 12–15 路 × 40 s:校准 ≈ 15 min,正式 ≈ 1.3 h,中间有一道人工门(B3 选择 → 冻结)。

### 10.3 日程(2026-10-26,北京时间)

1. 现在到约 17:30:实现三个新文件与离线自检(不跑仿真)。
2. 约 17:30–18:15:本机冒烟,同时最多 2 路仿真(本机有 R1 ≤ 6 路与 DeepSeek ≤ 6 路)。
3. PI 定 §14 的 D0、D1、D4;冒烟通过后跑校准 + 门(201 次):远程 18:00 后(hg2 结束;不杀别人的进程;`ssh -F <scratchpad>/sshcfg sprl1`,`cd ~/fcl && source ~/fcl_setup/env.sh`),或本机 20:00 后。
4. decide(B3)→ ref-b3(≤ 6 次)→ freeze → 正式 ≈ 1,340 次 → 分析。校准、正式、重复都在同一台机器上跑。
5. 长命令一律后台运行并写日志(`results/exp_exec_weighted/logs/<阶段>_<时间>.log`)。

## 11. 门(测试登记表冻结前决定,写进 `decisions_xw.json`)

- **G0 版本门**:每个运行类命令启动时核对 §9.1 的 sha,不同就停。
- **G2 B3 配置**:§4.3,按类。
- **G3 构造效度**:(a) H*:契约可行、预计不拒收、键互不相同(§3.2);(b) T-conf:并集规则、Δq 判据;(c) R:settle 起点离界 > 3σ(预计拒收);(d) 校准与测试编译键不相交。H* 不满足的单元丢弃不补,丢弃后簇数 < 10 → 停下报告。
- **G4 A 的执行有效性**:校准集任一类 A 的执行有效率 < 0.8 → 停下报告。A 是固定的正常编译,不为本实验调 A。
- **G5 B3 的绑定集**:B3 的 H 类配置 r_pref ≠ 0.1 时先跑 6 个无界参照,定 F3 的单元集;F3 的退路按 §7.2。

## 12. 威胁与局限

1. **执行器上限决定可测效应**:力界只进前馈(积分追 F_des);速度 hard 在所有臂都是规划器 soft(D6);手肘、关节位形主要由各臂相同的逆解决定(§1.6 的手肘行)。这些地方出现 A ≈ B,说明这个执行器没有用上相应字段;不能写成「容差 / 硬约束在执行中无用」,也不能外推到别的执行器。
2. **逆解不读字段**:主分析的逆解只读目标值,硬性、档位、容差一概不看,所以在手肘界、q 界、T-conf 上偏向无差异。代价一致逆解是预先登记的次要分析;这些类出现 null 时,只能归到「逆解不读字段」,不能归到表示本身。
   **代价一致逆解的增益不对称**(2026-10-26 代码审查 #6,按 §2.4 原样实现,未改):A 的分层 hard 位形项 k = 50(绝对值);B2 的同一项以障碍进和,κ 最大,归一化后 k = 5,手肘目标降到 0.5。两臂「界 : 目标」比值相同(10 : 1),但在 400 步、步长截断的求解器里 A 的绝对拉力是 B2 的 10 倍,A 也可能更常退回包装层逆解。所以手肘 / q 绑定格上的 A < B2 可能来自求解器增益而不是表示。分析按退路分层报告(`ik.all` / `ik.no_fallback`,另报各臂退路数),结论以 no_fallback 层为准并写明这一不对称。**请 PI 在冻结前决定**是否改成各臂最大 k 归一到同一绝对值(A hard = B2 障碍 = 50,其余按 κ 比例);若改,只影响 role = ik 的 60 + 42 次仿真,可作补充批次重跑,不影响确认族。
3. **容差 → σ 的映射是选择**:沿用 R2 §6.3。默认容差下 A 的容差不进入执行,容差只在 T 类上检验;A_dz 检验纯死区,而且只在倾角、手肘、关节上可表示(§1.4)。PI 若认为 A 应带死区,结论按 A_dz 读(§14 D0)。
4. **调过权重的加权代价追得上时**:B3 ≈ A → 在这类任务上,硬性 / 档位字段的执行作用可以由一组按类固定的权重复现;本方法的增量不在执行表现,而在字段是可读可验的物理量(E6)。A 沿用此前在同一测试台上定下的常数(D6、力 σ 下限 1 N、包装层的界 σ / 权重 / 档位常数、测试台目标项比例 3 : 5 : 4),本实验没有再调。B_oracle ≈ A > B3 → 字段给出的是逐情形的权重,加权代价要靠逐情形搜索(先跑仿真)才做得到。B3 > A → 本方法的编译不是最优;字段语义同样可以编译成 B3 那样的增益,论文不能写执行优势。三种情况都不支持「加权代价原理上做不到」:除分层与拒收外,加权和与本方法的编译是同一族代价函数。
5. **按构造的部分**:N、C-a、速度上 A = B1 = B2;T-conf 上 B 每对至多过 1 个;R 的结果按构造。结果里标出,不算发现。
6. **锚定**:H* 与 H-R2 的界按 A 的无界起点统计量定。A、B1、B2 的无界起点相同,锚定对三者对称;对 B3(r_pref ≠ 0.1)和 B1⁻ / B2⁻ 不对称,F3 只用对两臂都绑定的单元,B1⁻ / B2⁻ 只描述。
7. **已知的 A 列**:§7.4。
8. **随机性与机器**:确认性单元 3 个种子;其余单元单种子,报换种子翻转率与边界标记。跨机器不逐位一致,同一单元的全部臂同机跑。
9. **拒收的计分**:确认性终点里拒收与无效执行按最差计;描述里分「拒收(安全失败)」与「执行且越界(不安全)」两列。
10. **只有仿真**:验收量都是真机可测的,脚本便于以后搬到真机;现阶段不安排真机。

## 13. 冒烟清单(本机,同时 ≤ 2 路仿真;盐 {"smoke": "xw-s2"},不进分析)

| # | 内容 | 新仿真 |
|---|---|---|
| 1 | `selftest` 全部离线项(§9.2),含 H* / R / T-conf 生成与 R2 只读守卫 | 0 |
| 2 | 逐位相同:xw 入口空覆盖表跑 fr3_a 的 S0 契约,`ext_series.npz` 与 R2 缓存 `sims/fr3_a_946b2e6a83c1a7a3` 逐位相同(决定能否复用 R2 的 A 仿真);同一契约种子 1 有小差异 | 2 |
| 3 | B1 跑一个 H* 上限单元(fr3_a,δ 0.5):完成、有效,`xw_result.json` 的项表与 §2.3 相同 | 1 |
| 4 | B2 跑同一单元:障碍进和、slow 在 hard 层、拒收旁路生效 | 1 |
| 5 | B3 (1, 10, barrier) 跑同一单元:超过 weight 截断的增益(倾角界 300)被覆盖 | 1 |
| 6 | A\P 跑 C-a 一例(fr3_a J1):手肘 / 关节增益 20 | 1 |
| 7 | A_dz 跑 T-conf fr3_a 的 (i):rz target + rx/ry range 编译通过、手肘 / 关节 range 生效 | 1 |
| 8 | 代价一致逆解的 A 跑 H-R2 手肘下限 +0.03(fr3_a):`state["lim"]` 已设、退路被记录 | 1 |
| 9 | R 演示 iiwa_a(g 0.10):A 在 settle 拒收,B2 执行 | 2 |
| 10 | 同一单元同种子在新盐下重跑一次,逐位相同 | 1 |
| 11 | 基础设施:人为让一次仿真超时 → 判基础设施失败并重跑 1 次;`--max-new-sims` 预算停 | 1 |
| 12 | 远程批次前:sprl1 上 xw 入口跑 2 次(空覆盖表 A、B2 的 H* 单元),核对完成标记与 GPU 守卫 | 2(远程) |
| 合计 | | 本机 13–15 + 远程 2 |

## 14. 冻结前要定的事

- **D0 主臂 A 的容差语义**:σ 缩放(本方案,R2 §6.3)还是纯死区(A_dz 升为主臂)。请 PI 签字。论文与结果里写明:默认容差下 A 的容差不进入执行,容差只在 T 类上检验。
- **D1 B1 / B2 的形式(按审查定)**:主对照用 E6 r2 原样(档位常数折进权重;B1 二次、B2 障碍)。PI 原话「base weights as in the E6 R2 representation」的另一种读法(去档位、10 · 基础权重)保留为描述臂 B1⁻ / B2⁻。请 PI 确认。
- **D2 运行机器**:远程(18:00 后,约 1.6 h,不复用 R2)或本机(20:00 后,约 2.9–4.8 h,复用 R2 的 A 仿真 169 次)。
- **D3 接口文档与实现不符**:`api/robot_control_api.py` 22–26 行把容差写成「容差内不再牺牲别的项」,实现是 σ 归一化的平方项。改文档属于改他人文件,这里只记录,由用户决定。
- **D4 冲突类的范围**:冲突类只覆盖位形(C-a、T-conf);力 / 速度字段在本执行器上不经规划器折中,PI 点名的力 vs 速度、倾角 vs 路径只留 6 个探索性 FV。摘要与主张写明这个范围。请 PI 签字。
- **D5 C-b 删除**:探针表明姿态固定时 q1 受手肘约束而不受 ori 约束(§1.9),C-b 与 J2 / C-a 重复;改为 4 个单元的 R 拒收演示。
- **D6 新建 H***:H 的确认性检验改用新建的倾角单侧硬界(A 结果未知),R2 的 H 契约降为描述。这超出「复用 R2 的 H 契约」的原话,但生成规则与 R2 相同(按起点统计量偏移)。请 PI 知悉。

- **PI 签字(2026-10-26 16:54,冻结之前):** 「准备好了就直接跑」——按本节默认执行:D0 主臂 A 用 σ 缩放(实际实现),A_dz 为次要臂;D1 主加权对照用 E6 r2 原样,去档位的 B1⁻ / B2⁻ 只作描述;D2 远程优先(本机后备照驱动规则);D3 接口文档与实现不符只记录、不改 `api/`;D4 冲突类只覆盖位形,力 vs 速度、倾角 vs 路径只留探索性 FV,摘要写明范围;D5 删 C-b;D6 H 的确认性检验用新建 H*。

## 运行(2026-10-26 16:50 定稿;冒烟之后)

### 冒烟结果(本机,同时 2 路;盐 xw-s2 / xw-s2b,不进分析)

- `selftest` 141 项全过(新增 #9b 设备守卫);`analyze_exec_weighted.py selftest` 全过(合成数据含 30 行与主作业重复的 sens / ref 行,H* / C-a / H-R2 各臂 n = 单元数,F1–F4 敏感性齐全,Holm 固定 m = 4)。
- #2 逐位相同:入口改过(sha16 62d74c65093642e0),重做后 fr3_a S0 的 `ext_series.npz` 与 R2 缓存仍逐位相同,门 r2_bitid 已按新入口 sha 写回(本机后备运行可复用 R2 的 A 仿真 159 次)。
- #4 B2 障碍进和、slow 在 hard 层;#9 R 演示 B2 旁路拒收并记录 4 次、无记账错误;#10 同 cmd 换盐重跑逐位相同。
- #13 每类 1 个单元 × 该类全部臂(45 个作业 → 36 次仿真;按构造相同的臂共享仿真):框架问题 0。运行时项表与 §2.3 公式逐项一致(含 B3 (0.3, 10, barrier) 的倾角界增益 300、A\P 的手肘 / 关节 20、A_dz 的死区替换);逆解臂记了逆解项、没有退路;R 的 A 在 settle 拒收(预期)。
  - 情形结果(按 §6 记无效,不是框架错误):TT xarm_a 倾角 1.0° 的 A(end_y_err −6.37 mm)、FV xarm_b 的 A / B1(−5.31 / −5.34 mm)。R2 program_once 里 xarm_a 本来就有 11/69 次 |end_y_err| > 5 mm(中位 −3.92 mm),其余任务 ≤ 3 次;H* 有 3 个 xarm_a 单元,它们的无效执行在确认端点里按最差计,剔除无效的敏感性(§15a #2)单独报。
  - 只作冒烟的观察(不是结果):H* iiwa_a 下限 0.5 上 A / B2 的 v 都是 0.232、B1 0.282;H-R2 手肘绑定单元在代价一致逆解下 A 0.179、B2 0.44、B1 0.665(与 §12 #2 的增益不对称一致);C-a xarm_a offA 上 A 的 m 0.921、A\P 0.396。
- 远程预检:4 个新文件 + R2 登记表 / decisions / kin + cases_xw / decisions_xw 已 rsync --checksum 到 sprl1 `~/fcl`(只新文件,没有整树同步);冻结依赖干跑 0 个文件不同;远程 `exec_weighted.py g0` 通过(ok = True)。远程的 xw 入口仿真(冒烟 #12)由流水线第一步跑。

### 驱动与流水线

- 驱动:`exp_repair/exec_weighted_driver.py`(本机后台常驻,每 5 分钟轮询并写 `results/exp_exec_weighted/driver/driver.log`,状态 `driver/state.json`)。
  - 等远程:sprl1 上没有 `bash …hg2_work/drv_formal.sh` 进程、也没有 `python … hard_repair.py run` 进程(锚定匹配,不会被启动它们的 `bash -c` 外壳误判),连续 2 次;GPU 规则 = 物理卡 ⊂ {1,2,3,5,6,7},最近一次空闲 ≥ 8 GB,最近 3 次快照(约 10 分钟)占用变化 < 2 GB;卡 7 另要求 16:30 之后、无 `~/hg2_work/VACATE_GPU7`、无 exp_ft/ 微调进程、3 次快照占用都 < 1 GB;0 / 4 永不。并发:先用卡 5–7(每张 4 路),不足 12 路再加卡 1–3(每张 2 路),上限 12,不足 4 路不启动;`CUDA_VISIBLE_DEVICES` 只含用到的卡。
  - 本机后备:20:30 之后远程仍未启动、且本机连续 2 次轮询没有其他实验进程(R1 / DeepSeek / hg / 微调 / 任何 press 仿真)时在本机跑(cuda:0 cuda:1,6 路)。一旦在某台机器上启动,整批留在那台机器上。
  - 远程启动前:冻结依赖 rsync --checksum 干跑,有差异就停(不覆盖);再 rsync --checksum 新文件与数据(排除 `manifest*.json`、`*.lock`)。之后 `nohup setsid` 启动远程流水线,每次轮询拉回 `~/xw_work/{status,pipeline.log}` 与远程 `logs/`(到 `driver/remote_work/`、`driver/remote_logs/`)。设备守卫失败(卡被别人占了)→ 回到等卡、同机续跑(已完成的步跳过,仿真有缓存),最多 6 次;其他失败 → 停并记 ALERT。结束后拉回远程 `results/exp_exec_weighted/`(排除 manifest / lock / tmp;远程 infra_events.jsonl 存为 `infra_events_<主机>.jsonl`)。
- 流水线:`exp_repair/exec_weighted_pipeline.sh`,步骤与确切命令(远程在 `~/fcl`,先 `source ~/fcl_setup/env.sh`,再 `export CUDA_VISIBLE_DEVICES=<所选卡>`、`MUJOCO_GL=egl`):
  1. `.venv/bin/python exp_repair/exec_weighted.py smoke --items 12 --jobs 2 --devices <DEVS>`(本机后备为 `--items 2 12`)
  2. `.venv/bin/python exp_repair/exec_weighted.py run-cal --jobs <J> --devices <DEVS>`
  3. `.venv/bin/python exp_repair/exec_weighted.py decide`;`decisions_xw.json` 的 gates.G4.ok 不为真就停(stopped_G4)
  4. `.venv/bin/python exp_repair/exec_weighted.py ref-b3 --jobs <J> --devices <DEVS>`(B3 的 H 类 r_pref = 0.1 时只记 G5,不跑)
  5. `.venv/bin/python exp_repair/exec_weighted.py freeze`
  6. `.venv/bin/python exp_repair/exec_weighted.py run --jobs <J> --devices <DEVS>`
  7. `.venv/bin/python exp_repair/analyze_exec_weighted.py` → `results/exp_exec_weighted/analysis_xw.{md,json}`
  每个 run 类命令自己做 G0 与设备守卫(远程:每张选中的卡 ≥ 8 GB 且 5 s 内稳定)。B3 选择 → 冻结按 §4.3 的预先登记规则自动进行,不再有人工门;G3 / G4 / G5 由程序把关。
- 启动驱动(已执行):`nohup setsid .venv/bin/python exp_repair/exec_weighted_driver.py > results/exp_exec_weighted/driver/driver.out 2>&1 < /dev/null &`

### 仿真次数与时间(远程不复用 R2)

| 部分 | 次数 |
|---|---|
| 冒烟 #12 | 2 |
| 校准 | 201 |
| G5 参照 | 0 或 6 |
| 正式(含灵敏度、逆解、T / R / FV) | 1,114(不含 B3)+ B3:B3 全部选到 r_pref = 0.1 时合计 1,162,最坏 1,387 |
| 合计 | ≈ 1,365–1,596 |

- 远程 hg2 当前的仿真循环 wall 中位约 52 s(最近 30 个,30–78 s)。12 路时吞吐约 0.2 次 / s:1,365–1,596 次 ≈ 1.8–2.2 h。
- 预计:hg2 约 18:00 退出 → 等 2 次轮询 + 3 次稳定快照,约 18:10–18:30 启动 → 约 20:15–20:45 跑完(含分析与拉回)。只有卡 5、6 时 8 路,约 2.8–3.3 h。本机后备(6 路,复用 R2 的 159 次)≈ 2.3–2.8 h。

### 进度与错误检查

- 驱动:`tail -f results/exp_exec_weighted/driver/driver.log`;`cat results/exp_exec_weighted/driver/state.json`
- 远程流水线状态(每次轮询拉回):`cat results/exp_exec_weighted/driver/remote_work/status`;`tail results/exp_exec_weighted/driver/remote_work/pipeline.log`
- 远程实时:`ssh -F results/exp_exec_weighted/driver/sshcfg sprl1 'cat ~/xw_work/status; tail -3 ~/fcl/results/exp_exec_weighted/logs/pipe_run_*.log; find ~/fcl/results/exp_exec_weighted/sims/$(hostname) -name xw_result.json | wc -l'`
- 错误:`grep -hE '"status": "(failed|infra|framework|budget_stop)"' results/exp_exec_weighted/driver/remote_logs/{cal,run}_*.jsonl | wc -l`;`ssh -F results/exp_exec_weighted/driver/sshcfg sprl1 'cat ~/fcl/results/exp_exec_weighted/infra_events.jsonl; grep -lE "CUDA|out of memory" ~/fcl/results/exp_exec_weighted/sims/*/*/failed*.json | head'`
- 停止:`touch results/exp_exec_weighted/driver/STOP`(只停驱动轮询;已启动的远程流水线要停时:`ssh … 'pkill -f "^bash [^ ]*exec_weighted_pipeline"'`,在跑的仿真会自己跑完)

### 风险

1. 冻结在流水线里自动进行:§14 的 D0 / D1 / D4 与 §12 #2 的逆解增益不对称(代码审查 #6)还没有 PI 签字。若 PI 冻结后要改逆解归一化,只能作为补充批次(role = ik,约 100 次),并标为冻结后的补充分析。
2. xarm_a 的 end_y_err 常在 5 mm 附近:H* 的 3 个 xarm_a 单元可能出现与臂无关的无效执行(确认端点记 v = 3),会放大噪声;剔除无效的敏感性单独报。
3. 远程卡 1–3 被别人占满算力;卡 7 可能被微调再次占用。驱动只在规则满足时启动,中途被占由设备守卫拦下后回到等卡。
4. hg2 若推迟结束,启动顺延;20:30 之后本机空闲会改在本机跑(整批同机)。
5. 跨机器不逐位一致:远程批次的 A 不与 R2 的本机 A 列逐位比较;分析只用同一台机器的仿真。

## 15a. 代码审查处理记录(2026-10-26,实现后的代码审查,2 major + 7 minor)

| 编号 | 严重度 | 问题(摘要) | 处理 | 位置 |
|---|---|---|---|---|
| 1 | major | 灵敏度作业(role = sens)包含选中的 B3 配置本身,描述性聚合按 (uid, arm, cfg, seed) 取行时把它和主作业重复计入(H* 45 行 / 33 单元) | 所有描述聚合只取 role = main(ik 臂取 role = ik)且逐聚合断言 (uid, arm, cfg, seed, ik) 唯一;seed_mean / 换种子翻转率按选中的 cH;灵敏度表排除 role = ref;新增 `analyze_exec_weighted.py selftest`(合成数据含 30 行有意重复,核对 H* / C-a / H-R2 各臂 n = 单元数) | analyze:`uniq_check`、`pick1`、`main_rows`、`selftest` |
| 2 | major | §6 的「剔除无效执行与拒收」敏感性只做了 F1 / F2;§7.1 的单元级符号翻转也只做了 F1 / F2 | `confirmatory_supp`:F1–F4 都给剔除无效(v / m 不记最差)、单元级蒙特卡罗(10⁶)、按任务聚类(6 簇),全部标【描述】,放在确认表旁 | analyze:`confirmatory_supp`、md「确认族的敏感性」 |
| 3 | minor | stats_v3.holm 丢掉 NaN,族会小于 m = 4 | 非有限 p 按 1 计入,断言 Holm 结果 4 个都有限;md 标出被映射的检验 | analyze:`confirmatory` |
| 4 | minor | 拒收旁路的记账代码若出错会被 sim._start_window 记成「求值失败」并按无效执行记到 B 臂头上(只 B 臂跑这段代码,不对称) | 记账放进自己的 try,错误写 `bookkeeping_errors`;本实验目录里任何窗口出现「求值失败」一律判框架错误(R2 1367 个目录里 0 次) | testbed `_install` 包层;exec_weighted `load_xw` |
| 5 | minor | 设备守卫只核对卡 7 的空闲显存 | 远程每张选中的卡:空闲 ≥ 8 GB,隔 5 s 两次采样变化 < 2 GB;selftest #9b 覆盖 | exec_weighted `device_guard` |
| 6 | minor | 代价一致逆解里 A 的绝对增益是 B2 的 10 倍 | 未改实现(§2.4 预先登记);按退路分层报告并写进 §12 #2;请 PI 冻结前决定 | analyze `ik_desc`;§12 #2 |
| 7 | minor | 灵敏度子集 H* 的配置数与 §4.4 / §10.1 不符 | 方案改为「选中 r_pref 下全部 6 个 (m_b, form)」,预算改为 ≤ 60 | §4.4、§10.1 |
| 8 | minor | decide 遇到重跑仍失败的校准单元会崩 | 捕获 InfraError,该单元从所有配置的类得分里对称剔除并写 `cal_infra_excluded`;某类剔光就停 | exec_weighted `decide` |
| 9 | minor | H* 二值 McNemar 缺配对差区间;按任务聚类(6 簇)没算 | H* 硬界达标 / 全部达标的配对差 + 簇 bootstrap 95% 区间;F1–F4 的按任务聚类精确符号翻转(描述) | analyze `hs_desc.pairs`、`confirmatory_supp` |

冒烟扩展(§13 #10、#12、#13 已实现):#13 = 每类 1 个单元 × 该类在正式批次会跑的全部臂,逐仿真核对完成标记、执行有效性、运行时项表 = §2.3 公式、逐维验收与指标齐全、逆解记录。

## 15. 审查处理记录(2026-10-26,两份方案审查)

审查 A = 第一份(16 条:must 5、should 8、nice 3),审查 B = 第二份(11 条:must 3、should 5、nice 3)。逐条先对照代码 / 数据核实再处理。

| 编号 | 严重度 | 问题(摘要) | 核实 | 处理 | 位置 |
|---|---|---|---|---|---|
| A1 | must | H 的界锚定在 A 自己的起点轨迹上,A 达标的几乎全是松界;F1 / F2 的 A 占优只可能来自锚定伪影或约 6 个紧界单元;n = 85 的功效只有 0.06 / 0.21 | 属实(只读核对:非力非速度绑定 27 个里 A 过 6 个,分属 4 簇;力绑定 0/13) | 采纳并改做法。B1 / B2 改为 E6 r2 原样后,无界起点与 A 相同,锚定对 A、B1、B2 对称(审查建议的「各臂先跑自己的无界起点」对这三臂按构造免跑;对 B3 保留为 G5 的 6 个参照)。H 的确认性检验改用新建的 36 个倾角单侧硬界(全部绑定、A 结果未知),终点改为连续的违反量、簇级精确符号翻转;力、速度移出确认族;R2 的 H 单元按绑定 / 松界描述;用已知 A 列算明二值终点不可行 | §1.6、§3.2、§3.3、§7.2、§8 |
| A2 | must | §5 与已知 A 列矛盾(手肘正偏移 A 13/13 不过),没有披露 A 列设计时已知 | 属实 | 采纳。§5 改为以已知 A 列为条件,逐子类写出 A 达标数与绑定 / 松界;删掉手肘「A > B1」的预期,改为无差异(代价一致逆解下另有预期);文首、§1.6、§7.4 写明 A 列在确认族确定之前已观察到 | 文首、§1.6、§5、§7.4 |
| A3 | must | 去档位的 B1 / B2 等于 A\P,不是称职的加权代价 | 属实(audit_wb.py 13、418–424;在 N、C-a 上 v1 的 B1 与 A\P 逐项相同) | 采纳。B1 / B2 改为 E6 r2 原样(档位折进权重;二次 / 障碍);去档位版本降为描述臂 B1⁻ / B2⁻,在 N、C-a 上与 A\P 共用编译键;§2.5 补齐按构造相同的格(B1 = A\H、B1 = A\T、B3 网格点 = B1 / B2);D1 按此定 | §1.7、§2.3、§2.5、§14 D1 |
| A4 | must | T-conf 的 F5 / F6 按构造成立且有伪重复;B3 / B_oracle 的同比例缩放过不了 (i) | 属实(二次模型复算同审查) | 采纳。分析单位改为对,终点「两套都过」;B 结构上为 0,不做 McNemar;对数 14 < 20,T-conf 整体降为描述;F5、F6 删除,名额重排;删掉 T-conf 上的 B_oracle;论文写成执行层冲突 / 构造演示,并写明 w ∝ 1/tol² 的加权代价在软项上与 A 相同 | §3.6、§4.4、§7 |
| A5 | must | B3 网格定义与 B2 的等价关系写错;barrier 会把不可达的 soft q1 范围变成障碍项;手肘界的增益不清 | 属实(J1 的 q1_range 是 soft) | 采纳。界项 = 契约 hard 界(form、m_b 只作用于它们);soft 范围、关节目标走 r_pref 组的 ρ_quad;写出统一增益公式 g = 10 · w · a · b,手肘 hard 界 = 10 · 2 · r_pref · m_b;selftest #2 覆盖 J1、J2、手肘单元 | §2.3、§4.2、§9.2 |
| A6 | should | D6 只给了 A,B2 在速度子集上按构造吃亏,并可能左右 B3 的选择 | 属实 | 采纳。D6 作为执行器层规则对所有臂一致适用;速度单元移出校准分;速度子集上 A = B1 = B2 按构造 | §1.5、§2.1、§4.1 |
| A7 | should | B3 选择噪声大、并列偏向弱配置,网格没有 m_b < 1 | 属实 | 采纳。校准分改为连续的归一化余量;并列取离 (0.1, 1, barrier) 最近的点;网格加 m_b = 0.3(18 个配置);按契约结构分类各选一个配置(可部署) | §4 |
| A8 | should | C-b 的拒收、可达性与能力门问题;C-a 与 C-b 混在一个检验里 | 部分属实,且审查 B 的探针表明 C-b 的冲突根本不存在 | 采纳审查 B 的替代方案:删掉 C-b(§1.9 记录两次探针),改为 R 拒收演示(描述);C-a 单独成 F4 | §1.9、§3.4、§3.5 |
| A9 | should | Holm 族与问题不匹配:C007 核心(有无硬语义)只在描述里;F5 / F6 重复 | 属实 | 采纳。族重排为 F1(A vs B1,硬语义有无)、F2(A vs B2,分层 vs 障碍)、F3(A vs B3)、F4(C-a 上 A vs A\P,档位);「A ≈ B2」只在预先登记的 TOST(±0.10 Δ)成立时写 | §7.2、§7.3 |
| A10 | should | 伪重复、单种子;主检验把单元当独立 | 属实(J2 收紧同一任务三个单元几乎是同一契约) | 采纳并改做法。主检验改为 (任务, 变体) 簇级精确符号翻转,单元级降为敏感性;机器层面只描述;确认性单元上检验涉及的臂都跑 3 个种子取均值(连续终点下比「不一致单元多数票」更直接,预算见 §10.1) | §7.1、§10.1 |
| A11 | should | 逆解对表示不敏感,主分析偏向无差异;代价一致逆解只用在 T-conf | 属实 | 采纳。§12 #2 写明;代价一致逆解(hard 位形项进逆解、k = 50;soft 按 κ)设为 H-R2 手肘 / q 绑定单元与 T-conf 上预先登记的次要分析 | §2.4、§12 |
| A12 | should | A_dz 不是死区;容差只在 T 类进入执行,不能用「容差死区」的说法 | 属实(spec.py 473–483) | 采纳。A_dz 改为纯死区(倾角 rx/ry range + rz target、手肘、关节;力、路径 target 不变);D0 请 PI 签字;文中写明容差只在 T 类进入执行 | §1.4、§2.3、§14 D0 |
| A13 | should | 「拒收不算违反」按构造奖励 A | 属实 | 采纳。描述性违反率只在已执行单元上算;报三分类结果与「安全且有用」;确认性终点里拒收按最差计 | §6 |
| A14 | nice | 「A 没有调过、不用调参」说过头 | 属实 | 采纳。改为「A 沿用此前在同一测试台上定下的常数,本实验没有再调」,列出这些常数,删掉「增量是不用调参」 | §12 #4 |
| A15 | nice | 力 vs 速度、倾角 vs 路径的删除没有列为偏离 | 属实 | 采纳。§14 D4 请 PI 签字 | §3.6、§14 |
| A16 | nice | N 在天花板,n = 23 不能确认无差异;功效表与预期不一致 | 属实 | 采纳。N 定位为副作用基线(A、B1、B2 在 N 上按构造相同);写明只报区间;§8 用已知 A 列重写 | §3.1、§8 |
| B1 | must | C-b 不产生所述冲突,§5 预测错 | 属实,本次探针进一步表明姿态固定时 q1 能超出 E_kin(包络以手肘网格为条件) | 采纳:删除 C-b,改为 iiwa q4 拒收演示(审查给出的替代方案) | §1.9、§3.5、§14 D5 |
| B2 | must | EB 的 run_sim / sim_dir / infra_log / write_manifest / sim_lock 写进 R2 目录;device_guard 拒绝 GPU 7 | 属实(edit_breadth.py 127、198–244、662–757) | 采纳。只用 EB 的纯函数;自己的 run_sim 等根在 `results/exp_exec_weighted/`,白名单 {1, 2, 3, 5, 6, 7}(7 按时间与显存放行);R2 目录只用 `EB.load_sim` 读;selftest #8 写入守卫 | §9.1、§9.2 |
| B3 | must | 远程缺 R2 登记表 / kin / decisions / 仿真;整树同步会改 hard_repair 的哈希;逐位相同只在本机证明 | 属实(审查 B 只读 ssh 核对) | 采纳。§9.4 的同步清单、远程 G0 与远程冒烟;回传排除 manifest 与锁;远程按全额预算 | §9.4、§10、§13 #12 |
| B4 | should | B 的单层把脚手架 slow 也移出 hard 层;多处「按构造相同」因此不成立 | 属实(iiwa_press.py 304–325) | 采纳。所有臂 slow 留在 hard 层,单一加权和只作用于契约派生项;A\H 因而等于 B1,不再单列 | §2.1、§2.2、§2.5 |
| B5 | should | T-conf 实际只有 14(并集)/ 7(逐点)对;(i)(ii) 完全相关;σ 重放 4/132 预示 null | 属实(重算一致;sigma_replay.json program 臂 4/132) | 采纳。定为并集规则,逐点 7 对作敏感性;单位改为对,降为描述;两套逆解都报 | §1.4、§3.6 |
| B6 | should | A_dz 部分不可实现,可实现的部分也不是死区 | 属实(spec.py 366–368、454–455;PX.validate_ext 只接受 target / range / upper / lower) | 采纳。同 A12;写明力、速度、路径在本执行器上不能做死区;关节死区直接用 PX 支持的 range 模式 | §1.4、§2.3 |
| B7 | should | 缓存键不含主机;名义配置不同但效果相同的臂按名义键不会共享 | 属实 | 采纳。每台主机一个仿真根、键含主机名;父进程算规范化覆盖表作键,惰性字段丢掉;selftest #3 断言等与不等 | §2.6、§9.2 |
| B8 | should | 钩子实现的五个坑 | 属实 | 采纳。用包 `PX.install` 再原样调 `PX.main()` 的方式;入口自包含;失败判定加 XWCompileError;`<id>` 与 `<id>/range` 都映射;只有 xw_result.json 算完成;selftest #10 | §9.1、§9.2 |
| B9 | nice | 机制可行;G0 是 8 个 cost_layers 模块(含 llm.py)加 common.py | 属实(edit_breadth.py 120–124) | 采纳。改正 G0 的说法;冒烟 #2 保留为复用 R2 的门 | §1.8、§9.1、§13 |
| B10 | nice | 运行时间偏乐观;远程实际只有 GPU 5、6、7 | 属实 | 采纳。按 40 s / 次(满负载 66 s)估算;校准与正式分两个远程批次;GPU 1–3 只在显存稳定时用;保留 `--max-new-sims` 与 1 次基础设施重跑 | §10 |
| B11 | nice | B3 网格里手肘界既在位形组又在界项组 | 属实 | 采纳。同 A5:界项 = 契约 hard 界;手肘 hard 界取 r_pref · m_b | §2.3、§4.2 |

## 16. 偏离与运行记录(冻结之后;2026-10-26 起)

本节只追加,不改前文。时间是北京时间,取自 sprl1 进程写的时间戳(sprl1 文件系统 mtime 比进程时间快约 10 分钟,以进程时间为准)。修改前的方案原文:`plan_exec_weighted_20261026_before_dev_xw.md`;[dev-XW-01] 与 [run-02] 按科学审查改写前:`plan_exec_weighted_20261026_before_dev_xw_amend.md`。

### [run-01] 计划外中途查看 18:09

- 2026-10-26 18:09:30,PI 要求,正式 run 进行到 806/1349 时,用冻结的 `analyze_exec_weighted.py --partial --no-power` 只读看部分结果。记录:sprl1 `results/exp_exec_weighted/logs/interim_looks.log`、`interim_partial_stdout.log`;输出 `analysis_xw_partial.{md,json}`(生成于 18:09:38)。原件备份在 sprl1 `~/xw_dev01/backup_interim_1809/`(sha16 json f5dcc49287957835、md 4874e67d2dde4287);本机 `results/exp_exec_weighted/analysis_xw_partial.*` 是驱动 18:24 拉回的同一份。
- 当时看到的数(1015 行,缺 796 个作业):F1(H* 33 单元 / 12 簇)B1 − A = +0.144 [+0.083, +0.209],p = 0.0002,Holm p = 0.001,拒绝 H0;F2 −0.0003,p = 0.986,Holm p = 1,TOST(±0.10 Δ)等价成立(p_lower = p_upper = 0.0002);F3(B3 = (0.3, 1, barrier),own)−0.004 [−0.019, +0.016],p = 0.645,Holm p = 1;F4 没有数据(C-a 还没跑完 3 个种子)。
- 没有改任何文件、设计、配置、分析或停止规则,运行照常继续。分析与论文里如实披露这次查看。
- (19:50 补)这次查看的输出另存为 sprl1 `results/exp_exec_weighted/logs/interim_20261026_1809_analysis_xw_partial.{json,md}`(sha16 f5dcc49287957835 / 4874e67d2dde4287,与上面的备份逐字节相同);本机同名另存。见 [run-02] 的表。

### [dev-XW-01] A_dz 在目标超出硬件限位的单元上不可编译(框架停跑)

(2026-10-26 19:50 按科学审查改写本小节与 [run-02];改写前原文见 `plan_exec_weighted_20261026_before_dev_xw_amend.md`。)

**事实与时间**
- 16:58 sprl1 流水线启动(`CUDA_VISIBLE_DEVICES=5,6,7`,jobs 12)。smoke、run_cal、decide、ref_b3、freeze 全部 rc = 0(17:16:08 冻结);17:16 开始 run(1349 个唯一编译键)。
- 18:09 [run-01] 计划外中途查看(PI 要求)。
- 18:21:53 唯一一个框架错误:A_dz(Adz)在 `CA|iiwa_a|J3-offB-abs|000` 上,目录 `results/exp_exec_weighted/sims/da88a21e8aee/iiwa_a_c3448c02598df0cf`,入口 `exec_weighted_testbed.task_specs`(450 行)抛 `XWCompileError: 阶段 settle: reject_reason=None rejected_terms=[('eb_q4_target', '裁剪到硬件限位后 lb >= ub')]`。`run_batch` 按设计停止调度新作业;18:22:25 run 步 rc = 1(`FrameworkError: 批次 run 遇到框架错误`)。批次日志 `logs/run_20261026_171616.jsonl`:ok 1044、framework 1、skipped 304。skipped 里有 6 个键已经有结果(N 的 S0 单元上灵敏度作业 B3 (0.3, 1, barrier) 与 G5 参照作业编译键相同,ref-b3 时已跑),实际没跑的是 298 个键。
- 约 19:00 编排者(Claude)提出并开始实施本偏离,同时把处理方案告诉 PI:A_dz 在这类单元上记 N/A,只影响涉及 A_dz 的比较,如实披露。19:00–19:12 诊断、逐键编译枚举、实现。
- 19:10:47 / 19:11:38 两个包装层文件定稿(`exec_weighted_dev01.py` / `analyze_exec_weighted_dev01.py`),19:12 同步到 sprl1。
- 19:13:06–19:13:24 sprl1 冒烟 (a)(b)(c)(见下)。(c) 打印了 F4 的部分结果,见 [run-02]。19:13:30–19:16 写本小节初稿,时间在看到 F4 之后。
- 19:26 PI 要求看 F4,看到的是 19:13 那份部分结果(`logs/interim_looks.log` 19:26:31 条)。
- 两份对抗式审查。代码审查:不阻塞。科学审查:披露与分析表的问题阻塞(本次改写和分析包装层第二版就是为此),但明确认为重新启动本身没有问题。按代码审查,运行包装层改了两处(见「文件」)。
- 19:30:07 用运行包装层续跑(见「续跑」)。

**提出、决定与确认**
- 提出并决定:编排者(Claude),依据 PI 的常设指示「执行层加权消融这个准备好了就直接跑 / 有空卡就跑」。约 19:00 告知 PI 处理方案。
- PI 确认:**待 PI 确认**。
- PI 确认记录(时间 / 方式 / 原话):______________________________
- PI 确认之前,最终分析按常设指示照跑(F1–F4 不受本偏离影响)。如果 PI 不认可这个处理,数据和两个包装层都保留,按 PI 的决定重新处理 A_dz 的描述部分,并在本节追加记录;F1–F4 的数不变。
- 冒烟 (a)(b) 用的运行包装层 2b3d6718334d290c 没有另存;已核对:把 c0ba99fd57f64a31 的两处改动去掉后,哈希正好是 2b3d6718334d290c,可以从现版本重建。

**原因**
- J3-offB 的 q4 目标 = E_kin 边界外 `OFFB_GAP` 0.13 rad(= 容差 0.05 + 证明余量 0.05 + 取整 0.03;`edit_breadth.py` 268、1672–1676 行),本来就是为「运动学不可达」造的。
- iiwa_a 的 E_kin q4 = [−2.042, −1.545]:下界贴着 iiwa 关节 4 的硬件下限 −2.0944(R2 逆解把 q 截在限位内 0.05 rad),所以目标 −2.17 / −2.172 落在硬件限位外 0.076–0.078 rad,超出量大于容差 0.05。fr3_a、xarm_a 的 offB 目标离各自硬件限位 ≥ 0.29 rad,不受影响。
- A 的 q4 target 项被 `compile_spec` 裁剪到限位、只告警(`cost_layers/spec.py` 426–433 行),照常编译。A_dz 按 §2.3 把关节 target 换成 [x* − tol, x* + tol] = [−2.22, −2.12],整段在限位外,裁剪后 lb = ub = −2.0944,`compile_spec` 记 rejected_terms「裁剪到硬件限位后 lb >= ub」(434–435 行)。入口预编译按 §9.1 把它当框架错误,冻结框架按设计停跑。

**范围(冻结代码下逐键纯编译,不跑仿真)**:用 `XT.offline_tables`(加载测试台、建模型、各阶段 `compile_spec`)把冻结登记表的 1349 个测试唯一键和 201 个校准键全部编译一遍(脚本在 scratchpad `xw_dev01/enum_compile.py`)。只有 2 个键、3 个 (单元, 臂) 不可编译,全部是 A_dz:

| 单元 | 臂 | q4 目标 | A_dz 死区 | iiwa q4 硬件限位 | 目录(sprl1) | 状态 |
|---|---|---|---|---|---|---|
| CA\|iiwa_a\|J3-offB-abs\|000 | Adz | −2.170 | [−2.220, −2.120] | [−2.0944, 2.0944] | iiwa_a_c3448c02598df0cf | 18:21 失败;19:30 续跑时判 n/a |
| CA\|iiwa_a\|J3-offB-rel\|000 | Adz | −2.172 | [−2.222, −2.122] | 同上 | iiwa_a_43150c428929835e(与下一行同键) | 19:30 续跑时运行,编译期失败,判 n/a |
| CA\|iiwa_a\|J3-offB-unit\|000 | Adz | −2.172 | [−2.222, −2.122] | 同上 | 同上 | 同上 |

其余 1347 个测试键(全部非 A_dz 的臂,以及 N 23、C-a 另外 29、T-conf 28、T-tight 7 个单元上的 A_dz)和 201 个校准键都能编译。没有任何非 A_dz 的臂受影响。续跑的批次日志 `logs/run_dev01_20261026_193015.jsonl` 里只有这两个目录是 n/a。

**处理:A_dz 在这 3 个单元上记为不适用(N/A)**
- 记成 n/a:不是 ok、不是 failed(情形结果)、不是 infra、不是拒收;不给任何臂记情形结果。A、A\P、B1、B2、B3、B1⁻、B2⁻ 的全部作业、确认族 F1–F4、其他任何框架错误的停跑路径都与冻结版相同。
- 涉及 A_dz 的比较全是描述(N 副作用、C-a 描述、T-conf、T-tight);受影响的只有 C-a。
- 冻结的 C-a 描述表(`ca_desc`,按臂各自聚合)只在 A_dz 一列少了这 3 个单元:A、A\P、B1、B2、B3 列是 32 个单元 / 11 簇,A_dz 列是 29 个,两边单元集不同,不能直接比较。所以分析包装层:
  - 在 json `ca.Adz` 加标记 `dev_xw_01_flag` =「n = 29,与其他列的单元集不同,不可直接比较」,md 里写一行同样的话;冻结表的数值不动。
  - 给配对版本【描述】(`dev_xw_01.ca_common_units`):C-a 上全部臂都有行的 29 个单元 / 10 簇,A、A\P、A_dz、B1、B2、B3 全部在这同一单元集上按冻结 `ca_desc` 聚合;另给 A_dz − 各臂的配对差(先单元差、再簇均值,簇 bootstrap 95% 区间,不给 p)。**C-a 上涉及 A_dz 的比较,论文只引用这一版。** A、A\P、B1、B2、B3 之间的 C-a 描述仍以预先登记的冻结 `ca` 表(32 单元 / 11 簇)为准,F4 仍在 32 个单元上(20:15 按披露审查限定范围;改前原文见 `plan_exec_weighted_20261026_before_dev_xw_amend2.md`)。
  - 给最坏情形灵敏度【描述】(`dev_xw_01.ca_adz_worst_case`):把 iiwa_a|J3-offB 簇的 A_dz 记最坏(m_conf = −3、按优先级满足 = 否;task_kept 不补,与冻结版对无效执行的处理相同),共 32 个单元;只作披露。
- 这是有信息量的缺失,不是随机缺失:3 个 N/A 单元正好是 C-a 的一个完整簇(iiwa_a|J3-offB),由情形本身决定(q4 目标在 iiwa 关节 4 硬件限位外)。J3-offB 是按「运动学不可达」造的最难一类,这一簇的目标还落在硬件限位外。去掉这个簇,A_dz 的 C-a 描述就只剩其他情形,所以另给最坏情形行。
- 与科学审查表述的核对。审查写的是「这 3 个单元正是 R2 里 A 因同一原因失败的 C-a 簇」。R2 记录(`cases_xw.json` 的 `r2_po_eval`、R2 目录的 `ext_result.json`)显示:R2 里 A 在这 3 个单元上只有 q4 不达标(实测 −1.641 / −1.640 / −1.640,目标 −2.17 / −2.172)。q4 是 preference,按设计应当让步;倾角等 task 档都达标,没有 ik_fallback,按优先级满足。R2 C-a 里按优先级不满足的 3 个是 fr3_a J3-offB-abs / -rel 与 xarm_a J3-offB-abs(§1.6 表:倾角不达标、ik_fallback 在 pre 处失败)。所以只能说「这个簇上 A 的 q4 偏好在 R2 里也没有达到」(所有 J3-offB 单元都按设计达不到),不能说「A 在 R2 里失败」。本节按核对结果写。如果审查指的是本次运行里 A 的结果,要等最终分析之后再核对,因为现在核对就要读 C-a 的 F4 数据。

**依据**
- §2.3、§1.4:A_dz 定义为「容差内放松」的纯死区,并且只对能表示的量定义(力、路径保留 target)。这 3 个单元的容差带里没有一个硬件可达的构型,「容差内放松」没有定义,所以 A_dz 在这里不存在,谈不上表现差。
- §9.1:入口预编译出现 rejected_terms 是「框架错误,不是情形结果」。包装层 `press_ext_testbed.py` 也写明「执行被拒」只认 SpecRejected,运行时出现 rejected_terms 判包装层错误。所以不能记成 A_dz 的失败,也不能记成拒收。R 类的拒收是 hard 位置项起点在界外 3σ 以上(SpecRejected),属于情形结果,与这里不同。
- §6 的「基础设施失败 → 该单元整组配对剔除」针对的是缺任一臂都会破坏配对的情形。这里只缺 A_dz,A / A\P / B 的配对完整;整组剔除会无故删掉 F4 的 3 个 C-a 单元,并让确认族依赖一个与它无关的次要臂,所以不用。
- A_dz 只在描述里出现(§5 的 N、T-conf 两行,§7.3 的「A_dz」,C-a 的 `ca_desc`),不是 F1–F4 任何一个检验的臂。
- 另一种做法(在这些单元上让 A_dz 保留 q4 的 target,或用裁剪后的退化区间)要改冻结的 `arm_cmd`、产生新编译键和新仿真,等于事后改臂的定义,不用。
- 与结果无关:N/A 判定只看编译结果与作业元数据——`failed.json` 里的 XWCompileError 与拒收原因、`cmd.json` 的 `xw.replace`(只有 A_dz 有)、`key.json` 与目录哈希一致、批次 / 分析里该键的作业全是 Adz——不看任何仿真结果。N/A 集合完全由冻结代码与冻结登记表决定,上面的逐键编译不需要任何仿真结果。

**文件(只新建;冻结文件未改,`exec_weighted.py g0` 照常通过)**
- `exp_repair/exec_weighted_dev01.py`(运行包装层)。19:10:47 定稿时 sha16 2b3d6718334d290c,冒烟 (a)(b) 用的是这一版。代码审查后改了两处,正常数据上的行为不变:
  1. `na_info` 的 except 加 `AttributeError`:cmd 里某个字段不是 dict 时不判 N/A,也不抛异常;
  2. 包 `write_manifest`:manifest 的 run 事件加 `{dev, wrapper, wrapper_sha16}`。

  改后 **sha16 c0ba99fd57f64a31**,19:30 续跑用的就是这一版(`manifest_da88a21e8aee.json` 最后一个事件,19:30:14:dev = dev-XW-01,wrapper_sha16 = c0ba99fd57f64a31)。其余同前:包 `load_xw`(只有满足全部 N/A 条件的 FrameworkError 改成 NotApplicableXW,其余照抛);包 `run_batch`(冻结版的副本,冻结源码 sha16 d1ae61d7d05c851d 在导入时核对;多一个状态 "n/a";键下作业不全是 Adz 时仍按框架错误停);只放行 `g0` / `status` / `run`;`run --dry-run` 不往 manifest 追加事件;`dev01-selftest` 在临时目录里核对。
- `exp_repair/analyze_exec_weighted_dev01.py`(分析包装层)。19:11:38 定稿时 sha16 1f966b985882b42b,冒烟 (c) 用的是这一版(备份 `exp_repair/analyze_exec_weighted_dev01_20261026_before_sci_review.py`)。按科学审查改写后 **sha16 0fd539e6826e2fb8**,约 19:45 同步到 sprl1。改动:
  - 冻结 `ca` 表 Adz 列加标记;新增 `dev_xw_01.ca_common_units`(共同单元,全部臂同一单元集,加 A_dz − 各臂配对差)和 `dev_xw_01.ca_adz_worst_case`(最坏情形);md 在「功效」之前加一节「[dev-XW-01] C-a 上涉及 A_dz 的比较」。全部标【描述】,写明涉及 A_dz 的 C-a 比较只引用共同单元版本(其余臂之间的 C-a 描述与 F4 仍按冻结的 32 个单元)。F1–F4 与冻结 `run_all` 的其他全部输出逐值不变,只多 `ca.Adz.dev_xw_01_flag` 与 `dev_xw_01`。20:15 按披露审查把这句范围写进 CITE 字符串,改后 sha16 见 [run-03]。
  - 完整分析(不带 `--partial`)写 `analysis_xw.{md,json}`。缺任何仿真就拒绝(冻结 collect 的「缺 N 个仿真」;N/A 键不算缺)。N/A 集合必须正好等于已披露的 3 个 (单元, Adz)、种子 0 主作业,在主机 da88a21e8aee 上另核对 2 个目录名;多一个或少一个都拒绝。`--partial` 时只能是子集,多出就拒绝。
  - 合成数据自检:不读任何真实仿真,输出只写临时目录,不算真实 F4。`dev01-selftest` 27 项通过,核对了:
    - 已披露的 3 个 (单元, Adz) 恰好对应 2 个编译键;按主机 da88a21e8aee 算出的目录名就是上表那两个;
    - 完整分析写出 `analysis_xw.{json,md}`;ca.Adz n = 29 且带标记,其他列 32;
    - 共同单元 29 / 10 簇,各臂 n = 29;最坏情形 A_dz n = 32;
    - 冻结 `run_all` 的 16 个键逐值相同,F1–F4 相同;
    - 共同单元表、配对差、最坏情形按行独立重算一致;
    - 缺一个非 N/A 仿真、缺第二个 N/A 键、多一个未披露的 N/A → 完整分析拒绝,不写文件;多一个未披露的 N/A 在 `--partial` 时也拒;N/A 落在非 Adz 作业上 → FrameworkError;
    - 真实 `results/` 没有被改动。

    冻结 `selftest` 经包装运行也通过。
- 分析一律用 `analyze_exec_weighted_dev01.py` 的完整分析。冻结的 `analyze_exec_weighted.py` 在这批数据上会因为 N/A 目录停下。

**冒烟(19:13:06–19:13:24,sprl1;用的是两个文件 19:10–19:12 的定稿版 2b3d6718… / 1f966b98…)**
- (a) `exec_weighted_dev01.py g0`:ok = True,三份冻结代码 sha16 = 登记表 meta.code_sha。`run --dry-run`:unique 1349、cached 1050、new 299;扫描:done 1050、n/a 1(iiwa_a_c3448c02598df0cf)、not_run 298、其他失败 0。
- (b) `dev01-selftest` 24 项通过:真实失败目录经包装后 → N/A,冻结原版仍抛 FrameworkError,`is_infra_failure` = False(run_sim 不会把它改名重跑),目录没有被写;14 种合成目录(别的拒收原因、多项混合、reject_reason 非空、非 A_dz 的 cmd、被拒项不是关节目标、WrapperCompileError、XWFormatError、ExtFormatError、超时、目录哈希不符、「求值失败」窗口)仍按框架错误停;`run_batch_dev01` 遇到混臂键或普通 XWCompileError 时停。
- (c) `analyze_exec_weighted_dev01.py --partial --no-power` 不再停。F1–F3 的数(含区间、簇差、敏感性、H* 描述、TOST)与 18:09 的 `analysis_xw_partial.json` 逐值相同。**这一步同时算出并打印了 F4 的部分结果,是一次计划外中途查看,见 [run-02]。** 只改写了 `analysis_xw_partial.{md,json}`(18:09 原件已先备份);`results/exp_exec_weighted/` 其余文件逐个比对未变。

**续跑(19:30:07,sprl1;只跑 run,不接分析)**

进程命令行(`ps`;分离运行,环境 `source ~/fcl_setup/env.sh`、`CUDA_VISIBLE_DEVICES=5,6,7`、`MUJOCO_GL=egl`):

```
bash -c ".venv/bin/python exp_repair/exec_weighted_dev01.py run --jobs 12 --devices cuda:0 cuda:1 cuda:2 cuda:0 cuda:1 cuda:2 cuda:0 cuda:1 cuda:2 cuda:0 cuda:1 cuda:2 > results/exp_exec_weighted/logs/pipe_run_dev01_20261026_193008.log 2>&1; echo rc=\$? > ~/xw_dev01/run_dev01_20261026_193008.done"
```

- 计数:unique 1349、cached 1050、new 299。new 里有 2 个是 N/A 键:iiwa_a_c3448c02598df0cf 已有失败目录,直接判 n/a、不重跑;iiwa_a_43150c428929835e 跑一次、编译期失败后判 n/a。其余 297 个是真仿真。完成标记 `~/xw_dev01/run_dev01_20261026_193008.done`:rc=0;批次日志 `logs/run_dev01_20261026_193015.jsonl`。19:47:45 跑完 1349/1349:ok 1347(含缓存 1050)、failed 0、infra 0、budget_stop 0、framework 0、n/a 2(正是上表两个目录)。

**最终分析(run 的 rc = 0 之后;未执行)**

```
cd ~/fcl && source ~/fcl_setup/env.sh && cat ~/xw_dev01/run_dev01_20261026_193008.done   # 必须是 rc=0
TS=$(date +%Y%m%d_%H%M%S); nohup setsid bash -c ".venv/bin/python exp_repair/analyze_exec_weighted_dev01.py > results/exp_exec_weighted/logs/pipe_analyze_dev01_$TS.log 2>&1; echo rc=\$? > ~/xw_dev01/analyze_dev01_$TS.done" < /dev/null > /dev/null 2>&1 &
```

输出 `results/exp_exec_weighted/analysis_xw.{md,json}`。缺任何仿真(N/A 键除外)或 N/A 集合与上表不同,都会拒绝运行。

### [run-02] 冒烟 (c) 带出的第二次中途查看 19:13(F4)

(2026-10-26 19:50 按科学审查改写;改写前原文见 `plan_exec_weighted_20261026_before_dev_xw_amend.md`。)

- 19:13:24(进程时间)sprl1 冒烟步骤 (c) 跑 `analyze_exec_weighted_dev01.py --partial --no-power`,stdout 打印了确认族四个检验的部分结果(输出生成于 19:13:22,缺 404 个作业)。F1–F3 与 18:09 相同;F4 第一次有数:C-a 18/32 个单元、7/11 簇,A − A\P = +2.02,p = 0.0078,Holm p = 0.023。
- 这次查看**可以预见,也可以避免**。冒烟 (c) 的目的只是核对包装后的分析不再停下、F1–F3 与 18:09 一致,却跑了会算出并打印 F4 的分析。当时 C-a 的 A、A\P 各已完成 56/96 个作业(按 `logs/run_20261026_171616.jsonl` 的作业元数据计数),F4 会有数是能预见的。
- 时间顺序:两个包装层文件在 19:10:47 / 19:11:38 定稿,19:12 同步,都在查看之前;[dev-XW-01] 初稿写于 19:13:30–19:16,在查看之后。看到之后,N/A 规则、文件和设计都没有改。之后只有两项改动:一是代码审查后运行包装层的两处修改,不影响 N/A 判定的正常路径(见 [dev-XW-01]「文件」);二是科学审查要求的分析包装层第二版,只加描述表和运行前核对,F1–F4 逐值不变。N/A 只涉及 A_dz,不碰 F4 的两臂(A、A\P)。
- 看到的人:实现者与编排者(Claude)。PI 在 19:26 应其要求看到同一组 F4 数(`logs/interim_looks.log` 19:26:31 条,记为 PI 的第 2 次中途查看)。19:13:24 这次查看补记在 `interim_looks.log` 第 3 条,位置在 19:26:31 条之后,并注明是补记。
- (20:15 按披露审查补)看到的人还有:代码审查与科学审查的审查者(都读过写有这组 F4 部分结果的 §16 初稿),以及披露审查者(读 `~/xw_dev01/c_partial.log` 与 §16 时看到同一组数,没有新数据)。分析包装层第二版(0fd539e6826e2fb8)里的共同单元表、最坏情形表和「只引用共同单元版本」这句话,是**看过部分 F4 的科学审查者**要求加的;这些都是描述项,F1–F4 逐值不变,引用范围已在 [dev-XW-01] 限定为「C-a 上涉及 A_dz 的比较」。
- (20:15 补)19:13 的输出文件里不只有确认族:还有部分 C-a 描述表(`ca` 的 A / A\P / B1 / B2 / B3 各 20 个单元、A_dz 17 个)和第一版包装层的 `dev_xw_01.ca_A_vs_Adz_common_units`;stdout 只打印了确认族和 N/A 列表。编排者在 19:26 为回答 PI 打开了 `analysis_xw_partial.md` 的 F4 行和 json 的 `ca` 块,给 PI 的内容是:F4 一行(+2.02,区间 [+1.04, +2.95],p 0.0078,Holm 0.023)、C-a 部分描述里 A 与 A\P 的按优先级满足(18/20 vs 3/20)、任务维保持(0.975 vs 0.575)、任务维余量均值(+0.23 vs −1.91),以及 C-a 换种子翻转率 0/18。
- 两次中途查看的输出另存为不同的文件(sprl1 `results/exp_exec_weighted/logs/`;本机把 18:09 那份以同名另存在 `results/exp_exec_weighted/logs/`):

| 文件 | 生成于 | 缺作业 | sha16 |
|---|---|---|---|
| `interim_20261026_1809_analysis_xw_partial.json` | 18:09:38 | 796 | f5dcc49287957835 |
| `interim_20261026_1809_analysis_xw_partial.md` | 18:09:38 | 796 | 4874e67d2dde4287 |
| `interim_20261026_1913_analysis_xw_partial.json` | 19:13:22 | 404 | 91d58c2172a4b5f7 |
| `interim_20261026_1913_analysis_xw_partial.md` | 19:13:22 | 404 | 8dc6148b0dd9ea54 |

  18:09 的两份与 sprl1 `~/xw_dev01/backup_interim_1809/` 的备份逐字节相同(本机那两份也相同);19:13 的两份与当时的 `results/exp_exec_weighted/analysis_xw_partial.*` 逐字节相同。sprl1 上这 4 个文件设为只读。`interim_looks.log` 现有 3 条:18:09:30、19:26:31、19:13:24(补记)。
- 以后的规则:身份 / 一致性核对一律不算、不打印 F4,改用合成行、mock 或 selftest;最终分析之前不在真实数据上跑 `--partial`。分析与论文里如实披露这三次查看:18:09(PI 要求,F4 还没有数)、19:13(冒烟带出,F4 部分结果)、19:26(PI 要求,看的是 19:13 那份)。

### [run-03] 披露审查后的修改与最终分析(2026-10-26 晚)

- 披露审查(阻塞两条)后:[run-02] 补了看到 F4 部分结果的三位审查者和 19:13 文件里的部分 C-a 描述;[dev-XW-01] 把「只引用共同单元版本」限定到「C-a 上涉及 A_dz 的比较」,并写明 PI 确认前照跑、不认可时怎么处理;`interim_looks.log` 追加一条更正(「404 个仿真」应为「404 个作业」)与审查者补记。改前方案备份 `plan_exec_weighted_20261026_before_dev_xw_amend2.md`。
- 分析包装层只改了 CITE 等说明字符串(范围限定;注明 C-a 上 B1 / B2 / B3 与 A 同编译键、按构造相同、不当证据),改前备份 `exp_repair/analyze_exec_weighted_dev01_20261026_before_scope_fix.py`;改后 **sha16 423a51d9ff8ad45e**,`dev01-selftest` 27 项通过(合成数据)。分析审查(不阻塞)提出的 B1 / B2 / B3 按构造相同标注已写进 CITE。
- 最终分析:sprl1 进程时间 20:07:41 生成,`analyze_exec_weighted_dev01.py` 完整分析(不带 --partial),rc = 0。输出 `results/exp_exec_weighted/analysis_xw.{md,json}`,sha16 6610631539f2cb6a(md)/ 953614ad76e89b2a(json);已经暂存目录拉回本机(排除 manifest、锁文件、tmp、sims、analysis_xw_partial.*),本机两份 append-only 日志按「本机是远程前缀」更新。
- 确认族(Holm m = 4):F1 B1 − A = +0.144 [+0.083, +0.209],Holm 0.0010,拒绝;F2 −0.000,Holm 1.000(TOST 等价);F3 −0.004,Holm 1.000;F4 A − A\P = +1.584 [+0.841, +2.407](32 单元 / 11 簇),p 0.0005,Holm 0.0015,拒绝。按 §5「结果的读法」命中「F1 显著、F2 不显著且等价」与「F4 显著」两行。
