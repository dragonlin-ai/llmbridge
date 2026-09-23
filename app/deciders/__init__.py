"""判定器工厂：按配置选择实现，保留切换位（BaseDecider 抽象的意义所在）。"""
from app.core.config import get_settings
from app.deciders.base import BaseDecider
from app.deciders.mock_decider import MockDecider


def build_decider() -> BaseDecider:
    settings = get_settings()
    if settings.judge_provider == "jev" and settings.jev_api_key:
        # 延迟导入：未配置 jev 时不触发其依赖
        from app.deciders.jev_decider import JevDecider

        return JevDecider()
    return MockDecider()
