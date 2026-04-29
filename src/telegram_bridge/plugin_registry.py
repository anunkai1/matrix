from typing import Callable, Dict, List

try:
    from .channel_adapter import ChannelAdapter, TelegramChannelAdapter
    from .engine_adapter import ChatGPTWebEngineAdapter, CodexEngineAdapter, EngineAdapter, GemmaEngineAdapter, MavaliEthEngineAdapter, PiEngineAdapter, VeniceEngineAdapter
    from .signal_channel import SignalChannelAdapter
    from .transport import TelegramClient
    from .whatsapp_channel import WhatsAppChannelAdapter
except ImportError:
    from channel_adapter import ChannelAdapter, TelegramChannelAdapter
    from engine_adapter import ChatGPTWebEngineAdapter, CodexEngineAdapter, EngineAdapter, GemmaEngineAdapter, MavaliEthEngineAdapter, PiEngineAdapter, VeniceEngineAdapter
    from signal_channel import SignalChannelAdapter
    from transport import TelegramClient
    from whatsapp_channel import WhatsAppChannelAdapter

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
        if key == "chatgpt_web":
            key = "chatgptweb"
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
    registry.register_channel(
        "whatsapp",
        lambda config: WhatsAppChannelAdapter(config),
    )
    registry.register_channel(
        "signal",
        lambda config: SignalChannelAdapter(config),
    )
    registry.register_engine("codex", lambda: CodexEngineAdapter())
    registry.register_engine("chatgptweb", lambda: ChatGPTWebEngineAdapter())
    registry.register_engine("gemma", lambda: GemmaEngineAdapter())
    registry.register_engine("mavali_eth", lambda: MavaliEthEngineAdapter())
    registry.register_engine("pi", lambda: PiEngineAdapter())
    registry.register_engine("venice", lambda: VeniceEngineAdapter())
    return registry
