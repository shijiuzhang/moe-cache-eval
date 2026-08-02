# K3 静态配置与容量包络：最小聚合数据验证协议

日期：2026-08-01  
状态：**draft_for_vendor_discussion**

## 1. 目的

在不索取 prompt、token、请求级路由轨迹或客户业务数据的前提下，回答两个
彼此独立的问题：

1. 给定卡数、上下文、并发和 SLA，K3 offload 的容量—带宽包络在哪里；
2. workload-calibrated 静态 expert pin 是否能在目标 K3 工作点满足带宽和
   尾延迟预算，是否值得成为包络工具之外的配置生成产品。

本协议不承诺省卡。offload 本身创造容量替代；本工具只在完成标定后判断某个
更低卡数配置是否安全，以及静态 pin 是否比引擎默认策略有增量价值。

## 2. 关键口径：不是普通 token 激活直方图

目标统计量是 `touch_count[phase, batch_bucket, layer, expert]`：

- 对每个实际 scheduler step、每层、每专家；
- 若该微批中至少一个 token 路由到该专家，则该专家计数加 1；
- 同一步内多个 token/请求命中同一专家，只计一次；
- prefill 与 decode 分开；batch bucket 至少分为 1—2、3—4、5—8、9—16、
  17—32、33+。

原因：专家权重在同一调度步内只需搬运一次。普通逐 token 激活次数没有做
跨请求 union 去重，不能精确计算静态 offload 字节，也可能给出不同的 pin
排序。单一 B=1 场景除外。

K3 全模型单个 bucket 的矩阵只有 `92×896=82,432` 个 uint64，约 0.66MB。
即使按 phase、六个 batch bucket 和两个时间窗口拆分，也只有约 16MB。

## 3. 两个严格隔离的时间窗口

### A. Calibration window

用于选择 pin 清单。提供：

- 上述 union-touch 计数矩阵；
- 每个 phase/batch bucket 的 scheduler step 数；
- decode 输出 token 数和 logical expert assignments；
- active batch-size 直方图；
- 非敏感的负载配比标签，例如 RAG / agent / office / industrial 百分比；
- 采样时长和模型/引擎/量化版本。

### B. Held-out evaluation window

必须是之后的独立时间窗口，提供完全相同的聚合统计。禁止用 evaluation
直方图重新选择专家，再在同一窗口报告结果。

给定 calibration 生成的每层固定集合 `P_l`，held-out 稳态静态传输块数为：

`miss_blocks = Σ_l Σ_{e not in P_l} touch_count_eval[l,e]`

平均专家 H2D 字节/token 为：

`bytes_per_token = miss_blocks × expert_block_bytes / output_tokens`

初始 pin 加载字节单独报告，不混入长时间稳态平均值。

## 4. 一张累计直方图不能回答的内容

累计计数只能给平均传输字节，不能给：

- p95/p99/max miss burst；
- inter-token latency；
- PCIe/NVLink 拓扑上的实际并行 H2D 能力；
- KV/KDA、workspace、CUDA graph 与专家 cache 的真实显存竞争；
- LFRU/其他动态策略的表现。

因此需要一个不含路由信息的第二阶段回传。

## 5. 第二阶段：加载冻结 pin 后的聚合运行指标

厂商按生成的 pin 清单运行 held-out 负载，只返回：

- 平均、p95、p99、max H2D expert bytes per scheduler step；
- 平均与 p99 inter-token latency、聚合 tok/s；
- 真实 active batch-size 直方图；
- HBM 中非 routed 权重、专家 cache、KV/KDA、workspace 和空闲余量；
- 主机到各 GPU 以及聚合的可持续 H2D GB/s；
- 同硬件同负载下引擎默认 offload 策略的上述汇总指标。

仍不需要 prompt、token、request ID 或逐步专家 ID。

## 6. 冻结 go/no-go 口径

在首次 K3 数据返回前冻结以下判据。目标配置必须同时满足：

1. **容量**：真实峰值 HBM 占用留有至少 8% 安全余量；
2. **平均带宽**：静态专家 H2D 平均占用不超过实测可持续带宽的 70%；
3. **尾部**：p99 inter-token latency 满足对应 workload SLA，且 p99 expert
   H2D burst 不超过该 token 时间预算；
4. **迁移**：held-out 的 bytes/token 相对 calibration 估计恶化不超过 15%；
5. **产品增量**：静态策略必须至少满足以下一项：
   - 在同 SLA 下使安全配置跨过至少一个 96GB 卡数边界；
   - 相对引擎默认策略减少至少 10% 专家传输字节；
   - 传输量落后不超过 5%，但显著降低引擎集成/运行时复杂度，并由厂商明确
     接受这一交换。

若静态在 held-out 上超过带宽预算，或相对默认策略劣化超过 25%，静态配置
生成器 no-go，产品只保留容量—带宽—SLA 包络与验收工具。5%—25% 为商业
取舍区，不能包装成技术优化收益。

## 7. 容量与硬件标定输入

纸面常量可用于原型：非 routed 权重约 106.55GiB，routed experts 约
1347.12GiB，未去重 routed bytes 约 25.83GB/token。商业输出还必须取得：

- 目标引擎下 `S(context, active_sessions)`：KV/KDA、workspace、图缓存、碎片；
- 目标 CPU/NUMA/PCIe 拓扑的持续聚合 H2D 带宽，不使用峰值规格；
- expert block 的实际存储和传输字节，包括 scale/metadata/alignment；
- prefill/decode 的执行与 offload 重叠比例。

在这些量未标定前，卡数阶梯只能作为条件包络，不能写进客户合同。

## 8. 数据与合规

协议不包含业务内容，但聚合路由分布仍可能反映模型和工作负载特征，不能称为
“零敏感”。建议：

- 只传聚合 uint64 矩阵和粗粒度 workload 标签；
- calibration/evaluation 窗口各自至少覆盖足够多的 decode token；
- 可由厂商在本地运行开源计算脚本，只输出最终集中曲线和校验哈希；
- 合同明确禁止尝试从统计量反推客户业务。

## 9. 产品边界

- **包络工具不会创造省卡能力**；它把 offload 已存在的容量—吞吐交换算清，
  用于报价、验收边界和避免欠配烂尾。
- **静态配置生成器只有通过第 6 节后才是优化产品**；否则它只是分析候选项。
- 直接购买者更可能是服务器 OEM、系统集成商和一体机方案商；GPU 厂商的
  价值主要是设计赢单、参考配置和降低项目失败率，并非单纯减少 GPU 销量。
