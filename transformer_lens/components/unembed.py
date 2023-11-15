"""Hooked Transformer Unembed Component.

This module contains all the components (e.g. :class:`Attention`, :class:`MLP`, :class:`LayerNorm`)
needed to create many different types of generative language models. They are used by
:class:`transformer_lens.HookedTransformer`.
"""

from fancy_einsum import einsum
from jaxtyping import Float
import torch
import torch.nn as nn
from transformer_lens.HookedTransformerConfig import HookedTransformerConfig
from typing import Dict, Union

class Unembed(nn.Module):
    def __init__(self, cfg: Union[Dict, HookedTransformerConfig]):
        super().__init__()
        if isinstance(cfg, Dict):
            cfg = HookedTransformerConfig.from_dict(cfg)
        self.cfg = cfg
        # Note that there's a separate variable for d_vocab_out and d_vocab (the input vocab size). For language tasks these are always the same, but for algorithmic tasks we may want them to be different.
        self.W_U: Float[torch.Tensor, "d_model d_vocab_out"] = nn.Parameter(
            torch.empty(self.cfg.d_model, self.cfg.d_vocab_out, dtype=cfg.dtype)
        )
        self.b_U: Float[torch.Tensor, "d_vocab_out"] = nn.Parameter(
            torch.zeros(self.cfg.d_vocab_out, dtype=cfg.dtype)
        )

    def forward(
        self, residual: Float[torch.Tensor, "batch pos d_model"]
    ) -> Float[torch.Tensor, "batch pos d_vocab_out"]:
        return (
            einsum(
                "batch pos d_model, d_model vocab -> batch pos vocab",
                residual,
                self.W_U,
            )
            + self.b_U
        )
