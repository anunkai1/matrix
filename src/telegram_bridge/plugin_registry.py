from typing import Callable, Dict, List

try:
    from .channel_adapter import ChannelAdapter, TelegramChannelAdapter
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .transport import TelegramClient
except ImportError:
    from channel_adapter import ChannelAdapter, TelegramChannelAdapter
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from transport import TelegramClient

ChannelFactory = Callable[[object], ChannelAdapter]
EngineFactory = Callable[[], EngineAdapter]


class PluginRegistry:
    def __init__(self) -> None:
        self._channel_factories: Dict[str, ChannelFactory] = {}
        self._engine_factories: Dict[str, EngineFactory] = {}

    def register_channel(self, name: str, factory: ChannelFactory) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("Channel plugin name cannot be empty")
        self._channel_factories[key] = factory

    def register_engine(self, name: str, factory: EngineFactory) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("Engine plugin name cannot be empty")
        self._engine_factories[key] = factory

    def build_channel(self, name: str, config) -> ChannelAdapter:
        key = name.strip().lower()
        factory = self._channel_factories.get(key)
        if factory is None:
            raise KeyError(f"Unknown channel plugin: {name}")
        return factory(config)

    def build_engine(self, name: str) -> EngineAdapter:
        key = name.strip().lower()
        factory = self._engine_factories.get(key)
        if factory is None:
            raise KeyError(f"Unknown engine plugin: {name}")
        return factory()

    def list_channels(self) -> List[str]:
        return sorted(self._channel_factories.keys())

    def list_engines(self) -> List[str]:
        return sorted(self._engine_factories.keys())


def build_default_plugin_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register_channel(
        "telegram",
        lambda config: TelegramChannelAdapter(TelegramClient(config)),
    )
    registry.register_engine("codex", lambda: CodexEngineAdapter())
    return registry
