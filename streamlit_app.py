"""Streamlit interface for the fictional, local-first Portfolio Radar workspace."""

from __future__ import annotations

import hmac
import os
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

import streamlit as st

import server
from ibkr_provider import IBKRConnectionError

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


def save_open_research_run(query: str, result: dict[str, Any]) -> dict[str, Any]:
    run = {
        "id": f"research-{int(datetime.now().timestamp() * 1000)}",
        "kind": "web_research",
        "query": query.strip(),
        "provider": "OpenAI API · web search",
        "model": result["model"],
        "createdAt": server.utc_now(),
        "scope": "Question sent to OpenAI; web search enabled. Not connected to ChatGPT history.",
        "report": result["report"],
        "sources": result["sources"],
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
        f"{run['provider']} · {run['model']} · {run['createdAt']} · {run.get('scope', 'Supplied data only; no external sources searched.')}"
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


def display_open_research_run(run: dict[str, Any]) -> None:
    st.caption(f"{run['provider']} · {run['model']} · {run['createdAt']} · {run['scope']}")
    st.markdown(f"**Research question:** {run['query']}")

    st.markdown(link_research_citations(run["report"]["text"], run.get("sources", [])))

    sources = run.get("sources", [])
    if sources:
        st.markdown("**Sources**")
        for index, source in enumerate(sources, start=1):
            if source.get("url", "").startswith("https://"):
                st.link_button(
                    f"{index}. {source.get('title') or source['url']}",
                    source["url"],
                    key=f"research-source-{run['id']}-{index}",
                )


def link_research_citations(report_text: str, sources: list[dict[str, Any]]) -> str:
    linked_text = report_text
    ordered_sources = sorted(
        sources,
        key=lambda item: item.get("startIndex")
        if isinstance(item.get("startIndex"), int)
        else -1,
        reverse=True,
    )
    for source in ordered_sources:
        start = source.get("startIndex")
        end = source.get("endIndex")
        url = source.get("url", "")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(linked_text)
            or not url.startswith("https://")
        ):
            continue
        cited_text = linked_text[start:end].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        encoded_url = quote(url, safe=":/?#@!$&'()*+,;=%")
        linked_text = (
            linked_text[:start]
            + f"[{cited_text}](<{encoded_url}>)"
            + linked_text[end:]
        )
    return linked_text


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
    st.caption("A research desk for monitoring coverage and reviewing real account data.")
    st.warning(
        "The sample companies, findings, priorities, events and evidence below remain fictional. "
        "Use the read-only IBKR panel to fetch your actual holdings and available market data. No trades are placed."
    )

    columns = st.columns(4)
    columns[0].metric("Seed priorities", dashboard["priorityCount"])
    columns[1].metric("Research data", "Fictional")
    columns[2].metric("Sample trackers", len(payload["companies"]))
    columns[3].metric("Monitor", "On" if monitoring["enabled"] else "Paused")

    render_ibkr_portfolio()

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


def render_research_desk(payload: dict[str, Any]) -> None:
    st.title("Research desk")
    st.caption(
        "Ask research questions from this dashboard. Portfolio Radar calls the OpenAI API directly; "
        "it does not access ChatGPT conversations or plugins."
    )
    st.info(
        "Web search is enabled for each run. Your question is sent to OpenAI, which may send search "
        "queries to the web. Reports are saved in this app with clickable citations and a retrieval timestamp."
    )
    configured = payload["integrations"]["openai"]["configured"]
    if not configured:
        st.warning(
            "OpenAI is not configured. Add OPENAI_API_KEY using the app's local environment or deployment secrets. "
            "A ChatGPT subscription does not include API access."
        )

    with st.form("open-research-form"):
        query = st.text_area(
            "What should Portfolio Radar research?",
            max_chars=2_000,
            height=120,
            placeholder="Example: Recent earnings, guidance changes, and major risks for a company or sector",
        )
        consent = st.checkbox(
            "I consent to sending this question to OpenAI and enabling web search for this run.",
            disabled=not configured,
        )
        submitted = st.form_submit_button(
            "Research with OpenAI",
            type="primary",
            disabled=not configured,
        )
    if submitted:
        if not consent:
            st.error("Confirm the data-sharing notice before starting a research run.")
        else:
            try:
                result = server.ResearchAgent().run_research(query)
                save_open_research_run(query, result)
            except (RuntimeError, OSError, ValueError) as error:
                st.error(f"Research run failed: {error}")
            else:
                st.success("Research completed and saved to this workspace.")
                st.rerun()

    runs = [run for run in payload["researchRuns"] if run.get("kind") == "web_research"]
    st.subheader("Research history")
    if not runs:
        st.caption("No dashboard research runs yet.")
    for run in runs:
        with st.expander(f"{run['createdAt']} · {run['query'][:90]}"):
            display_open_research_run(run)


def render_ibkr_portfolio() -> None:
    st.subheader("Interactive Brokers · read-only account data")
    st.caption(
        "Fetch holdings, snapshot quotes and available ReportSnapshot fundamentals on demand. "
        "Data is shown in this session only. Quotes may be delayed or unavailable depending on your IBKR subscriptions."
    )
    st.info(
        "IBKR access works only when Portfolio Radar runs on the same computer as TWS or IB Gateway. "
        "The hosted Streamlit Cloud app cannot connect to a gateway on your computer."
    )
    if st.button("Fetch IBKR holdings and market data", key="fetch-ibkr"):
        try:
            positions = server.BrokerDataProvider().get_positions()
        except (IBKRConnectionError, OSError, RuntimeError, ValueError) as error:
            st.error(f"IBKR data request failed: {error}")
        else:
            st.session_state["ibkr_snapshot"] = {
                "positions": positions,
                "retrievedAt": server.utc_now(),
            }

    snapshot = st.session_state.get("ibkr_snapshot")
    if snapshot is None:
        return
    positions = snapshot["positions"]
    st.caption(f"IBKR TWS API · retrieved {snapshot['retrievedAt']} · account identifiers are not displayed.")
    if not positions:
        st.info("IBKR connected successfully; no open positions were returned.")
        return

    rows = []
    for position in positions:
        rows.append(
            {
                "Symbol": position["symbol"],
                "Type": position["securityType"],
                "Quantity": position["quantity"],
                "Average cost": position["averageCost"],
                "Market price": position["marketPrice"],
                "Market value": position["marketValue"],
                "Unrealized P/L": position["unrealizedPnl"],
                "Currency": position["currency"],
                "Quote": position["quoteType"] or position["marketDataType"],
                "P/E": position["fundamentals"].get("P/E"),
                "P/B": position["fundamentals"].get("Price/book"),
                "P/S": position["fundamentals"].get("Price/sales"),
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")

    for position in positions:
        issues = []
        if position["quoteError"]:
            issues.append(f"Quote: {position['quoteError']}")
        elif position["securityType"] == "STK" and position["marketPrice"] is None:
            issues.append("No quote was returned; check market-data permissions or delayed-data settings in TWS.")
        if position["fundamentalsError"]:
            issues.append(f"Fundamentals: {position['fundamentalsError']}")
        elif position["securityType"] == "STK" and not position["fundamentals"]:
            issues.append(
                "No supported fundamental ratios were returned; IBKR permissions and report availability vary."
            )
        if issues:
            st.caption(f"{position['symbol']} · " + " ".join(issues))

    with st.expander("Fundamental metrics returned by IBKR"):
        for position in positions:
            if position["fundamentals"]:
                st.write(f"**{position['symbol']} · {position['currency']}**")
                st.json(position["fundamentals"])
        st.caption(
            "Only P/E, market capitalization, price/book, price/sales, return on equity, gross margin "
            "and dividend yield are extracted when IBKR supplies them. Fundamentals are not guaranteed."
        )

    st.markdown("#### Optional OpenAI analysis of one holding")
    if not server.ProviderConfiguration.openai_configured():
        st.info(
            "OpenAI is not configured. Add OPENAI_API_KEY through local environment variables or Streamlit secrets. "
            "A ChatGPT subscription does not include API access."
        )
        return

    selected_index = st.selectbox(
        "Position",
        range(len(positions)),
        format_func=lambda row_index: (
            f"{positions[row_index]['symbol']} · {positions[row_index]['securityType']} · "
            f"{positions[row_index]['currency']}"
        ),
        key="ibkr-analysis-position",
    )
    selected_position = positions[selected_index]
    position_key = (
        f"{selected_position['symbol']}-{selected_position['securityType']}-"
        f"{selected_position['exchange']}-{selected_index}"
    )
    consent = st.checkbox(
        "I consent to sending only this holding's quantity, cost, quote and available fundamentals to OpenAI. "
        "No account ID, other holdings or notes are sent.",
        key=f"ibkr-analysis-consent-{position_key}",
    )
    if st.button(
        "Analyze selected holding with OpenAI",
        disabled=not consent,
        key=f"ibkr-analysis-run-{position_key}",
    ):
        try:
            result = server.ResearchAgent().run_position(selected_position)
        except (RuntimeError, OSError, ValueError) as error:
            st.error(f"OpenAI analysis failed: {error}")
        else:
            reports = st.session_state.setdefault("ibkr_ai_reports", {})
            reports[position_key] = {
                "provider": "OpenAI API",
                "model": result["model"],
                "createdAt": server.utc_now(),
                "scope": (
                    "Selected IBKR position snapshot only; sent by explicit consent. "
                    "No account ID, notes, other holdings or external sources included."
                ),
                "report": result["report"],
            }
    report = st.session_state.get("ibkr_ai_reports", {}).get(position_key)
    if report:
        with st.expander(f"Analysis · {report['createdAt']} · {report['model']}", expanded=True):
            display_report(report)
            st.caption("AI-generated interpretation of supplied data only; not independently verified or financial advice.")


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
        :root {
            color-scheme: dark;
            --radar-bg: #071510;
            --radar-panel: #0e2119;
            --radar-panel-raised: #132a20;
            --radar-line: #244436;
            --radar-text: #e5f3eb;
            --radar-muted: #a8c0b2;
            --radar-green: #68e0a4;
            --radar-amber: #f3c66c;
        }
        html, body, .stApp {
            background: var(--radar-bg);
            color: var(--radar-text);
        }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 91% 7%, rgba(34, 113, 75, .18), transparent 25rem),
                linear-gradient(rgba(68, 133, 99, .045) 1px, transparent 1px),
                linear-gradient(90deg, rgba(68, 133, 99, .045) 1px, transparent 1px),
                var(--radar-bg);
            background-size: auto, 36px 36px, 36px 36px, auto;
        }
        [data-testid="stSidebar"] {
            background: #091a13;
            border-right: 1px solid var(--radar-line);
        }
        [data-testid="stSidebar"] > div:first-child { background: transparent; }
        .block-container { max-width: 1440px; padding-top: 2rem; }
        h1, h2, h3, h4, h5, h6, p, li, label, [data-testid="stMarkdownContainer"] {
            color: var(--radar-text);
        }
        h1, h2 { letter-spacing: -.035em; }
        [data-testid="stCaptionContainer"], [data-testid="stMetricLabel"],
        [data-testid="stWidgetLabel"] p, small {
            color: var(--radar-muted) !important;
        }
        [data-testid="stSidebar"] h1 { margin-bottom: .15rem; }
        .radar-brand {
            display: flex;
            align-items: center;
            gap: .7rem;
            margin: .25rem 0 1.25rem;
            color: var(--radar-text);
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: -.06em;
        }
        .radar-brand small {
            display: block;
            margin-top: .12rem;
            color: var(--radar-muted);
            font-size: .55rem;
            font-weight: 600;
            letter-spacing: .16em;
        }
        .radar-icon {
            position: relative;
            display: grid;
            width: 2.45rem;
            height: 2.45rem;
            place-items: center;
            overflow: hidden;
            border: 1px solid rgba(104, 224, 164, .65);
            border-radius: 50%;
            background:
                radial-gradient(circle, transparent 29%, rgba(104,224,164,.35) 30%, transparent 32%,
                    transparent 59%, rgba(104,224,164,.35) 60%, transparent 62%),
                linear-gradient(90deg, transparent 49.5%, rgba(104,224,164,.3) 50%, transparent 50.5%),
                linear-gradient(transparent 49.5%, rgba(104,224,164,.3) 50%, transparent 50.5%),
                #10281d;
            box-shadow: 0 0 18px rgba(65, 212, 139, .12);
        }
        .radar-icon::after {
            position: absolute;
            inset: 0;
            border-radius: inherit;
            background: conic-gradient(from 0deg, transparent 0 76%, rgba(104,224,164,.42));
            content: "";
            animation: radar-sweep 5s linear infinite;
        }
        .radar-icon i {
            z-index: 1;
            width: .32rem;
            height: .32rem;
            border-radius: 50%;
            background: var(--radar-green);
            box-shadow: 0 0 9px var(--radar-green);
        }
        @keyframes radar-sweep { to { transform: rotate(360deg); } }
        div[data-testid="stMetric"] {
            border: 1px solid var(--radar-line);
            border-top: 2px solid rgba(104, 224, 164, .7);
            border-radius: 12px;
            background: linear-gradient(145deg, rgba(19,42,32,.96), rgba(11,29,21,.96));
            padding: 1rem;
            box-shadow: 0 10px 28px rgba(0,0,0,.16);
        }
        [data-testid="stMetricValue"] {
            color: var(--radar-green);
            font-size: 1.25rem !important;
            line-height: 1.2;
        }
        [data-testid="stMetricValue"] p {
            font-size: inherit !important;
            white-space: normal;
        }
        [data-testid="stMetricLabel"] p {
            font-size: .68rem !important;
            line-height: 1.2;
            white-space: normal;
        }
        [data-testid="stAlert"] {
            border: 1px solid rgba(243,198,108,.35);
            border-radius: 12px;
            background: rgba(105,76,27,.2);
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--radar-line);
            background: rgba(14,33,25,.75);
        }
        [data-baseweb="select"] > div, [data-baseweb="input"] > div,
        [data-baseweb="textarea"] > div {
            border-color: var(--radar-line);
            background: var(--radar-panel);
        }
        [data-testid="stDataFrame"] { border: 1px solid var(--radar-line); border-radius: 10px; }
        button[kind="secondary"] {
            border-color: var(--radar-line);
            background: var(--radar-panel-raised);
            color: var(--radar-text);
        }
        button[kind="secondary"]:hover {
            border-color: var(--radar-green);
            color: var(--radar-green);
        }
        @media (prefers-reduced-motion: reduce) {
            .radar-icon::after { animation: none; }
        }
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
    st.sidebar.markdown(
        '<div class="radar-brand"><span class="radar-icon"><i></i></span>'
        '<span>radar<small>PRIVATE RESEARCH</small></span></div>',
        unsafe_allow_html=True,
    )
    pages = [
        "Overview",
        "Research desk",
        "Discovery",
        "Company trackers",
        "Notes & watchlists",
        "Review templates",
    ]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = pages[0]
    page = st.sidebar.radio("Workspace", pages, key="page")
    st.sidebar.caption("Fictional seed data · No trading")
    if st.sidebar.button("Sign out"):
        st.session_state["authenticated"] = False
        st.session_state.pop("authenticated_until", None)
        st.rerun()
    st.caption(f"Workspace / {page} · Seed examples are fictional · Live research is labelled by source")

    if page == "Overview":
        render_dashboard(payload)
    elif page == "Research desk":
        render_research_desk(payload)
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
