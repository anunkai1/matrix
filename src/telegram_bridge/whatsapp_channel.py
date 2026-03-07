try:
    from .http_channel import HttpBridgeChannelAdapter
except ImportError:
    from http_channel import HttpBridgeChannelAdapter


class WhatsAppChannelAdapter(HttpBridgeChannelAdapter):
    channel_name = "whatsapp"
    supports_message_edits = True

    def __init__(self, config) -> None:
        super().__init__(
            config,
            channel_name="whatsapp",
            enabled_attr="whatsapp_plugin_enabled",
            api_base_attr="whatsapp_bridge_api_base",
            auth_token_attr="whatsapp_bridge_auth_token",
            timeout_attr="whatsapp_poll_timeout_seconds",
            display_name="WhatsApp",
            supports_message_edits=True,
        )
