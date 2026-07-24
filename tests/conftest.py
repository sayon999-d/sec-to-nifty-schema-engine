from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

HTML_REPORT_PATH: Path | None = None
HTML_RESULTS: list[dict[str, Any]] = []


def pytest_addoption(parser: pytest.Parser) -> None:
    try:
        parser.addoption("--html", action="store", default=None, help="Write a minimal HTML report to the given path.")
    except Exception:
        # Another plugin already registered --html; reuse that path instead.
        return


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    global HTML_REPORT_PATH, HTML_RESULTS
    html = config.getoption("--html")
    HTML_REPORT_PATH = Path(html) if html else None
    HTML_RESULTS = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call":
        HTML_RESULTS.append(
            {
                "nodeid": report.nodeid,
                "outcome": report.outcome,
                "duration": getattr(report, "duration", 0.0),
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path = HTML_REPORT_PATH
    if not path:
        return
    out = path
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"<tr><td>{item['nodeid']}</td><td>{item['outcome']}</td><td>{item['duration']:.4f}</td></tr>"
        for item in HTML_RESULTS
    )
    html = f"""
    <html>
      <head><title>Pytest Report</title></head>
      <body>
        <h1>Pytest Report</h1>
        <p>Exit status: {exitstatus}</p>
        <table border="1" cellspacing="0" cellpadding="4">
          <tr><th>Test</th><th>Outcome</th><th>Duration</th></tr>
          {rows}
        </table>
      </body>
    </html>
    """
    out.write_text(html, encoding="utf-8")
