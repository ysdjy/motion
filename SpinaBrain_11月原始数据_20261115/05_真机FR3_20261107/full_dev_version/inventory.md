# 真机实验材料清单（第 1 步，待确认范围）

清点时间：2026-11-09。只清点了本机（`/home/zhangbanghai`）。边缘卡（`user@172.16.0.1`）上的 `~/recordings`、`~/brainary_edge_v2` 没有登录查看。
以下"真机"指 `execute=True`、动作下发到 FR3 的运行；`*_fake` / `*_dry` 是假桥空跑，只用于说明开发过程，不计入真机次数。

## 0. 与任务说明第 2 节不一致的地方（先列出）

| 说明里的说法 | 本机记录 |
|---|---|
| 模型有 Gemini flash-lite、其它 Gemini、Qwen3-30B-A3B / Qwen3-32B | 写字真机 15 次全部是 `provider=gemini, model=gemini-4-argon, thinking=True`。写字组里，`gemini-flash-lite-latest` 只出现在 10-20 的假桥运行中；但在实验二前端任务中，腕部感知用的是 gemini-flash-lite-latest / gemini-3.1-flash-lite（11-09 核对后更正）。本机记录中没有 Qwen。抓放 / 推移任务用的是 claude-opus-5-5、gpt-6-astra、deepseek-flash / deepseek-server-v4.1-flash。 |
| 代码版本能对应到 `backup_YYYYMMDD_*` 目录 | 本机没有这种命名的目录，项目也不是 git 仓库。能用的版本线索有三类：`*.bak_MMDD` 文件（如 `cost_layers/real.py.bak_1029/1030`、`run_real_llm.py.bak_1030`、`write_real.py.bak_1107`）；`~/brainary/backup_before_restore_20261105/`；`~/Documents/Codex/2026-11-0{3,4}/…` 下的代码快照。每次运行的 `run.json.args` 记录了全部命令行参数，所以参数可以逐次核对，代码版本只能按日期近似。 |
| FR3 书写 16 次开发期运行，共 44 个字 | 本机的写字真机（`write_real_llm_full.py`）运行是 **15 次**：10-21 一次、10-23 六次、10-25 八次。按字数累加是 8×"山水木" + 6×"优必选" + 1×"刘杨 cysren"，共 45 个字。如果 cysren 算 1 个"字"，则为 8×3 + 6×3 + 3 = 45。带逐字笔压 / 速度 / 姿态要求（`per_char`）的只有 10-25 的 5 次、共 15 个字。30/30、43/44、0/20、0/4 这几个数暂时对不上，需要在第 5 步重算，或者它们来自另一台电脑。 |
| 笔压闭环开关 | 10-21 那次 `force_loop=False`；10-23 起全部 `force_loop=True`（`press_mode=hold`）。与"笔压由 `real.py` 程序级闭环控制"一致。 |

## 1. 写字（旧接口 `write_real_llm_full.py`，LLM 按窗口重写规格）

位置：`~/brainary/franka_cost_layers/results/real/`

| 运行目录 | 字 | 结果字段 | 备注 |
|---|---|---|---|
| 20261021_184401_writefull_real | 山水木 | ok=False，状态包中断 170 ms | 抓笔后抬起时中止 |
| 20261023_173223_writefull_real | 山水木 | ok=False，状态包中断 154 ms | |
| 20261023_175245_writefull_real | 山水木 | ok=False，"探到名义纸面以下 8 mm 还没有碰到" | 笔尖估高 |
| 20261023_175635_writefull_real | 山水木 | 同上 | |
| 20261023_180451_writefull_real | 山水木 | ok=True | |
| 20261023_185214_writefull_real | 山水木 | ok=False，"被停止" | 人手动停 |
| 20261023_185536_writefull_real | 山水木 | ok=False，claimed_done=True | 验收未全过 |
| 20261025_141132_writefull_real | 山水木 | ok=False，claimed_done=True | 有 per_char |
| 20261025_142910_writefull_real | 优必选 | ok=False，claimed_done=True（6 项验收过 5 项） | 有 per_char；**有 ZED 视频** |
| 20261025_151351_writefull_real | 优必选 | ok=False，状态包中断 152 ms | |
| 20261025_153004_writefull_real | 优必选 | ok=False，claimed_done=True | 有 per_char |
| 20261025_154239_writefull_real | 优必选 | ok=False，外力读数冻结 22.1 s | |
| 20261025_155101_writefull_real | 优必选 | ok=False，外力读数冻结 21.2 s | |
| 20261025_160018_writefull_real | 优必选 | ok=False，claimed_done=True | 有 per_char |
| 20261025_182610_writefull_real | 刘杨 / cysren | ok=False，claimed_done=True | 有 per_char |

- 每个目录里有：`run.json`（参数、每次 LLM 问答 `records`、`per_char`、`force_monitor`、`trace`、`checks`、`guard_trips`、`touch`）、`log.npz`（时间序列）、`system_prompt.txt`、`bridge*.log`、`write.png`（笔尖轨迹对目标笔画，是绘图，不是照片）。
- 10-25 的 8 次另有 flow 包装目录 `flow_20261025_*_real/`，内容包括定位笔 `pen/`、纸面视角、`photo/rgb.png`（写完后的腕部相机照片）、`纸面照片.png`、`writer_real.log`、`flow.json`。
- 定位笔记录：`locate_20261021_write{,2,3}`、`locate_20261023_write{,2..10}`、`locate_20261025_{multi,ubtech,ubtech2,ubtech3}`、`pre_ubtech2_1025`。
- 终端日志：`~/brainary/franka_cost_layers/logs/write_real_*.log`、`flow_real_*.log`、`locate_pen_*.log`（10-23、10-25）。
- 视频：
  - `results/real/20261025_142910_writefull_real/zed_ubtech_142901{.avi,.mp4,_x4.mp4}`。
  - `~/Desktop/FR3写优必选_20261025/录像_原速.mp4`、`录像_4倍速.mp4`，是同一次运行，附 `说明.md`。
  - **其余 14 次写字运行在本机没有找到视频。**
- 已整理的副本：`~/Desktop/FR3写优必选_20261025*/`（5 个）、`~/Desktop/FR3写刘杨_cysren_20261025_182453/`，内含纸面照片、轨迹图、run.json、每字意图.json。
- 假桥空跑：10-20 到 10-25 共约 40 个 `*_writefull_fake`，以及 `logs/write_fake_*.log`。

## 2. 单物体 LLM 任务（旧接口 `run_real_llm.py`）

| 运行目录 | 指令 | 模型 | 结果 |
|---|---|---|---|
| 20261020_191300_llm_real | 把马克笔往左移 10 cm | gemini-4-argon | ok=True，LLM 调用 15 次 |
| 20261030_115215_llm_real | 把红色铁盒放到 N95 盒位置…用其他关节将 N95 盒移开… | claude-opus-5-5 | ok=False，状态包中断 163 ms |
| 20261030_120325_llm_real | 同上 | claude-opus-5-5 | ok=True，12 次 |
| 20261030_122034_llm_real | 同上 | claude-opus-5-5 | ok=False，"40 秒没有得到可用的规格" |
| 20261030_123901_llm_real | 同上 | claude-opus-5-5 | ok=True，26 次 |
| 20261030_113539 / 114327_llm_real | 同上 | 未记录 | 只有 bridge.log，没有 run.json |

- 程序移动（无 LLM，`*_real`）：20261020_190123；20261030_114124、114608、115540（"竖直上抬 20 s 没完成"）、115648、122923；20261107_182504、190053、190917、195542。
- 视频：`videos/realexp/realexp_can_20261030_{105220,114059,121932}.avi`（3.1 / 1.7 / 3.1 GB）可能覆盖 10-30 的运行，需要核对时间戳。10-20 没有找到视频。

## 3. Brainary 前端发起的任务（`task_*_edge`，10-24 至 11-05，共 155 个目录）

位置：`results/real/task_*_edge/`，每个目录有 `task.json`（指令、模型、路线、阶段、checks、录像 tag），多数还有 `ui_run.log`、`qa.jsonl`、`replay/`、`view/`。执行日志在 `results/realexp/e2_can_run/ui_task_*`（74 组 json / npz / summary / bridge.log）。

| 日期 | 模型 | 执行路线 | 目录数 | execute | ok |
|---|---|---|---|---|---|
| 10-24 | gemini-4-argon | – | 2 | 0 | 0（连不上边缘卡） |
| 10-29 | claude-opus-5-5 | – | 3 | 3 | 0 |
| 10-30 | claude-opus-5-5 | – | 18 | 18 | 2 |
| 11-03 | claude-opus-5-5 / deepseek-flash | – | 6 | 6 | 0 |
| 11-03 | deepseek-flash / gpt-6-astra | expert_side_push | 29 | 29 | 0 |
| 11-04 | gpt-6-astra / 未记录 | –、expert_scraper_push、expert_side_push、llm_top_grasp | 46 | 46 | 2 |
| 11-05 | 未记录 / claude-opus-5-5 / gpt-6-astra | –、expert_side_push | 51 | 47 | 6 |

- 说明：
  - execute=True 不等于机械臂动了：不少目录在感知或连接阶段就中止了，例如 SSH 超时、HTTP 429、"边缘卡上还有桥接在跑"。
  - ok 取的是 `task.json` 的 ok 字段，还没逐条核对。
- 任务类型（按指令原文）：
  - 夹起铁盒 / 铁罐 / 可乐罐，用其他关节推开 N95 盒，再放到原位（10-29 至 11-05，大部分；即实验二）。
  - 夹刮刀推 N95 盒（11-04，12 次）。
  - **多物体分拣**："将马克笔放到 A；订书机放到 B；刮刀放到 C"等（11-04 至 11-05，约 40 个目录）。
  - 零散指令："抬升机械臂"、"将手中的刮刀放回桌面并抬升机械臂"、"把红色方块放到蓝色盘子里"（10-24，未执行）。
- 视频：`videos/realexp/realexp_can_2026{1029..1105}_*.avi` 约 60 个。
  - 11-04 19:48 起附带 `.timestamps.jsonl`、`.clock.json`，可以按墙钟对到 task。
  - `task.json.recording.tag` 记录了对应的视频名。
- 已整理的成功包：`~/brainary/archives/e2_real_success_20261105.tar`（run1_205419、run2_211835）。

## 4. 实验脚本直接运行的抓放 / 推移（`realexp/e2_can_run.py` 等，非前端）

- `results/realexp/e2_can_run/`：
  - pick_real1–2、all_real1–3、tin_real1–2（10-29）。
  - return_iron_* real ×4（11-03）。
  - 另有 dry 若干。
- `results/realexp/e1_real_run/`：
  - 真机 27 次（10-29 ×12、11-06 ×6、11-07 ×9），内容为 pick / place / flip / home / handover / tohand / retreat。
  - 这是 11-06 的笔尖朝上方案和笔的取放调试。
- 其他：`e2_real/`、`e2/real_*.json`（10-29）、`e2tin_result/`，以及 `videos/realexp/e2_tin_real_20261029_1959.mp4`。
- 这些运行**没有 LLM 参与**，或只用缓存模板（见第 5 节），需要确认是否纳入报告。

## 5. 11-06 至 11-07 实验一 / 实验三（`realexp/e1_handover_run.py`、`e3_handover.py`）

- 控制方式（本会话亲自执行，已知）：
  - 手写代价规格经 MPPI 逐窗口下发，书写模板是缓存的 gpt-6-astra 输出，**运行时没有 LLM 调用**。
  - 实验三的中途指令走确定映射，不是六字段 PMS，也没有 HMR。
- 实验三：`results/realexp/e3_handover/`
  - 正式运行 e3_formal_r1（11 笔，ok）。
  - 另有 probe_r1–4、write_r1–3、lift_r1–5、air_r1–2 等真机记录。
  - 视频 `realexp_can_20261107_1{20321..34028}.avi`；打包为 `E3_formal_20261107.zip`。
- 实验一：`results/realexp/e1_handover/`
  - e1_write_r1–r5，其中 r5 完成 16 笔。
  - 另有 probe_r1–5、lower ×3、out ×1 等真机记录。
  - 视频 `realexp_can_20261107_1{54547..73620}.avi`；打包为 `E1_formal_20261107.zip`。
- 11-06：笔尖朝上写字的旧方案（`e1_real_run`、`e1_paper_probe`、`pen_pick`），视频 `realexp_can_20261106_155109.avi`（3.3 GB）、`215747`、`215827`。
- 力标定：`results/real/force_calib.json`、`20261106_17*_force_touch_fake`（11-06，只有假桥）。
- 三个实验的合集：`~/桌面/FR3_三个实验真机_20261109.zip`。

## 6. 11-07 晚 写"永"（`write_real.py`，无 LLM）

- 记录：`results/real/20261107_{182247,190003,190246,191012,191840,192831,195638}_write_real`，共 7 次。
  - 前两次"探到纸面以下 8 mm 没碰到"。
  - 其余 ok，其中 195638 为 `mode=air`（空中写）。
  - 参数逐次不同：press 3.0 / 1.0 / 3.0 / 2.5 / 2.5 / 3.0，夹持 40 / 70 N，tilt 50°。
- 视频：`videos/realexp/write_yong3_192826.{avi,mp4,webm}`。
- 跟踪笔的录像：`videos/realexp/track_pen_200230/`。
- 笔测量：`results/real/measure_20261107_180816_pen`。

## 7. 截图 / 照片来源

- 写完后的腕部相机纸面照片：`flow_20261025_*_real/photo/rgb.png`（4 张），以及 `~/Desktop/FR3写*/纸面照片*.png`。
- 抓放任务扫描图：`task_*_edge/view/rgb.png`、`view_after/rgb.png`。
- 视频截帧：只能从上面列出的 ZED 视频里截取。本机没有 10-21、10-23 写字运行的视频。

## 8. 没有找到的材料

- 论文第 1 节所说的"16 次 / 44 个字"的原始统计脚本或表格（在本机全文搜索 `43/44`、`30/30`、`44 个字`，都没有找到）。
- Qwen 模型的真机运行。
- `backup_YYYYMMDD_*` 目录。
- 六字段 PMS 接口或 HMR（L1 / L1b / L2）在真机上的运行记录（还需要在 `task_*_edge` 的 replay 里再确认一遍）。
- "约 17 条抓放情景记录"：暂时没有对上。可能是 `results/realexp/e2_can_run/` 或 `task_*_edge` 的某个子集，需要你指认。
