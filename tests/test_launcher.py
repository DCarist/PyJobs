import os
import sys
from unittest.mock import patch

from run import launch_browser, main


def test_launch_browser_calls_webbrowser():
    with patch("webbrowser.open") as mock_open:
        launch_browser("http://127.0.0.1:8000", delay=0.0)
        mock_open.assert_called_once_with("http://127.0.0.1:8000")


def test_main_with_no_browser_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--no-browser"])
    monkeypatch.delenv("PYJOBS_BROWSER_OPENED", raising=False)

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("threading.Thread") as mock_thread,
    ):
        main()
        mock_uvicorn.assert_called_once_with("main:app", host="127.0.0.1", port=8000, reload=True)
        mock_thread.assert_not_called()


def test_main_spawns_browser_thread(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.delenv("PYJOBS_BROWSER_OPENED", raising=False)

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("threading.Thread") as mock_thread,
    ):
        main()
        mock_uvicorn.assert_called_once_with("main:app", host="127.0.0.1", port=8000, reload=True)
        mock_thread.assert_called_once()
        assert os.environ.get("PYJOBS_BROWSER_OPENED") == "1"
