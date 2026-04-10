from types import SimpleNamespace

from src.utils import ollama


class _ConfirmStub:
    def __init__(self, answers: list[bool]):
        self._answers = iter(answers)

    def __call__(self, *args, **kwargs):
        return SimpleNamespace(ask=lambda: next(self._answers))


class _FakeStdout:
    def __init__(self, lines: list[str]):
        self._lines = iter(lines)
        self.exhausted = False

    def readline(self):
        line = next(self._lines, "")
        if line == "":
            self.exhausted = True
        return line


class _FakeDownloadProcess:
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = _FakeStdout(lines)
        self._returncode = returncode
        self._done = False

    def poll(self):
        return self._returncode if self._done or self.stdout.exhausted else None

    def wait(self):
        self._done = True
        return self._returncode


def test_install_ollama_darwin_download_flow_succeeds(monkeypatch, capsys):
    opened_urls: list[str] = []

    monkeypatch.setattr(ollama.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ollama.questionary, "confirm", _ConfirmStub([True, True]))
    monkeypatch.setitem(__import__("sys").modules, "webbrowser", SimpleNamespace(open=lambda url: opened_urls.append(url)))
    monkeypatch.setattr(ollama, "is_ollama_installed", lambda: True)
    monkeypatch.setattr(ollama, "start_ollama_server", lambda: True)

    assert ollama.install_ollama() is True
    assert opened_urls == [ollama.OLLAMA_DOWNLOAD_URL["darwin"]]
    stdout = capsys.readouterr().out
    assert "Please download and install the application" in stdout
    assert "Ollama is now properly installed and running!" in stdout


def test_install_ollama_reports_unsupported_os(monkeypatch, capsys):
    monkeypatch.setattr(ollama.platform, "system", lambda: "FreeBSD")

    assert ollama.install_ollama() is False
    stdout = capsys.readouterr().out
    assert "Unsupported operating system for automatic installation" in stdout
    assert "Please visit https://ollama.com/download" in stdout


def test_ensure_ollama_and_model_delegates_remote_workflow(monkeypatch):
    calls: list[tuple[str, str]] = []

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setattr(ollama.docker, "ensure_ollama_and_model", lambda model_name, ollama_url: calls.append((model_name, ollama_url)) or True)

    assert ollama.ensure_ollama_and_model("llama3") is True
    assert calls == [("llama3", "http://ollama:11434")]


def test_ensure_ollama_and_model_runs_local_install_and_download_flow(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(ollama, "is_ollama_installed", lambda: False)
    monkeypatch.setattr(ollama, "is_ollama_server_running", lambda: False)
    monkeypatch.setattr(ollama, "install_ollama", lambda: True)
    monkeypatch.setattr(ollama, "start_ollama_server", lambda: True)
    monkeypatch.setattr(ollama, "get_locally_available_models", lambda: [])
    monkeypatch.setattr(ollama, "download_model", lambda model_name: model_name == "llama3")
    monkeypatch.setattr(ollama.questionary, "confirm", _ConfirmStub([True, True]))

    assert ollama.ensure_ollama_and_model("llama3") is True
    stdout = capsys.readouterr().out
    assert "Ollama is not installed on your system." in stdout
    assert "Starting Ollama server..." in stdout
    assert "Model llama3 is not available locally." in stdout


def test_download_model_renders_progress_and_succeeds(monkeypatch, capsys):
    monkeypatch.setattr(ollama, "is_ollama_server_running", lambda: True)
    monkeypatch.setattr(
        ollama.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeDownloadProcess(
            [
                "pulling manifest: 10%\n",
                "downloading: 55.5%\n",
                "",
            ]
        ),
    )

    assert ollama.download_model("llama3") is True
    stdout = capsys.readouterr().out
    assert "Downloading model llama3..." in stdout
    assert "Download progress:" in stdout
    assert "Model llama3 downloaded successfully!" in stdout
