# 面向企业与工业场景的 MoE 内存控制器：本地验证行动计划

日期：2026-07-29  
阶段：本地可行性验证  
资源边界：Mac mini M4 Pro 24GB + Mac mini M4 16GB；近期不依赖 K3、NVIDIA GPU 或租赁集群。Qwen3-30B-A3B 4-bit 已在 24GB 主机完成本地路由采集。

## 1. 目标调整

项目当前目标不是证明 Perron 树式专家层级，也不是首先追求论文新颖性，而是验证并构建一个严格无损的、面向企业混合负载尤其工业负载的 MoE 内存控制器。

控制器在给定模型、工作负载、显存/内存和带宽预算下，联合决定：

1. 哪些专家常驻快速存储；
2. 哪些专家在何时淘汰；
3. 不同层之间如何分配专家缓存容量；
4. 多请求如何组成或轮转微批，以提高专家复用；
5. 工作负载变化后如何在线调整策略；
6. 后续阶段中，哪些专家值得预取以及何时应禁止预取；
7. 专家缓存与 KV/KDA 缓存如何竞争同一显存预算。
8. prefill 采用 chunk-major、layer-major 还是混合顺序，以及如何与
   在线 decode 交错。

第一版只做严格无损模式：缓存未命中时必须读取原始专家并等待，不替代、不跳过、不使用低精度临时专家。这样控制器只改变性能和资源占用，不改变模型输出。

## 2. 当前已有资产与边界

### 2.1 已有资产

- Granite 3.1 3B-A800M：40 个专家、top-8、32 个 MoE 层；
- OLMoE 1B-7B：64 个专家、top-8、16 个 MoE 层；
- Qwen3-30B-A3B 4-bit：128 个专家、top-8、48 层；已完成 120 条
  ControllerProbe discovery 的 decode-64 路由采集，峰值 Metal 内存
  17.86GB；
- 两个模型均已在 M4 Pro 上通过 Transformers 4.57.6 + MPS 插桩；
- Probe-1K 的两套 512-token 全量路由 trace 均已完成：
  - Granite：1000 条，约 5 分钟采集；
  - OLMoE：1000 条，约 14 分钟采集；
- trace 已保存完整 router logits、top-k、门概率、熵、margin、token NLL；
- EnterpriseProxy-1K 与 SyntheticEnterprise-1K 已冻结；
- 已有 450 条真实工业多尺度结构化案例和 500 条标准化工业种子；
- 本机剩余磁盘约 307GiB，近期实验没有存储压力；
- 测试数持续增长，最新状态以仓库测试输出为准，不在计划中手工冻结。

### 2.2 必须承认的边界

1. 当前 Probe-1K trace 的文本包含参考答案，只能用于模拟器开发和基线调试，不能直接作为在线服务结论。
2. 当前 trace 主要是 teacher-forced 序列，没有真实 autoregressive decode 调度过程。
3. 450 条工业案例仍是结构化 JSON，不是可直接送入模型的 prompt。
4. Granite 与 OLMoE 的专家粒度远小于 K3；它们可以验证控制器机制和跨架构可移植性，不能证明 K3 上的数值可行性。
5. 当前没有 NVIDIA GPU，不能验证真实 H2D overlap、CUDA Graph、PCIe 拓扑和 kernel 开销。
6. 目前没有发现 SpecMD 的官方公开代码仓库，因此不能把“直接使用 SpecMD 实现”作为依赖。应依据论文实现 trace-first 兼容评测器，并把 Least-Stale 严格复现为基线；若官方代码随后公开，再做交叉验证。
7. Qwen3 的本地结果已探测到 `union/cache` 交叉区，但仍不能数值外推到
   K3 的 896 专家/top-16、KDA 长上下文或真实 PCIe 拓扑。
8. Qwen3 B=8、per-layer、ρ=40% 的工作负载条件化结果已经在独立
   confirmatory split 复现：六类纯负载均优于 balanced mixed；DCS 的
   union 降低 36.82%，最佳因果 miss 降低 57.24%。下一步优先验证会话
   churn 与调度亲和性，不再把“类别是否影响缓存”作为开放问题。

## 3. 核心实验对象：访问事件，而不是语义层级

缓存模拟器的基本对象必须与真实推理执行顺序一致。

### 3.1 Prefill 事件

prefill 不能按每个 token 独立加载专家。真实 fused MoE 通常先聚合一个请求块或微批在某一层的路由，再对专家执行批量计算。因此事件定义为：

```text
(scheduler_step, phase=prefill, request_group, chunk_id, layer_id,
 requested_expert_set, token_count_per_expert, gate_mass_per_expert)
```

同一层、同一请求块中重复出现的专家只形成一次权重需求。

这里的 `scheduler_step` 不是固定常量。prefill 必须显式比较：

- chunk-major：每个 chunk 依次走完全部层；
- layer-major/weight-stationary：某层处理完已接纳的全部 chunk 后换层；
- layer-group/chunk-group 混合顺序；
- 与 decode continuous batching 的交错。

event-atomic 只规定一个 fused MoE 事件内部的服务语义，不替任何一种
跨事件执行顺序背书。

### 3.2 Decode 事件

decode 事件定义为：

```text
(scheduler_step, phase=decode, active_request_set, layer_id,
 requested_expert_union, token_count_per_expert, gate_mass_per_expert)
```

并发请求的专家并集必须在同一个调度步内形成，不能事后用单会话命中率相加。

### 3.3 专家块身份

专家块的全局身份为 `(layer_id, expert_id)`。控制器既要支持：

- 全局统一缓存预算；
- 每层固定配额；
- 每层动态配额。

这三种模式必须分开报告。

## 4. 第一阶段：建立可相信的 trace-first 模拟器

预计 3—5 个工作日。

### 4.1 输入转换

把现有 safetensors 转换为统一事件流，同时保留：

- 请求 ID、类别、split；
- phase、调度步、层；
- 专家 ID、rank、门概率和累计门质量；
- 序列长度和请求边界；
- 原始模型、commit、trace hash。

原始 safetensors 保持不变；转换结果是可重建的派生物。

### 4.2 第一批策略

必须实现并测试：

1. Demand Fetch，无缓存；
2. 最优静态常驻集；
3. LRU；
4. LFU；
5. LFRU；
6. Least-Stale；
7. 每层独立 Least-Stale；
8. Belady MIN 离线无损上界。

第一阶段暂不加入预取。先隔离“减少传输字节”的效果，避免把延迟隐藏与字节减少混为一谈。

### 4.3 输出指标

每个策略至少输出：

- compulsory / capacity / collision miss；
- miss ratio curve；
- transferred expert blocks；
- transferred bytes/token；
- transferred bytes/scheduler-step；
- p50/p95/p99 miss burst；
- cache occupancy；
- eviction 数量与无效搬运数量；
- cache insertion、换入换出总量和每 1000 调度步的策略抖动；
- 相对 Demand Fetch 和最强因果基线的改善；
- Belady 与最强可实现策略之间的 gap。

容量首先使用专家总字节的归一化比例：

```text
5%, 10%, 20%, 30%, 40%, 50%, 60%
```

同时保留绝对专家块数和字节数，不能只报命中率。

## 5. 第二阶段：构建 ControllerProbe-v0.1

预计 4—7 个工作日，可与模拟器开发部分并行。

不继续扩张完整 IndustrialProbe-1K。先构建一个小而平衡、可快速反复采集的 240 条控制器探测集，每类 40 条，discovery/confirmatory 各 20 条：

1. 文档问答与 RAG；
2. 工具调用与 agent；
3. ERP、表格与结构化分析；
4. 办公、法务与软件工程；
5. DCS、工艺时序、异常和报警；
6. 设备、维修、BOM 与资产管理。

来源优先复用现有公开和合成资产：

- EnterpriseProxy-1K；
- SyntheticEnterprise-1K；
- HAI、PRONTO、包装机报警、Petrobras 3W、OFBiz。

工业 JSON 通过确定性模板渲染为 prompt，保留底层记录 ID、来源、许可证、标签和渲染器版本。禁止引入公司内部数据。

每条记录必须分开保存：

- `prompt_text`：真实送入模型的输入，不包含答案；
- `reference_continuation`：可选的标准续写；
- `task_type`、`workload_archetype`；
- `session_id`、`turn_index`；
- `expected_phase`；
- `split`。

## 6. 第三阶段：补齐真实服务所需的 decode trace

预计 4—7 个工作日。

### 6.1 两种续写轨迹

对 ControllerProbe-v0.1 同时采集：

1. **受控 teacher-forced 轨迹**：`prompt_text + reference_continuation`，用于跨模型可比；
2. **模型自身 greedy decode 轨迹**：先生成 32—64 token，再对完整序列 teacher-force 重放并标注 prompt/decode 边界。

先在每类 10 条、合计 60 条上做 smoke；资源允许后扩到 240 条。

必须抽样验证 greedy 在线生成与 teacher-forced 重放的 top-k 路由是否一致。若不一致，记录差异层、差异 token 和 router margin；不能默认二者等价。

### 6.2 采集器扩展

新增以下字段或派生信息：

- `prompt_length`；
- `decode_length`；
- `phase_mask`；
- `scheduler_request_id`；
- top-k 边界 margin，而不仅是 top-1/top-2 margin；
- 第 k 名与第 k+1 名 router score/probability gap；
- 可选的下一层候选专家列表。

不保存全量 hidden state。若后续评估 Fate 类跨层预测，应在前向时直接计算并保存候选专家及置信度，避免产生巨量激活数据。

## 7. 第四阶段：同质与混合并发回放

预计 4—6 个工作日。

### 7.1 调度条件

离线合成以下 active decode microbatch：

```text
B = 1, 2, 4, 8, 16
```

20—30 个企业用户首先解释为注册/在线会话；活跃 decode 流单独建模。可以额外模拟 B=24/32 作为压力测试，但不能把在线用户数直接等同于每一步的 decode batch。

### 7.2 负载条件

- 六类纯负载；
- 工业主导混合；
- RAG 主导混合；
- agent 主导混合；
- 办公均衡混合；
- 场景突变：例如 RAG 主导突然切换到 agent/工业报警主导；
- 缓慢漂移：任务配比在数百个调度步内渐变。

混合事件流必须保留真实请求内 token 顺序，只在请求之间改变调度次序。

### 7.3 调度基线

- FCFS；
- round-robin continuous batching；
- 同类请求聚合；
- 基于专家集合相似度的 affinity grouping；
- 等待上限约束下的 affinity grouping。

任何提高复用的调度都必须同时报告额外排队延迟，不能只报告传输字节。

## 8. 第五阶段：控制器 v0

只有在基线和 Belady gap 清楚后才实现，预计 5—7 个工作日。

控制器 v0 不追求复杂学习算法，采用可解释、可审计的结构：

1. 根据各层 MRC 的边际收益动态分配缓存配额；
2. 层内使用 Least-Stale 或当前最强因果淘汰策略；
3. 用 EWMA/贝叶斯计数更新当前工作负载类型和专家热度；
4. 在工作负载突变时限制旧热度的惯性；
5. 在排队延迟约束内选择 affinity microbatch；
6. 输出每次决策的原因和预期收益。

控制器输入不能依赖客户事先提供 trace。产品冷启动输入是工作负载描述和容量参数；上线后仅依赖推理过程中自然产生的路由遥测在线适应。

第一版不做：

- 专家替代、剪枝、合并；
- 低精度 fallback；
- learned prefetcher；
- K3 专用逻辑；
- CUDA/H2D 实现；
- 自动输出采购配置单。

## 9. KV/KDA 与专家缓存的预算关系

缓存容量不能固定写成 40%。统一预算公式为：

```text
expert_cache_bytes =
    total_fast_memory
  - non_routed_weight_bytes
  - kv_or_kda_state_bytes(context, active_requests)
  - runtime_workspace_bytes
  - safety_reserve_bytes
```

本地阶段先把专家缓存比例 `rho` 作为外生变量扫描，得到：

```text
MRC(rho, B, workload_mix, scheduler)
```

随后为 Granite 和 OLMoE 加入解析式 KV 占用估算，把上下文长度和并发映射到 `rho`。K3 的 KDA/AttnRes 精确预算留到有可信实现或官方 profiling 数据后，不用猜测值替代。

初始上下文扫描：

```text
512, 1024, 2048, 4096 token
```

第一轮先做 512；只有 512 的事件和模拟器验证通过后再扩长上下文。

## 10. 本地阶段的预注册判据

“减少多少张卡”是最终商业 KPI，但在没有 K3 trace、真实 GPU、H2D 带宽和 kernel profiling 时，不能由小模型直接换算卡数。本地阶段用下面三个可验证判据决定是否继续。

### 10.0 第一周的分层早停门槛

对每个已经具有正确服务语义的实验单元
`(模型, phase, cache_scope, rho, B, workload_mix)`，定义：

```text
recoverable_gap =
    (transferred_blocks_best_causal
     - transferred_blocks_Belady)
    / transferred_blocks_best_causal
```

在当前没有独立 calibration split 的 Probe-1K 回放中，
`best_causal` 只从 LRU、LFU、LFRU 和 Least-Stale 中选择。
当前“最优静态常驻”使用整条待测 trace 统计热度，属于同数据
oracle static，只作为诊断，不能冒充可部署基线。ControllerProbe
建好后，只有在 discovery split 标定、confirmatory split 评估的
静态集才能进入 `best_deployable`。Belady 必须允许旁路准入，
不能强制把每个 miss 块写入缓存。

- 早停必须同时满足：连续稳态 gap 小于 10%，且代表目标适应时间尺度的
  contiguous request-block / 场景切换 stress 中，gap 的敏感性区间
  97.5% 上界仍小于 10%；
- 10%—20% 为有限空间；
- 超过 20% 才是强算法空间。

当前 Probe-1K 只有 prefill teacher-forced 事件，因此它只能否决相应的 **prefill 单元**。项目级早停必须等 ControllerProbe 的真实 decode/mixed replay，在 `B=4/8, rho=20%—40%` 上由 Granite 与 OLMoE 共同确认。不得用 prefill 结果提前否决 decode 调度、层配额或在线适应。

2026-07-29 的 event-atomic 阻塞审计进一步把六个 per-layer 目标点的
best-causal→Belady gap 修正为 0.155%—3.169%。这正式关闭“开发新的
稳态 prefill eviction/admission 算法”路线。下一项 prefill 实验仅剩
暖缓存场景切换；它检验工作负载先验和适应速度，不再检验稳态淘汰。

暖缓存转移矩阵也已完成。两模型共 1440 个 gap 单元，仅一个
OLMoE/rho=40%/N=10 单元达到 10.739%，且到 N=25 已降至 6.827%；
所有 N=50/100 单元均低于 10%。按预注册规则，prefill 的
eviction/admission/场景热启动策略路线关闭；prefill 执行顺序与
prefill/decode 联合调度仍开放。项目级判据仍等待 decode/mixed
`B=4/8`。

块边界冷启动会改变缓存状态，因此 block-reset bootstrap 必须明确称为
“空缓存/热启动先验敏感性实验”，不能冒充连续缓存流的 IID 置信区间，
也不能代表生产中的暖缓存负载切换。首次 Probe-1K 结果中，连续长流
gap 为 2.4%—8.1%，而 50-request 冷重置块为 20.1%—35.2%。后者只支持
“场景先验可能改善冷启动”，不证明存在同等大小的在线控制器空间。

此外，本地项目级早停要求 `B=4/8` 的 decode/mixed replay；当前纯
prefill 没有 B，故判据是“尚不可评估”，而不是被冷启动结果否决。
连续长流全部 12 个目标点落入 10% 以下，已经足以停止开发新的稳态
prefill 淘汰算法。

decode 判据不能只看 gap。必须同时报告 best-causal 与 Belady 的绝对
传输字节，并对照 `m <= BW/(25.83GB*R)`。若 Belady 本身仍超过带宽
预算，则该硬件/并发配置下严格无损纯缓存/调度路线物理不可行，无论
relative gap 多大。完整冻结口径见
`DECODE_CONCURRENCY_EXPERIMENT_DESIGN_2026-07-29.zh-CN.md`。

decode 的 best-causal baseline 固定包含 FCFS 同步骤跨请求专家并集
去重。逐请求独立模拟只可作为诊断，不能把免费去重收益冒充控制器收益。

2026-07-29 已完成 ControllerProbe-v0.1.3 的真实 autoregressive decode
采集与 `B=1/2/4/8/16` FCFS+union 回放。两个本地 MoE 在
`rho=40%, B=4/8` 上方向一致：Belady 的归一化绝对传输仍超过
150GB/s、每活动用户 20tok/s 条件预算；同时 gap 随 B 增大而缩小。
Granite `B=8/per-layer` gap 仅 8.17%，但 Belady 仍是预算约 5.1 倍；
OLMoE 同单元 gap 28.26%，Belady 仍是预算约 5.3 倍。这证明项目判据
必须同时看绝对字节与 gap。

该结果不触发 K3 项目级死刑：40/64 experts 的 `m_eff` 不得直接冒充
896 experts/top-16 的 K3 实测。它触发的是机制级暂停：不开发新的
decode eviction 变体，也不立即实现 controller v0。

2026-07-30 的 union/cache regime 复核进一步改变了实验优先级：
Granite 与 OLMoE 在 B=8、rho=40% 时几乎所有逐层事件都出现
`union>cache`，而 K3 均匀独立零假设下 B=8 只有
`union/cache≈0.336`。本地模型主要测到事件内强制溢出，K3 目标更可能
由跨步工作集漂移主导。Qwen3-30B-A3B 在同条件下
`union/cache≈1.008`，恰位于交叉区，故提升为下一实验；限活动流轮转
与 affinity microbatch 后移。

固定 `20tok/s/active-user` 的 oracle veto 仍是合法的 SLA 点判据，但
不再用作系统整体的二元产品叙事。现有数据已重算为
`(B, rho, bandwidth, per-user/aggregate rate)` 运行包络。完整复核见
`analysis/DECODE_OPERATING_ENVELOPE_AND_REGIME_AUDIT_2026-07-30.zh-CN.md`；
此前联合裁决见
`analysis/DECODE_CONCURRENCY_CROSS_MODEL_BASELINE_2026-07-29.zh-CN.md`。

第一周同时完成一份纸面硬件包络：分别写出容量约束与带宽约束，说明 transferred bytes 的下降在什么条件下能转化为更少 GPU。20% 是有意设置的高商业门槛，不把“20% 字节”直接等同为“20% 卡数”。

### 10.1 场景条件化是否必要

把某一负载上标定的最优因果策略迁移到另一负载。如果跨负载 transferred bytes 或 p99 burst 恶化不足 10%，说明场景条件化价值较弱；若稳定恶化超过 10%，说明 workload-aware 控制有实际空间。

### 10.2 控制器是否优于强基线

在 `rho=20%—40%`、`B=4/8` 下：

- 相对最强因果基线，传输字节降低至少 20%；
- p99 miss burst 不恶化；
- 加入 affinity scheduling 后的排队延迟处于预设上限内；
- Granite 与 OLMoE 方向一致。

若改善小于 10%，暂不进入生产插件开发；10%—20% 为灰区；超过 20% 才值得寻找 GPU 厂商或服务器厂商做真实硬件验证。

### 10.3 在线适应是否有效

负载发生突变后，控制器应在预设的 32—64 个 decode 调度步内恢复至少 80% 的稳态收益，并且切换期间 p99 burst 不超过最强静态基线的 1.2 倍。

恢复速度必须与稳定性同时报告，避免奖励过度敏感的控制器：

- 稳态策略抖动：每 1000 调度步的 cache insertion + eviction；
- 抖动放大率：相对同条件最强稳定基线的换入换出量；
- 无真实负载切换时的错误适应次数；
- 突变后的恢复曲线与恢复期间累计额外传输量。

控制器只有在恢复目标达标且稳态抖动不显著恶化时才通过。

这些阈值是工程 go/no-go，不是论文显著性结论。第一轮运行后可以依据观测噪声修订一次，此后冻结。

### 10.4 跨模型迁移失效条件（在接触 K3 前冻结）

本地模型结论未来迁移到 K3 时，至少检查以下三项；任何一项触发，都必须将本地数值结论标为失效，只能保留模拟器和方法：

| 可测量量 | 本地口径 | K3 失效条件 |
|---|---|---|
| top-k 边界稳定性 | `g=(z_k-z_{k+1})/std(z_all_router_logits)`；Granite median=0.08665、`P(g<=0.01)=7.76%`；OLMoE median=0.07419、`P(g<=0.01)=9.24%` | K3 median `<0.0371`，或 `P(g<=0.01)>19.25%` |
| 并发专家并集放大 | `a_B=|union(E_1...E_B)|/(B*k)`，在匹配 phase/负载/B 下测量 | K3 的 B=4/8 中位数比本地两模型最大值再高 0.15 以上 |
| 可用专家缓存比例 | 由非路由权重、KV/KDA、workspace 和安全余量反推 `rho` | 目标长上下文与并发下 `rho<20%`，则所有只在 20%—40% 得到的结论失效 |

数值阈值在首次看到 K3 trace 前冻结；得到 K3 后不因结果不理想而事后移动。

## 11. 两台 Mac 的分工

### M4 Pro 24GB

- OLMoE 路由采集；
- 必要时 Granite 路由采集；
- greedy decode 与 teacher-forced 重放；
- 模型结构和专家字节 profiling。

### M4 16GB

- 数据渲染、审计和测试；
- trace 转换；
- 缓存模拟器；
- 混合并发合成；
- 结果统计和绘图；
- 若 Granite 可稳定运行，可分担 Granite 采集，但不作为计划依赖。

两台机器不必共享运行时状态。使用冻结输入 hash 和输出 manifest 保证结果可合并。

## 12. 建议进度

### 第 1 周：让模拟器跑起来

- 建立事件 schema；
- 将现有两套 Probe-1K trace 转成事件流；
- 实现 Demand Fetch、静态、LRU、LFU、LFRU、Least-Stale、Belady；
- 输出第一版 MRC 与 burst 曲线；
- 用小型人工 trace 做单元测试和手算校验。
- 输出每个有效 prefill 单元的 Belady recoverable gap；
- 完成容量/带宽硬件包络，明确 20% 字节门槛与卡数的关系。

### 第 2 周：建立场景负载

- 物化 ControllerProbe-v0.1；
- 先采集 prompt-only 路由；
- 比较六类纯负载的 MRC；
- 判断“场景条件化”是否已有信号。

### 第 3 周：加入 decode 与混合并发

- 已完成 discovery 的 greedy decode 采集；
- 已完成 B=1/2/4/8/16 的 FCFS 企业六类 round-robin 混合事件流；
- 下一步先在 Qwen3-30B-A3B 探测 `union≈cache` 交叉区；
- 交叉区确认后再加入限活动流轮转与 affinity-aware 微批调度；
- 同质流与未见混合配比留到调度机制出现继续信号后再扩充；
- 量化混合负载干扰和并发悬崖。

### 第 4 周：控制器 v0 与第一次 go/no-go

- 实现动态层配额、在线热度更新和 affinity 调度；
- 对比 Least-Stale 与 Belady；
- 运行 discovery/confirmatory；
- 输出本地可行性报告。

如果第 4 周结果为 go，再进入：

- 更长上下文；
- 预取准入；
- 第三个中型 MoE；
- 与 GPU/服务器厂商合作取得 K3 或同级模型 trace；
- 真实硬件上的卡数、吞吐、SLA 和成本验证。

## 13. 立即开工顺序

下一步不下载新模型，也不继续扩充工业原始数据。基线工作已经完成，
顺序调整为：

1. 已完成 event-atomic 事件顺序审计；
2. 已完成 EnterpriseProxy-1K 暖缓存转移矩阵；
3. 停止 prefill eviction/admission/场景热启动算法开发，保留
   prefill 执行调度；
4. 设计并验证真实 autoregressive decode 路由采集；
5. 已构造 `B=1/2/4/8/16` 的 FCFS 混合调度步，并完成免费跨请求
   union 去重；
6. 已在 `B=4/8, rho=20%—40%` 同时评估绝对字节与 Belady gap；
7. 当前不开发 eviction/controller v0；先检验服务调度能否把绝对
   传输带入可救区；
8. 只有绝对预算和可恢复空间同时出现后，才开发对应控制器机制。

第一批结果只回答：“在现有模型上，强缓存策略之间还有多大 gap？”  
在这个数字出来以前，不开发预取器，不下载 Qwen3-30B，也不讨论 K3 卡数。
