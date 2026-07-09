import os
import threading

import requests

from src.tools.akshare_api import _disable_proxy_temporarily
from src.tools.akshare_runtime_helpers import run_without_system_proxies


def test_disable_proxy_temporarily_does_not_patch_requests_methods(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example")
    original_get = requests.get
    original_post = requests.post
    original_request = requests.request

    @_disable_proxy_temporarily()
    def decorated():
        assert requests.get is original_get
        assert requests.post is original_post
        assert requests.request is original_request
        assert "HTTP_PROXY" not in os.environ

    decorated()

    assert requests.get is original_get
    assert requests.post is original_post
    assert requests.request is original_request
    assert os.environ["HTTP_PROXY"] == "http://proxy.example"


def test_disable_proxy_temporarily_holds_proxy_state_for_full_call(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example")
    observed = []
    first_entered = threading.Event()
    second_entered = threading.Event()
    first_finished = threading.Event()

    @_disable_proxy_temporarily()
    def first_call():
        first_entered.set()
        second_entered.wait(0.2)
        observed.append(os.environ.get("HTTP_PROXY"))

    @_disable_proxy_temporarily()
    def second_call():
        second_entered.set()
        first_finished.wait(1)
        observed.append(os.environ.get("HTTP_PROXY"))

    first_thread = threading.Thread(target=first_call)
    second_thread = threading.Thread(target=second_call)

    first_thread.start()
    assert first_entered.wait(1)
    second_thread.start()
    first_thread.join(1)
    assert not first_thread.is_alive()

    first_finished.set()
    second_thread.join(1)
    assert not second_thread.is_alive()

    assert observed == [None, None]


def test_run_without_system_proxies_bypasses_requests_system_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy.example")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(
        requests.utils,
        "getproxies",
        lambda: {"https": "http://system-proxy.example"},
    )
    observed = {}

    def _fetch():
        observed["NO_PROXY"] = os.environ.get("NO_PROXY")
        observed["no_proxy"] = os.environ.get("no_proxy")
        observed["proxies"] = requests.utils.get_environ_proxies("https://push2his.eastmoney.com")

    run_without_system_proxies(_fetch)

    assert observed == {
        "NO_PROXY": "*",
        "no_proxy": "*",
        "proxies": {},
    }
    assert os.environ["HTTPS_PROXY"] == "http://env-proxy.example"
    assert "NO_PROXY" not in os.environ
    assert "no_proxy" not in os.environ
