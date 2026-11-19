# 真机运行表：独立重算说明

- 完成时间：2026-11-09。
- 只读取了原始日志。`real_robot_report/` 下只看了 `inventory.md`（用来找文件位置）和 `work/video_index.json`。
- 生成脚本放在会话 scratchpad，不属于项目文件：`build.py`、`claims.py`。
- 结果表：`runs_independent.csv`，191 行，UTF-8 BOM。

## 0. 判定口径

### 怎样算一次"真机尝试"
满足以下任一条件即算：
- `execute=True`，或者
- 目录名带 `_real`，并且有 bridge 记录。

以下不算真机尝试：
- `*_fake`、`*_dry`。
- `e1_handover/a1–a4`、`e3_handover/h0/h1`。这几个文件有 `sim_paper_drop_m`、`sim_s`，没有 `execute` 字段，判为仿真。

### 结果判定
- **完成**：日志 `ok=True`。
- **部分**：动作全部走完，但验收没通过。
  - writefull 中指 `claimed_done=True` 且 `ok=False`。
  - UI 任务中指 `returncode=0`、没有 `error`、`ok=False`。
- **失败**：其余情况。
- 两行只有 bridge.log，结果记为"未记录"：`e1_handover/out_162052_real`，以及两个没有 run.json 的 llm_real 目录。

### 开始时间的来源
来源写在 `start_source` 列，共五种：
- 目录名或文件名时刻。
- `task.json.started`（epoch）。
- `command.wall − command.t`：仅 e3_formal_r1 有，这是唯一精确的。
- `run.json mtime − sim_s`：约值。
- `summary mtime − npz t[-1]`：约值。

一个时间都推不出来时，`start_local=未记录`，`start_source` 里给出结束时刻（文件 mtime）。

### 视频匹配
- 只用 `video_index.json` 里带 start/end 的条目，或者日志里的 `recording.tag`。
- 偏移 = 运行开始 − 视频起点。
- E1/E3 很多偏移约为 −7~−9 s，即视频比控制循环 t=0 晚开始约 8 s。e3_formal_r1 可以精确核对：
  - 视频起点 13:40:30.40（edge 时钟），sidecar `clock.json` 给出的时钟偏差只有 0.15 s。
  - 运行 t=0 是 13:40:21.9。
  - 所以负偏移是录像晚于控制循环启动，不是时钟错。
- 日志 tag 指向的视频本机没有时，写 `未记录(日志 tag=…;本机无此视频文件)`。

### E2 机械臂是否动过（`robot_moved` 列）
- **L0 未动**：在连接、预检、大模型整理验收条件、路线拒绝、ZED 启动这些阶段失败，或手动停止，或移动请求被拒（返回码 4），没有任何运动证据。
- **L1 仅观察/重扫**：日志里有 `手腕移到观察位:到位`，或 rescan.log 里有 `拍好了`，或 `live.json.script=real_scan.py`。机械臂移动过，但没有开始夹取/推移。
- **L2 进入操作执行**：有 `run_dir`，或 `live.json.script=e2_can_run.py`，或 ui_run.log 里有闭环轨迹行（`object 下 [`）。

### E2 指令分类（按 task.json 原文）
- **E2**：同时出现"铁盒/可乐罐/铁罐"和"N95/盒子"。
- **刮刀变体**（`E2_variant_scraper`）："刮刀…N95"，单列，不计入 E2。
- **排除**：
  - 含"；"或"放到 A/B/C"的多物体分拣，53 个目录。
  - 无关单句，4 个："把红色方块放到蓝色盘子里"×2、"抬升机械臂"、"将手中的刮刀放回桌面并抬升机械臂"。

### 去重
- 10-30 的 `*_llm_real` 运行就是对应 UI 任务的执行体，同一次尝试不重复计数。
  - 115215/120325/122034/123901 已并入 UI 行，见 `other_params` 中的 `llm_real=`。
  - 113539/114327 只有 bridge.log，对应 UI 任务 113504/114243。它们单列为 `E2_llm_real_unlinked`，不计数。

## 1. 计数（Wilson 95% CI，按"完成"计）

| 范围 | 尝试 | 完成 | 部分 | 完成率 95% CI |
|---|---|---|---|---|
| writing_check（writefull_real 全部） | 15 | 1 | 6 | 1.2–29.8% |
| E1 全部真机执行（e1_real_run 33 + e1_handover 14） | 47 | 22 | 0 | 33.3–60.8% |
| E1 书写尝试（10-29 draw×3 + 11-07 e1_write_r1–r5） | 8 | 1（e1_write_r5） | 0 | 2.2–47.1% |
| E3 全部真机执行（probe 4、lift 5、air 2、write 3、formal 1） | 15 | 9 | 0 | 35.7–80.2% |
| E3 书写尝试（write_r1–r3 + e3_formal_r1） | 4 | 2（write_r3、formal_r1） | 0 | 15.0–85.0% |
| E2 UI 任务（execute=True） | 81 | 6 | 1 | 3.4–15.2% |
| E2 UI 中的 L0 未动机械臂 | 18 | 0 | – | – |
| E2 UI 中的 L1 仅观察/重扫后中止 | 35 | 0 | – | – |
| E2 UI 中的 L2 进入执行 | 28 | 6 | 1 | 10.2–39.5% |
| E2 脚本（指定的 11 个） | 11 | 4 | 0 | 15.2–64.6% |
| E2 脚本中的全流程 all_real1–3、tin_real1–2 | 5 | 1（tin_real2） | 0 | 3.6–62.4% |
| E2 脚本中的仅夹取 pick_real1–2 | 2 | 0 | 0 | – |
| E2 脚本中的仅放置 return_iron_*_real | 4 | 3 | 0 | – |
| E2 全流程合计（UI L2 + 脚本全流程） | 33 | 7 | 1 | 10.7–37.8% |
| 刮刀变体（不计入 E2） | 13 | 0 | 0 | 0–22.8% |
| E2 额外脚本（execute=True，不在指定列表，不计） | 7 | 5 | 0 | – |

另有 4 个 E2 指令的 UI 任务 `execute=False`，不计：`task_20261105_190324/190857/191106/191524`。

### E2 UI 中 L0（从未动机械臂）的 18 个任务

**连接 / 预检（3）**
- 10-29 184323：Host key verification failed。
- 10-30 105234：FCI refused。
- 10-29 191119：边缘卡上桥接在跑。

**边缘卡上桥接在跑（3）**
- 10-30 130652、130947、130955。

**流程拒绝"用其他关节推"（4）**
- 10-30 125107、125739、131433、131914。

**缺 API 密钥或环境变量（3）**
- 11-03 152232、153204、153623。

**手动停止（2）**
- 11-04 183700、184630。

**ZED 录像没起来（2）**
- 11-04 184658、184818。

**移动请求被拒，返回码 4（1）**
- 11-05 203636。

### 补充说明
- **感知阶段失败的 35 个属于 L1**：它们在失败前都已把手腕移到观察位，或做过重扫，机械臂是动过的。如果按"感知/连接阶段就中止"来统计，则为 L0+L1 = 53 个。
- **UI 成功的 6 个**：
  - 10-30：120232、123817（旧的从上往下夹流程）。
  - 11-05：193547、195924、205419、211835。
- **"部分"那一次是 11-03 231231**：执行器 summary `ok=True`，但任务验收没通过。`checks_after` 记录了两条：
  - `放到了放置点 = 离 [0.478,-0.023] 46 mm(允许 20 mm)`。
  - `重拍核对 = 找不到…N95`。

## 2. 写字论断重算

原论断：
- 16 次开发期运行，共 44 字。
- 目标笔压 ≥1.5 N 的字 30/30 在事后容差内。
- 倾角 43/44 在 3° 内。
- 速度目标 20–30 mm/s：0/20 达到。
- 0.5 N 笔压：0/4 达到。

### 数据来源
- `run.json.per_char[i]`：
  - 目标：`requested.press_n`、`speed_scale`、`ori_frame`。
  - 实测：`Fz_mean_n`、`requested.F_meas`、`speed_mm_s`、`tilt_deg`。
- 速度和倾角的文字目标，从本次运行的 `sentence` 中"第 k 个字"一段解析，例如"约 30 mm/s"、"离竖直约 10°"。
  - 没有直接用 `specs/*.json`，因为该文件在运行之后被改过，见 §3-1。
- 握笔姿态坐标系的实际倾角，从 `records` 提示词中解析，例如"(pose:write_flat_left):笔杆离竖直 52°"。

### 能算出的结果

**运行数和字数**
- writefull_real 共 **15 次**，不是 16 次。
- 指令字数合计 **45**：8 次"山水木"，6 次"优必选"，1 次"刘杨 cysren"按 3 个路径计。
- 真正进入"沿路径写"的只有 7 次，共 **21 字**：180451、185536、141132、142910、153004、160018、182610。
- 有逐字目标（`per_char`）的只有 5 次，共 **15 字**，都在 10-25。
- 10-23 的两次只有整段目标（press 2.0 / force_target 2.0 或 3.5），没有逐字分界，无法逐字评估。

**笔压，目标 ≥1.5 N 的 11 字**

按 `|Fz_mean_n − 目标|` 计：

| 容差 | 达标 |
|---|---|
| ±0.25 N | 6/11 |
| ±0.3 N | 8/11 |
| ±0.4 N | 10/11 |
| ±0.5 N | 11/11 |
| ±10% | 4/11 |
| ±20% | 9/11 |

按 `F_meas` 计：

| 容差 | 达标 |
|---|---|
| ±0.5 N | 10/11 |
| ±0.6 N | 11/11 |

要得到"全部达标"，至少需要 ±0.5 N（用 `Fz_mean_n`）或 ±0.6 N（用 `F_meas`）。分子分母都不是 30。

**笔压 0.5 N**
- 真机运行中没有任何一个字的目标是 0.5 N。`specs/write1_light.json` 只出现在 10-20/10-21 的 fake 运行里。
- 目标 1.0 N 的字恰好有 **4 个**：141132 的山，142910、153004、160018 的优。
  - 实测 `Fz_mean_n` 为 1.55 / 1.59 / 1.62 / 1.83，全部超出 0.5 N 以上，即 0/4。
  - "0.5 N 0/4"很可能指的就是这 4 个 1.0 N 的字，或者是用的偏差阈值。按字面无法复现。

**倾角**
- 相对指令文字的"离竖直约 10° / 55° / 33°"：**7/15** 在 3° 内。
- 相对实际可用的姿态坐标系（7–8° / 52–53° / 30–31°）：**14/15** 在 3° 内。唯一超出的是 141132 的山：10.6° 对 7°。
- 两种口径都不是 43/44。

**速度**
- 目标在 20–30 mm/s 的字有 **6 个**：141132、142910 各 2 个 30 mm/s，182610 有 2 个 20 mm/s。达到 0/6。
- 全部 15 字也是 0/15。`speed_mm_s` 的最大值只有 7.9 mm/s，其余在 0.3–2.1 mm/s。
- 分母 20 无法得到。

### 加入 fake 运行后的对照
fake 运行的力和速度来自假桥，没有物理意义，这里只是为了核对口径。
- 带 `per_char` 的运行，fake + real 恰好 **16 次**（11 fake + 5 real），共 **48 字**。"16 次"可能来自这里，但字数是 48，不是 44。
- 在这 48 字上重算：
  - 笔压 ≥1.5 N 的字有 35 个，±0.5 N 内 33 个。
  - 倾角 3° 内：对文字目标 24/48，对姿态坐标系 47/48。
  - 速度 20–30 mm/s 的字有 22 个，达到 2 个。
- 仍然对不上 30/30、43/44、0/20、0/4。

**结论**：本机原始记录复现不出这四个数。能复现的最接近结果是：
- 15 次运行，45 字指令，21 字实际书写，15 字有逐字目标。
- 笔压 ≥1.5 N：11/11（±0.5 N）。
- 倾角：14/15（对姿态坐标系）。
- 速度：0/6（20–30 mm/s）。
- 1.0 N 目标：0/4。

## 3. 日志中的异常与不一致

1. **specs 文件在运行后被改过**
   - `specs/write3_fastest_first2.json` 的 mtime 是 2026-10-25 15:39:42，里面"选"写的是 `force_n: 2.0`。
   - 但在它之前启动的两次运行，`sentence` 里都是"笔压 2.5 N"，`per_char[2].requested.press_n=2.5`：
     - `results/real/20261025_151351_writefull_real/run.json`
     - `results/real/20261025_153004_writefull_real/run.json`
   - 15:42 以后的运行写的是 2 N。
   - 所以 specs 文件不能用来回溯早期运行的目标。

2. **specs 文件名与内容不符**
   - `specs/write3_slow_fast_slow.json` 名为"慢-快-慢"，内容却是前两个字"最快(约 30 mm/s)"、第三个字"慢一点(约 10 mm/s)"，即快-快-慢。

3. **`force_monitor` 很可能只统计了最后一个字**
   - 5 次中有 4 次，`force_monitor.Fz_mean` 与最后一个字的 `per_char[-1].Fz_mean_n` 逐位相同：
     - 142910：2.2974。
     - 153004：2.08。
     - 160018：2.05。
     - 182610：1.6527。
   - 另一方面，`force_monitor.samples`（5228）与 `trace.per_char.write_3.samples`（2470）对不上。

4. **185536 的笔压字段互相矛盾**
   - `results/real/20261023_185536_writefull_real/run.json` 中 `trace.press.mean_n = -0.126 N`（p5 −1.90 N）。
   - 同一文件中 `force_monitor.Fz_mean = 2.16 N`。
   - 两者符号和量级都不一致。

5. **`per_char` 的力和速度无法从 `log.npz` 复现**
   - 用 `log.npz` 中"沿路径写"窗口内的 `F[:,2]` 直接平均，得到 −0.1 到 −1.05 N。只取 `press_d>0` 的样本平均 |Fz|，得到 0.7–1.2 N。
   - 两种算法都与 `per_char.Fz_mean_n`（1.5–2.3 N）对不上。
   - TCP 速度均值为 8–13 mm/s，中位数约 2 mm/s；`per_char.speed_mm_s` 为 0.3–7.9 mm/s。
   - 所以 `per_char` 的定义（坐标系、样本筛选）无法从日志反推，应以写日志的代码为准。

6. **10-30 12:38 的"成功"运行把 N95 盒推倒了**
   - `results/real/20261030_123901_llm_real/run.json` 和 `task_20261030_123817_edge/task.json` 都记为 `ok=True`。
   - 但之后的 `task_20261030_125107_edge/task.json.error` 写着："12:38 那次就这样把 N95 盒子推倒了"。

7. **验收结果在不同文件里不一致**
   - **E3 探纸**：`e3_handover/probe_r2_real` 和 `probe_r4_real` 的 `run.json.ok=False`，而 `summary.json.ok=True`。
   - **E1 探纸**：`e1_handover/probe_r2/r3/r5_real` 的 `run.json.ok=False` 且记有阶段超时，但 `summary.summary.ok=True`，并给出了 paper_z。
   - **E2 231231**：执行器 summary `ui_task_20261103_231231_edge.summary.json` 中 `ok=True`，而 `task.json` 中 `ok=False`。

8. **铁罐倾角与"保持铁罐姿态不变"的要求矛盾**
   - 11-05 的 4 次成功，以及 11-03 231231，`can_tilt_max_deg` 都在 76–81°，例如 `ui_task_20261105_205419_edge.summary.json` 为 77.2°。
   - 这些任务的指令都要求"保持铁罐姿态不变"。
   - 但这几次 `final` 里记的"罐倾"只有约 9°。最大值可能包含夹取前的姿态，口径需要确认。

9. **10-30 两个 UI 任务没有结果记录**
   - `task_20261030_113504_edge` 和 `114243_edge` 的 `stage="6 执行"`，`error`、`finished` 都没有，ui_run.log 停在闭环中途。
   - 对应的 `20261030_113539_llm_real`、`114327_llm_real` 只有 bridge.log。

10. **execute=False 却 ok=True**
    - `task_20261105_191524_edge/task.json` 中 `execute=False`、`ok=True`、`stage=None`。

11. **10-30 的 llm_real 字段缺失**
    - 都没有 `seconds` 字段，只有 `seconds_llm`。
    - `20261030_115215_llm_real/run.json` 的 `llm_calls=None`。

12. **E2 UI 实际用到了 flash-lite 视觉模型**
    - 10-30 至 11-05 的 qa.jsonl 感知记录用的是 `gemini-flash-lite-latest` 或 `gemini-3.1-flash-lite`，例如 `task_20261105_205419_edge/qa.jsonl` 中 id=perc-wrist 的记录。
    - inventory 说 flash-lite 只出现在 10-20 的 fake 运行里。这里看到它作为 UI 真机任务的感知模型。

13. **外力读数从一开始就冻结**
    - `e2_can_run/pick_real2.summary.json` 的 error 为："O_F_ext_hat_K 从 t=-0.0 s 起 16.2 s 没变"。外力读数从 t=0 起就冻结。
    - 同类"外力读数冻结"或"状态包中断"的中止，在 writefull、E1、E2、E3 中反复出现，见 csv 的 `direct_cause` 列。

14. **10-29 的 draw 段**
    - `full_164936_draw`、`full2_165616_draw`、`full2_170105_draw` 的 summary 都记 `strokes=[0,16]`，即计划 16 笔。
    - 但分别在 press_0、press_0、press_7 超时中止。

15. **录像 tag 名与实际开始时间相差约 3 s**
    - tag 名 `realexp_can_20261029_190331`，而 `zed.t_start_str` 为 "19:03:34"。
    - 本机只有 `realexp_can_20261029_190331_from5604.avi` 片段，index 中没有起点，因此 10-29 的 E2 脚本运行都没有填偏移。

16. **11-05 晚间的 E2 UI 目录没有 ui_run.log**
    - 这些目录的 F_GUARD 记为未记录。
    - 10-29 至 11-04 的 ui_run.log 中都是"接触保护 15 N"，与 `realexp/e2_can_run.py` 当前的 `F_GUARD = 15.0` 一致。

17. **两次成功另有视频**
    - 11-05 205419、211835 另有 `videos/realexp/e2_success_20261105_205419.mp4` 和 `211835.mp4`，起点与 task.started 一致。
    - csv 里只填了覆盖它的第一条视频，201752.avi 或 211437.avi。

18. **writefull 的力保护和视频**
    - writefull 的 args 里没有 F_GUARD 类参数。`guard_trips.limit` 观察到 2.0 N 和 0.0 N（body 保护）。
    - 15 次中只有 142910 有视频 `zed_ubtech_142901.avi`，index 中没有起点，偏移约 +9 s 只是按文件名推算的。
