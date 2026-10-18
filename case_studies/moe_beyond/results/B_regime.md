# Analysis B — operating regime

| events | B | rho | union mean / p95 | r̄ | r p95 | fraction r > 1 | null union | measured below null |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| E1 (per-token) | 1 | 0.10 | 6.00 / 6 | 0.945 | 1.000 | 0.0000 | 6.00 | 0.0% |
| E1 (per-token) | 1 | 0.20 | 6.00 / 6 | 0.469 | 0.500 | 0.0000 | 6.00 | 0.0% |
| E1 (per-token) | 1 | 0.30 | 6.00 / 6 | 0.313 | 0.316 | 0.0000 | 6.00 | 0.0% |
| E1 (per-token) | 1 | 0.40 | 6.00 / 6 | 0.234 | 0.240 | 0.0000 | 6.00 | 0.0% |
| E2 (whole-prefill) | 1 | 0.10 | 39.42 / 52 | 6.203 | 8.333 | 1.0000 | 47.05 | 16.2% |
| E2 (whole-prefill) | 1 | 0.20 | 39.42 / 52 | 3.081 | 4.083 | 0.9988 | 47.05 | 16.2% |
| E2 (whole-prefill) | 1 | 0.30 | 39.42 / 52 | 2.054 | 2.684 | 0.9473 | 47.05 | 16.2% |
| E2 (whole-prefill) | 1 | 0.40 | 39.42 / 52 | 1.540 | 2.040 | 0.9092 | 47.05 | 16.2% |
| E1 (per-token) — constructed by this paper | 2 | 0.10 | 11.10 / 12 | 1.749 | 2.000 | 0.9833 | 11.40 | 2.7% |
| E1 (per-token) — constructed by this paper | 2 | 0.20 | 11.10 / 12 | 0.867 | 1.000 | 0.0000 | 11.40 | 2.7% |
| E1 (per-token) — constructed by this paper | 2 | 0.30 | 11.10 / 12 | 0.579 | 0.632 | 0.0000 | 11.40 | 2.7% |
| E1 (per-token) — constructed by this paper | 2 | 0.40 | 11.10 / 12 | 0.433 | 0.480 | 0.0000 | 11.40 | 2.7% |
| E1 (per-token) — constructed by this paper | 4 | 0.10 | 19.51 / 23 | 3.074 | 3.667 | 0.9958 | 20.77 | 6.1% |
| E1 (per-token) — constructed by this paper | 4 | 0.20 | 19.51 / 23 | 1.525 | 1.769 | 0.9879 | 20.77 | 6.1% |
| E1 (per-token) — constructed by this paper | 4 | 0.30 | 19.51 / 23 | 1.017 | 1.200 | 0.5112 | 20.77 | 6.1% |
| E1 (per-token) — constructed by this paper | 4 | 0.40 | 19.51 / 23 | 0.762 | 0.885 | 0.0000 | 20.77 | 6.1% |
| E1 (per-token) — constructed by this paper | 8 | 0.10 | 31.07 / 37 | 4.895 | 6.000 | 0.9934 | 34.30 | 9.4% |
| E1 (per-token) — constructed by this paper | 8 | 0.20 | 31.07 / 37 | 2.428 | 2.917 | 0.9885 | 34.30 | 9.4% |
| E1 (per-token) — constructed by this paper | 8 | 0.30 | 31.07 / 37 | 1.619 | 1.895 | 0.9725 | 34.30 | 9.4% |
| E1 (per-token) — constructed by this paper | 8 | 0.40 | 31.07 / 37 | 1.214 | 1.440 | 0.9151 | 34.30 | 9.4% |

Rows marked “constructed by this paper” are FCFS batches built by the package; they are not MoE-Beyond's setting, which is B = 1.

## Placement (B = 1, ρ = 40%, per-layer)

- Under our reporting frame, the E1 (per-token) event stream of this setting has r̄ = 0.234 at ρ = 40% (per-layer scope); the nearest measured alignment point in Table 11 is 128-expert, B = 2 (r̄ = 0.293).
- Under our reporting frame, the E2 (whole-prefill) event stream of this setting has r̄ = 1.540 at ρ = 40% (per-layer scope); the nearest measured alignment point in Table 11 is 64-expert, B = 8 (r̄ = 1.44).
