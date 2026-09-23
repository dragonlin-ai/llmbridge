"""控制台 /admin 路由聚合。"""
from fastapi import APIRouter

from app.api.admin.api_keys import router as api_keys_router
from app.api.admin.auth import router as auth_router
from app.api.admin.decider_settings import router as decider_settings_router
from app.api.admin.eval import router as eval_router
from app.api.admin.models import router as models_router
from app.api.admin.observe import router as observe_router
from app.api.admin.providers import router as providers_router
from app.api.admin.route_preview import router as preview_router
from app.api.admin.rules import router as rules_router
from app.api.admin.usage import router as usage_router

router = APIRouter()
for r in (auth_router, providers_router, models_router, rules_router,
          observe_router, preview_router, api_keys_router, decider_settings_router,
          eval_router, usage_router):
    router.include_router(r)
