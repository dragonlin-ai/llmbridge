"""受控工具调用：把上游模型的工具请求执行后再交回模型。"""
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings


class ToolCallError(Exception):
    """工具执行的可预期失败（未注册工具 / URL 非法 / 上游非 2xx）。

    与「代码 bug」区分开：这类失败需要原样回灌给模型，让它换 URL 或改口径。
    """


#: 抓回正文的字符上限。不清洗的话，一个新闻列表页的原始 HTML 能到 120KB，
#: 实测把单次请求的 prompt 从 500 撑到 18800 token —— 成本翻 30 倍且信息密度极低。
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RE = re.compile(r"\n{3,}")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(raw: str, limit: int) -> str:
    """把 HTML 压成纯文本：去脚本样式 → 去标签 → 收敛空白 → 截断。

    只做「够模型读懂」的清洗，不引第三方解析库（避免为单个工具增加部署依赖）。
    """
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", "\n".join(line.strip() for line in text.splitlines()))
    text = text.strip()
    return text[:limit]


_TOOL_XML_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

#: 网关真正能执行的工具白名单。零命中 = 不动正文，保持纯透传语义
#: （调用方只是在讨论工具语法时，不该被网关擅自抓取 URL）。
REGISTERED_TOOLS = {"WebFetch"}


def filter_registered(calls: list[dict]) -> list[dict]:
    return [c for c in calls if (c.get("function") or {}).get("name") in REGISTERED_TOOLS]


def parse_xml_calls(content: str | None) -> list[dict]:
    """把正文里的 `<tool_call>{"name":...}</tool_call>` 还原成原生 tool_calls 结构。

    这是本项目的现实约束：部分下游模型（Qwen 系及其兼容实现）不走原生 tool_calls，
    而是把工具请求当正文吐出来，网关必须两种都认。
    """
    if not isinstance(content, str):
        return []
    calls = []
    for index, match in enumerate(_TOOL_XML_RE.finditer(content)):
        try:
            raw = json.loads(match.group(1))
            calls.append({
                "id": f"xml_call_{index}",
                "type": "function",
                "function": {
                    "name": raw.get("name", ""),
                    "arguments": json.dumps(raw.get("arguments") or {}, ensure_ascii=False),
                },
            })
        except (json.JSONDecodeError, TypeError):
            continue
    return calls


def extract_tool_calls(response: dict) -> tuple[list[dict], str | None]:
    """提取 OpenAI tool_calls 或模型吐出的 XML tool_call。"""
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    native = message.get("tool_calls") or []
    if native:
        return native, "native"

    calls = parse_xml_calls(message.get("content"))
    return calls, "xml" if calls else None


def strip_tool_xml(content: str | None) -> str | None:
    """去掉正文里的 <tool_call> 片段，只留模型真正想说的话。

    不清理的话，回传历史里会再次出现工具语法，模型会把它当成「我该继续调用」的信号，
    陷入反复调工具的循环。
    """
    if not isinstance(content, str):
        return content
    cleaned = _TOOL_XML_RE.sub("", content).strip()
    return cleaned or None


def _public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolCallError("WebFetch 只允许 http/https 公网 URL")
    host = parsed.hostname
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise ToolCallError(f"无法解析目标地址: {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolCallError("WebFetch 禁止访问本机、内网或保留地址")
    return url


async def execute_tool_call(call: dict, client: httpx.AsyncClient, timeout_ms: int) -> str:
    function = call.get("function") or {}
    name = function.get("name")
    if name not in REGISTERED_TOOLS:
        raise ToolCallError(f"未注册工具: {name or 'unknown'}")
    try:
        arguments = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        raise ToolCallError("WebFetch arguments 不是合法 JSON") from exc
    url = _public_url(str(arguments.get("url") or ""))
    try:
        response = await client.get(
            url,
            headers={"User-Agent": "llmbridge-WebFetch/1.0"},
            follow_redirects=True,
            timeout=min(timeout_ms / 1000, 15),
        )
    except httpx.HTTPError as exc:
        # 网络层失败同样是「可预期失败」：模型必须知道取不到，才能换地址。
        raise ToolCallError(f"请求失败: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise ToolCallError(f"目标返回 HTTP {response.status_code}")
    limit = get_settings().tool_result_max_chars
    text = html_to_text(response.text, limit)
    prompt = str(arguments.get("prompt") or "")
    truncated = len(response.text) > limit
    return json.dumps({"url": str(response.url), "prompt": prompt,
                       "truncated": truncated, "content": text}, ensure_ascii=False)


def append_tool_results(messages: list[dict], calls: list[dict], results: list[str]) -> None:
    for call, result in zip(calls, results):
        function = call.get("function") or {}
        messages.append({
            "role": "tool",
            "tool_call_id": call.get("id") or "tool_call",
            "name": function.get("name", ""),
            "content": result,
        })
