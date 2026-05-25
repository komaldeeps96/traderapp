import yaml
import logging
from .constants import CONFIG_PATH, INDICATORS_CONFIG_PATH

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load YAML from {path}: {e}")
        return {}


def save_yaml(path: str, data: dict):
    try:
        with open(path, 'w') as f:
            yaml.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save YAML to {path}: {e}")
