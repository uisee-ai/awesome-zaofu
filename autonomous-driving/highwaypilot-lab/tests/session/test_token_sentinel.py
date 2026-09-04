from pathlib import Path


PRODUCTION_SOURCES = [
    Path("src/highwaypilot_lab/protocol/messages.py"),
    Path("src/highwaypilot_lab/session/core.py"),
    Path("web/src/features/session/sessionControls.ts"),
]
FORBIDDEN_TOKEN_CARRIERS = [
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "location.search",
    "URLSearchParams",
    "console.log",
    "console.debug",
    "logger.info",
    "logger.debug",
    "screenshot",
    "telemetry",
]


def test_resume_token_production_sources_have_no_persistence_logging_or_url_carrier() -> None:
    matches: list[str] = []
    for path in PRODUCTION_SOURCES:
        source = path.read_text(encoding="utf-8")
        for carrier in FORBIDDEN_TOKEN_CARRIERS:
            if carrier in source:
                matches.append(f"{path}:{carrier}")

    assert matches == []
