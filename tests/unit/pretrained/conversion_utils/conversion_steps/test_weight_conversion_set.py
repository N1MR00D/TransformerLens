from unittest import mock


import torch
from transformer_lens.pretrained.conversion_utils.conversion_steps.weight_conversion_set import WeightConversionSet
from transformer_lens.pretrained.conversion_utils.conversion_steps.direct_weight_conversion import DirectWeightConversion


def test_weight_conversion_for_root():
    
    conversion = WeightConversionSet("", {
        "embed.W_E": DirectWeightConversion("embed_tokens.weight"),
        "pos_embed.W_pos": DirectWeightConversion("wpe.weight"),
        "ln_final.w": DirectWeightConversion("ln_f.weight"),
    })
    
    embed_tokens = torch.rand(2, 3)
    wpe = torch.rand(80, 5)
    ln_f = torch.rand(10, 5)
    
    transformers_model = mock.Mock()
    transformers_model.transformer = mock.Mock()
    transformers_model.transformer.embed_tokens = mock.Mock()
    transformers_model.transformer.embed_tokens.weight = embed_tokens
    transformers_model.transformer.wpe = mock.Mock()
    transformers_model.transformer.wpe.weight = wpe
    transformers_model.transformer.ln_f = mock.Mock()
    transformers_model.transformer.ln_f.weight = ln_f
    
    result = conversion.convert(transformers_model)
    
    print("result", result)
    assert result["embed.W_E"] == embed_tokens
    assert result["pos_embed.W_pos"] == wpe
    assert result["ln_final.w"] == ln_f
    


# def test_rearrange_weight_conversion_with_subset():
    
#     conversion = RearrangeWeightConversion("transformer.wpe.weight", "(n h) m->n m h", n=8)
    
#     starting = torch.rand(80, 5)
    
#     print(starting.shape)
    
#     transformers_model = mock.Mock()
#     transformers_model.transformer = mock.Mock()
#     transformers_model.transformer.wpe = mock.Mock()
#     transformers_model.transformer.wpe.weight = starting
    
#     result = conversion.convert(transformers_model)
    
#     assert result.shape == (8, 5, 10)