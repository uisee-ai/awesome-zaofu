from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from playwright.sync_api import Browser, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DIRECT_OPENER = build_opener(ProxyHandler({}))


def _loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass
class LocalWebService:
    process: subprocess.Popen[bytes]
    workspace: Path
    port: int
    log_path: Path
    _log_stream: object = field(repr=False)
    _stopped: bool = False
    _suspended_workers: set[int] = field(default_factory=set, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def wait_until_ready(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                request = Request(f"{self.base_url}/api/session", method="GET")
                with DIRECT_OPENER.open(request, timeout=0.5) as response:
                    payload = json.loads(response.read())
                if (
                    payload.get("schema_version") == "scenarioforge.web-session/v1"
                    and isinstance(payload.get("csrf_token"), str)
                ):
                    return
            except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
            time.sleep(0.05)
        self.stop()
        detail = self.log_path.read_text(encoding="utf-8", errors="replace")
        raise AssertionError(
            f"local Web service did not become ready: {last_error!r}\n{detail}"
        )

    def wait_for_worker_pid(self, timeout: float = 15.0) -> int:
        tasks = Path(f"/proc/{self.process.pid}/task")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            child_pids: list[int] = []
            for children in tasks.glob("*/children"):
                try:
                    child_pids.extend(
                        int(value) for value in children.read_text().split()
                    )
                except (FileNotFoundError, ProcessLookupError):
                    continue
            live_children = [pid for pid in child_pids if Path(f"/proc/{pid}").exists()]
            if live_children:
                return live_children[0]
            time.sleep(0.01)
        raise AssertionError("real MetaDrive Worker process was never observed")

    @staticmethod
    def worker_state(worker_pid: int) -> str:
        status = Path(f"/proc/{worker_pid}/status")
        try:
            for line in status.read_text(encoding="utf-8").splitlines():
                if line.startswith("State:"):
                    return line.split()[1]
        except FileNotFoundError as error:
            raise AssertionError("real MetaDrive Worker is no longer live") from error
        raise AssertionError("real MetaDrive Worker state is unavailable")

    def suspend_worker(self, timeout: float = 5.0) -> int:
        worker_pid = self.wait_for_worker_pid()
        os.kill(worker_pid, signal.SIGSTOP)
        self._suspended_workers.add(worker_pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.worker_state(worker_pid) == "T":
                return worker_pid
            time.sleep(0.01)
        raise AssertionError("real MetaDrive Worker did not enter stopped state")

    def resume_worker(self, worker_pid: int, timeout: float = 5.0) -> None:
        try:
            os.kill(worker_pid, signal.SIGCONT)
        except ProcessLookupError:
            self._suspended_workers.discard(worker_pid)
            return
        self._suspended_workers.discard(worker_pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.worker_state(worker_pid) != "T":
                    return
            except AssertionError:
                return
            time.sleep(0.01)
        raise AssertionError("real MetaDrive Worker did not leave stopped state")

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            for worker_pid in tuple(self._suspended_workers):
                self.resume_worker(worker_pid)
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
        finally:
            self._log_stream.close()


@pytest.fixture
def service_factory(tmp_path: Path) -> Callable[..., LocalWebService]:
    services: list[LocalWebService] = []

    def create(*, timeout_seconds: int = 120) -> LocalWebService:
        workspace = tmp_path / f"service-{len(services) + 1}"
        workspace.mkdir()
        log_path = workspace / "service.log"
        log_stream = log_path.open("wb")
        port = _loopback_port()
        child_environment = dict(os.environ)
        inherited_python_path = child_environment.get("PYTHONPATH", "")
        child_environment["PYTHONPATH"] = str(ROOT / "src") + (
            os.pathsep + inherited_python_path if inherited_python_path else ""
        )
        child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scenarioforge",
                "--project-root",
                str(ROOT),
                "--workspace",
                str(workspace),
                "web",
                "--port",
                str(port),
                "--timeout-seconds",
                str(timeout_seconds),
            ],
            cwd=ROOT,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        service = LocalWebService(
            process=process,
            workspace=workspace,
            port=port,
            log_path=log_path,
            _log_stream=log_stream,
        )
        services.append(service)
        service.wait_until_ready()
        return service

    yield create

    for service in reversed(services):
        service.stop()


@pytest.fixture(scope="session")
def browser() -> Browser:
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        if not executable.is_file():
            pytest.fail(
                f"preinstalled Chromium executable is missing: {executable}",
                pytrace=False,
            )
        browser = playwright.chromium.launch(
            headless=True,
            args=["--enable-webgl", "--use-angle=swiftshader"],
        )
        yield browser
        browser.close()


def pytest_sessionstart(session: pytest.Session) -> None:
    if os.environ.get("SCENARIOFORGE_E2E_MOCK_SERVER"):
        raise pytest.UsageError("mock-only Web servers cannot satisfy tests/web")
