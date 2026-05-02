from fastapi import APIRouter

from .health import router as health_router
from .sample import router as sample_router
from .races import router as races_router
from .external import router as external_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(sample_router, tags=["sample"])
api_router.include_router(races_router, tags=["races"])
api_router.include_router(external_router, tags=["external"])
