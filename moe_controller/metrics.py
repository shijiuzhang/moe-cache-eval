from __future__ import annotations

import torch


def normalized_topk_boundary_gap(
    router_logits: torch.Tensor,
    *,
    top_k: int,
    epsilon: float = 1e-8,
) -> torch.Tensor:
    """Return (z_k - z_k+1) / std(z) for each token/router row."""
    if router_logits.ndim < 1:
        raise ValueError("router_logits must have an expert dimension.")
    num_experts = int(router_logits.shape[-1])
    if top_k <= 0 or top_k >= num_experts:
        raise ValueError("top_k must be in [1, num_experts - 1].")
    values = router_logits.to(torch.float32)
    boundary = torch.topk(
        values,
        k=top_k + 1,
        dim=-1,
        sorted=True,
    ).values
    raw_gap = boundary[..., top_k - 1] - boundary[..., top_k]
    scale = values.std(dim=-1, unbiased=False).clamp_min(epsilon)
    return raw_gap / scale
