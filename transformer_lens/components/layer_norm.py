"""Hooked Transformer Components.

This module contains all the components (e.g. :class:`Attention`, :class:`MLP`, :class:`LayerNorm`)
needed to create many different types of generative language models. They are used by
:class:`transformer_lens.HookedTransformer`.
"""
from jaxtyping import Float
import torch
import torch.nn as nn
from transformer_lens.hook_points import HookPoint
from transformer_lens.HookedTransformerConfig import HookedTransformerConfig
from typing import Dict, Optional, Union


class LayerNorm(nn.Module):
    def __init__(
        self, cfg: Union[Dict, HookedTransformerConfig], length: Optional[int] = None
    ):
        """
        LayerNorm with optional length parameter

        length (Optional[int]): If the dimension of the LayerNorm. If not provided, assumed to be d_model
        """
        super().__init__()
        if isinstance(cfg, Dict):
            cfg = HookedTransformerConfig.from_dict(cfg)
        self.cfg = cfg
        self.eps = self.cfg.eps
        self.length = self.cfg.d_model if length is None else length

        self.w = nn.Parameter(torch.ones(self.length, dtype=cfg.dtype))
        self.b = nn.Parameter(torch.zeros(self.length, dtype=cfg.dtype))

        # Adds a hook point for the normalisation scale factor
        self.hook_scale = HookPoint()  # [batch, pos, 1]
        # Hook_normalized is on the LN output
        self.hook_normalized = HookPoint()  # [batch, pos, length]

    def forward(
        self,
        x: Union[
            Float[torch.Tensor, "batch pos d_model"],
            Float[torch.Tensor, "batch pos head_index d_model"],
        ],
    ) -> Union[
        Float[torch.Tensor, "batch pos d_model"],
        Float[torch.Tensor, "batch pos head_index d_model"],
    ]:
        if self.cfg.dtype not in [torch.float32, torch.float64]:
            x = x.to(torch.float32)

        x = x - x.mean(axis=-1, keepdim=True)  # [batch, pos, length]
        scale: Float[torch.Tensor, "batch pos 1"] = self.hook_scale(
            (x.pow(2).mean(-1, keepdim=True) + self.eps).sqrt()
        )
        x = x / scale  # [batch, pos, length]
        return self.hook_normalized(x * self.w + self.b).to(self.cfg.dtype)