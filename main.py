"""Launch ExecScreen in the default browser."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from threading import Timer

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from execscreen.config import load_dotenv_if_present


def main() -> None:
    import uvicorn
    import webbrowser

    load_dotenv_if_present()
    host = os.environ.get("EXECSCREEN_HOST", "127.0.0.1")
    port = int(os.environ.get("EXECSCREEN_PORT", "8000"))
    url = f"http://{host}:{port}/"

    def open_browser() -> None:
        if not webbrowser.open(url):
            print(f"Could not open a browser automatically. Open this URL: {url}")

    print(f"ExecScreen is running at {url} (press Ctrl+C to stop).")
    timer = Timer(1.0, open_browser)
    timer.daemon = True
    timer.start()
    uvicorn.run("execscreen.app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
