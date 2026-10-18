# Analysis D — residency-gap decomposition

## Main: B = 1, per-layer, (i) persistent

| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| E1 (per-token) | 0.10 | lfru | 71.93% | 82.76% | 53.85% | 65.13% | 25.13% | 62.42% | 37.58% |
| E1 (per-token) | 0.20 | lfru | 58.10% | 70.49% | 37.95% | 40.98% | 34.69% | 15.06% | 84.94% |
| E1 (per-token) | 0.30 | lfru | 47.97% | 58.90% | 27.66% | 29.05% | 42.34% | 6.86% | 93.14% |
| E1 (per-token) | 0.40 | lfu | 38.20% | 48.65% | 19.97% | 20.69% | 47.71% | 3.95% | 96.05% |
| E2 (whole-prefill) | 0.10 | lfu | 35.87% | 35.76% | 35.76% | 35.76% | 0.30% | 7.19% | 92.81% |
| E2 (whole-prefill) | 0.20 | lfu | 29.65% | 29.95% | 28.92% | 29.40% | 2.48% | 65.89% | 34.11% |
| E2 (whole-prefill) | 0.30 | lfu | 24.15% | 24.90% | 22.48% | 25.34% | 6.93% | 171.35% | -71.35% |
| E2 (whole-prefill) | 0.40 | lfu | 19.28% | 20.22% | 16.54% | 21.85% | 14.20% | 194.06% | -94.06% |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

## B = 1, global, (i) persistent

| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| E1 (per-token) | 0.10 | lru | 73.27% | NA | 51.93% | 52.24% | 29.12% | 1.45% | 98.55% |
| E1 (per-token) | 0.20 | lfru | 60.86% | NA | 36.52% | 36.62% | 40.00% | 0.42% | 99.58% |
| E1 (per-token) | 0.30 | lfu | 48.97% | NA | 26.42% | 26.47% | 46.06% | 0.25% | 99.75% |
| E1 (per-token) | 0.40 | lfu | 38.13% | NA | 18.97% | 19.01% | 50.25% | 0.18% | 99.82% |
| E2 (whole-prefill) | 0.10 | lru | 42.58% | NA | 35.76% | 37.19% | 16.03% | 20.99% | 79.01% |
| E2 (whole-prefill) | 0.20 | lfu | 32.22% | NA | 28.90% | 29.96% | 10.31% | 32.05% | 67.95% |
| E2 (whole-prefill) | 0.30 | lfu | 26.42% | NA | 22.43% | 23.10% | 15.09% | 16.75% | 83.25% |
| E2 (whole-prefill) | 0.40 | lfu | 21.17% | NA | 16.37% | 16.68% | 22.69% | 6.51% | 93.49% |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

## Alignment column: B = 1, per-layer, (ii) per-request reset

| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| E1 (per-token) | 0.10 | lfru | 72.91% | NA | 58.40% | 66.93% | 19.90% | 58.78% | 41.22% |
| E1 (per-token) | 0.20 | lfru | 61.70% | NA | 48.24% | 49.72% | 21.81% | 11.01% | 88.99% |
| E1 (per-token) | 0.30 | lfru | 54.44% | NA | 44.37% | 44.71% | 18.49% | 3.35% | 96.65% |
| E1 (per-token) | 0.40 | lfru | 49.24% | NA | 43.07% | 43.15% | 12.53% | 1.32% | 98.68% |
| E2 (whole-prefill) | 0.10 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.20 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.30 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.40 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

## Alignment column: B = 1, global, (ii) per-request reset

| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| E1 (per-token) | 0.10 | lru | 73.82% | NA | 56.90% | 57.13% | 22.92% | 1.35% | 98.65% |
| E1 (per-token) | 0.20 | lfru | 64.40% | NA | 47.35% | 47.41% | 26.47% | 0.30% | 99.70% |
| E1 (per-token) | 0.30 | lfru | 55.80% | NA | 43.98% | 43.99% | 21.17% | 0.07% | 99.93% |
| E1 (per-token) | 0.40 | lfru | 49.73% | NA | 42.88% | 42.88% | 13.77% | 0.02% | 99.98% |
| E2 (whole-prefill) | 0.10 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.20 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.30 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |
| E2 (whole-prefill) | 0.40 | lru | 42.58% | NA | 42.58% | 42.58% | 0.00% | — | — |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

## Secondary: B = 8 constructed by this paper, per-layer, (i)

| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| E1 (per-token) | 0.10 | lfru | 55.16% | NA | 52.62% | 52.69% | 4.61% | 3.00% | 97.00% |
| E1 (per-token) | 0.20 | lfru | 45.94% | NA | 39.31% | 42.31% | 14.44% | 45.24% | 54.76% |
| E1 (per-token) | 0.30 | lfru | 37.79% | NA | 27.66% | 39.18% | 26.80% | 113.69% | -13.69% |
| E1 (per-token) | 0.40 | lfu | 30.27% | NA | 19.77% | 25.05% | 34.68% | 50.30% | 49.70% |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*
