# D1 Belady gap 归因：B=2 regime 对齐复核

日期：2026-08-01  
状态：**complete_future-victim-dominant（结果在冻结后追加）**

目的：K3 B=8、ρ≈40% 的 `union/cache` 纸面对齐更接近 Qwen3 B≈2，而不是
此前主实验 B=8。用同一长 decode trace 在 B=2 重放，检查 gap 来源是否改变。

固定口径：

- matched 72 discovery、held-out 72 confirmatory；
- 原 arrival map、FCFS、category-round-robin、同一步去重、event-atomic；
- per-layer，总容量 2458 blocks；
- 三策略和归因公式与 B=8 预注册完全相同；
- 不重采 trace，不改类别和请求。

裁决：held-out admission share ≥50% 且 discovery 同方向，才重新打开在线准入
控制器；25%—50% 为灰区；<25% 则 B=2 也由 future-victim 主导，动态缓存
控制器降级。该对齐仍是 Qwen→K3 的机制代理，不是 K3 实测。

## 冻结后结果

| split | LFRU miss | forced-admit Belady | full Belady | 总 gap | admission 占 gap | future-victim 占 gap |
|---|---:|---:|---:|---:|---:|---:|
| discovery matched | 13.09% | 6.65% | 6.42% | 50.91% | 3.37% | 96.63% |
| confirmatory held-out | 12.84% | 6.59% | 6.37% | 50.42% | **3.40%** | **96.60%** |

held-out admission share 远低于冻结的 25% 下限，且 discovery 同方向，触发
`future_victim_dominant_stop_dynamic_controller`。B=2 下 gap 比 B=8 更大，
但可由 bypass/admission 直接解释的部分反而从约 15.7% 降至 3.4%。

这关闭的是**当前证据支持下的在线准入/淘汰控制器继续开发**，不是证明未来
访问永远不可预测，也不是 K3 实测。若未来提出新的、可离线验证的因果信号
（例如能稳定预测 victim 的 reuse distance），必须作为新假设重新预注册，
不能把 full Belady 的 50.42% 当作现成可兑现收益。

结果：`analysis/controller-probe-d1-belady-gap-attribution-b2-v1/`。
