"""OpenAI 兼容协议适配器（MVP 唯一必需实现）。

DeepSeek / OpenAI / Moonshot / Qwen 兼容模式 / 本地 vLLM 等均走此实现。
差异（如鉴权头形态、流式空行约定）全部收敛在本文件内。
"""
import json
from typing import AsyncIterator

import httpx

from app.adapters.base import BaseAdapter, UpstreamError


class OpenAICompatAdapter(BaseAdapter):
    name = "openai_compat"

    async def chat(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        payload: dict,
        timeout_ms: int,
        client: httpx.AsyncClient,
    ) -> dict:
        body = {**payload, "model": model_name, "stream": False}
        try:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout_ms / 1000,
            )
            if resp.status_code >= 400:
                # 带上游错误体摘要：仅有「HTTP 400」无法区分「模型名不存在」与「key 无权限」，
                # 试跑台的诊断价值依赖这行 detail。
                raise UpstreamError(model_name, f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        except httpx.HTTPError as e:
            raise UpstreamError(model_name, repr(e)) from e

    async def chat_stream(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        payload: dict,
        timeout_ms: int,
        client: httpx.AsyncClient,
    ) -> AsyncIterator[bytes]:
        body = {**payload, "model": model_name, "stream": True}
        req = client.build_request(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_ms / 1000,
        )
        resp = await client.send(req, stream=True)
        if resp.status_code >= 400:
            detail = (await resp.aread()).decode("utf-8", "replace")[:300]
            await resp.aclose()
            raise UpstreamError(model_name, f"HTTP {resp.status_code}: {detail}")
        try:
            buffer = b""
            async for chunk in resp.aiter_bytes():
                buffer += chunk
                # 按 SSE 事件边界切分，残包留 buffer（粘包处理，代码审查关注点）
                while b"\n\n" in buffer:
                    event, buffer = buffer.split(b"\n\n", 1)
                    for line in event.splitlines():
                        if line.strip():
                            yield line + b"\n"
                    yield b"\n"
            if buffer.strip():  # 冲洗残余
                yield buffer
                yield b"\n\n"
            yield b"data: [DONE]\n\n"
        except httpx.HTTPError as e:
            raise UpstreamError(model_name, repr(e)) from e
        finally:
            await resp.aclose()  # C-03：任何路径都释放上游连接
