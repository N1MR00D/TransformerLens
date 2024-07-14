import math

import pytest
import torch
from transformers import AutoModelForCausalLM

from transformer_lens import HookedTransformer


class TestMatchHuggingFace:
    # fixtures
    @pytest.fixture(scope="class", params=["joelb/Mixtral-8x7B-1l"])
    def model_name(self, request):
        return request.param

    # tests
    def test_compare_huggingface_mlp_match_local_implementation(self, model_name):
        tl_model = HookedTransformer.from_pretrained_no_processing(model_name, device="cpu")
        hf_model = AutoModelForCausalLM.from_pretrained(model_name, device_map="cpu")
        tensor_shape = (3, 5, tl_model.cfg.d_model)
        test_tensor = torch.randn(tensor_shape)

        for layer_n in range(len(tl_model.blocks)):
            tl_out = tl_model.blocks[layer_n].mlp(test_tensor)
            # hf_out = hf_model.transformer.h[layer_n].mlp(test_tensor)
            hf_out, router_logits = hf_model.model.layers[layer_n].block_sparse_moe(test_tensor)

            print(f"test: {tl_out[:2, :2, :2]=}")
            print(f"test: {hf_out[:2, :2, :2]=}")
            print(f"test: {(tl_out - hf_out)[:5, :5, :5]=}")
            print(f"test: {torch.sum(tl_out - hf_out)=}")
            assert torch.sum(tl_out == hf_out) == math.prod(tensor_shape)

    # def test_compare_huggingface_attention_match_local_implementation(self, model_name):
    #     tl_model = HookedTransformer.from_pretrained_no_processing(
    #         model_name, device="cpu"
    #     )
    #     hf_model = AutoModelForCausalLM.from_pretrained(model_name, device_map="cpu")
    #     batch, pos, d_model = 3, 5, tl_model.cfg.d_model
    #     input = torch.randn(batch, pos, d_model)
    #
    #     for layer_n in range(len(tl_model.blocks)):
    #         tl_out = tl_model.blocks[layer_n].attn(
    #             query_input=input,
    #             key_input=input,
    #             value_input=input,
    #             past_kv_cache_entry=None,
    #             attention_mask=None,
    #         )
    #         # hf_out, _ = hf_model.transformer.h[layer_n].attn(hidden_states=input)
    #         hf_out, _, _ = hf_model.model.layers[layer_n].self_attn(hidden_states=input)
    #
    #         print(f"{tl_out[:2, :2, :2]=}")
    #         print(f"{hf_out[:2, :2, :2]=}")
    #         assert torch.sum(tl_out == hf_out) == math.prod(tl_out.shape)
