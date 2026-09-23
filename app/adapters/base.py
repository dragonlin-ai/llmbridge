"""BaseAdapter：厂商适配器抽象。

基线 3.11 边界约定：协议与流式格式差异只允许出现在 app/adapters/ 内，
不得上溢至 router_engine 与 api 层。适配器内部禁止 import db——
模型与凭据由调用方以参数传入。
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx


class UpstreamError(Exception):
    """上游调用失败（429/超时/5xx）。pipeline 据此按 priority 降级。"""

    def __init__(self, model_name: str, detail: str = ""):
        self.model_name = model_name
        super().__init__(f"upstream {model_name} failed: {detail}")


class BaseAdapter(ABC):
    """每家厂商（或每种协议族）一个实现。"""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        payload: dict,
        timeout_ms: int,
        client: httpx.AsyncClient,
    ) -> dict:
        """非流式对话。返回 OpenAI 兼容响应体。失败抛 UpstreamError。"""

    @abstractmethod
    async def chat_stream(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        payload: dict,
        timeout_ms: int,
        client: httpx.AsyncClient,
    ) -> AsyncIterator[bytes]:
        """流式对话。逐段产出 SSE 字节（含 data: 前缀）。失败抛 UpstreamError。

        实现必须在 finally 中正确释放上游连接（代码审查 C-03）。
        """
