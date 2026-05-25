from .state_manager import StateManager
from .connection_manager import ConnectionManager
from .aggregator import AggregatorService
from ..providers.ibkr_provider import IBKRProvider
from ..providers.alpaca_provider import AlpacaProvider
from ..core.constants import CONFIG_PATH, IBKR_PORT


class AppContainer:
    """Holds all singleton service instances."""
    def __init__(self):
        self.state_manager: StateManager = StateManager(CONFIG_PATH)
        self.connection_manager: ConnectionManager = ConnectionManager()
        self.aggregator: AggregatorService = AggregatorService()
        self.ibkr_provider: IBKRProvider = IBKRProvider(port=IBKR_PORT)
        self.alpaca_provider: AlpacaProvider = AlpacaProvider(config_path=CONFIG_PATH)

    def wire(self):
        """Wire up provider → aggregator dependencies."""
        self.ibkr_provider.set_aggregator(self.aggregator)
        self.alpaca_provider.set_aggregator(self.aggregator)
        self.ibkr_provider.register_callback(self.aggregator.on_tick)

    def init_indicators(self, indicators_path: str):
        import yaml
        try:
            with open(indicators_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            self.aggregator.set_indicator_config(config.get('indicators', []))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not load indicators config: {e}")


_container: AppContainer = None


def get_container() -> AppContainer:
    global _container
    if _container is None:
        _container = AppContainer()
        _container.wire()
    return _container
