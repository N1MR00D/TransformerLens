"""Hooked Transformer Components.

This module contains all the components (e.g. :class:`Attention`, :class:`MLP`, :class:`LayerNorm`)
needed to create many different types of generative language models. They are used by
:class:`transformer_lens.HookedTransformer`.
"""
from typing import Dict, Optional, Union

import einops
import torch
import torch.nn as nn
from jaxtyping import Int

from transformer_lens.components import Embed, LayerNorm, PosEmbed, TokenTypeEmbed
from transformer_lens.hook_points import HookPoint
from transformer_lens.HookedTransformerConfig import HookedTransformerConfig


class BertEmbed(nn.Module):
    """
    Custom embedding layer for a BERT-like model. This module computes the sum of the token, positional and token-type embeddings and takes the layer norm of the result.
    """

    def __init__(self, cfg: Union[Dict, HookedTransformerConfig]):
        super().__init__()
        if isinstance(cfg, Dict):
            cfg = HookedTransformerConfig.from_dict(cfg)
        self.cfg = cfg
        self.embed = Embed(cfg)
        self.pos_embed = PosEmbed(cfg)
        self.token_type_embed = TokenTypeEmbed(cfg)
        self.ln = LayerNorm(cfg)

        self.hook_embed = HookPoint()
        self.hook_pos_embed = HookPoint()
        self.hook_token_type_embed = HookPoint()

    def forward(
        self,
        input_ids: Int[torch.Tensor, "batch pos"],
        token_type_ids: Optional[Int[torch.Tensor, "batch pos"]] = None,
    ):
        base_index_id = torch.arange(input_ids.shape[1], device=input_ids.device)
        index_ids = einops.repeat(
            base_index_id, "pos -> batch pos", batch=input_ids.shape[0]
        )
        if token_type_ids is None:
            token_type_ids = torch.zeros_like(input_ids)

        word_embeddings_out = self.hook_embed(self.embed(input_ids))
        position_embeddings_out = self.hook_pos_embed(self.pos_embed(index_ids))
        token_type_embeddings_out = self.hook_token_type_embed(
            self.token_type_embed(token_type_ids)
        )

        embeddings_out = (
            word_embeddings_out + position_embeddings_out + token_type_embeddings_out
        )
        layer_norm_out = self.ln(embeddings_out)
        return layer_norm_out

