# Qwen3 工作负载条件化 confirmatory 预注册

日期：2026-08-01  
冻结状态：**contaminated_invalid_for_confirmation（2026-08-01 审计后追加）**  
discovery 依据：ControllerProbe-v0.1.3 discovery 的 B=8 结果

> 本文保留为预注册与失败分析记录，不再作为确认性证据。旧采集器把裸
> `prompt_text` 当续写输入，没有应用 chat template；固定模板回声、统一 63
> step 长度和同步 decode position 系统性放大了同类请求重叠。交叉区基线与
> ρ 扫描不依赖本节类别比较，仍然有效。

## 固定实验口径

- 模型与 commit：与 Qwen3 discovery 相同；
- 数据：ControllerProbe-v0.1.3 `split=confirmatory`，此前未用于本分析；
- 六个 workload archetype，每类按源顺序取前 16 条；
- 每条最多 63 个 decode forward；
- B=8，所有调度步保持满 batch；
- 纯类别：每类单独形成 16 请求流；
- 混合对照：六类各 16 条，category-round-robin；
- FCFS，同一步跨请求专家去重；
- event-atomic；
- 主缓存口径：per-layer，ρ=40%；
- 策略集合不变：LRU、LFU、LFRU、Least-Stale、Belady；
- 最佳因果策略只能从上述四个因果基线中选择。

## 主指标

1. 每层每调度步的平均专家 union；
2. 最佳因果策略的 effective miss fraction；
3. Belady effective miss fraction；
4. recoverable gap。

## 冻结判据

设改善均相对 balanced16 混合对照计算。

1. 六个纯类别的平均 union 均低于混合对照；
2. DCS/process diagnostics 的 union 至少降低 25%；
3. DCS/process diagnostics 的最佳因果 miss 至少降低 40%；
4. 六个纯类别的最佳因果 miss 改善中位数至少为 20%。

四条全部成立，才把“工作负载条件化具有稳定工程价值”升级为本模型内的
confirmatory 结论。任何一条失败都如实报告，不调整阈值、不更换类别、不改用
更有利的 cache scope 或 ρ。

## 仍不允许推出的结论

- 不外推到 K3；
- 不把类别差异解释为语义专家专精；
- 不证明真实企业流量具有相同比例；
- 不证明控制器能回收全部 Belady gap；
- 不把固定 63-step 会话当作真实 churn。

## Confirmatory 执行结果（冻结后追加）

执行状态：历史上完成并通过四条旧判据；**审计后判定受污染，结论撤回。**

| 条件 | union 改善 | 最佳因果 miss 改善 | 判定 |
|---|---:|---:|---|
| document RAG | 17.32% | 57.85% | 方向通过 |
| tool agent | 6.21% | 9.48% | 方向通过；收益较小 |
| ERP structured analytics | 14.10% | 36.22% | 方向通过 |
| office/legal | 10.44% | 26.86% | 方向通过 |
| DCS/process diagnostics | 36.82% | 57.24% | 两个冻结阈值均通过 |
| equipment maintenance/BOM | 22.01% | 35.32% | 方向通过 |

六类最佳因果 miss 改善中位数为 35.77%，超过旧冻结的 20% 阈值；该数字
包含模板回声贡献，不可解释为工作负载条件化的净效应。

原始派生结果：
`analysis/controller-probe-v0.1.3-qwen3-30b-a3b-4bit-decode64-workload-conditioning-confirmatory-b8-v1/`
