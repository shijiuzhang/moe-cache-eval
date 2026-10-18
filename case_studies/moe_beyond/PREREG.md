# MoE-Beyond 外部案例研究 — 预注册（PREREG）

- 日期：2026-10-18
- 依据：《MoE-Beyond 外部案例研究：实施协议》（作者，2026-10-18）；`RECON.md` 及其 §3.1、§6 的作者裁定
- 本文件在**任何**会产出阶段 3 结果的脚本运行之前提交。提交后不得修改，改动只能追加到 `DEVIATIONS.md`，
  并逐条注明时间、内容、理由，以及“改动前是否已读到任何结果”。
- 提交后，本文件的 `shasum -a 256` 与提交号写入 `PREREG.lock`。

## 0. 冻结的输入与参照

| 对象 | 标识 |
|---|---|
| 第三方仓库 | `github.com/ngavhane/moe-beyond` @ `47031eefc7808e996ecd5c01d7ed90aa32e32514` |
| 第三方输入文件清单 | `case_studies/moe_beyond/INPUTS.sha256`，共 2206 行，文件本身 SHA-256 为 `bc8213a0a58672ab42ba031801de3028345d3865619925019ff53b45e2a6512c` |
| MoE-Beyond 论文文本 | `https://arxiv.org/html/2508.17137v1`，取得的 HTML SHA-256 为 `ef57960064f883656578c12ed6df67d2d66313181ee333fd0ceb29888f0fc590` |
| 报告块字段定义 | SPE 投稿补充材料 Appendix B.1（`paper/spe_submission/supplementary-material.md`，SHA-256 `b56d69b119334aacc21d38d6872489d02575edf1171983ea4a302abe324cc3f0`），与本文 §10.5 逐字一致 |
| 本文代码 | 本分支 `moe_controller/`（与研究目录逐字节一致，见 RECON §1.1） |

**机械执行 R5。**每个 `analysis_*.py`：
- 启动时重新计算 `PREREG.md` 的 SHA-256 并与 `PREREG.lock` 比对，不一致或缺少 lock 即拒绝运行；
- 校验所用第三方文件与 `INPUTS.sha256` 一致；
- 把 PREREG 哈希与全部输入哈希写进输出 JSON 的 `inputs` 字段。

## 1. 数据映射

1. **层**：trace 层号 1–26 映射为 0–25，共 26 个 MoE 层；第 0 层是稠密层，不在 trace 中。
2. **专家**：每层 N = 64 个路由专家，top-k = 6。块宇宙为 26 × 64 = 1664。
3. **共享专家**：每层 2 个，不在 trace 中（采集钩子挂在路由门上）。视为常驻，不计入块宇宙、容量和缺失。报告中单列说明。
4. **测试集**：`test_datasets/predicted_csvs/prompt_{1..100}_data_predicted.csv`。专家序列取自该文件，即其模拟器实际读取的输入。
   token 字符串取自 `formatted_csvs`，按 RECON Q2 的“逐层专家集合序列精确匹配”双射连接；双射表由适配器生成并记录哈希。
   请求顺序按 predicted 编号 1→100，请求 ID 为 `moebeyond-test-{n}`。
5. **训练集**：`training_data_eamc/prompt_{1..1000}` 与 `expert_activation_scripts/training_data_eamc/prompt_{1001..2000}`，仅用于 Static 拟合。
6. **门控权重**：原始数据中没有，记为 null。

## 2. 两种声明的事件定义（RECON §6-3a，作者已同意）

trace 全部来自一次 prefill 前向（RECON Q4）。两种定义都报告，不择优，结论分别陈述。

- **E1，逐 token 事件**：每个（请求，prompt 位置 t，层 l）是一个事件，专家集合为该行的 6 个专家，|E| = 6。
  B = 1 时的回放顺序为请求 → 位置 → 层 0..25，与其模拟器的 token 优先顺序一致。
  实现方式：适配器输出本文 decode route 源格式，`collection.kind = autoregressive_decode` 表示
  **回放模型**为逐位置顺序；另加字段 `physical_phase = "prefill"` 和 `replay_model = "E1"` 如实标注，
  然后用 `convert_decode_trace` 生成。
- **E2，整段 prefill 事件**：每个（请求，层）是一个事件，专家集合为该请求所有 prompt 位置在该层的专家并集。
  逻辑分配数为 6 × T，用于去重前分母。由适配器直接构造 `EventTrace`（`phase = PREFILL`），只做 B = 1。
  B > 1 时 E2 记为 NA：批量 prefill 模型既不是其设置，也不在本文冻结的构建器内。

**由配置推出的结构性预期**（不依赖数据，在此写明以示非事后）：
- 在 E1 下，每个事件 |E| = 6 恒定，所以 r(s,l) = 6 / c_l 由配置决定；
- 在其报告工况点（全局作用域，容量 166），E1（|E| = 6）和 E2（|E| ≤ 64）的事件**必然**都装得下；
- 在逐层作用域、ρ = 10% 时，c_l ∈ {6, 7}，E1 必然装得下，E2 取决于数据。

## 3. 冻结参数

| 参数 | 冻结值 |
|---|---|
| 驻留比例网格 ρ | 0.10、0.20、0.30、0.40 |
| 本文策略分析的容量 | `capacity_blocks_from_fractions`（§2.3：`C = max(1, round(1664·ρ))`），逐层 `c_l = C//26 + (l < C%26)` |
| 复现其设置的容量（P2 报告工况点、P3） | 其规则 `int(1664·ρ)`，全局作用域；ρ = 0.10 时为 166 |
| 缓存作用域 | 主分析 `per_layer`，附加一列 `global` |
| 并发 | 主分析 B = 1。次要分析 B ∈ {2, 4, 8}，只在 E1 下做，由 `convert_decode_trace` 合成（FCFS、同步跨请求去重、`queue_order="source"`），**标注“本文构造”** |
| 到达偏移（B > 1） | `stable_rank("moe-beyond-case-study-20261018" + "arrival", request_id) % 24`；`stable_rank` 取自 `scripts/build_controller_probe_d1.py:80`，与本文 0–23 规则相同 |
| 回放 | 事件原子，`simulate_event_atomic` |
| 策略 | `lru`、`lfu`、`lfru`、`least_stale`、`static`、`belady`、`belady_forced_admit`，全部无预取 |
| 最佳因果策略 | 在 {LRU, LFU, LFRU, Least-Stale} 中取 5 个种子平均缺失率最低者（与本文 Table 12 相同）。Static 单独报告，不参与选择 |
| Static 拟合 | 规则同 `scripts/freeze_static_pins.py`：逐层等额配额、按频次降序、平局取较小 ID。频次由训练 trace 在**同一事件定义**下用 `flatten_accesses` 统计，在测试 trace 上评估。只做 `per_layer`，`global` 记为 NA |
| 平局种子 | `DEFAULT_TIE_SEEDS = (11, 23, 47, 89, 131)`（`scripts/build_paper_blocking_evidence.py:28`）。报告均值与最小–最大值 |
| 起始状态（RECON §6-3c） | (i) **主结果**：整条测试 trace 冷启动，跨请求保留；(ii) **对齐列**：每个请求冷启动重置（用 `subset_event_trace` 逐请求模拟后求和，Belady 也逐请求计算）。(ii) 只对齐“每 prompt 重置”，不复制其随机预填与前 10 个 token 预热 |
| 缺失率与差距 | `m = M / logical`（去重前），`g = (m_c − m_B) / m_c`（本文 §2）；`admission share = (m_F − m_B)/(m_c − m_B)`，`future-victim share = (m_c − m_F)/(m_c − m_B)`（本文 §7.2） |
| 均匀路由零模型 | `expected_union(N=64, k=6, m)`（`scripts/build_decode_operating_envelope.py:33`）。E1 在批量 B 下 m = B；E2 下 m = 该请求的 token 数 T |
| 污染检测阈值（§5.8，逐字抄录） | route 侧：`exact_sequences < n` 或 `p95(位置 token 一致率) ≥ 0.05` 或 `p95(token 5-gram Jaccard) ≥ 0.30`。prompt 侧：不同 prompt 头（前 70 字符）≤ 2，或不同末行 ≤ 2，或 `p95(5-gram Jaccard) ≥ 0.30` |
| route 侧检测器样本（作者裁定） | predicted 编号前 48 条，`max_tokens = 512`，沿用 §5.8 冻结默认值 |

## 4. 判定规则与结论模板

论文英文句式以下列模板为准，只替换花括号内容。数字一律来自 `results/*.json` 生成的 `\CS*` 宏。

### P1 执行契约分类（分析 A）

**运行方式。**外部 harness 在独立 venv 中以 `python -I` 运行，直接调用其
`test_single_csv_predict_mode_with_predicted(path, cache_size=c, warmup_count=0, top_k=6)`。
所有行的 `Predicted Expert IDs` 置为 `[]`，即预取为空。不修改其代码，也不把其代码 import 进本文包。
每个探针在 5 个种子下运行：每次调用前执行 `np.random.seed(s)`。

**哨兵行。**代码阅读显示，即使 `warmup_count = 0`，第 0 行仍会在预热循环中被访问一次，
然后在计数循环中再计一次（RECON Q6）。因此每个探针 CSV 前置哨兵行，使第 0 行不是探针事件：
- A0、A2：层 1 加一行 token_idx = 0 的哨兵，专家为 `[63]`；探针放在层 1 的随后两行；
- A1：层 1、2、3 各加一行 token_idx = 0 的哨兵，专家为 `[63]`；参考 trace 放在层 1–3、专家 0–3。

按其逐访问代码推算，哨兵的固定贡献为：A0、A2 各 1 次命中、0 次缺失；A1 为 1 次命中、2 次缺失。
**探针计数 = 原始计数 − 哨兵贡献。**
harness 以相同种子重放其预填洗牌来推知预填集合。若预填集合与探针块或哨兵块相交，
该种子的原始计数照常报告，但不参与分类。

**判定（探针部分，非哨兵部分）。**
- **A0**（c = 3）：期望 3 次缺失、3 次命中。不符则**停止**，先查适配器。
- **A2**（c = 2，{0,1,2} → {0,1,2}）：4 次缺失归为“事件级保留”，6 次缺失归为“逐访问保留”，其他值归为“其他”并记录原始计数。
- **A1**（全局容量 6）：12 次命中、18 次缺失归为“与事件原子契约一致”。
  在其全局 LRU 下，三层对称的参考 trace 与逐层容量 2 等价，这是映射核对。
- A1 与 A2 冲突时以 A2 为准，并在报告中说明。所有有效种子结果一致时才作出分类，否则写“种子间不一致”并给出原始计数。

**模板。**
- A2：“On the in-event eviction probe, the published simulator recorded {m} misses, the count expected under {per-access | event-level} retention; its executed replay contract is classified as {per-access | event-level}.”
- 其他：“…recorded {m} misses, matching neither reference contract; we report the raw counts and do not classify it.”
- A1：“On the reference trace of §2.5 the published simulator recorded {h} hits and {m} misses, {matching | not matching} the event-atomic reference counts (12 / 18).”

### P2 轴 I 的适用性

对每个事件计算 |E(s,l)| 与容量，在以下四种情形分别给出结论：
- 其报告工况点（B = 1，全局，容量 166）× {E1, E2}；
- 本文主口径（B = 1，`per_layer`，ρ = 0.10，c_l ∈ {6, 7}）× {E1, E2}。

- 全部事件装得下：“At {setting}, every event's expert set fits within capacity, so in-event eviction cannot occur; whatever replay semantics the simulator uses, its counts there coincide with the event-atomic contract. Axis I does not operate in this setting.”
- 否则（报告比例 f）：“At {setting}, a fraction {f} of events exceed capacity; in that setting the replay contract affects the counts and should be declared (checklist A1–A2).”
- **不得**推断其报告数值的方向或大小。

另外记录三项契约字段（来自代码阅读，并经 harness 执行确认）：
1. 缓存是否跨请求保留：否，每个 prompt 重置；
2. 命中计数分母：逐个专家访问；
3. 预取载入是否计入命中：否，但预取会改变 LRU 次序。

### P3 复现检查（作者裁定：17% 与 72% 都纳入）

- **17%（MoE-Infinity 基线）**：按其 `main()` 被注释掉的路径构造。`EAMC(capacity=1000)` 加入训练 prompt 1–9 的 REAM，
  `cluster_reams(1)`；对 predicted 1–100 调用 `test_single_csv_predict_mode(path, eamc, 166, warmup_count=10)`。
- **72%（MoE-Beyond）**：对 predicted 1–100 调用 `test_single_csv_predict_mode_with_predicted(path, 166, warmup_count=10)`。
- 汇总方式与其 `main()` 完全相同，包括它跳过零计数文件的规则。5 个种子，每次调用前执行 `np.random.seed(s)`。
- **比较量**：5 个种子的 `cache_hit_rate` 均值，与论文摘要的 17% 和 72% 比较，容差为绝对 ±2.0 个百分点。
  同时报告各种子的值与 `prediction_hit_rate`，后者只作描述，不作比较。
- 模板：
  - 在容差内：“Running the published artifact at the reported configuration reproduced the reported value ({X}% vs {Y}%).”
  - 超出容差：“Running the published artifact at the reported configuration yielded {X}% against a reported {Y}%; the difference is not attributed.”
  - 无法运行：“The published artifact could not be run in this environment ({reason}).”
- **不得**写任何原因猜测。

### P4 工况定位（分析 B）

报告 r(s,l) 的均值 r̄、p95、超过 1 的比例，以及每事件并集的均值与 p95；
ρ 取网格中的每个值，`per_layer` 作用域，E1 与 E2 都报告。

**定位**只对 B = 1、ρ = 0.40 做，因为本文 Table 11 的坐标是 ρ = 40%、逐层、事件原子。
对齐点 r̄ 取自 Table 11：40-expert B8 = 1.75、64-expert B8 = 1.44、128-expert B8 = 0.83、
64-expert B1 = 0.313、128-expert B2 = 0.293、40-expert B1 = 0.500、128-expert B4 = 0.519。
取最近者；差值大于 0.15 时判为不在已测范围。

- 模板：“Under our reporting frame, the {E1 | E2} event stream of this setting has r̄ = {x} at ρ = 40% (per-layer scope); the nearest measured alignment point in Table 11 is {model, B} (r̄ = {y}).”
- 超出范围时：“…; this lies outside the range of regimes we measured (nearest: {model, B}, difference {d}).”

ρ ≠ 0.40 以及 B > 1 的行只作描述，不作定位；B > 1 行标注“本文构造”。附加一列均匀零模型期望并集及其与实测之差。
可选图：横轴 r̄，纵轴为本文已测点的 gap，用竖线标出本设置的 r̄。**不画其 gap。**

### P5 工作负载构造诊断（分析 C）

- **prompt 侧**：对 100 条测试 prompt 运行。prompt 文本由 formatted token 还原：去掉 BOS
  `<｜begin▁of▁sentence｜>`，按字节级 BPE 约定把 `Ġ` 还原为空格、`Ċ` 还原为换行，其余原样拼接。
  这是近似还原，诊断只用到 prompt 头、末行和 5-gram。报告不同 prompt 头数、不同末行数、5-gram Jaccard 的均值与 p95。
  “最大重复模板数”写 `NA(本文无骨架聚类规则)`。
- **chat template**：“no”。依据是三个采集脚本都对原文直接调用 `tokenizer(...)`（`generate_deepseek_logs_eamc.py:122`）；
  仓库没有标明生成测试集的是哪一份脚本实例，此点一并注明。
- **route 侧**：前 48 条测试记录（第 3 节）。序列为 **prompt 输入序列**，没有生成序列，与 §5.8 的 C4 用法相同。
  报告：唯一序列数、位置 token 一致率均值与 p95、两两专家 Jaccard 分布、低文本重叠对（位置一致率 < 5%）上的 Jaccard。
  用第 3 节冻结阈值输出 flag。
- **类别相关项**：`NA(无类别标签)`。
- 模板：“On the public test prompts, the §5.8 detector reports flag = {true | false}; this is a detector-level screening result, not a replication or refutation of any workload effect in that study.”

### P6 驻留差距分解（分析 D）

- 对每个 ρ × {E1, E2} × B = 1 × {`per_layer`（主）, `global`} × 起始状态 {(i) 主, (ii) 对齐列}，报告：
  每个因果策略与 Static 的 m、best causal、Belady、Belady-forced-admit、g、admission share、future-victim share。
- 次要：E1、B = 8、`per_layer`、起始状态 (i)，标注“本文构造”。
- **每张表下固定附注**：“These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.”

### P7 报告块差值（分析 E）

- **字段表**：Appendix B.1 共 30 个字段，即执行模型 4 个、工作负载 9 个、工况 13 个、Oracle 4 个，按第 0 节文件逐字使用。
- **paper-only 模式**：只依据第 0 节的论文 HTML。每个非 NR 字段附小节或句子出处；其余记为 NR（not reported in the public text）。
- **with-artifacts 模式**：描述**其报告配置**（其模拟器契约、ρ = 0.10、全局、B = 1、按其回放单位即 E1），
  由公开制品加分析 A–D 填写。取值只能是三类之一：计算值（附文件哈希）、`DECLARE`、`NA(原因)`。
- 主结果：两种模式下可填字段数之差，以及差额字段清单。
- 模板：“From the paper text alone, {a} of the 30 reporting-block fields can be filled; with the public artifact and the released package, {b} can be filled. The fields that only the package made fillable are: {list}.”

## 5. 不做的推断（照录协议 §3.3，并补充）

- 不从 P1–P7 推断 MoE-Beyond 或 MoE-Infinity 的任何报告值偏高或偏低。
- 不把 Belady 上界或任何本文 gap 与其命中率放进同一表格列或同一张图。
- 不把 B > 1 的合成结果描述为其系统的行为。
- 不把 E1 与 E2 中任一种称为其系统的“真实”执行方式；两者都是声明的报告契约。
- 不评价其论文措辞，只逐字引用。
- 任一结果看起来可能被解读为“其报告值有误”时（协议 §7），**不写结论文字**，先把原始数字交给作者。

## 6. 措辞与检查

- 遵守协议 R3 的允许 / 禁止对照表。
- 禁用词检查（不区分大小写）：`incorrect`、`wrong`、`flawed`、`deficient`、`overestimat`、`underestimat`、
  `inflated`、`artifact of`、`fails to`、`invalid`、`error in`、`bug`、`misleading`、`corrected`、`true hit rate`。

## 7. 回归检查（R6，按作者裁定 RECON §3.1）

每次合并新代码前运行：
- **(a)** §2.5 参考 trace 必须得到 12 次命中、18 次缺失；
- **(b)** 重新生成 `controller-probe-v0.1.3-olmoe-decode64-fcfs-{b1,b8}-v1`：
  `events.safetensors` 与 `requests.jsonl` 逐字节一致；`schedule.jsonl` 删去 `arrival_offsets` 后逐字节一致，且该字段全为零；
- **(c)** 以规范化格式重新读入一份本文冻结 trace，事件流哈希不变；
- **(d)** `python -m unittest discover -s tests` 全部通过。
