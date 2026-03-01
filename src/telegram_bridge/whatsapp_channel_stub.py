class WhatsAppChannelStubAdapter:
    channel_name = "whatsapp"

    def __init__(self, _config) -> None:
        raise RuntimeError(
            "Channel plugin 'whatsapp' is currently a stub and not runtime-enabled."
        )
