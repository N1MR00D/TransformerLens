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
    cfg = HookedTransformerConfig(1, 10, 1, 1, act_fn="relu", d_vocab=50256)
    model2 = HookedTransformer(cfg)
    original_tokenizer = model2.tokenizer
    assert original_tokenizer is None, "initialize without tokenizer"
    model2.set_tokenizer(AutoTokenizer.from_pretrained("gpt2"))
    tokenizer = model2.tokenizer
    assert tokenizer is not None and tokenizer.name_or_path == "gpt2", "set tokenizer"
    assert model2.to_single_token(" SolidGoldMagicarp") == 15831, "glitch token"


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


def test_correct_tokenization():
    # fmt: off
    assert model.to_tokens([my_test_string, "hello"], padding_side="right", prepend_bos=True).tolist() == torch.LongTensor(
        [[    1,     5,   826,   311, 29229,  2063,   282,  1056, 10391,  1296, 
           188,   188,  1510, 29229,    65,  3578,    65,    19,    10,  3457,
            19,    14,  2167,    20,  2192,   477,  1800,   826,   311, 29229,
          2063,   282,  1056, 10391,  1296,   477,   603,  2167,    19,  2170,
          2167,    20,    28,   647,   324,   883,   276,  2413,    10,  3457,
            19,  2192,   926,  1800,   826,   311, 29229,  2063,   282,  1056,
         10391,  1296,   926,  1205,  2167,    20,   653,   883,    28,  1003,
          2167,    20,  6892,   338,   210,  1800,   826,   311, 29229,  2063,
           282,  1056, 10391,  1296,  1003,  1574,    28,  2498,  1800,   826,
           311, 29229,  2063,   282,  1056, 10391,  1296,  2498,  2167,    19,
           426,  2167,    20,  1209,   883,  1003,  3584, 25449, 14765,  1273,
          4608,    28,  2498,  1800,   826,   311, 29229,  2063,   282,  1056,
         10391,  1296,  2498,  3270,  1551, 40271, 10673,   407,  4907,  2719,
          1003,  4574,    28,  2498,  1800,   826,   311, 29229,  2063,   282,
          1056, 10391,  1296,  2498,  3270,  1551, 15194,   319,   985,   883,
            11,   188,   188,  1510, 29229,    65,  3578,    65,    20, 14439,
           477,  1800,   826,   311, 29229,  2063,   282,  1056, 10391,  1296,
           477,   343,  1493,  2012, 40501,    16,  9867,  1358,   684,    89,
          3291,   348,  1819,    28,   647,  1800,   826,   311, 29229,  2063,
           282,  1056, 10391,  1296,   647,  1819,    16,  6171,  1551,  1516,
           311, 29229,  2063,   282,  1056, 10391,  1296,   188,  2719,   188,
           188,     5,   826,   311, 29229,  2063,   282,  1056, 10391,  1296,
           188, 40501,    65,  3434,   426,   543, 40501,    65,  3578,    65,
            19,    14, 29229,    65,  3578,    65,    20,    63,   188,   188,
          1507, 29229,   276, 29229,    65,  3434,    28,   477,  1800,   826,
           311, 29229,  2063,   282,  1056, 10391,  1296,   477,   603,  1052,
           494,    10, 40501,  2192,   647,  1800,   826,   311, 29229,  2063,
           282,  1056, 10391,  1296,   647, 29229,    10,    19,    18,    14,
           607,    11,   210,  1800,  7189,   436,  3175,   311,  3469,   324,
           512, 29229,  3357,   188,   188,     5,   826,   311, 29229,  2063,
           282,  1056, 10391,  1296],
        [    1, 24684,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2,     2,     2,     2,     2,     2,     2,
             2,     2,     2,     2]]).tolist()
    # fmt: on


# # Code used to generate the correct tokenization: (Using transformer-lens 1.6.1, built from source to ensure poetry select exact versions)
# tokens = model.to_tokens([my_test_string, "hello"], padding_side="right", prepend_bos=True)
# print(tokens)
