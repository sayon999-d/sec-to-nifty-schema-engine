from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

try:
    import streamlit as st
except Exception:  
    st = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dashboard.utils.db import get_companies, get_documents


def _company_labels() -> dict[str, str]:
    companies = get_companies()
    if companies.empty:
        return {}
    id_col = "id" if "id" in companies.columns else companies.columns[0]
    name_col = "company_name" if "company_name" in companies.columns else companies.columns[-1]
    ticker_col = "ticker" if "ticker" in companies.columns else None
    mapping: dict[str, str] = {}
    for _, row in companies.iterrows():
        ticker = str(row.get(ticker_col, "")).strip() if ticker_col else ""
        company_name = str(row.get(name_col, "")).strip()
        if not ticker:
            continue
        label = f"{company_name} ({ticker})"
        mapping[label] = ticker
    return mapping


def _safe_link(url: str | None) -> str:
    if not url or not str(url).strip():
        return ""
    url = str(url).strip()
    if "404" in url:
        return ""
    return url


def main() -> None:
    if st is None:
        return

    st.title("Reports")

    labels = _company_labels()
    if not labels:
        st.warning("No companies available.")
        return

    selected_label = st.selectbox("Company", list(labels.keys()), key="reports_company")
    ticker = labels[selected_label]

    documents = get_documents(ticker)
    if documents.empty:
        st.error("Report unavailable")
        st.caption("No document records were found for the selected company.")
        return

    documents = documents.copy()
    if "document_date" in documents.columns:
        documents["document_year"] = pd.to_numeric(documents["document_date"].astype(str).str[:4], errors="coerce")
    elif "created_at" in documents.columns:
        documents["document_year"] = pd.to_datetime(documents["created_at"], errors="coerce").dt.year
    else:
        documents["document_year"] = pd.NA

    year_options = (
        documents["document_year"]
        .dropna()
        .astype(int)
        .sort_values(ascending=False)
        .unique()
        .tolist()
    )
    selected_year = st.selectbox("Report year", year_options, key="reports_year") if year_options else None

    if selected_year is not None:
        documents = documents.loc[documents["document_year"].astype("Int64") == int(selected_year)].copy()

    if documents.empty:
        st.error("Report unavailable")
        st.caption("There is no document for the selected year.")
        return

    rows: list[dict[str, str]] = []
    for _, row in documents.iterrows():
        doc_url = _safe_link(row.get("document_url") or row.get("source_url"))
        doc_year = row.get("document_year")
        if doc_url:
            rows.append(
                {
                    "Year": str(int(doc_year)) if pd.notna(doc_year) else "N/A",
                    "Document Type": str(row.get("document_type", "N/A")),
                    "Title": str(row.get("document_title", "N/A")),
                    "Link": doc_url,
                    "Status": "Report available",
                }
            )
        else:
            rows.append(
                {
                    "Year": str(int(doc_year)) if pd.notna(doc_year) else "N/A",
                    "Document Type": str(row.get("document_type", "N/A")),
                    "Title": str(row.get("document_title", "N/A")),
                    "Link": "",
                    "Status": "Report unavailable",
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        st.error("Report unavailable")
        return

    st.caption(f"Selected ticker: {ticker}")

    for _, record in frame.iterrows():
        if record["Status"] == "Report available":
            st.success(f"{record['Year']} - {record['Document Type']} - {record['Title']}")
            st.markdown(f"[Open report]({record['Link']})")
        else:
            st.error(f"{record['Year']} - {record['Document Type']} - {record['Title']} - Report unavailable")

    st.dataframe(frame[["Year", "Document Type", "Title", "Status"]], use_container_width=True)


if __name__ == "__main__":
    main()
