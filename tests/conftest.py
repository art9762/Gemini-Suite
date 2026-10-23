"""Load the standalone applications without touching user configuration."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, source):
    spec = importlib.util.spec_from_file_location(name, ROOT / source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(monkeypatch, tmp_path):
    module = load_module("gemini_cli_test", "gemini-cli/gemini_cli.py")
    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path / "cli")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "cli/config.json")
    return module


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setenv("PROXY_API_KEY", "test-proxy-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    return load_module("gemini_proxy_test", "gemini-proxy/gemini_proxy.py")


@pytest.fixture
def mock_gemini(monkeypatch, cli):
    def install(handler):
        def client(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(cli, "httpx", SimpleNamespace(
            AsyncClient=client,
            TimeoutException=httpx.TimeoutException,
            RequestError=httpx.RequestError,
        ))
    return install
