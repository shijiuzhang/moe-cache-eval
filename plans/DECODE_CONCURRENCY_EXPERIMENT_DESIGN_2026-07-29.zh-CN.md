# Decode 与并发 MoE 内存实验：预注册设计

日期：2026-07-29  
状态：采集器开工前冻结

## 1. 目标

回答两个相互独立的问题：

1. 在 FCFS 并发和免费跨请求去重之后，绝对专家传输量是否落入 K3
   级硬件带宽预算？
2. 最强可实现因果基线与 Belady 之间是否仍有足够算法空间？

只报告 gap 不足以判定项目：gap 小可能代表现成策略已经够好，也可能
代表包括 Belady 在内的所有策略都同样不可行。

## 2. 路由采集

- 模型：Granite 3.1 3B-A800M、OLMoE 1B-7B；
- 数据：ControllerProbe-v0.1.3；
- discovery：每类 20 条，共 120 条；
- confirmatory：暂不采集；只有 discovery 出现继续信号后才使用；
- prompt 上限：512 token；
- 生成：greedy、无采样、最多 64 个新 token；
- EOS 后停止该会话，不生成 EOS 之后的伪 token；
- 保存每个真实 decode forward 所消费的 token、该 forward 发出的下一
  token，以及所消费 token 的逐层 top-k、门质量和 router logits；
- prompt prefill 与 decode 路由分开保存，不把 teacher-forced prompt
  token 冒充 decode。

先用每模型每类 1 条（共 6 条）、8 token 做 smoke test，验证 KV
cache、token 对齐、EOS 和路由层数；通过后才采集 discovery。

Token 对齐固定如下：prefill forward 直接发出第一个新 token；它不另有
decode 路由事件。随后第 t 个 decode forward 消费上一步发出的 token，
其 MoE 路由属于该 consumed token，并发出下一个 token。若 prefill
直接发出 EOS，则 decode 事件数为零；若某 decode forward 发出 EOS，
记录该 forward，但不再把 EOS 喂回模型。不得把 emitted token 的标签
错贴到本次 forward 的 router trace 上。

## 3. 冻结 FCFS+去重基线

并发取：

```text
B = 1, 2, 4, 8, 16
```

主 baseline 是 FCFS continuous batching：

1. 从冻结队列顺序取前 B 个活动会话；
2. 每个 decode scheduler step，每个活动会话产生一个 token；
3. 对同一步、同一层的全部请求专家集合先求 union；
4. 同一 `(layer, expert)` 即使被多个请求命中，也只形成一次权重需求；
5. 会话 EOS/达到 64 token 后，下一步由 FCFS 队列头补位；
6. 不按专家亲和性重排请求，不延迟某个已活动请求来制造复用。

缓存 LRU/LFU/LFRU/Least-Stale/Belady 全部运行在这个已经去重的事件流
上。`best_causal` 必须从 **FCFS + 同步骤跨请求去重** 的策略中选择。

“逐请求分别模拟后相加”只作为错误上界/诊断，不得进入
best-causal，也不得把去重收益计入控制器增量。

## 4. 事件与指标

decode 主事件：

```text
(scheduler_step, active_request_set, layer_id,
 union_expert_set, token_count_per_expert, gate_mass)
```

每个 `(模型, B, workload_mix, rho)` 至少报告：

- logical requested blocks（去重前）；
- union requested blocks（FCFS 免费去重后）；
- transferred blocks；
- transferred blocks/output-token；
- effective miss fraction：

```text
m_eff =
transferred_blocks
/ logical_requested_blocks_before_dedup
```

- bytes/scheduler-step 与 bytes/output-token；
- p50/p95/p99/max miss burst；
- FCFS union 去重收益；
- best-causal→Belady recoverable gap；
- Belady 的绝对 transferred bytes，而不只报告相对 gap。

rho 扫描 20%/30%/40%，主 cache scope 同时报告 global 与
per-layer equal quota；动态层配额尚不进入 baseline。

## 5. K3 绝对带宽包络

K3 未去重逻辑 routed-expert 字节为 25.83GB/output-token。对本地 trace
得到的 `m_eff`，只做条件性纸面投影：

```text
projected_K3_bytes_per_output_token = 25.83GB * m_eff
required_BW = aggregate_output_rate_R * projected_bytes
m_budget = BW / (25.83GB * R)
```

在取得 K3 trace 前，该投影只能用于判断机制是否值得继续，不能作为
K3 性能承诺。

主敏感性场景使用 `BW=150GB/s`：

| 活跃并发 | 每用户目标 | 聚合 R | m_budget |
|---:|---:|---:|---:|
| B=1 | 20 tok/s | 20 tok/s | 29.04% |
| B=2 | 20 tok/s | 40 tok/s | 14.52% |
| B=4 | 20 tok/s | 80 tok/s | 7.26% |
| B=8 | 20 tok/s | 160 tok/s | 3.63% |
| B=16 | 20 tok/s | 320 tok/s | 1.81% |

同时扫 `BW=100/150/200GB/s`，避免把未经实测的 150GB/s 当成事实。

## 6. 绝对字节 × 算法 gap 判据

先以 best-causal 的绝对字节判断，再看 gap：

| | Belady gap <10% | Belady gap ≥10% |
|---|---|---|
| best-causal ≤ 带宽预算 | 现成策略已达标；无控制器算法生意，可做配置/集成 | 已可用但仍有明显优化空间 |
| best-causal > 带宽预算 | 若 Belady 也超预算则纯缓存/调度路线死亡；否则现有策略失败但可恢复空间接近门槛 | 高风险高回报；只有 Belady 能落入预算才可能被控制器救活 |

额外设置 **oracle veto**：

```text
如果 Belady absolute bytes > bandwidth budget，
则该 (B, rho, R, BW) 配置下严格无损的纯缓存/调度方案判死，
无论 relative gap 多大。
```

这比单纯 2×2 更严格：大 gap 不保证物理上可达。

## 7. 控制器增量的归属

以下属于 baseline 免费能力，不能算控制器创新：

- 同一步跨请求 expert union 去重；
- FCFS continuous batching；
- event-atomic 服务语义；
- 强固定 cache policy。

只有相对该 baseline 的以下增量才能归给控制器：

- affinity-aware 请求分组/轮转；
- 动态层配额；
- workload/phase-aware 状态；
- 带宽突发抑制；
- prefill/decode 联合调度。

在 discovery 结果出来前，不实现这些控制器机制。
