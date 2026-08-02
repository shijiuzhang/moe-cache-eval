# D1 Belady gap 归因预注册

日期：2026-08-01  
状态：**complete_future-victim-dominant（结果在冻结后追加）**

## 问题

约 45% 的 causal-to-Belady gap 主要来自哪一种未来知识？

1. **victim future knowledge**：知道哪个现有常驻块最晚再用；
2. **optional bypass admission**：知道一个新 miss 在被淘汰前不会复用，因此
   根本不把它留进 cache。

只有第二类存在明确的在线近似产品路径（复用预测准入）。

## 三个固定策略

- `LFRU`：当前最强因果基线；
- `Belady forced-admit`：保留 Belady 的未来 victim 排序，但所有新 miss 在
  容量允许时必须留在 cache；若单事件 miss 已超过容量，只在强制集合内按
  下一次使用保留容量允许的部分；
- `Belady bypass`：当前 event-atomic Belady，可拒绝收留未来无复用的新块。

定义：

- 总 gap blocks = `LFRU - Belady bypass`；
- admission contribution = `forced-admit - bypass`；
- future-victim contribution = `LFRU - forced-admit`；
- 两项之和必须严格等于总 gap。

## 数据与口径

- discovery：D1 matched diverse 72 混合流；
- confirmatory：D1 held-out diverse 72 混合流；
- B=8、staggered arrivals、FCFS、同一步去重、event-atomic、per-layer；
- 主容量：2458 blocks（ρ≈40%，与此前主结果完全一致）；
- 次级容量探针：每层 6/39/43/51 槽，用于观察归因是否随容量改变；
- 只用 trace，不新增采集，不调整请求顺序。

## 冻结判据

以 held-out 主容量的 admission contribution / total gap 为主：

- ≥50%，且 discovery 同方向：准入是 gap 主因；进入“因果复用预测器能否拿到
  ≥5% 实际字节收益”的下一阶段；
- 25%—50%：灰区，先做简单 causal upper-bound，不开发生产控制器；
- <25%：gap 主要依赖未来 victim knowledge；动态控制器路线停止，产品回到
  选型/包络与静态配置。

该探针是归因 oracle，不是可部署算法。即使 admission 占比高，也不能把它
直接写成可实现收益。

## 冻结后 B=8 结果

主容量 held-out：LFRU 18.01%，forced-admit Belady 11.20%，full Belady
9.93%。总 gap 中 admission 占 15.69%，future-victim 占 84.31%；discovery
对应 16.33% / 83.67%。触发 `future_victim_dominant_stop_dynamic_controller`。

该裁决只覆盖 Qwen B=8。由于 K3 B=8 的 `union/cache` 更接近 Qwen B≈2，
另行冻结 B=2 regime 对齐复核，不能用本节直接关闭 K3 尺度。
