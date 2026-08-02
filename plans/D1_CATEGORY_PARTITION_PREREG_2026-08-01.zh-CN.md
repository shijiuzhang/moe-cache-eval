# D1 混合流类别感知缓存分区预注册

日期：2026-08-01  
状态：**complete_no_go_hard_partition（结果在冻结后追加）**

## 核心问题

同质流上的 office/legal 与 document RAG 收益，能否在同一条六类混合流中
转化为运行时收益？如果不能，workload 类别只保留为容量规划/选型输入，不进入
在线内存控制器。

## 数据分工

- discovery：D1 confirmatory 中 72 个 matched diverse 请求（12/类）；
- confirmatory：同一 split 中未参与 matched 分析的另外 72 个 diverse 请求
  （12/类）；
- 两组均为 B=8、category-round-robin、使用各自冻结的 arrival map；
- 模型、chat template、thinking=false、EOS 与路由 trace 均保持不变。

## 共同容量与策略

- per-layer，ρ=40%；总容量固定为 2458 expert blocks；
- 共享基线：一个 LFRU cache 使用全部 2458 blocks；
- 分区方案：三个互不共享权重副本的硬分区：
  1. `office_legal`；
  2. `document_rag`；
  3. 其余四类共享 `other`；
- 三分区容量总和必须严格等于共享基线。每层基础容量为 51，额外 10 个
  block 全部分给 `other`，避免 dedicated 分区获得 remainder 优势。

## Discovery 容量网格

每层 `(office, RAG, other)` 固定扫描：

`(4,4,43), (6,6,39), (8,8,35), (10,10,31), (12,12,27),
(14,14,23), (16,16,19)`。

仅用 discovery 选择 transferred blocks 最少的一个 allocation；随后冻结该
allocation，在 held-out 上只评估一次。held-out 最优 allocation 只作 oracle
诊断，不用于主结论。

## 主指标与判据

主指标：LFRU transferred blocks / logical expert assignments；次指标为每输出
token blocks、p99 step misses 和 cache churn。

- held-out 分区相对共享基线降低 ≥5%：类别分区有运行时工程价值，继续 affinity
  调度；
- 改善在 0%—5%：灰区，只允许研究 soft reservation/动态借槽，不进入产品
  承诺；
- held-out 不改善：硬类别分区失败；场景先验降级为选型输入，affinity 调度
  不得以“专用缓存池”作为机制前提。

所有比较必须使用同一请求、同一到达顺序、同一 B 和严格相等的总缓存容量。
不能把跨请求去重或冷启动整批错开记为分区收益。

## 冻结后执行结果

- discovery 选择：`office=6 / RAG=6 / other=39`；相对共享缓存传输量
  **增加 102.5%**；
- held-out 使用冻结分配：effective miss `18.01% → 38.89%`，传输量
  **增加 115.9%**；
- held-out 网格内 oracle allocation 仍为 `6/6/39`，仍增加 115.9%；
- 七个硬分区 allocation 全部失败；判据裁决为 `no_go_hard_partition`。

审计后的适用范围修正：本实验只关闭 **Qwen3、ρ≈40%、当前 B/配比下的硬
分区配置**，不能外推到 K3。6/6/39 的两个专用池甚至小于模型 top-k=8；
容量碎片化解释约 96% 的劣化，跨类别重复驻留/共享损失只解释约 4%。K3
ρ=40% 约有 358 槽/层，六等分仍约 60 槽，大于 top-k=16，不受同一算术
否决。

本实验也不否定共享缓存内基于真实专家亲和性的调度，因为后者不削减单请求
可用容量。若继续，必须建立新的机制假设与独立判据，不能继承同质流收益。
