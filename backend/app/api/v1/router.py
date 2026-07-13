from fastapi import APIRouter

from app.api.v1.endpoints import auth, jobs

# health.router is mounted separately, unversioned, at the app root (see main.py) —
# it's not included here to avoid also serving it under /api/v1.
api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(jobs.router)
