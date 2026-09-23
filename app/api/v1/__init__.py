"""对外 /v1 路由聚合。"""
from fastapi import APIRouter

from app.api.v1.chat import router as chat_router

router = APIRouter()
router.include_router(chat_router)
