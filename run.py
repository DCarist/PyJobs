import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn


def get_local_ip() -> str:
    """Detects the primary local area network (LAN) IPv4 address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def launch_browser(url: str, delay: float = 1.0) -> None:
    """Waits briefly for the server to bind before opening the default browser."""
    time.sleep(delay)
    webbrowser.open(url)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PyJobs - Intelligent Job Curation & Application Tracker"
    )
    parser.add_argument(
        "--network",
        "--lan",
        action="store_true",
        help="Enable local network access for other machines on LAN (binds to 0.0.0.0)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Custom IP address/interface to bind (default: 127.0.0.1, or 0.0.0.0 if --network)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the web browser on launch",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reloading",
    )
    return parser.parse_args(args)


def main() -> None:
    opts = parse_args(sys.argv[1:])

    if opts.network:
        host = opts.host or "0.0.0.0"
    else:
        host = opts.host or "127.0.0.1"

    port = opts.port
    local_ip = get_local_ip()

    if host == "0.0.0.0":
        print("\n" + "=" * 60)
        print("             PyJobs Local Network Server")
        print("=" * 60)
        print(f"  * Local machine:  http://localhost:{port}")
        print(f"  * Local IP:       http://127.0.0.1:{port}")
        print(f"  * LAN Network:    http://{local_ip}:{port}")
        print("-" * 60)
        print("  Connect any device on the same local Wi-Fi or LAN.")
        print("  Press Ctrl+C in this terminal to stop the server.")
        print("=" * 60 + "\n")
    else:
        print(f"\nPyJobs server running locally on http://{host}:{port}\n")

    browser_url = f"http://localhost:{port}" if host == "0.0.0.0" else f"http://{host}:{port}"

    # Only trigger browser launch once in the parent process to avoid opening tabs on reload
    if not os.environ.get("PYJOBS_BROWSER_OPENED") and not opts.no_browser:
        os.environ["PYJOBS_BROWSER_OPENED"] = "1"
        threading.Thread(target=launch_browser, args=(browser_url,), daemon=True).start()

    uvicorn.run("main:app", host=host, port=port, reload=not opts.no_reload)


if __name__ == "__main__":
    main()
