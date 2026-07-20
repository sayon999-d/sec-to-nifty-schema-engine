from __future__ import annotations

from pathlib import Path
import sys

try:
    import streamlit as st
except Exception:  
    st = None  

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _set_page_config() -> None:
    if st is None:
        return
    st.set_page_config(
        page_title="Nifty 100 Analytics",
        layout="wide",
        initial_sidebar_state="expanded",
        page_icon="📈",
    )


def _sidebar_nav() -> None:
    if st is None:
        return
    st.sidebar.title("Nifty 100 Analytics")
    st.sidebar.caption("Sprint 4 Dashboard Scaffold")
    pages = [
        "01_home.py",
        "02_profile.py",
        "03_screener.py",
        "04_peers.py",
        "05_trends.py",
        "06_sectors.py",
        "07_capital.py",
        "08_reports.py",
    ]
    for page in pages:
        st.sidebar.page_link(f"pages/{page}", label=page.replace(".py", "").replace("_", " ").title())


def main() -> None:
    _set_page_config()
    _sidebar_nav()
    if st is None:
        return
    st.title("Nifty 100 Financial Intelligence Platform")
    st.write(
        "Sprint 4 introduces the Streamlit dashboard scaffold, valuation engine, and data-access utilities "
        "for interactive financial analytics."
    )
    st.info("Use the sidebar to open the analytic pages.")


if __name__ == "__main__":
    main()
