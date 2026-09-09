import os
import sys
from unittest.mock import MagicMock, patch

from run import get_local_ip, launch_browser, main, parse_args


def test_launch_browser_calls_webbrowser():
    with patch("webbrowser.open") as mock_open:
        launch_browser("http://127.0.0.1:8000", delay=0.0)
        mock_open.assert_called_once_with("http://127.0.0.1:8000")


def test_get_local_ip_success():
    mock_sock = MagicMock()
    mock_sock.getsockname.return_value = ("192.168.1.123", 12345)
    with patch("socket.socket", return_value=mock_sock):
        ip = get_local_ip()
        assert ip == "192.168.1.123"
        mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))
        mock_sock.close.assert_called_once()


def test_get_local_ip_fallback():
    mock_sock = MagicMock()
    mock_sock.connect.side_effect = OSError("No network route")
    with (
        patch("socket.socket", return_value=mock_sock),
        patch("socket.gethostname", side_effect=OSError("Hostname lookup failed")),
    ):
        ip = get_local_ip()
        assert ip == "127.0.0.1"


def test_parse_args_defaults():
    opts = parse_args([])
    assert opts.network is False
    assert opts.host is None
    assert opts.port == 8000
    assert opts.no_browser is False
    assert opts.no_reload is False


def test_parse_args_network():
    opts = parse_args(["--network", "--port", "8080", "--no-reload"])
    assert opts.network is True
    assert opts.port == 8080
    assert opts.no_reload is True


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


def test_main_with_network_flag(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run.py", "--network", "--no-browser"])
    monkeypatch.delenv("PYJOBS_BROWSER_OPENED", raising=False)

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("run.get_local_ip", return_value="192.168.1.99"),
    ):
        main()
        mock_uvicorn.assert_called_once_with("main:app", host="0.0.0.0", port=8000, reload=True)
        captured = capsys.readouterr()
        assert "PyJobs Local Network Server" in captured.out
        assert "http://192.168.1.99:8000" in captured.out


def test_main_with_custom_host_and_port(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["run.py", "--host", "10.0.0.5", "--port", "9090", "--no-browser"]
    )
    monkeypatch.delenv("PYJOBS_BROWSER_OPENED", raising=False)

    with patch("uvicorn.run") as mock_uvicorn:
        main()
        mock_uvicorn.assert_called_once_with("main:app", host="10.0.0.5", port=9090, reload=True)
