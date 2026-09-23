"""MockDecider：无外部依赖的确定性判定器。

用途：开发/离线/私有化默认（安全方案 R-03：生产模板默认 mock）。
算法：关键词词表打分 → softmax 归一 → confidence=最高概率。
与 JevDecider 输出同构（契约测试 C-11）。
"""
import math
import re

from app.deciders.base import BaseDecider
from app.router_engine.context import Decision, RouterContext

# 简易词表：task_type → 特征词（中文/英文/代码特征）
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "code_generation": ("代码", "函数", "python", "def ", "java", "javascript", "sql", "bug", "调试", "算法", "class "),
    "translation": ("翻译", "translate", "英文", "中文", "译成"),
    "summarize": ("总结", "摘要", "概括", "summarize", "要点"),
    "complex_reasoning": ("为什么", "推理", "分析", "证明", "推导", "策略"),
}


class MockDecider(BaseDecider):
    name = "mock"

    async def decide(self, ctx: RouterContext) -> Decision | None:
        text = ctx.input_text.lower()
        scores: dict[str, float] = {t: 0.0 for t in _KEYWORDS}
        scores["general"] = 0.6  # 基础分

        has_code = 0.0
        if re.search(r"```|def |class |;|\{|\}|=>", ctx.input_text):
            has_code = 0.85
            scores["code_generation"] += 2.0
        for task, words in _KEYWORDS.items():
            for w in words:
                if w in text:
                    scores[task] += 1.5

        # softmax 归一
        m = max(scores.values())
        exps = {k: math.exp(v - m) for k, v in scores.items()}
        total = sum(exps.values())
        probs = {k: round(v / total, 4) for k, v in exps.items()}
        top_type = max(probs, key=probs.get)  # type: ignore[arg-type]
        confidence = probs[top_type]

        # 复杂度：粗略按长度与问句特征
        complexity = 0.2 if ctx.token_len < 100 else (0.6 if ctx.token_len < 1000 else 0.9)

        return Decision(
            task_type=top_type,
            confidence=confidence,
            probabilities=probs,
            features={
                "complexity": complexity,
                "has_code": has_code,
                "is_sensitive": 0.05 if re.search(r"密码|身份证|银行卡", text) else 0.01,
            },
            decider=self.name,
        )

    async def health_check(self) -> bool:
        return True
