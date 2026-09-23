"""成本核算：token 用量 → 元。单价单位：元/百万 token。"""


def calc_cost(model_input_price: float, model_output_price: float,
              prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens / 1_000_000 * model_input_price
        + completion_tokens / 1_000_000 * model_output_price,
        6,
    )


def estimate_tokens(text: str) -> int:
    """粗估：中英混合按字符数/2.5（已知问题 K-03，阈值校准见测试计划 §七）。"""
    return max(1, int(len(text) / 2.5))
