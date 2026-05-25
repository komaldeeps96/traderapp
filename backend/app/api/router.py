from fastapi import APIRouter
from .endpoints.config_routes import router as config_router

api_router = APIRouter()
api_router.include_router(config_router)
