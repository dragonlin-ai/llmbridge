"""JevDecider：TypeSafe AI System One 官方 API 实现。

API（基线 3.2-5）：POST {jev_base_url}，Bearer 鉴权，单次调用并行问 4 个问题：
task_type(Choice) / complexity(Score) / has_code(Noul) / is_sensitive(Noul)。
取值路径 answers.<qid>.choice/.probabilities/.confidence。

⚠️ 官方 API 未对中国大陆开放（安全方案 §3）：本实现仅在 judge_provider=jev
且网络可达时启用；默认 mock。枚举外 task_type 视为无效 → 返回 None。

实测口径（2026-09-21，jev-1.13.0）：
- task_type.choice 返回值落在本地 TASK_TYPES 内（criteria 传什么就回什么枚举名）；
- complexity 是 **score** 类型，返回 0~2 的类别期望值（legend {0:简单,1:中等,2:复杂}，
  score = Σ(类别索引 × 概率)），不是 1/2/3 整型类别 —— 必须 /2 归一化到 0~1；
- 单次调用延迟约 0.4~1.2s，DECIDER_TIMEOUT_MS=3000 够用；
- 失败一律记 warning 并写 ctx.fallback_reason（否则「判定器挂了」会伪装成「置信度低」）。
"""
import logging

import httpx

from app.core.config import get_settings
from app.deciders.base import TASK_TYPES, BaseDecider
from app.router_engine.context import Decision, RouterContext

logger = logging.getLogger("deciders.jev")


def _as_float(value, default: float = 0.0) -> float:
    """安全取浮点。注意 0.0 是合法取值，不能用 `or` 兜底（会把 0.0 误判为缺失）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class JevDecider(BaseDecider):
    name = "jev"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self.last_error: str | None = None

    def _build_body(self, text: str) -> dict:
        # 判定输入最小化：仅截断后的文本，不带历史与 system（安全方案 §3）
        return {
            "state": text[:1000],
            "model": "jev-latest",
            "questions": {
                "task_type": {
                    "type": "choice",
                    "instructions": "这段内容属于哪类任务？",
                    "criteria": {t: t for t in TASK_TYPES},
                },
                "complexity": {
                    "type": "score",
                    "instructions": "任务复杂度",
                    "criteria": ["简单", "中等", "复杂"],
                },
                "has_code": {"type": "noul", "instructions": "输入是否包含代码块"},
                "is_sensitive": {"type": "noul", "instructions": "是否涉及合规敏感内容"},
            },
        }

    def _mark(self, ctx: RouterContext | None, reason: str, detail: str) -> None:
        """失败必须留下可观测痕迹：否则「Jev 挂了」在外部表现为「置信度低走了 L3」。"""
        self.last_error = detail
        if ctx is not None:
            ctx.fallback_reason = reason
        logger.warning("jev decide unavailable: %s (%s)", reason, detail)

    async def decide(self, ctx: RouterContext) -> Decision | None:
        settings = get_settings()
        if not settings.jev_api_key:
            self._mark(ctx, "DECIDER_UNAVAILABLE", "JEV_API_KEY 未配置")
            return None
        client = self._client or httpx.AsyncClient(timeout=settings.decider_timeout_ms / 1000)
        try:
            resp = await client.post(
                settings.jev_base_url,
                json=self._build_body(ctx.input_text),
                headers={"Authorization": f"Bearer {settings.jev_api_key}"},
            )
            resp.raise_for_status()
            answers = resp.json().get("answers", {})
            tt = answers.get("task_type", {})
            task_type = tt.get("choice")
            if task_type not in TASK_TYPES:  # 枚举外 = 无效判定
                self._mark(ctx, "DECIDER_INVALID", f"task_type 枚举外: {task_type!r}")
                return None
            # complexity 为 score 类型：官方返回 0~2 的类别期望值
            # （legend {"0":"简单","1":"中等","2":"复杂"}，score = Σ(类别索引 × 概率)）
            # 归一化到 0~1 后入 features，与 MockDecider 口径一致。
            raw_cx = answers.get("complexity", {})
            complexity = min(1.0, max(0.0, _as_float(raw_cx.get("score")) / 2.0))
            return Decision(
                task_type=task_type,
                confidence=_as_float(tt.get("confidence")),
                probabilities={k: _as_float(v) for k, v in dict(tt.get("probabilities", {})).items()},
                features={
                    "complexity": round(complexity, 4),
                    "has_code": _as_float(answers.get("has_code", {}).get("noul")),
                    "is_sensitive": _as_float(answers.get("is_sensitive", {}).get("noul")),
                },
                decider=self.name,
            )
        except httpx.HTTPStatusError as e:  # 401/429 等：区分「key 失效」与「网络不通」
            self._mark(ctx, f"DECIDER_HTTP_{e.response.status_code}",
                       e.response.text[:200].replace("\n", " "))
            return None
        except httpx.HTTPError as e:
            self._mark(ctx, "DECIDER_UNAVAILABLE", f"{type(e).__name__}: {e}")
            return None
        except Exception as e:  # 解析异常等：不冒泡，仍按判定不可用处理
            self._mark(ctx, "DECIDER_ERROR", f"{type(e).__name__}: {e}")
            return None
        finally:
            if self._client is None:  # 自建客户端才负责关闭
                await client.aclose()

    async def health_check(self) -> bool:
        """真实探活：key 存在且 API 可达才算健康。

        仅判断 key 是否配置无法暴露「key 已失效 / 网络不可达 / 出口被拦」，
        启动时会打印 healthy=False 以便第一时间发现（调试期明确要求不用 mock）。
        """
        settings = get_settings()  # 每次读最新：库覆盖（sys_config）保存后即生效
        self.last_error = None
        if not settings.jev_api_key:
            self.last_error = "JEV_API_KEY 未配置"
            logger.warning("jev health_check: JEV_API_KEY 未配置")
            return False
        client = self._client or httpx.AsyncClient(timeout=settings.decider_timeout_ms / 1000)
        try:
            resp = await client.post(
                settings.jev_base_url,
                json=self._build_body("health check"),
                headers={"Authorization": f"Bearer {settings.jev_api_key}"},
            )
            resp.raise_for_status()
            model = resp.json().get("model")
            logger.info("jev health_check ok: model=%s", model)
            return True
        except httpx.HTTPStatusError as e:
            # 失败原因要能回传设置页（否则「不通」在界面上只有一个裸 False）
            self.last_error = "HTTP {}: {}".format(
                e.response.status_code, e.response.text[:200].replace("\n", " "))
            logger.warning("jev health_check failed: HTTP %s %s",
                           e.response.status_code, e.response.text[:200].replace("\n", " "))
            return False
        except httpx.HTTPError as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.warning("jev health_check failed: %s: %s", type(e).__name__, e)
            return False
        finally:
            if self._client is None:
                await client.aclose()
