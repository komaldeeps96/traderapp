import yaml
import logging
from fastapi import APIRouter

from ...core.constants import INDICATORS_CONFIG_PATH
from ...services.container import get_container

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/active-ticker")
async def get_active_ticker():
    container = get_container()
    ticker = container.state_manager.get_active_ticker()
    return {"active_ticker": ticker}


@router.get("/api/active-timeframe")
async def get_active_timeframe():
    container = get_container()
    tf = container.state_manager.get_active_timeframe()
    return {"active_timeframe": tf}


@router.get("/api/indicators")
async def get_indicators():
    try:
        with open(INDICATORS_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f) or {}
        return config.get('indicators', [])
    except Exception as e:
        logger.error(f"Failed to read indicators config: {e}")
        return []
