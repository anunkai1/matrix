from __future__ import annotations

from .config import BrowserBrainConfig
from .server import BrowserBrainHTTPServer
from .service import BrowserBrainService


def main() -> None:
    config = BrowserBrainConfig.from_env()
    controller = BrowserBrainService(config)
    server = BrowserBrainHTTPServer((config.host, config.port), controller)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop({})
        server.server_close()


if __name__ == "__main__":
    main()
