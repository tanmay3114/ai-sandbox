"""Consolidated API v1 router."""

from fastapi import APIRouter

from app.api.v1.sandboxes import router as sandboxes_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(sandboxes_router)
