# ControllerProbe-D1 matched-pair confirmatory 预注册

日期：2026-08-01  
状态：**frozen_before_full_trace_read**  
说明：冻结时仅完成 diverse 每类 1 条的管线冒烟；未读取全量两臂路由统计。

## 研究问题

把三种量分开估计，禁止再用一个全窗口数字混写：

1. 固定 prompt 壳和同步前缀造成多少“模板回声”；
2. 去除生成文本近重复后，workload 类别是否仍对应不同专家工作集；
3. 该残差在长 decode 位置与真实 EOS/churn 下是否持久。

## 固定采集口径

- 模型：本地 MLX `Qwen3-30B-A3B-4bit`，commit
  `d388dead1515f5e085ef7a0431dd8fadf0886c57`；
- split：confirmatory；
- diverse：每类 24 条，共 144 条；
- single-template：每类 12 条，共 72 条；其 `pair_id` 指向同源 diverse；
- Qwen chat template，单轮 `user`，`add_generation_prompt=true`；
- `enable_thinking=false`；
- greedy；prompt 上限 4096；总生成上限 385，对应最多 384 次带路由的
  decode forward；遇真实 EOS 即停止；
- 保存 emitted token、有效长度、生成文本和完整 router/top-k；
- 不在采集后删除近重复样本。近重复过滤只作为预注册的分层分析，原始数据
  必须完整保留。

## 固定调度与缓存口径

- 主口径 B=8、FCFS、同一步跨请求专家去重；
- 使用 `collection.arrival_offset_steps` 错开准入；
- event-atomic；per-layer；ρ=40%；
- 因果基线固定为 LRU/LFU/LFRU/Least-Stale 中传输最少者；oracle 为带
  bypass admission 的 Belady；
- single-template 与 diverse 的主比较只使用 72 个 matched source pairs；
  diverse 额外 72 条只作覆盖度/稳健性分析。

## 固定输出

1. 位置段 `0–16 / 16–64 / 64–160 / 160–384` 的纯类别与混合 union；
2. 每个位置段的有效请求数与存活比例，避免把 EOS 构成差异误写成路由效应；
3. 每类 positional token agreement、unique sequence 数、within-class expert
   Jaccard，以及 token agreement <5% 子集的 Jaccard；
4. 跨类别 expert Jaccard 基线；
5. 两臂在 matched source 上的 union、最佳因果 miss、Belady miss 与
   recoverable gap；
6. staggered-arrival 的平均 active B、miss burst p95/p99 和吞吐包络。

## 冻结解释规则

- **模板回声贡献**：同源 single-template 相对 diverse 的增量；它不是可被
  控制器回收的 workload 结构收益。
- **持久 workload 残差**：只在 diverse 臂中解释，且必须同时满足：后段
  union 效应不只存在于 `0–16`；低 token 重合子集的 within-class expert
  Jaccard 仍高于跨类别基线。只满足其一，记为不确定。
- **工业 DCS 旗舰论断**：本轮不会自动恢复。只有 DCS 在 diverse 的稳定段
  仍达到旧阈值（union 改善 ≥25%、因果 miss 改善 ≥40%），并在另一个独立
  split 重复，才允许重新提出。
- 不以 full-window 数字替代分段结果；不因结果不利而换 band、ρ、B、类别或
  thinking 模式。
- 本轮只确认 Qwen 本地机制；不得按相同 B 直接外推 K3。K3 投影只能按
  `union/cache` regime 对齐，并明确标为纸面条件映射。

