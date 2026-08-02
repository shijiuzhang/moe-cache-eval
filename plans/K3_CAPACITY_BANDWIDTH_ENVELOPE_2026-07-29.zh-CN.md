# K3 级 MoE：容量—带宽纸面包络

日期：2026-07-29  
性质：基于已完成的 K3 权重索引审计；不是性能承诺

## 1. 已审计常量

- 8×96GiB 总 HBM：768GiB；
- 非 routed-expert 权重：106.55GiB；
- routed-expert 权重：1347.12GiB；
- 82,432 个专家块，每块约 16.74MiB；
- 每 token 激活 92×16=1472 个专家块，未去重逻辑字节约 25.83GB。

运行状态统一记为：

```text
S = KV/KDA + workspace + 通信/CUDA graph + 碎片 + 安全余量
```

可常驻专家比例：

```text
rho = (768GiB - 106.55GiB - S) / 1347.12GiB
```

| S | 可用专家缓存 | rho |
|---:|---:|---:|
| 64GiB | 597.45GiB | 44.35% |
| 96GiB | 565.45GiB | 41.98% |
| 128GiB | 533.45GiB | 39.60% |
| 160GiB | 501.45GiB | 37.22% |
| 192GiB | 469.45GiB | 34.85% |
| 224GiB | 437.45GiB | 32.47% |
| 256GiB | 405.45GiB | 30.10% |

因此“40% 常驻”不是常量：仅当全部运行状态约不超过 127GiB 时成立。
长上下文 RAG 和并发会直接压低 `rho`。

## 2. 容量约束与带宽约束必须分开

容量所需卡数的下界：

```text
N_capacity =
ceil((non_routed + S + rho * routed_expert_bytes) / 96GiB)
```

减少传输字节本身不会自动减少 `N_capacity`。只有控制器在相同质量和
SLA 下允许使用更小 `rho`，并且跨过一个 96GiB 整数边界，才真正少一张
卡。因而后续应报告：

```text
在固定 miss/SLA 下，策略把所需 rho 从多少降到多少
```

而不是把“字节降低 20%”直接换算成“卡数降低 20%”。

带宽约束：

```text
required_H2D_BW =
aggregate_output_tokens_per_second
* effective_miss_bytes_per_token
```

若不考虑同一步/跨 token 去重，K3 的无缓存上界约为
25.83GB/token。假设主机到 8 卡的可持续聚合带宽为 `BW`，要达到系统
聚合输出速率 `R`，允许 miss fraction 的纸面上限为：

```text
m <= BW / (25.83GB * R)
```

例如仅用于量纲检查，若 `BW=150GB/s`、`R=20 token/s`，则
`m<=29.0%`。这不是实测值：PCIe 拓扑、分片方式、计算重叠和 burst
都会把要求收紧。

## 3. 20% 工程门槛的正确含义

本地阶段要求控制器相对最强因果基线至少减少 20% 传输字节，是一个
有意设置的高 bar，因为成熟基线已经很强。它代表“值得进入昂贵硬件
验证”的信号，不代表已经减少了整数张 GPU。

真实商业通过条件应是二选一或同时满足：

1. 在固定 HBM 卡数下，跨过目标吞吐/p99 SLA；
2. 在固定质量和 SLA 下，将 `rho` 压低到跨过整数卡容量边界。

只有取得 K3/同级 trace、真实 KV/KDA 占用和 H2D profiling 后，才能
把本地 MRC 转换成“16 卡到 8 卡”之类的产品声明。

## 4. Prefill 执行顺序是独立于 eviction 的大杠杆

对 100k token、chunk=128、rho=40%，在独立均匀路由近似下：

- 每层每 chunk 期望触及 806.738/896 个专家；
- 每层只能常驻 358 个，单事件 miss 下界约 448.738；
- chunk-major 的 routed-expert 传输量约 566.5TB；
- layer-major 在长上下文饱和后约等于一次 routed-expert 全池扫描：
  1.446TB；
- 纸面差距约 391.6 倍。

layer-major 需要保存跨 chunk activation/route state，并与 TTFT、
chunked prefill、continuous batching 和在线 decode 形成真实权衡。
因此低 prefill Belady gap 只否决淘汰/准入算法，不能否决执行调度。
完整推导见
`../analysis/K3_PREFILL_SCHEDULING_ORDER_AUDIT_2026-07-29.zh-CN.md`。
