import yaml
import logging
import os
from ..core.constants import CONFIG_PATH, DEFAULT_TIMEFRAME

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, config_path: str = CONFIG_PATH):
        # Redirect config/config.yaml to config/state.yaml to separate volatile state
        # from static secret configurations and prevent accidental credentials overwriting.
        if config_path == CONFIG_PATH:
            self.config_path = 'config/state.yaml'
        else:
            self.config_path = config_path

    def _load_state(self) -> dict:
        try:
            # 1. Attempt to load from the dedicated state file
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = yaml.safe_load(f) or {}
                # Handle both {'state': {...}} and flat {...} structures
                if 'state' in data:
                    return data['state']
                return data

            # 2. Backward compatibility fallback: read state from the main config.yaml
            from ..core.constants import CONFIG_PATH as MAIN_CONFIG_PATH
            if os.path.exists(MAIN_CONFIG_PATH):
                with open(MAIN_CONFIG_PATH, 'r') as f:
                    config = yaml.safe_load(f) or {}
                return config.get('state', {})
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
        return {}

    def get_active_ticker(self) -> str:
        state = self._load_state()
        return state.get('active_ticker')

    def get_active_timeframe(self) -> str:
        state = self._load_state()
        return state.get('active_timeframe', DEFAULT_TIMEFRAME)

    async def save_state(self, ticker: str, timeframe: str):
        def _write():
            try:
                # Ensure the parent directory (e.g. config/) exists
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                state = {'active_ticker': ticker, 'active_timeframe': timeframe}
                with open(self.config_path, 'w') as f:
                    yaml.dump(state, f)
            except Exception as e:
                logger.error(f"Failed to save state: {e}")

        import asyncio
        await asyncio.to_thread(_write)

