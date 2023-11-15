"""Hooked Transformer Components.

This module contains all the components (e.g. :class:`Attention`, :class:`MLP`, :class:`LayerNorm`)
needed to create many different types of generative language models. They are used by
:class:`transformer_lens.HookedTransformer`.
"""

import einops
from fancy_einsum import einsum
from jaxtyping import Float, Int
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformer_lens.FactoredMatrix import FactoredMatrix
from transformer_lens.hook_points import HookPoint
from transformer_lens.HookedTransformerConfig import HookedTransformerConfig
from transformer_lens.past_key_value_caching import HookedTransformerKeyValueCacheEntry
from transformer_lens.utils import get_offset_position_ids
from typing import Dict, Optional, Tuple, Union


# Attention
class Attention(nn.Module):
    def __init__(
        self,
        cfg: Union[Dict, HookedTransformerConfig],
        attn_type: str = "global",
        layer_id: Optional[int] = None,
    ):
        """Attention Block - params have shape [head_index, d_model, d_head] (or [head_index, d_head, d_model] for W_O) and multiply on the right. attn_scores refers to query key dot product immediately before attention softmax

        Convention: All attention pattern-style matrices have shape [batch, head_index, query_pos, key_pos]

        Args:
            cfg (Union[Dict, HookedTransformerConfig]): Config
            attn_type (str, optional): "global" or "local", used by GPT-Neo. Local attention means the model can only attend back cfg.window_size tokens (here, 256). Not used by any other model at the moment. Defaults to "global".
            layer_id (int, optional): The index of the current layer. Used by the Mistal models (labelled here as stanford-gpt2) to scale down attention scores pre softmax for numerical stability reasons by 1/(layer_id+1). Defaults to None.
        """
        super().__init__()
        
        self.cfg = HookedTransformerConfig.from_dict(cfg) if isinstance(cfg, Dict) else cfg

        self.W_Q = nn.Parameter(
            torch.empty(
                self.cfg.n_heads, self.cfg.d_model, self.cfg.d_head, dtype=cfg.dtype
            )
        )
        self.W_K = nn.Parameter(
            torch.empty(
                self.cfg.n_heads, self.cfg.d_model, self.cfg.d_head, dtype=cfg.dtype
            )
        )
        self.W_V = nn.Parameter(
            torch.empty(
                self.cfg.n_heads, self.cfg.d_model, self.cfg.d_head, dtype=cfg.dtype
            )
        )
        self.W_O = nn.Parameter(
            torch.empty(
                self.cfg.n_heads, self.cfg.d_head, self.cfg.d_model, dtype=cfg.dtype
            )
        )
        self.b_Q = nn.Parameter(
            torch.zeros(self.cfg.n_heads, self.cfg.d_head, dtype=cfg.dtype)
        )
        self.b_K = nn.Parameter(
            torch.zeros(self.cfg.n_heads, self.cfg.d_head, dtype=cfg.dtype)
        )
        self.b_V = nn.Parameter(
            torch.zeros(self.cfg.n_heads, self.cfg.d_head, dtype=cfg.dtype)
        )
        self.b_O = nn.Parameter(torch.zeros(self.cfg.d_model, dtype=cfg.dtype))

        # Create a max_ctx x max_ctx mask, with True iff that query position
        # can attend to that key position (query is first axis, key is second axis)
        causal_mask = torch.tril(torch.ones((self.cfg.n_ctx, self.cfg.n_ctx)).bool())

        if attn_type == "global":
            # For global attention, this is a lower triangular matrix - key <= query
            self.register_buffer("mask", causal_mask)
        elif attn_type == "local":
            # For local, this is banded, query - window_size < key <= query
            assert isinstance(self.cfg.window_size, int)
            self.register_buffer(
                "mask", torch.triu(causal_mask, 1 - self.cfg.window_size)
            )
        else:
            raise ValueError(f"Invalid attention type: {attn_type}")

        self.register_buffer("IGNORE", torch.tensor(-torch.inf))

        self.layer_id = layer_id

        # attn_scale is a constant that we divide the attention scores by pre-softmax. I'm not entirely sure why it matters, but it's probably a mix of softmax not being scale invariant and numerical stability?
        self.attn_scale = np.sqrt(self.cfg.d_head) if self.cfg.use_attn_scale else 1.0

        if self.cfg.scale_attn_by_inverse_layer_idx:
            self.attn_scale *= self.layer_id + 1

        self.hook_k = HookPoint()  # [batch, pos, head_index, d_head]
        self.hook_q = HookPoint()  # [batch, pos, head_index, d_head]
        self.hook_v = HookPoint()  # [batch, pos, head_index, d_head]
        self.hook_z = HookPoint()  # [batch, pos, head_index, d_head]
        self.hook_attn_scores = HookPoint()  # [batch, head_index, query_pos, key_pos]
        self.hook_pattern = HookPoint()  # [batch, head_index, query_pos, key_pos]
        self.hook_result = HookPoint()  # [batch, pos, head_index, d_model]

        # See HookedTransformerConfig for more details.
        if self.cfg.positional_embedding_type == "shortformer":
            # This tracks the input to the keys and queries, which is resid_pre + pos_embeds
            self.hook_attn_input = HookPoint()  # [batch, pos, d_model]
        elif self.cfg.positional_embedding_type == "rotary":
            # Applies a rotation to each two-element chunk of keys and queries pre dot producting to bake in relative position. See HookedTransformerConfig for details
            self.hook_rot_k = HookPoint()
            self.hook_rot_q = HookPoint()
            sin, cos = self.calculate_sin_cos_rotary(
                self.cfg.rotary_dim, self.cfg.n_ctx, dtype=self.cfg.dtype
            )
            self.register_buffer("rotary_sin", sin)
            self.register_buffer("rotary_cos", cos)

    @property
    def OV(self) -> FactoredMatrix:
        """
        OV-Circuit, as defined in A Mathematical Framework. Because there's no non-linearity between the value vector and the output of the layer, the output is purely determined by the matrix W_OV = W_V @ W_O, and not W_V or W_O individually. (Mathematically, for a single head, output == pattern @ residual @ W_V @ W_O, see the glossary for more)

        Done in the order W_V, W_O because the paper uses left-multiplying weight matrices, and TransformerLens uses right-multiplying, sorry!

        Returns a FactoredMatrix, with left matrix W_V [head_index, d_model, d_head] and right matrix W_O [head_index, d_head, d_model] - this is a low rank factorisation of the underlying [head_index, d_model, d_model]. FactoredMatrix has helper functions to deal with these large matrices efficiently. To get the OV circuit of a head k, attn.OV[k] works.
        """
        return FactoredMatrix(self.W_V, self.W_O)

    @property
    def QK(self) -> FactoredMatrix:
        """
        QK-Circuit, as defined in A Mathematical Framework. Because there's no non-linearity in the key-query dot product, the output is purely determined by the matrix W_QK = W_Q.T @ W_K, and not W_Q or W_K individually. (Mathematically, for a single head, pattern = destination_residual.T @ W_Q.T @ W_K @ source-residual, see the glossary for more).

        Done in the order Q on the left, K on the right, because the pattern has dimensions [destination_pos, source_pos]

        Returns a FactoredMatrix, with left matrix W_Q [head_index, d_model, d_head] and right matrix W_K.T [head_index, d_head, d_model] - this is a low rank factorisation of the underlying [head_index, d_model, d_model] matrix. FactoredMatrix has helper functions to deal with these large matrices efficiently. To get the QK circuit of a head k, attn.QK[k] works.
        """
        W_K_transpose = einops.rearrange(
            self.W_K, "head_index d_model d_head -> head_index d_head d_model"
        )
        return FactoredMatrix(self.W_Q, W_K_transpose)

    def forward(
        self,
        query_input: Union[
            Float[torch.Tensor, "batch pos d_model"],
            Float[torch.Tensor, "batch pos head_index d_model"],
        ],
        key_input: Union[
            Float[torch.Tensor, "batch pos d_model"],
            Float[torch.Tensor, "batch pos head_index d_model"],
        ],
        value_input: Union[
            Float[torch.Tensor, "batch pos d_model"],
            Float[torch.Tensor, "batch pos head_index d_model"],
        ],
        past_kv_cache_entry: Optional[HookedTransformerKeyValueCacheEntry] = None,
        additive_attention_mask: Optional[Float[torch.Tensor, "batch 1 1 pos"]] = None,
        attention_mask: Optional[Int[torch.Tensor, "batch offset_pos"]] = None,
    ) -> Float[torch.Tensor, "batch pos d_model"]:
        """
        shortformer_pos_embed is only used if self.cfg.positional_embedding_type == "shortformer", else defaults to None and is irrelevant. See HookedTransformerConfig for more details
        past_kv_cache_entry is an optional entry of past keys and values for this layer, only relevant if generating text. Defaults to None
        additive_attention_mask is an optional mask to add to the attention weights. Defaults to None.
        attention_mask is the attention mask for padded tokens. Defaults to None.
        """

        if self.cfg.use_split_qkv_input or self.cfg.use_attn_in:
            qkv_einops_string = "batch pos head_index d_model"
        else:
            qkv_einops_string = "batch pos d_model"

        q = self.hook_q(
            einsum(
                f"{qkv_einops_string}, head_index d_model d_head \
                -> batch pos head_index d_head",
                query_input,
                self.W_Q,
            )
            + self.b_Q
        )  # [batch, pos, head_index, d_head]
        k = self.hook_k(
            einsum(
                f"{qkv_einops_string}, head_index d_model d_head \
                -> batch pos head_index d_head",
                key_input,
                self.W_K,
            )
            + self.b_K
        )  # [batch, pos, head_index, d_head]
        v = self.hook_v(
            einsum(
                f"{qkv_einops_string}, head_index d_model d_head \
                -> batch pos head_index d_head",
                value_input,
                self.W_V,
            )
            + self.b_V
        )  # [batch, pos, head_index, d_head]

        if past_kv_cache_entry is not None:
            # Appends the new keys and values to the cached values, and automatically updates the cache
            kv_cache_pos_offset = past_kv_cache_entry.past_keys.size(1)
            k, v = past_kv_cache_entry.append(k, v)
        else:
            # Not using a cache
            kv_cache_pos_offset = 0

        if self.cfg.positional_embedding_type == "rotary":
            q = self.hook_rot_q(
                self.apply_rotary(q, kv_cache_pos_offset, attention_mask)
            )
            k = self.hook_rot_k(
                self.apply_rotary(k, 0, attention_mask)
            )  # keys are cached so no offset

        if self.cfg.dtype not in [torch.float32, torch.float64]:
            # If using 16 bits, increase the precision to avoid numerical instabilities
            q = q.to(torch.float32)
            k = k.to(torch.float32)

        attn_scores = (
            einsum(
                "batch query_pos head_index d_head, \
                    batch key_pos head_index d_head \
                    -> batch head_index query_pos key_pos",
                q,
                k,
            )
            / self.attn_scale
        )  # [batch, head_index, query_pos, key_pos]

        if self.cfg.positional_embedding_type == "alibi":
            query_ctx = attn_scores.size(-2)
            # The key context length is the number of positions in the past - this includes all positions in the cache
            key_ctx = attn_scores.size(-1)
            
            alibi = self.get_cached_alibi(key_ctx=key_ctx)

            attn_scores += alibi[
                :, :query_ctx, :key_ctx
            ]  # [batch, head_index, query_pos, key_pos]

        if self.cfg.attention_dir == "causal":
            # If causal attention, we mask it to only attend backwards. If bidirectional, we don't mask.
            attn_scores = self.apply_causal_mask(
                attn_scores, kv_cache_pos_offset, attention_mask
            )  # [batch, head_index, query_pos, key_pos]

        if additive_attention_mask is not None:
            attn_scores += additive_attention_mask

        attn_scores = self.hook_attn_scores(attn_scores)
        pattern = F.softmax(attn_scores, dim=-1)
        pattern = torch.where(torch.isnan(pattern), torch.zeros_like(pattern), pattern)
        pattern = self.hook_pattern(pattern)  # [batch, head_index, query_pos, key_pos]
        pattern = pattern.to(self.cfg.dtype)
        z = self.hook_z(
            einsum(
                "batch key_pos head_index d_head, \
                batch head_index query_pos key_pos -> \
                batch query_pos head_index d_head",
                v,
                pattern,
            )
        )  # [batch, pos, head_index, d_head]

        if not self.cfg.use_attn_result:
            return (
                (
                    einsum(
                        "batch pos head_index d_head, \
                            head_index d_head d_model -> \
                            batch pos d_model",
                        z,
                        self.W_O,
                    )
                )
                + self.b_O
            )  # [batch, pos, d_model]
        else:
            # Explicitly calculate the attention result so it can be accessed by a hook
            # This is off by default because it can easily eat through your GPU memory.
            result = self.hook_result(
                einsum(
                    "batch pos head_index d_head, \
                        head_index d_head d_model -> \
                        batch pos head_index d_model",
                    z,
                    self.W_O,
                )
            )  # [batch, pos, head_index, d_model]
            return (
                einops.reduce(
                    result, "batch position index model->batch position model", "sum"
                )
                + self.b_O
            )  # [batch, pos, d_model]


    def apply_causal_mask(
        self,
        attn_scores: Float[
            torch.Tensor, "batch head_index pos pos_plus_past_kv_pos_offset"
        ],
        past_kv_pos_offset: int = 0,
        attention_mask: Optional[Int[torch.Tensor, "batch offset_pos"]] = None,
    ):
        # The query context length is the number of positions we take queries from - if not using a past_kv_cache this is just the context length (for the current prompt), but if we're caching it can be different.
        query_ctx_length = attn_scores.size(-2)
        # The key context length is the number of positions in the past - this includes all positions in the cache
        # If not caching, query_ctx_length == key_ctx_length
        key_ctx_length = attn_scores.size(-1)

        assert (
            query_ctx_length + past_kv_pos_offset == key_ctx_length
        ), f"query_ctx_length {query_ctx_length} + past_kv_pos_offset {past_kv_pos_offset} != key_ctx_length {key_ctx_length} - you likely have a bug."

        # Index back to front to ensure local attention works
        final_mask = self.mask[
            None, None, -query_ctx_length:, -key_ctx_length:
        ]  # [1, 1, pos, pos]

        if attention_mask is not None:
            # Apply a causal mask to the attention scores considering the padding
            einsum_str = "batch head pos offset_pos, batch offset_pos -> batch head pos offset_pos"
            final_mask = einops.einsum(final_mask, attention_mask, einsum_str).bool()

        return torch.where(final_mask, attn_scores, self.IGNORE)

    def calculate_sin_cos_rotary(
        self,
        rotary_dim: int,
        n_ctx: int,
        base: int = 10000,
        dtype: torch.dtype = torch.float32,
    ) -> Tuple[
        Float[torch.Tensor, "n_ctx rotary_dim"], Float[torch.Tensor, "n_ctx rotary_dim"]
    ]:
        """
        Calculate the sine and cosine waves to use in a rotary embedding. See https://blog.eleuther.ai/rotary-embeddings/ for details

        Note: For some inexplicable reason, in GPT-J each ADJACENT pair of elements in k and q are rotated, in GPT-NeoX the pair of elements at k and k+n//2 are rotated (ie folding the full length in half, and then looking at pairs accordingly). I have absolutely no clue why, it should be completely equivalent.
        To resolve this, I've coded it to default to the GPT-J mode, but to explicitly check whether it's GPT-NeoX and then do the GPT-NeoX thing if it is.
        """
        high_precision = torch.float32 if dtype != torch.float64 else torch.float64
        pos = torch.arange(n_ctx, dtype=high_precision)
        dim = torch.arange(rotary_dim // 2, dtype=high_precision)

        # A set of frequencies evenly spaced in log space
        freq = base ** (dim / (rotary_dim / 2))
        if self.cfg.original_architecture in ["GPTNeoXForCausalLM", "LlamaForCausalLM"]:
            freq = einops.repeat(freq, "d -> (2 d)")
        else:
            freq = einops.repeat(freq, "d -> (d 2)")

        # Create a n_ctx x rotary_dim tensor, where each column is an arithmetic sequence of angles in that frequency
        angles = pos[:, None] / freq[None, :]

        return torch.sin(angles).to(dtype), torch.cos(angles).to(dtype)

    def rotate_every_two(
        self, x: Float[torch.Tensor, "... rotary_dim"]
    ) -> Float[torch.Tensor, "... rotary_dim"]:
        """
        Rotary helper function, splits x into blocks of size 2 along the final axis and maps [x0, x1] to [-x1, x0]

        The final axis of x must have even length.

        GPT-NeoX and GPT-J do rotary subtly differently, see calculate_sin_cos_rotary for details.
        """
        rot_x = x.clone()
        if self.cfg.original_architecture in ["GPTNeoXForCausalLM", "LlamaForCausalLM"]:
            n = x.size(-1) // 2
            rot_x[..., :n] = -x[..., n:]
            rot_x[..., n:] = x[..., :n]
        else:
            rot_x[..., ::2] = -x[..., 1::2]
            rot_x[..., 1::2] = x[..., ::2]

        return rot_x

    def apply_rotary(
        self,
        x: Float[torch.Tensor, "batch pos head_index d_head"],
        past_kv_pos_offset=0,
        attention_mask: Optional[Int[torch.Tensor, "batch offset_pos"]] = None,
    ) -> Float[torch.Tensor, "batch pos head_index d_head"]:
        # Only apply rotary to first rotary_dim dimensions (eg, if rotary_dim=64 and d_head=256, only apply to first 1/4 of dimensions)
        x_pos = x.size(1)
        x_rot = x[..., : self.cfg.rotary_dim]
        x_pass = x[..., self.cfg.rotary_dim :]
        x_flip = self.rotate_every_two(x_rot)

        if attention_mask is None:
            rotary_cos = self.rotary_cos[
                None, past_kv_pos_offset : past_kv_pos_offset + x_pos, None, :
            ]
            rotary_sin = self.rotary_sin[
                None, past_kv_pos_offset : past_kv_pos_offset + x_pos, None, :
            ]
            x_rotated = x_rot * rotary_cos + x_flip * rotary_sin
        else:
            offset_position_ids = get_offset_position_ids(
                past_kv_pos_offset, attention_mask
            )
            mask_rotary_cos = self.rotary_cos[offset_position_ids, None, :]
            mask_rotary_sin = self.rotary_sin[offset_position_ids, None, :]
            x_rotated = x_rot * mask_rotary_cos + x_flip * mask_rotary_sin

        return torch.cat([x_rotated, x_pass], dim=-1)

    @staticmethod
    def create_alibi_slope(
        n_ctx: int, device: torch.device = None
    ) -> Float[torch.Tensor, "query key"]:
        """Create an ALiBi Slope Matrix.

        Create the slope matrix used in ALiBi, before it is multiplied by the head-specific scalar.

        See :meth:`create_alibi_bias` for the full ALiBi bias calculation.

        Examples:

        >>> Attention.create_alibi_slope(3)
        tensor([[ 0.,  0.,  0.],
                [-1.,  0.,  0.],
                [-2., -1.,  0.]])

        >>> Attention.create_alibi_slope(4)
        tensor([[ 0.,  0.,  0.,  0.],
                [-1.,  0.,  0.,  0.],
                [-2., -1.,  0.,  0.],
                [-3., -2., -1.,  0.]])

        Args:
            n_ctx: The maximum number of tokens in a prompt.

        Returns:
            A tensor of shape (n_ctx, n_ctx), where the upper triangle is zero and the lower
            triangle is decreasing by a constant slope of 1 (towards the bottom left corner).
        """
        # set rows as [[0,1,2...]]
        rows = torch.arange(n_ctx, device=device).unsqueeze(0)

        # Set cols as [[0],[1],[2]...]
        cols = torch.arange(n_ctx, device=device).unsqueeze(1)

        # Use broadcasting to create the desired lower triangular part of the matrix
        slope_matrix = rows - cols

        # Use the clamp method to set all positive values (upper right triangle) to
        return slope_matrix.clamp(max=0).to(torch.float32)

    @staticmethod
    def create_alibi_multipliers(
        n_heads: int, device: torch.device = None
    ) -> Float[torch.Tensor, "head_idx"]:
        """Create the ALiBi Scalar Multipliers for each Head.

        For n heads, the set of multipliers (m) is the geometric sequence that starts at 2^(-8/n), and
        uses that same value as its ratio. For example, with 8 heads the values would be [1/(2^1),
        1/(2^2), ... , 1/(2^8)]. With 16 heads the values would be [1/(2^0.5), 1/(2^1), ... , 1/(2^8)].

        See :meth:`create_alibi_bias` for the full ALiBi bias calculation.

        Examples:

        >>> Attention.create_alibi_multipliers(8)
        tensor([0.5000, 0.2500, 0.1250, 0.0625, 0.0312, 0.0156, 0.0078, 0.0039])

        >>> Attention.create_alibi_multipliers(16)
        tensor([0.7071, 0.5000, 0.3536, 0.2500, 0.1768, 0.1250, 0.0884, 0.0625, 0.0442, 0.0312,
                0.0221, 0.0156, 0.0110, 0.0078, 0.0055, 0.0039])

        Args:
            n_heads: The number of heads in a layer.
            device: The device to create the tensor on.

        Returns:
            A tensor of shape (n_heads,) containing the scalar multiplier for each head.
        """
        # Calculate the starting value
        start = 2 ** (-8 / n_heads)

        # Generate the indices [0, 1, ..., n_heads-1]
        indices = torch.arange(n_heads, device=device)

        # Compute the multipliers, with the starting value being the same as the ratio
        multipliers = start * (start**indices)

        return multipliers

    @staticmethod
    def create_alibi_bias(
        n_heads: int, n_ctx: int, device: torch.device = None
    ) -> Float[torch.Tensor, "head_idx query key"]:
        """Create the ALiBi Bias for all Heads.

        Calculate the ALiBi bias (https://arxiv.org/pdf/2108.12409.pdf) for all heads in a layer.

        The broad idea behind ALiBi is to remove the positional encoding from the original transformer
        model, and instead apply a bias to each attention score. This bias is proportional to the
        distance between the query and key (i.e. it encourage paying less attention to more distant
        tokens), and is added to the attention scores before the softmax. It is used in models such as
        Bloom.

        Examples:

        >>> Attention.create_alibi_bias(2, 4, torch.device('cpu'))
        tensor([[[ 0.0000,  0.0000,  0.0000,  0.0000],
            [-0.0625,  0.0000,  0.0000,  0.0000],
            [-0.1250, -0.0625,  0.0000,  0.0000],
            [-0.1875, -0.1250, -0.0625,  0.0000]],
            [[ 0.0000,  0.0000,  0.0000,  0.0000],
            [-0.0039,  0.0000,  0.0000,  0.0000],
            [-0.0078, -0.0039,  0.0000,  0.0000],
            [-0.0117, -0.0078, -0.0039,  0.0000]]])

        Args:
            n_heads: The number of heads in a layer.
            n_ctx: The maximum number of tokens in a prompt.
            device: The device to create the tensor on.

        Returns:
            The ALiBi bias that should be added to the attention scores before the softmax.
        """
        # Create the slope matrix
        slope: Float[torch.Tensor, "query key"] = Attention.create_alibi_slope(
            n_ctx, device
        )

        # Create the scalar multiplier for each head.
        multipliers: Float[
            torch.Tensor, "head_idx"
        ] = Attention.create_alibi_multipliers(n_heads, device)

        # The ALiBi bias is then m * slope_matrix
        alibi_bias = torch.einsum("ij,k->kij", slope, multipliers)

        return alibi_bias
    
    def get_cached_alibi(self, key_ctx: int) -> Float[torch.Tensor, "head_idx query key"]:
        """Get A Cached ALiBi bias For Calculation.
        
        This function will check for if an instance of our ALiBi bias is currently set.
        If the ALiBi bias is not set or if our key context is greater than it's cached size, a new
        instance will be initiated.
        
        The cached ALiBi bias is then returned

        Returns:
            The ALiBi bias that should be added to the attention scores before the softmax.
        """
        # only recompute when necessary to increase efficiency.
        if self.cached_alibi is None or key_ctx > self.cached_alibi.size(-1):
            self.cached_alibi = Attention.create_alibi_bias(
                self.cfg.n_heads, key_ctx, self.cfg.device
            )
        
        return self.cached_alibi