"""Streamlit interface for the fictional, local-first Portfolio Radar workspace."""

from __future__ import annotations

import hmac
import os
import time
from datetime import datetime
from typing import Any

import streamlit as st

import server

SESSION_LIFETIME_SECONDS = 12 * 60 * 60


def configured_secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except FileNotFoundError:
        value = ""
    return str(value or os.getenv(name, "")).strip()


def configure_provider_secrets() -> None:
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        value = configured_secret(name)
        if value:
            os.environ[name] = value


def save_note(company_id: str, text: str) -> None:
    clean_text = text.strip()
    seed = server.load_json(server.SEED_PATH)
    company = next((row for row in seed["companies"] if row["id"] == company_id), None)
    if company is None:
        raise ValueError("Choose a valid company for this note.")
    if not clean_text or len(clean_text) > 2_000:
        raise ValueError("Note must contain 1–2000 characters.")

    with server.STATE_LOCK:
        state = server.load_state()
        state["notes"].append(
            {
                "id": f"note-{int(datetime.now().timestamp() * 1000)}",
                "companyId": company_id,
                "companyName": company["name"],
                "text": clean_text,
                "createdAt": server.utc_now(),
            }
        )
        server.save_state(state)


def toggle_watchlist(company_id: str) -> bool:
    seed = server.load_json(server.SEED_PATH)
    valid_ids = {row["id"] for row in seed["companies"]}
    if company_id not in valid_ids:
        raise ValueError("Choose a valid company.")

    with server.STATE_LOCK:
        state = server.load_state()
        if company_id in state["watchlist"]:
            state["watchlist"].remove(company_id)
            saved = False
        else:
            state["watchlist"].append(company_id)
            saved = True
        server.save_state(state)
    return saved


def save_research_run(company: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    run = {
        "id": f"research-{int(datetime.now().timestamp() * 1000)}",
        "companyId": company["id"],
        "companyName": company["name"],
        "ticker": company["ticker"],
        "provider": "OpenAI API",
        "model": result["model"],
        "createdAt": server.utc_now(),
        "scope": "Analysis of supplied fictional tracker data only; no external sources were searched.",
        "report": result["report"],
    }
    with server.STATE_LOCK:
        state = server.load_state()
        state["researchRuns"].append(run)
        server.save_state(state)
    return run


def navigate_to_tracker(company_id: str) -> None:
    company = next(
        (row for row in server.load_json(server.SEED_PATH)["companies"] if row["id"] == company_id),
        None,
    )
    if company is None:
        raise ValueError("Choose a valid company.")
    st.session_state["selected_company"] = company_id
    st.session_state["tracker-company"] = company["name"]
    st.session_state["page"] = "Company trackers"


def display_evidence(company: dict[str, Any]) -> None:
    for item in company["evidence"]:
        with st.container(border=True):
            st.markdown(f"**{item['type']} · fictional seed**")
            st.write(item["text"])
            st.caption(f"{item['source']} · {item['timestamp']}")


def display_report(run: dict[str, Any]) -> None:
    report = run["report"]
    st.caption(
        f"{run['provider']} · {run['model']} · {run['createdAt']} · "
        "Analysis of supplied fictional tracker data only; no external sources searched."
    )
    st.markdown("**Facts (from supplied data)**")
    if report["facts"]:
        for fact in report["facts"]:
            st.write(f"- {fact['statement']} — Source: {fact.get('source', 'Unavailable')}")
    else:
        st.write("No facts returned.")
    for title, key in (
        ("Assumptions", "assumptions"),
        ("Risks", "risks"),
        ("Open questions", "openQuestions"),
    ):
        st.markdown(f"**{title}**")
        if report[key]:
            for item in report[key]:
                st.write(f"- {item}")
        else:
            st.write("None returned.")
    st.markdown("**Interpretation**")
    st.write(report["interpretation"])


def render_login(password: str) -> None:
    if not password:
        st.error(
            "Portfolio Radar requires a password in this Streamlit app. "
            "Configure PORTFOLIO_RADAR_PASSWORD in Streamlit secrets or the local environment."
        )
        return
    if len(password) < 12:
        st.error("PORTFOLIO_RADAR_PASSWORD must contain at least 12 characters.")
        return

    st.title("Sign in to Portfolio Radar")
    st.caption("Private workspace · Fictional seed data · No trading")
    with st.form("login"):
        supplied = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8")):
            st.session_state["authenticated"] = True
            st.session_state["authenticated_until"] = time.time() + SESSION_LIFETIME_SECONDS
            st.rerun()
        st.error("Incorrect password.")


def render_dashboard(payload: dict[str, Any]) -> None:
    dashboard = payload["dashboard"]
    monitoring = payload["monitoring"]
    companies = {company["id"]: company for company in payload["companies"]}
    st.title("Overview")
    st.caption("A calm view of what needs attention across your coverage.")
    st.warning(
        "Fictional seed data. Companies, metrics, events, evidence and findings are invented. "
        "No live market or broker data is connected. No trades are placed."
    )

    columns = st.columns(4)
    columns[0].metric("Priority items", dashboard["priorityCount"])
    columns[1].metric("Data freshness", "Sample only")
    columns[2].metric("Coverage", len(payload["companies"]))
    columns[3].metric("Monitoring", "Enabled" if monitoring["enabled"] else "Paused")

    left, right = st.columns(2)
    with left:
        st.subheader("Priority queue")
        for item in dashboard["priorities"]:
            company = companies[item["companyId"]]
            with st.container(border=True):
                st.markdown(f"**{item['label']}** · {company['ticker']}")
                st.caption(f"{company['name']} · {item['detail']}")
                st.button(
                    "Open tracker",
                    key=f"priority-{company['id']}",
                    on_click=navigate_to_tracker,
                    args=(company["id"],),
                )

    with right:
        st.subheader("Upcoming events")
        st.caption("Sample calendar · verify dates independently")
        for event in payload["events"]:
            with st.container(border=True):
                st.markdown(f"**{event['date']} · {event['title']}**")
                st.write(event["detail"])
                st.caption(event["kind"])

    st.subheader("Monitoring status")
    st.caption("Opt-in · saved watchlist only · 09:00 local time")
    status = monitoring["status"].replace("_", " ").title()
    st.write(f"**Status:** {status}")
    st.write(f"**Next scheduled run:** {monitoring['nextRunAt'] or 'Not scheduled'}")
    st.write(f"**Last completed:** {monitoring['lastCompletedAt'] or 'Never'}")
    st.caption(
        "When explicitly enabled, the local scheduler sends saved-watchlist tracker data to OpenAI. "
        "It does not search external sources. The app makes no provider calls by default."
    )
    if monitoring["lastError"]:
        st.error(monitoring["lastError"])
    if monitoring["lastOutcomes"]:
        st.write("Latest outcomes")
        st.dataframe(monitoring["lastOutcomes"], hide_index=True, width="stretch")

    if not payload["integrations"]["openai"]["configured"]:
        st.info("OpenAI is not configured. Add OPENAI_API_KEY in Streamlit secrets to enable manual or scheduled analysis.")
    else:
        col_enable, col_run = st.columns(2)
        if monitoring["enabled"]:
            if col_enable.button("Pause daily monitoring"):
                server.monitoring_scheduler.disable()
                st.rerun()
        else:
            consent = col_enable.checkbox(
                "I understand this sends saved-watchlist tracker data to OpenAI.",
                key="monitoring-consent",
            )
            if col_enable.button("Enable daily monitoring", disabled=not consent):
                try:
                    server.monitoring_scheduler.enable()
                    server.monitoring_scheduler.start()
                except RuntimeError as error:
                    st.error(str(error))
                else:
                    st.rerun()
        run_consent = col_run.checkbox(
            "I understand this runs analysis for every saved-watchlist company.",
            key="monitoring-run-consent",
        )
        if col_run.button("Run watchlist now", disabled=not run_consent):
            try:
                server.monitoring_scheduler.run_now()
            except RuntimeError as error:
                st.error(str(error))
            else:
                st.success("Watchlist analysis started. Refresh the page to see its status.")
    if monitoring["enabled"]:
        server.monitoring_scheduler.start()


def render_discovery(payload: dict[str, Any]) -> None:
    st.title("Discovery")
    st.caption("Searchable sample findings with expandable evidence. All findings are fictional.")
    query = st.text_input("Search findings", placeholder="Company, ticker, or keyword")
    categories = ["All"] + sorted({item["category"] for item in payload["discoveries"]})
    category = st.selectbox("Category", categories)
    companies = {company["id"]: company for company in payload["companies"]}
    matching = [
        item
        for item in payload["discoveries"]
        if (category == "All" or item["category"] == category)
        and query.casefold()
        in " ".join(
            (item["finding"], item["category"], companies[item["companyId"]]["name"], item["companyId"])
        ).casefold()
    ]
    if not matching:
        st.info("No sample findings match those filters.")
    for index, item in enumerate(matching):
        company = companies[item["companyId"]]
        with st.container(border=True):
            st.markdown(f"### {company['name']} · {item['category']}")
            st.write(item["finding"])
            st.caption(f"{company['ticker']} · Confidence: {item['confidence']} · Fictional seed finding")
            with st.expander("Evidence and provenance"):
                display_evidence(company)
            st.button(
                "Open company tracker",
                key=f"discovery-{index}-{company['id']}",
                on_click=navigate_to_tracker,
                args=(company["id"],),
            )


def render_trackers(payload: dict[str, Any]) -> None:
    st.title("Company trackers")
    companies = payload["companies"]
    names = {company["name"]: company["id"] for company in companies}
    selected_id = st.session_state.get("selected_company", companies[0]["id"])
    selected = next((item for item in companies if item["id"] == selected_id), companies[0])
    selected_name = st.selectbox(
        "Company",
        list(names),
        index=list(names).index(selected["name"]),
        key="tracker-company",
    )
    company = next(item for item in companies if item["id"] == names[selected_name])
    st.session_state["selected_company"] = company["id"]
    st.subheader(f"{company['name']} · {company['ticker']}")
    st.caption(f"{company['sector']} · Fictional tracker · Signal: {company['signal']}")

    is_saved = company["id"] in payload["watchlist"]
    if st.button("Remove from watchlist" if is_saved else "Add to watchlist", key=f"tracker-watch-{company['id']}"):
        toggle_watchlist(company["id"])
        st.rerun()

    left, right = st.columns([2, 1])
    with left:
        st.markdown("#### Investment thesis")
        st.write(company["thesis"])
        st.markdown("#### Key metrics · sample values only")
        st.dataframe(company["metrics"], hide_index=True, width="stretch")
        st.markdown("#### Evidence trail")
        display_evidence(company)
    with right:
        st.markdown("#### Risks & open questions")
        for risk in company["risks"]:
            st.write(f"- {risk}")
        st.markdown("#### History of changes")
        for change in company["history"]:
            st.write(f"**{change['date']} · {change['by']}**")
            st.write(change["change"])
        st.markdown("#### Research provenance")
        st.write(f"Sample tracker status · {company['status']}")
        st.write("Provider · Local fictional seed")
        st.write("Monitoring · " + ("Enabled" if payload["monitoring"]["enabled"] else "Disabled"))

    openai_configured = payload["integrations"]["openai"]["configured"]
    consent = st.checkbox(
        "I understand the selected tracker data will be sent to OpenAI; no notes or external sources are included.",
        key=f"research-consent-{company['id']}",
        disabled=not openai_configured,
    )
    if st.button("Run OpenAI analysis", disabled=not openai_configured or not consent):
        try:
            result = server.ResearchAgent().run(company)
            save_research_run(company, result)
        except (RuntimeError, OSError, ValueError) as error:
            st.error(f"Research run failed: {error}")
        else:
            st.success("Analysis completed. It reflects only supplied fictional tracker data.")
            st.rerun()

    runs = [run for run in payload["researchRuns"] if run["companyId"] == company["id"]]
    if runs:
        st.markdown("#### Analysis history · not independently verified")
        for run in runs:
            with st.expander(f"{run['createdAt']} · {run['provider']} · {run['model']}"):
                display_report(run)


def render_notes(payload: dict[str, Any]) -> None:
    st.title("Notes & watchlists")
    st.caption("Saved locally in the app state file. Avoid confidential personal or financial information.")
    company_by_id = {company["id"]: company for company in payload["companies"]}

    st.subheader("Watchlist")
    for company in payload["companies"]:
        saved = company["id"] in payload["watchlist"]
        col_company, col_toggle = st.columns([3, 1])
        col_company.write(f"**{company['ticker']} · {company['name']}**")
        if col_toggle.button("Remove" if saved else "Add", key=f"watchlist-{company['id']}"):
            toggle_watchlist(company["id"])
            st.rerun()

    st.subheader("Add a note")
    with st.form("new-note", clear_on_submit=True):
        names = {company["name"]: company["id"] for company in payload["companies"]}
        company_name = st.selectbox("Company", list(names))
        note_text = st.text_area("Note", max_chars=2_000)
        submitted = st.form_submit_button("Save note", type="primary")
    if submitted:
        try:
            save_note(names[company_name], note_text)
        except (OSError, ValueError) as error:
            st.error(str(error))
        else:
            st.success("Note saved.")
            st.rerun()

    st.subheader("Saved notes")
    if not payload["notes"]:
        st.info("No saved notes yet.")
    for note in payload["notes"]:
        company = company_by_id.get(note["companyId"])
        with st.container(border=True):
            st.markdown(f"**{note['companyName']}** · {note['createdAt']}")
            st.write(note["text"])
            if company:
                st.button(
                    "Open tracker",
                    key=f"note-{note['id']}",
                    on_click=navigate_to_tracker,
                    args=(company["id"],),
                )


def render_templates(payload: dict[str, Any]) -> None:
    st.title("Review templates")
    st.caption("Consistent structures for discovery, earnings, deterioration and weekly reviews.")
    templates = payload["templates"]
    template_names = {item["name"]: item for item in templates}
    selected_name = st.selectbox("Template", list(template_names))
    template = template_names[selected_name]
    st.subheader(template["name"])
    st.write(template["description"])
    for section in template["sections"]:
        st.markdown(f"- {section}")
    st.info("Use each section as a prompt for research; record facts separately from assumptions and interpretation.")


def main() -> None:
    st.set_page_config(page_title="Portfolio Radar · Private research", page_icon="📡", layout="wide")
    st.markdown(
        """
        <style>
        .stApp { background: #f5f7f5; }
        [data-testid="stSidebar"] { background: #fbfcfb; }
        .block-container { max-width: 1440px; padding-top: 2rem; }
        div[data-testid="stMetric"] { background: white; border: 1px solid #e3e9e3; padding: 1rem; border-radius: 14px; }
        div[data-testid="stAlert"] { border-radius: 12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    configure_provider_secrets()
    password = configured_secret("PORTFOLIO_RADAR_PASSWORD")
    authenticated = st.session_state.get("authenticated", False)
    if authenticated and st.session_state.get("authenticated_until", 0) <= time.time():
        st.session_state["authenticated"] = False
        st.session_state.pop("authenticated_until", None)
        authenticated = False
    if not authenticated:
        render_login(password)
        return

    payload = server.api_payload()
    if payload["monitoring"]["enabled"]:
        server.monitoring_scheduler.start()
    st.sidebar.title("📡 radar")
    st.sidebar.caption("PRIVATE RESEARCH")
    pages = ["Overview", "Discovery", "Company trackers", "Notes & watchlists", "Review templates"]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = pages[0]
    page = st.sidebar.radio("Workspace", pages, key="page")
    st.sidebar.caption("Fictional seed data · No trading")
    if st.sidebar.button("Sign out"):
        st.session_state["authenticated"] = False
        st.session_state.pop("authenticated_until", None)
        st.rerun()
    st.caption(f"Workspace / {page} · FICTIONAL SEED DATA")

    if page == "Overview":
        render_dashboard(payload)
    elif page == "Discovery":
        render_discovery(payload)
    elif page == "Company trackers":
        render_trackers(payload)
    elif page == "Notes & watchlists":
        render_notes(payload)
    else:
        render_templates(payload)


if __name__ == "__main__":
    main()
