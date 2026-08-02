# D1 因果 affinity 组批最终诊断预注册

日期：2026-08-01  
状态：**complete_no-go（结果在冻结后追加）**

## 1. 问题

在不改变模型、专家精度和缓存总容量的前提下，利用每个请求上一 token 的
逐层专家集合，在最大服务间隔 `W=4` 个调度步内重组 B=8 微批，能否相对
公平 FCFS/round-robin 显著减少整条轨迹的专家传输量？

本实验是本地动态控制器方向的最后一个机制诊断。逐步 union 的下降不作为
结论；只认整条调度轨迹经过缓存回放后的总传输量。

## 2. 数据与隔离

- 模型：Qwen3-30B-A3B-4bit，128 experts、top-8、48 层；
- discovery：D1 diverse matched 72；
- confirmatory：D1 diverse held-out 72，只在 discovery 的实现、参数和静态
  pin 清单冻结后评估一次；
- 使用已修正的 chat-template、thinking-off、最长 384 decode trace；
- 使用既有到达 offset，不重采、不删样本、不按结果更换类别。

## 3. 调度语义

- 每个物理微批最多 B=8；
- 主实验最多维护 24 个已准入活跃会话（B×W 的 75% 负载）；其余请求按
  既有队列等待准入；
- 每一步先选出本步达到 deadline 的请求，再在剩余槽位中做 affinity 选择；
  已准入请求从首次服务起相邻两次服务的间隔不得超过 W=4；
- 请求 EOS 后立即移除，并在下一步从已到达等待队列按冻结顺序补位；
- 所有策略使用完全相同的到达、准入和请求完成规则，只改变每一步如何从
  活跃集合中选择最多 B=8 个请求；
- 每个微批仍做同一步跨请求专家去重，缓存事件使用 event-atomic 语义。

三个固定 scheduler：

1. `fcfs_deadline`：按最早服务 deadline、再按准入顺序选择；
2. `causal_prev_route`：只使用每个请求上一次已执行 token 的逐层专家集合，
   在强制 deadline 请求之外，用确定性贪心最小化预测 union；position=0
   没有历史时退化为 deadline/FCFS；
3. `oracle_current_route`：使用当前待执行 token 的真实逐层专家集合运行同一
   选批算法。它是 route-aware rolling oracle，不是全局最优或可部署策略；
   但最终指标在完整轨迹上计算，可检验逐步收益是否只是把代价后移。

固定 tie seed：20260801。禁止在 held-out 后更改聚类规则、seed、W 或 B。

### 冻结前可行性修正记录

最初草案把活跃上限设为 `B×W=32` 并按四批 round 分组。执行前检查发现：
32 个会话、B=8、W=4 时服务负载正好 100%，稳态每一步都有 8 个请求到期，
不存在可供 affinity 利用的调度松弛；而 round 间任意换组还可能把实际服务
间隔拉到 7。故在没有生成或读取任何实验结果前，改为逐步 deadline 调度，
主活跃上限固定 24。该值覆盖目标 20—30 并发的主体区间，并留下 25% 调度
松弛；不得在结果后改回 16 或放宽 W。

## 4. 缓存基线

总容量固定为 2458 blocks（ρ≈40%），per-layer、event-atomic：

- `LFRU`：当前冻结的最强动态因果驻留基线；
- `static_fixed`：每层等配额，专家排名只由 discovery FCFS 轨迹确定；同一张
  pin 清单用于 discovery/held-out 以及全部 scheduler。初始加载 2458 blocks
  计入总传输量。

不允许每种 scheduler 或 held-out 自己重拟合 static pin 清单。

## 5. 指标

主指标：

- `transferred_blocks / logical_assignments`；
- causal 相对同一驻留策略下 FCFS 的整轨迹传输量变化；
- causal 回收 oracle 头寸的比例。

次指标：

- union/logical；
- step-miss p99 与 max burst；
- 已准入请求最大/平均服务间隔；
- admission wait p50/p95/p99/max；
- 每请求服务次数与 starvation（必须为 0）。

## 6. 冻结裁决

confirmatory held-out 为唯一裁决集。动态 affinity 方向继续，当且仅当：

1. `causal_prev_route` 相对 `fcfs_deadline`，在 **LFRU 和 static_fixed
   两条基线中至少一条**总传输量降低 ≥10%；
2. 另一条基线不得恶化超过 2%；
3. 已准入请求最大服务间隔 ≤4，starvation=0；
4. p99 step miss 不恶化超过 10%；
5. discovery 方向一致（不要求同幅度）。

若 causal 改善 <10%，本地动态 affinity 方向永久关闭，产品收敛为
“选型/容量—带宽包络 + 静态配置生成器”。5%—10% 不设灰区，不因结果修改
阈值。oracle 结果无论多好都不能单独触发继续。

## 7. 外推边界

本实验不等于 K3 实测。Qwen 的 `union/cache`、expert balancing、专家粒度和
KV/KDA 竞争均与 K3 不同。通过只说明存在值得在 K3 上复核的调度机制；失败
只关闭当前本地证据支持下的动态方向。

## 8. 冻结后结果

### 8.1 Discovery

| residency | causal 传输改善 | rolling oracle 头寸 | causal 回收 oracle | p99 变化 |
|---|---:|---:|---:|---:|
| LFRU | 4.63% | 5.83% | 79.32% | +4.79% |
| static_fixed | 4.72% | 8.03% | 58.84% | +11.85% |

### 8.2 Confirmatory held-out

| residency | FCFS miss/logical | causal miss/logical | oracle miss/logical | causal 改善 | oracle 头寸 | causal 回收 oracle | p99 变化 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LFRU | 23.08% | 21.98% | 21.71% | **4.76%** | 5.92% | 80.43% | +7.06% |
| static_fixed | 19.15% | 18.28% | 17.64% | **4.55%** | 7.90% | 57.65% | +10.08% |

held-out union/logical 从 FCFS 67.63% 降到 causal 63.42%（约 6.22%），
rolling oracle 为 59.40%（约 12.16%）。但完整缓存轨迹上的可兑现传输改善
只有 4.55%—4.76%；oracle 自身也只有 5.92%—7.90%，证明原先 19.3% 的
单步组合头寸确实被无等待约束和逐步 order statistic 系统性高估。

causal 已回收 LFRU rolling-oracle 头寸的 80.43%，因此主要瓶颈不是上一 token
预测信号太弱，而是 W=4、24 活跃会话下可利用的全轨迹调度空间本来就不足。
所有请求均完成，starvation=0，最大服务间隔=4；但 static_fixed 的 p99 step
miss 恶化 10.08%，略越过冻结的 10% 上限。

### 8.3 裁决

主传输指标在两条驻留基线下都低于冻结的 10%，且一项 p99 约束失败，触发
`stop_local_dynamic_affinity`。至此，本地动态准入、淘汰、场景硬分区和
affinity 调度四条机制均关闭；不得把 oracle 结果作为继续开发的理由。

同时观察到：discovery FCFS 生成、对 held-out 完全冻结的静态 pin 清单，在
本实验人为引入的 24 会话 deadline 轮转下达到 19.15%，优于 LFRU 的 23.08%。
冻结后的适用范围审计证明，这个反转主要是轮转纪律打碎 LFRU 状态造成的，
不是一般性的“静态抗并发”：标准连续批处理 B=8 下 static fixed 为 19.37%，
仍输给 LFRU 18.01%。因此该观察不能作为静态产品的性能主论据。

标准连续批处理 B=2/4/8/16/24/32 扫描显示，static fixed 相对 LFRU 分别差
67.35% / 27.99% / 7.54% / 2.80% / 2.41% / 2.34%。可保留的产品论据仅是：
在本地高并发区间，静态 pin 接近动态策略且无需在线状态机；它不是性能前沿。
K3 B=8、ρ≈40% 的 `union/cache` 更接近 Qwen B≈2，恰好是静态劣势最大的
本地区间，必须列为静态配置生成器的头号外推风险。

结果：

- `analysis/controller-probe-d1-affinity-discovery-v1/`
- `analysis/controller-probe-d1-affinity-confirmatory-v1/`
- `analysis/controller-probe-d1-affinity-static-pins-v1.json`
- `analysis/controller-probe-d1-static-pin-concurrency-audit-v1/`
