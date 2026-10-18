# MoE-Beyond 外部案例研究 — 阶段 0 勘察（RECON）

**状态：阶段 0 完成，停在 §0.4，等待作者确认。**
§2 中的 R6 停止已由作者在 §3.1 裁定，按新判据基线通过；随后完成了 §4（第三方仓库）、
§5（Q1–Q9）、§6（待确认事项）。

- 日期：2026-10-18
- 工作分支：`moe-cache-eval-release` 上的 `case-study/moe-beyond`（基于 `a7f8223`），未提交、未推送
- 本阶段未计算任何结果量（R5）：没有命中率、r̄ 或 Jaccard

## 1. 本文仓库盘点（协议 §0.1）

### 1.1 代码位置

`moe_controller/` 在两个目录中**逐字节一致**：六个文件分别用 `shasum -a 256` 比对，全部 SAME。
- 公开发布仓库：`/Users/zhangyu/Documents/moe-cache-eval-release`（git，remote 为 `shijiuzhang/moe-cache-eval`）
- 研究目录：`/Users/zhangyu/Documents/moe-hierarchy-lab`（**不是 git 仓库**），存放全部冻结 trace（63 个 `cache-events-*` 目录）及其上游 route 源

### 1.2 组件与入口

| 组件 | 位置 | 入口 |
|---|---|---|
| 事件原子回放（Definition 2） | `moe_controller/simulation.py:702` | `simulate_event_atomic(trace, *, policy, capacity_blocks, cache_scope, tie_seed, include_event_misses)` |
| 逐访问回放（对照） | `moe_controller/simulation.py:395` | `simulate(...)` |
| 策略 | `simulation.py:15-23` | `demand, static, lru, lfu, lfru, least_stale, belady`；`belady_forced_admit` 属于 `ATOMIC_PROBE_POLICIES` |
| Static 冻结驻留 | `simulation.py:352` | `simulate_static_fixed(...)` |
| 容量取整（§2.3） | `simulation.py:961` | 总容量 `C = max(1, round(L·N·ρ))`；逐层 `c_l = C // L + (l < C % L)` |
| 规范化事件 trace 格式 | `moe_controller/events.py:55` | `EventTrace`（safetensors + manifest），`load_event_trace` / `save_event_trace` |
| FCFS 事件构建器（同步去重、到达偏移） | `moe_controller/convert.py:201` | `convert_decode_trace(source, out, *, batch_size, queue_order, category_field, include_request_ids, arrival_offset_field, arrival_offset_map, ...)`；CLI 为 `scripts/build_decode_cache_events.py` |
| Prefill 事件构建 | `moe_controller/convert.py:23` | `convert_prefill_trace(...)` |
| §2.5 参考 trace | `scripts/build_paper_blocking_evidence.py:70` `_toy_trace()`；断言在 `:125` | 3 层 × 4 专家，5 步，逐层容量 2（总 6），LRU，`per_layer`；期望 12 命中 / 18 缺失 |
| 污染诊断（route 侧，§5.8） | `scripts/audit_external_route_contamination.py` | 输入格式绑定 allenai Mixtral/C4 JSONL（`_load_complete_rows`）；flag 规则在 `:214-217` |
| 污染诊断（prompt 侧） | `scripts/audit_probe_diversity.py` | `audit_probe(path, text_field, group_fields)`；判定在 `:96-101` |
| 报告块（Appendix B.1）生成器 | — | **不存在**，阶段 2 新建 |

### 1.3 冻结阈值（逐字抄录，不重新调参）

- route 侧 §5.8 `contamination_flag`（`audit_external_route_contamination.py:214-217`）：
  `exact_sequences < n` 或 `p95(位置 token 一致率) ≥ 0.05` 或 `p95(token 5-gram Jaccard) ≥ 0.30`
- prompt 侧（`audit_probe_diversity.py:96-101`）：不同 prompt 头（前 70 字符）≤ 2，或不同末行 ≤ 2，
  或 `p95(5-gram Jaccard) ≥ 0.30`
- §5.6 骨架聚类规则：**尚未定位**，阶段 0 继续时补查

### 1.4 适配器设计含义（只是设计观察，不是结果）

本文已有规范化格式：decode route 源格式（`manifest.json` 中 `collection.kind = autoregressive_decode`，
safetensors 内含 `topk_indices[N, L, T, k]` / `topk_weights` / `sequence_lengths`，另附 metadata jsonl），
以及由 `convert_decode_trace` 生成的 `EventTrace`。按协议 §4.1“已有等价格式则复用”，
适配器的目标应当是**把 MoE-Beyond 原始 trace 转成这个 decode route 源格式**，然后直接复用
`convert_decode_trace` 生成 B=1 与合成的 B∈{2,4,8}，而不是另起 parquet 格式。最终定案取决于 Q1/Q4。

route 侧检测器的计算写在脚本的 `main()` 里，并且绑定 Mixtral JSONL 输入。要复用而不修改它，
阶段 2 需要一个外部适配层，把 MoE-Beyond trace 喂进检测器的计算函数。如果必须改动该脚本，
按 R1 先停下征得同意。

### 1.5 环境

- Python 3.12.13（`.venv`），`requires-python = ">=3.12,<3.13"`，锁文件为 `uv.lock`，包版本 `0.2.0a1`
- 测试命令：`.venv/bin/python -m unittest discover -s tests` → **105 tests OK**
- 磁盘：数据卷剩余 267 GiB

## 2. R6 回归基线 — 第二项未按字面通过

### 2.1 R6(a) 参考 trace：通过

直接调用产品代码 `_toy_trace()` 和 `simulate_event_atomic(policy="lru", capacity_blocks=6,
cache_scope="per_layer", tie_seed=7)`：hits = 12，misses = 18，event_misses =
`(2,2,2,1,1,1,1,1,1,1,1,1,1,1,1)`，与脚本内断言一致。

### 2.2 R6(b) 冻结条件重新生成：events 与 requests 一致，schedule 不一致

选取的两个冻结条件共用同一个源：`artifacts/controller-probe-v0.1.3-olmoe-decode64-discovery-v1`
（源 `manifest.json` 实测 `34882e5c1d5ac074286027d752070622dc82ad9aee4cf894c8a09039e189f3e0`，
与两份 cache-events manifest 中的记录一致）。按 manifest 记录的参数（`batch_size`、
`queue_order=category_round_robin`、`category_field=workload_archetype`）用当前代码重新生成，
输出到 scratchpad。全部哈希都用 `shasum -a 256` 实测：

| 条件 | 文件 | 冻结 | 重新生成 | 结果 |
|---|---|---|---|---|
| olmoe-decode64-fcfs-**b1**-v1 | events.safetensors | `13d993494eb90ce63f15fd21f57ddc423f89c0e1aff634c8500859be7d0b3219` | 同左 | 一致 |
| | requests.jsonl | `94ccdb026019fffe230d40a141c2a776540b382254dd59a85bdbd9f6b3ca31ba` | 同左 | 一致 |
| | schedule.jsonl | `2c7b1da9e55383c11c11c7276d81bc5f95194321eef9ea071004fe086fa2532e` | `abd86e0257ce4421db581f02023bca2f00f94ffe4e62fd8faee6c450b31606a2` | **不一致** |
| olmoe-decode64-fcfs-**b8**-v1 | events.safetensors | `5d31a0f36bff49237bff8c6ca9648a8cb2099f51855e92b0bc851afe2ac93a15` | 同左 | 一致 |
| | requests.jsonl | `94ccdb026019fffe230d40a141c2a776540b382254dd59a85bdbd9f6b3ca31ba` | 同左 | 一致 |
| | schedule.jsonl | `3d7499cba2330eb118db5f600d7820e8a85d5f34cfc54b3aa7b744a09b6cba8e` | `a32aa1b636a7f4d59b4cd632f0cee013bfa94397fd93cd39e8cf30b3c0a1f094` | **不一致** |

两个冻结 schedule 文件的实测哈希都等于各自 manifest 中的记录，因此不一致不是冻结文件被改动造成的。

### 2.3 差异定性

- 行数相同（b1 为 7560 行，b8 为 945 行）。重新生成的每一行多出一个键 `arrival_offsets`，
  两个条件中所有值都是 `0`（非零行数为 0）。
- 从重新生成的每一行删去 `arrival_offsets` 后重新写出，实测哈希
  **恰好等于冻结值**：b1 为 `2c7b1da9e55383c11c11c7276d81bc5f95194321eef9ea071004fe086fa2532e`，b8 为
  `3d7499cba2330eb118db5f600d7820e8a85d5f34cfc54b3aa7b744a09b6cba8e`。
- 冻结 trace 创建于 2026-07-29。`arrival_offsets` 字段是之后加入转换器的，并且在公开仓库首个提交
  `f7bacc2 Initial artifact release` 中已经存在。

**结论：模拟器实际回放的内容（events.safetensors）与请求表逐字节一致；唯一差异是 schedule 中
后来新增的一个信息字段，在这两个条件下全为零。**

研究目录中 D1 stagger 等较新的冻结条件，其 schedule 已经包含 `arrival_offsets`，
理论上可以逐字节对比。但它们的 manifest 只记录了 `include_request_ids_count: 72` 和
`arrival_offset_map_used: true`，**没有记录 ID 列表和偏移映射文件的路径**，要重新生成需要先找到这两份输入。

## 3. 需要作者裁定

1. **R6(b) 怎么定义。**建议：重新生成的 `events.safetensors` 与 `requests.jsonl` 必须与冻结值
   逐字节一致；`schedule.jsonl` 在删去 `arrival_offsets` 后必须逐字节一致，同时这些条件下的
   `arrival_offsets` 必须全为零。这比只比 events 更严，因为它证明了 schedule 的差异仅此一个字段。
   备选：改用较新的 D1 stagger 条件，前提是先找到其 ID 列表和偏移映射输入。
2. **这两个 olmoe decode64 条件算不算“主论文冻结清单”中的条件。**仓库里没有单一的“冻结清单”文件：
   `paper/CITATION_CLAIM_MAP.md` 管的是引用，不是条件；冻结记录是研究目录中各条件自带的 manifest。
   如果主论文表格用的是别的条件，请指定。
3. 裁定后我继续阶段 0：克隆 MoE-Beyond 到被忽略的 `third_party/`，回答 Q1–Q9，补查 §5.6 骨架规则。

### 3.1 作者裁定（2026-10-18）

1. R6(b) 采用 §3 第 1 条的判据：重新生成的 `events.safetensors` 与 `requests.jsonl` 必须逐字节一致；
   `schedule.jsonl` 在删去 `arrival_offsets` 后必须逐字节一致，且该字段全为零。
   在此判据下，R6(b) 的基线**通过**（b1、b8 两个条件）。
2. `controller-probe-v0.1.3-olmoe-decode64-fcfs-b1-v1` 与 `-b8-v1` 计入主论文冻结清单。
   作者说明：论文于 2026-07-29 完稿，此后新增的信息字段属于正常演进。

## 4. 第三方仓库（协议 §0.2）

- 克隆：`third_party/moe-beyond`。git 全局配置里的代理 `127.0.0.1:7897` 未运行，因此仅对这一条命令用
  `-c http.proxy= -c https.proxy=` 直连克隆，**未改动全局配置**。
- **commit：`47031eefc7808e996ecd5c01d7ed90aa32e32514`**（2025-10-12，共 46 个提交）
- **许可证：没有 LICENSE、COPYING、NOTICE 文件，README 也没有提到许可证** → 按 R2“保留所有权利”处理。
- `third_party/` 已加入 `.gitignore:26`，`git check-ignore` 确认生效。
- LFS 只有 2 个文件，都是预测器权重：`model_training_6000p_512tpp_100e_try1/checkpoint_epoch_{6,10}.pth`，
  各 171 MB。未拉取，本研究不需要。
- 总体积 418 MB（含 .git）。
- 本阶段**没有运行任何第三方代码**，只读取了源码和 CSV。

| 目录 | 文件数 | 大小 | 内容 |
|---|---:|---:|---|
| `cache_simulator/` | 1 | 12K | `infinity_moe_sim.py` |
| `expert_activation_scripts/` | 1004 | 94M | 3 个采集脚本；嵌套的 `training_data_eamc/` 为 prompt 1001–2000 |
| `training_data_eamc/` | 1000 | 97M | 训练 trace，prompt 1–1000 |
| `test_datasets/formatted_csvs` | 100 | — | 测试 trace（带 token 字符串） |
| `test_datasets/predicted_csvs` | 100 | — | 测试 trace（token 为位置下标）+ 预测器输出 |
| `prompt_datasets/` | 2 | 3.5M | `tagged_puffin_prompts.txt`（6994 条）、`codegen_instruct_tagged.txt`（4535 条） |
| `prompt_expert_activation_examples/` | 3 | 49M | 3 个带 hidden state 向量的示例 |
| `trace_analysis_scripts/`、`transformer_model/`、`model_training_*` | — | — | 分析脚本、预测器训练代码与日志 |

被引用文件的实测 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `cache_simulator/infinity_moe_sim.py` | `734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa` |
| `expert_activation_scripts/generate_deepseek_logs_eamc.py` | `17458e1904928fb8c381286cea7ef508b33b685a7d6910a2ac630b414525077e` |
| `expert_activation_scripts/generate_deepseek_logs_v2.py` | `64e06f854362d8879efd7d7a7e46c72d749110f25eb221fcf1171cc20c903634` |
| `expert_activation_scripts/generate_deepseek_logs.py` | `7d431369dca8aca67575f17317a2d45e964c2511197dd5a8a41eca2e314f134b` |
| `prompt_datasets/tagged_puffin_prompts.txt` | `baa52eb71d93abcf8216313a4bd9f9335e02cbbbee2d33fc041d7421e9030a88` |
| `README.md` | `ad131662b1764aa93f8b44000dfa30c6b8d1f5d6883c0721cd73dd6c96bd6259` |
| 论文 HTML `arxiv.org/html/2508.17137v1`（取于 2026-10-18，存于 scratchpad） | `ef57960064f883656578c12ed6df67d2d66313181ee333fd0ceb29888f0fc590` |

## 5. 勘察问题 Q1–Q9（协议 §0.3）

**Q1 是否有逐 token、逐层的专家 ID 序列？— 有。置信度：确认。**
CSV 列为 `Layer ID, Batch Number, Token, Activated Expert IDs`，每行是一个（token，层）上的 6 个路由专家。
层号 1–26，每个 prompt 文件的行数为 26 × token 数，按层优先排列，`Batch Number` 恒为 0。
`predicted_csvs` 另有 `Predicted Expert IDs` 列，且 `Token` 列是位置下标。没有门控权重列。
不需要回退方案 F1 或 F2。

**Q2 trace 对应哪些 prompt？— 置信度：确认。**
- 测试：WebGLM-QA 100 条（论文 Test Dataset 小节原文：“we selected 100 prompts from the WebGLM-QA dataset”）。
  每条 15–28 个 token，合计 2366 行。
- 训练：Puffin，共 2000 个 trace 文件（根目录 1–1000，`expert_activation_scripts/training_data_eamc/` 1001–2000）。
  Puffin 原文件中相邻编号常是同一多轮对话的连续轮次，被拆成独立 prompt
  （例如 #1–#3：“How do I center a text element…” → “Add some spacing…” → “Instead of using a spacer…”）。
- **两套测试 CSV 的关系（核对后确认）**：同一编号的 `formatted` 与 `predicted` 文件不是同一个 prompt
  （100 个里有 95 个行数不同）。按“逐层专家集合序列”精确匹配后，**100 个 predicted 文件都在 formatted 中
  恰好找到唯一一个对应，构成双射**（例：predicted 1↔formatted 20、2↔34、3↔39、4↔4）。
  结论：两套是**同一批 trace，只是文件编号不同**，并且不是字典序。
  `predicted` 每行专家 ID 升序排列，`formatted` 保留路由输出顺序（1950 行非升序）。
  适配器将以该双射连接两套文件：专家序列取模拟器实际读取的 `predicted`，token 字符串取 `formatted`。
  双射表将在阶段 2 由适配器生成并记录哈希。

**Q3 模型结构？— 置信度：确认。**
- 模型：DeepSeek-V2-Lite-**Chat**（`generate_deepseek_logs_eamc.py:18`），8-bit 加载（`:26`）
- 论文原文：“2 shared experts and 64 routed experts, with 6 experts activated per token”，“27 layers”
- 采集钩子挂在 `mlp.gate` 上（`:114-118`），所以只记录**路由专家**；共享专家不经过 gate，**不在 trace 中**。
  第 0 层是稠密层，没有 gate，因此 trace 层号为 1–26。
- 块宇宙为 26 × 64 = 1664，与其模拟器的 `int(1664 * i/10)` 一致（`infinity_moe_sim.py:275`）。

**Q4 是否含生成 token，是否区分 prefill / decode？— 置信度：确认。**
三个采集脚本都只对 prompt 做**一次前向**：`model(input_ids=..., attention_mask=...)`，
见 `generate_deepseek_logs_eamc.py:122-124`。全仓库 `.py` 中没有 `generate(`、`max_new_tokens`、`do_sample`。
因此 **trace 全部来自 prefill，没有 decode，也没有生成 token**。
token 字符串可以从 `formatted_csvs` 取得；没有 token ID 列，但 tokenizer 的 token 字符串与 ID 一一对应。

**Q5 是否套用 chat template，解码方式如何？— 置信度：确认。**
- 直接调用 `tokenizer(text, return_tensors="pt")`（`:122`），**没有套用 chat template**；
  全仓库没有 `apply_chat_template`。BOS 由 tokenizer 自动添加。
- 没有生成，所以“解码方式 / 最大生成长度”**不适用**。

**Q6 `cache_simulator` 的契约字段 — 置信度：确认（代码阅读）。**
- 作用域：**全局**，单个 `ExpertCache` 以（层，专家）为键覆盖全部 1664 块（`:81-90`）
- 容量单位：块数，`cache_sizes = [int(1664 * (i/10)) for i in 1..10]`，10% 对应 166（`:275`）
- 初始状态：每个 prompt 新建缓存，并用**未设种子**的 `np.random.shuffle` 随机预填满到容量（`:86-90`）
- 淘汰：LRU（`OrderedDict`，`:92-102`）
- 回放顺序：先把行重排为**token 优先**（同一 token 的 26 层依次，再到下一个 token，`:206-209`），
  然后在每行内按 CSV 列表顺序**逐个专家访问**（`:242-251`），即逐访问更新
- 预热：每个 prompt 的前 `26 × warmup_count` 行（`warmup_count=10` 个 token）只访问、不计数（`:216-226`）。
  第一个循环在处理完下标 260 后 `break`，第二个循环从下标 260 开始计数，所以下标为 260 的一行在两个循环中各被处理一次
- 预取：计数前先把该行的预测专家载入缓存，载入不计命中/缺失，但会更新 LRU 次序（`:237-239`）。
  **没有关闭预取的开关**；不过把输入中的 `Predicted Expert IDs` 置为 `[]`，在不修改其代码的前提下即可使预取为空
- 命中分母：逐个实际专家访问（`:248-251`）
- 跨 prompt：**不保留**；每个 prompt 重新随机预填和预热，最后按所有 prompt 汇总命中与访问
- 两种模式：当前生效的是 `test_single_csv_predict_mode_with_predicted`（读取已发布的预测列，`:291-292`）；
  基于 EAMC 质心的 `test_single_csv_predict_mode` 在 `main()` 中被注释掉（`:294-295`）。EAMC 使用训练 prompt 1–9（`:259`）

**Q7 能否在本机运行？— 置信度：推断（尚未执行）。**
模拟器只依赖 pandas、numpy、scipy、scikit-learn，不需要 CUDA 或 bitsandbytes。采集脚本需要 CUDA 和 8-bit，本研究不运行。
方案：独立 venv、`python -I`、外部 harness 直接调用其函数，**不修改、不 import 进本文包**；
harness 在每次调用前 `np.random.seed(s)`，使随机预填可复现。

**Q8 能否找到 10% 与 17% / 72% 对应的配置？— 置信度：推断。**
- 10% 对应 `cache_sizes[0] = int(166.4) = 166`，全局作用域。
- 论文摘要写“improves GPU cache hit rate from 17% to 72% when only 10% of experts fit in GPU cache”；
  正文图 7 的说明写“over 70% … compared to just 17% for MoE-Infinity”；
  结论写“lifts prediction hit rate from 17% to 72%”。这里只逐字记录，供 E 的 paper-only 报告块引用，不作评判。
- 17%（MoE-Infinity 基线）对应被注释掉的 EAMC 路径；72% 对应当前生效的“已发布预测列”路径。
- **72% 的复现检查不需要运行预测器推理**，因为预测结果已作为 `Predicted Expert IDs` 发布。
  协议原本把它列为“需要推理、可选”，这一前提不成立，是否纳入 P3 请作者决定。

**Q9 测试 prompt 是否公开，是否有类别标签？— 置信度：确认。**
测试 prompt 原文没有单独文件，但 `formatted_csvs` 的 token 字符串可以还原 prompt 文本。
文件名里的 “tagged” 指的是 `PROMPT_START/END` 分隔标记，**不是类别标签**，因此 B6 和分类别项写 `NA(无类别标签)`。

**补查：§5.6 骨架聚类规则 — 不存在。**
§5.6 只有 70 字符 prompt 头、末行和 5-gram Jaccard（选样阈值 0.30），没有“去数字和专有名词后聚类”的规则。
按协议，分析 C 的“最大重复模板数”写 NA。

## 6. 进入阶段 1 前需要作者确认（协议 §0.4）

1. **许可证**：未发现任何许可证 → 按 R2 处理：第三方数据和代码只放在被忽略的 `third_party/`；
   发布制品只含下载脚本、适配器、哈希清单和聚合统计。
2. **分析对象**：
   - 测试：`predicted_csvs` 100 个，即其模拟器实际读取的输入，经双射连接 `formatted_csvs` 取 token 字符串；
   - 训练：`training_data_eamc` 共 2000 个，用于 Static 拟合；
   - 不需要 F1 或 F2。
3. **预注册中必须先冻结的参数**（不定下来就会出现“看到数字再选口径”）：
   - **(a) 事件定义。**trace 全部来自一次 prefill 前向，而其模拟器把每个（token，层）当作依次发生的访问。
     建议预注册两种声明契约并都报告：**逐 token 事件**（对齐其回放单位）和**整段 prefill 每层一个事件**
     （对齐实际前向的执行单位）。P2 在两种定义下分别判定。这正是开工前预计的关键选择。
   - **(b) 容量取整。**其设置用 `int()`（10%→166），本文 §2.3 用 `round()`（10%→166，但 20% 时 332 vs 333）。
     建议：复现其设置的条目用 `int()`；本文策略分析用 §2.3。
   - **(c) 起始状态。**其契约是每个 prompt 重置、随机预填、前 10 个 token 预热不计数。
     建议分析 D 主结果按本文默认（同一 trace 流内跨请求保留，冷启动），另加一列“每 prompt 重置”对齐其契约，两者都预先注册。
   - **(d) 其模拟器的随机种子。**沿用本文 5 个平局种子作为 `np.random.seed`，报告各种子下的结果。
   - **(e) 72% 复现检查**是否纳入 P3（见 Q8）。
   - **(f) route 侧检测器参数。**§5.8 冻结默认值为前 48 条完整记录、截断 512 token。
     建议原样沿用：按 predicted 编号取前 48 条，并报告 n；其测试 prompt 最长 28 token，截断不会生效。
   - **(g) Puffin 多轮拆分**只影响训练集，测试集 WebGLM-QA 都是单问。
     分析 C 只对测试集运行，Puffin 这一点仅在 RECON 中记录。

## 7. 勘误（2026-10-18，阶段 3 开始时发现）

原版已原样归档为 `history/RECON_as_reported_8221b36.md`，SHA-256 为
`e41f60d8f293f509265f30c0631815d970d73281e14ce7418d98f7faf9f84321`，与提交 `8221b36` 中的版本一致。

- **错误**：§5 Q2 写“每条 15–28 个 token，合计 2366 行”；§6-3(f) 写“其测试 prompt 最长 28 token”。
- **原因**：该统计只覆盖了 100 个测试文件中的 5 个。当时按**同一编号**配对 formatted 与 predicted，
  行数不等的 95 对都被跳过了；而两套文件的编号本来就不对应，这一点在同一节后面才确认。
- **更正**：由规范化 trace 的 `sequence_lengths` 重新统计（`canonical/test-e1-source`），
  100 条测试 prompt 每条 **3–38 个 token**，合计 **1543 个 token、40118 行**。
- **影响**：
  - `PREREG.md` 没有引用这些数字，冻结参数不受影响。
  - §6-3(f) 的“截断不会生效”仍然成立，因为最长 38 远小于 512。
  - 新增一个描述性事实：其模拟器每个 prompt 前 10 个 token 只预热、不计数，按其 `main()` 的汇总规则，
    token 数 ≤ 10 的 prompt 不计入命中率，这是其汇总方式本身的结果。P3 会报告实际计入的文件数。
