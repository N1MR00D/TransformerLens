import pytest
import torch
from torch import Size, equal, tensor
from transformers import AutoTokenizer

from transformer_lens import HookedTransformer, HookedTransformerConfig

model = HookedTransformer.from_pretrained("solu-1l")


def test_set_tokenizer_during_initialization():
    assert (
        model.tokenizer is not None
        and model.tokenizer.name_or_path == "ArthurConmy/alternative-neel-tokenizer"
    ), "initialized with expected tokenizer"
    assert model.cfg.d_vocab == 48262, "expected d_vocab"


def test_set_tokenizer_lazy():
    cfg = HookedTransformerConfig(
        n_layers=1, d_model=10, n_ctx=1024, d_head=1, act_fn="relu", d_vocab=50256
    )
    model2 = HookedTransformer(cfg)
    original_tokenizer = model2.tokenizer
    assert original_tokenizer is None, "initialize without tokenizer"
    model2.set_tokenizer(AutoTokenizer.from_pretrained("gpt2"))
    tokenizer = model2.tokenizer
    assert tokenizer is not None and tokenizer.name_or_path == "gpt2", "set tokenizer"
    assert (
        model2.to_single_token(" SolidGoldMagikarp") == 43453
    ), "Glitch token didn't tokenize properly"
    assert (
        model2.to_string([43453]) == " SolidGoldMagikarp"
    ), "Glitch token didn't detokenize properly"


def test_to_tokens_default():
    s = "Hello, world!"
    tokens = model.to_tokens(s)
    assert equal(
        tokens, tensor([[1, 11765, 14, 1499, 3]]).to(model.cfg.device)
    ), "creates a tensor of tokens with BOS"


def test_to_tokens_without_bos():
    s = "Hello, world!"
    tokens = model.to_tokens(s, prepend_bos=False)
    assert equal(
        tokens, tensor([[11765, 14, 1499, 3]]).to(model.cfg.device)
    ), "creates a tensor without BOS"


@pytest.mark.skipif(
    torch.cuda.is_available() or torch.backends.mps.is_available(),
    reason="Test not relevant when running on GPU",
)
def test_to_tokens_device():
    s = "Hello, world!"
    tokens1 = model.to_tokens(s, move_to_device=False)
    tokens2 = model.to_tokens(s, move_to_device=True)
    assert equal(
        tokens1, tokens2
    ), "move to device has no effect when running tests on CPU"


def test_to_tokens_truncate():
    assert model.cfg.n_ctx == 1024, "verify assumed context length"
    s = "@ " * 1025
    tokens1 = model.to_tokens(s)
    tokens2 = model.to_tokens(s, truncate=False)
    assert len(tokens1[0]) == 1024, "truncated by default"
    assert len(tokens2[0]) == 1027, "not truncated"


def test_to_string_from_to_tokens_without_bos():
    s = "Hello, world!"
    tokens = model.to_tokens(s, prepend_bos=False)
    s2 = model.to_string(tokens[0])
    assert s == s2, "same string when converted back to string"


def test_to_string_multiple():
    s_list = model.to_string(tensor([[1, 11765], [43453, 28666]]))
    assert s_list == [
        "<|BOS|>Hello",
        "Charlie Planet",
    ], "can handle list of lists"


def test_to_str_tokens_default():
    s_list = model.to_str_tokens(" SolidGoldMagikarp")
    assert s_list == [
        "<|BOS|>",
        " Solid",
        "Gold",
        "Mag",
        "ik",
        "arp",
    ], "not a glitch token"


def test_to_str_tokens_without_bos():
    s_list = model.to_str_tokens(" SolidGoldMagikarp", prepend_bos=False)
    assert s_list == [
        " Solid",
        "Gold",
        "Mag",
        "ik",
        "arp",
    ], "without BOS"


def test_to_single_token():
    token = model.to_single_token("biomolecules")
    assert token == 31847, "single token"


def test_to_single_str_tokent():
    s = model.to_single_str_token(31847)
    assert s == "biomolecules"


def test_get_token_position_not_found():
    single = "biomolecules"
    input = "There were some biomolecules"
    with pytest.raises(AssertionError) as exc_info:
        model.get_token_position(single, input)
    assert (
        str(exc_info.value) == "The token does not occur in the prompt"
    ), "assertion error"


def test_get_token_position_str():
    single = " some"
    input = "There were some biomolecules"
    pos = model.get_token_position(single, input)
    assert pos == 3, "first position"


def test_get_token_position_str_without_bos():
    single = " some"
    input = "There were some biomolecules"
    pos = model.get_token_position(single, input, prepend_bos=False)
    assert pos == 2, "without BOS"


def test_get_token_position_int_pos():
    single = 2
    input = tensor([2.0, 3, 4])
    pos1 = model.get_token_position(single, input)
    pos2 = model.get_token_position(single, input, prepend_bos=False)
    assert pos1 == 0, "first position"
    assert pos2 == 0, "no effect from BOS when using tensor as input"


def test_get_token_position_int_pos_last():
    single = 2
    input = tensor([2.0, 3, 4, 2, 5])
    pos1 = model.get_token_position(single, input, mode="last")
    assert pos1 == 3, "last position"


def test_get_token_position_int_1_pos():
    single = 2
    input = tensor([[2.0, 3, 4]])
    pos = model.get_token_position(single, input)
    assert pos == 0, "first position"


def test_tokens_to_residual_directions():
    res_dir = model.tokens_to_residual_directions(model.to_tokens(""))
    assert res_dir.shape == Size([512]), ""


my_test_string = """# This is placeholder code to test tokenization

def placeholder_function_1(param1, param2):
    # This is placeholder code to test tokenization
    if param1 > param2:
        for i in range(param1):
            # This is placeholder code to test tokenization
            while param2 < i:
                param2 += 1  # This is placeholder code to test tokenization
                try:
                    # This is placeholder code to test tokenization
                    param1 = param2 / i
                except ZeroDivisionError:
                    # This is placeholder code to test tokenization
                    print("Cannot divide by zero")
                finally:
                    # This is placeholder code to test tokenization
                    print("Iteration", i)

def placeholder_function_2():
    # This is placeholder code to test tokenization
    with open('placeholder.txt', 'w') as file:
        # This is placeholder code to test tokenization
        file.write("This is placeholder code to test tokenization\n")

# This is placeholder code to test tokenization
placeholder_list = [placeholder_function_1, placeholder_function_2]

for placeholder in placeholder_list:
    # This is placeholder code to test tokenization
    if callable(placeholder):
        # This is placeholder code to test tokenization
        placeholder(10, 5)  # assuming this input is valid for all placeholder functions

# This is placeholder code to test tokenization"""


def test_correct_tokenization(snapshot):
    # Assuming model and my_test_string are defined and accessible
    token_output = model.to_tokens(
        [my_test_string, "hello"], padding_side="right", prepend_bos=True
    ).tolist()
    snapshot.assert_match(token_output)
