import os
import sys
import threading
import time
import webbrowser

import uvicorn


def launch_browser(url: str, delay: float = 1.0) -> None:
    """Waits briefly for the server to bind before opening the default browser."""
    time.sleep(delay)
    webbrowser.open(url)


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"

    # Only trigger browser launch once in the parent process to avoid opening tabs on reload
    if not os.environ.get("PYJOBS_BROWSER_OPENED") and "--no-browser" not in sys.argv:
        os.environ["PYJOBS_BROWSER_OPENED"] = "1"
        threading.Thread(target=launch_browser, args=(url,), daemon=True).start()

    uvicorn.run("main:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()
