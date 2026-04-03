import os

import requests

from src.tools.akshare_api import _disable_proxy_temporarily


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
