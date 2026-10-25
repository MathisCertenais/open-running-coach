#!/usr/bin/env python3
"""Desktop launcher for Coach Running.

Starts the local server on a free port, opens the default browser, and keeps
running until you stop it (Ctrl+C). This is also the PyInstaller entry point.
"""

from __future__ import annotations

import socket
import threading
import webbrowser

import uvicorn

from app.main import app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Coach Running is available at {url}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
