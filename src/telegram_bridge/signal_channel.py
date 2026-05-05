from telegram_bridge.http_channel import HttpBridgeChannelAdapter

class SignalChannelAdapter(HttpBridgeChannelAdapter):
    channel_name = "signal"
    supports_message_edits = False

    def __init__(self, config) -> None:
        super().__init__(
            config,
            channel_name="signal",
            enabled_attr="signal_plugin_enabled",
            api_base_attr="signal_bridge_api_base",
            auth_token_attr="signal_bridge_auth_token",
            timeout_attr="signal_poll_timeout_seconds",
            display_name="Signal",
            supports_message_edits=False,
        )
