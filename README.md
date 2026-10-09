# Portfolio Radar

A private investment research workspace using clearly labelled fictional seed data. The Streamlit interface is the recommended way to run and deploy the app. The original dependency-free HTTP interface remains available with `python server.py` at <http://127.0.0.1:8000>.

## Run the Streamlit app locally

Install the interface dependency and start the app:

```powershell
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

The Streamlit app requires `PORTFOLIO_RADAR_PASSWORD` (at least 12 characters) from the environment or Streamlit secrets. In PowerShell, set it in the same terminal session before running Streamlit:

```powershell
$env:PORTFOLIO_RADAR_PASSWORD = "use-a-unique-password-here"
streamlit run streamlit_app.py
```

Do not put real passwords or API keys in source control or chat. Locally saved notes and watchlists are stored in `data/user_state.json`.

## What works

- Monitoring dashboard with sample priorities, data freshness, upcoming events, coverage and monitoring status.
- On-demand, read-only IBKR positions with TWS/IB Gateway snapshot quotes and available fundamental ratios when run locally.
- Search and category filters for discovery cards, with expandable evidence trails.
- Company trackers with theses, sample metrics, risks, evidence provenance and change history.
- Consistent discovery, earnings, deterioration and weekly-review outlines.
- Local notes and watchlist toggles persisted in `data/user_state.json`.
- Responsive desktop/mobile interface with a high-contrast dark radar theme and scan-inspired brand styling.
- A tested metric-change calculation exposed as a backend research tool.
- Research desk for asking questions from the dashboard, calling the OpenAI API with web search, and saving source-linked reports.
- Manual, per-company OpenAI analysis of the supplied tracker data when locally configured.
- Opt-in local scheduler: once daily at 09:00 local time, analyzing saved-watchlist companies only.
- Monitoring controls for enabling, pausing and running immediately, with timestamps and per-company outcomes.

## What is simulated

Every company, metric, finding, event, evidence source, timestamp and history entry in `data/seed.json` is fictional sample content. It is not live research, a recommendation, or a real portfolio. Research Desk runs are real OpenAI API calls with web search, only after explicit user action and consent; they are stored locally with clickable web citations and a retrieval timestamp. Per-company tracker analysis and the optional daily watchlist monitor still analyze only supplied tracker data and do not search the web. The dashboard's sample dates are illustrative and should not be relied on.

No trading functionality is implemented. Without manually triggering research/analysis or explicitly enabling monitoring, the app makes no outbound provider calls. It does not collect credentials in the UI or chat.

## OpenAI research provider

Portfolio Radar is the research interface: use its **Research desk** page to submit a question, call the OpenAI Responses API with web search, and review saved reports and citations in the dashboard. This does not query your ChatGPT account, subscription, plugins, or conversation history. API access and billing are separate from a ChatGPT subscription.

Set `OPENAI_API_KEY` in the app's local environment or deployment secrets; optionally set `OPENAI_MODEL` (default `gpt-4.1-mini`) and `OPENAI_RESEARCH_MODEL` (default `gpt-5.5`, which must be available to your API account and support the Responses API web-search tool). Never paste credentials into chat or commit them. Research Desk displays a consent notice because the question is sent to OpenAI and web search may send search queries to external websites. It does not send saved notes, watchlist membership, or other tracker data with a standalone research question. Reports are saved locally in `data/user_state.json` with provider, model, question, citations, scope and retrieval timestamp. Model responses and sources are not independently verified by the app.

The separate tracker-analysis flow sends the selected fictional tracker name, ticker, sector, thesis, metrics, risks and evidence to OpenAI after confirmation; it does not search external sources. The opt-in daily scheduler checks at 09:00 local time while the app server is running and analyzes saved-watchlist tracker data sequentially, without web search. Enable/pause and “Run now” controls are on the dashboard. Runs while the app is stopped are not queued; an enabled schedule resumes when the app restarts. Per-company provider errors appear in monitoring outcomes, and failed reports are not saved as successful results.

## Connect ChatGPT to save reports in Portfolio Radar

This is a separate flow from the dashboard's OpenAI API research: a private Custom GPT can use your ChatGPT account to research during a conversation, then call Portfolio Radar's HTTPS Action API to save the completed report. It does not let the dashboard initiate requests through your ChatGPT subscription, and it does not read ChatGPT history. ChatGPT only calls the Action when you use the GPT; it does not run scheduled or background research.

1. Deploy the latest repository to Render. In the Render service environment, set two separate random values of at least 32 characters: `PORTFOLIO_RADAR_ACTION_TOKEN` and `PORTFOLIO_RADAR_DASHBOARD_TOKEN`. Generate each locally in PowerShell with `python -c "import secrets; print(secrets.token_urlsafe(48))"`; run it twice and do not paste either value into chat or commit it. `render.yaml` declares these as secret environment variables.
2. In Streamlit Community Cloud, add these entries to the app's secrets. Set `PORTFOLIO_RADAR_DASHBOARD_TOKEN` to the exact same dashboard-read token configured on Render:

   ```toml
   PORTFOLIO_RADAR_ACTION_API_URL = "https://portfolio-radar-myhf.onrender.com"
   PORTFOLIO_RADAR_DASHBOARD_TOKEN = "same dashboard-read token as Render"
   ```

   Save and reboot the Streamlit app. Its Research desk reads ChatGPT Action reports from the Render API over HTTPS; those reports are persisted on Render's disk. This read token is separate from the ChatGPT Action token.
3. In ChatGPT, create a private Custom GPT and open **Configure → Actions → Create new action**. Import or paste [`openapi/portfolio-radar-chatgpt-action.yaml`](./openapi/portfolio-radar-chatgpt-action.yaml). Select **API Key** authentication using the **Bearer** authorization scheme, and provide the Render `PORTFOLIO_RADAR_ACTION_TOKEN` value. Never use the website password or the dashboard-read token for this Action.
4. Add GPT instructions such as: “Research using reliable sources. Keep facts separate from assumptions and interpretation. Include HTTPS source URLs and map every fact to at least one source URL. If a claim cannot be sourced, put it under assumptions or open questions rather than facts. Do not save anything unless I explicitly ask you to save the report to Portfolio Radar. When asked, call `saveResearchRun` with the question, facts, assumptions, interpretation, risks, open questions, and sources. Tell me whether the save succeeded.”
5. Keep the GPT sharing setting private. Test it by asking a research question, reviewing the results, then asking it to save the report. Confirm the saved report and clickable sources appear under **Research desk → From ChatGPT** in the Streamlit app.

The Action API uses a write token, validates HTTPS citations, and only accepts the bounded research-report fields in the OpenAPI schema. The dashboard uses a distinct read-only token. Both API tokens remain server-side secrets; the Action token is stored in the GPT's encrypted authentication configuration. The Action does not fetch brokerage data and cannot place trades. Saving a report sends that research content to your Portfolio Radar Render service and stores it on its persistent disk.

This app is local-first and binds only to `127.0.0.1` by default. A single-user password gate is available for a private reverse-proxy deployment:

- Set `PORTFOLIO_RADAR_PASSWORD` in the server environment to a unique password of at least 12 characters. It is never stored in source or JSON. The app checks it with PBKDF2, issues an HttpOnly/SameSite session cookie, enforces CSRF tokens on state-changing requests, expires idle sessions and throttles repeated failed logins. Sessions are in memory and end when the server restarts.
- Set `PORTFOLIO_RADAR_SECURE_COOKIES=true` when HTTPS terminates at the reverse proxy.
- Keep this Python server bound to loopback (`PORTFOLIO_RADAR_HOST=127.0.0.1`) and place it behind a TLS reverse proxy on the selected host. A direct non-loopback bind requires a strong local password and secure cookies, but the app itself does not provide TLS. Never expose its development HTTP server directly to the public internet.
- Baseline CSP, anti-framing, MIME-sniffing and referrer headers are set by the app. Configure HTTPS/HSTS at the TLS proxy, backups, host updates/firewall, monitoring and secure environment-variable handling before launch.

The existing Render deployment serves the original HTTP interface. The new Streamlit deployment is a separate service. This remains a single-user app; it does not provide multi-user accounts, persistent session storage, database backups or production operations tooling. Treat this hardening as a starting point, not a claim of production readiness.

## Deploy the Streamlit app

The Streamlit entry point is `streamlit_app.py`; `requirements.txt` installs Streamlit. To deploy through Streamlit Community Cloud, connect the GitHub repository, select the `main` branch and `streamlit_app.py`, and configure secrets in the app's settings:

```toml
PORTFOLIO_RADAR_PASSWORD = "choose-a-unique-password-of-at-least-12-characters"
# Optional: enable dashboard research and opt-in monitoring.
# OPENAI_API_KEY = "..."
# OPENAI_MODEL = "gpt-4.1-mini"
# OPENAI_RESEARCH_MODEL = "gpt-5.5"
```

Set `PORTFOLIO_RADAR_PASSWORD` before sharing the deployment. Keep the app's platform visibility/access controls appropriately restricted as well; the in-app password is an additional gate, not a replacement for platform access controls. Never put credentials in GitHub source files or chat.

The Streamlit app saves notes and watchlists to `data/user_state.json`. Streamlit Community Cloud does not provide durable local-file storage as an application database; local state can be lost when the app restarts, rebuilds, or is moved. Use a persistent database and backups before relying on saved research. The opt-in daily scheduler runs only while the app process is alive and is not a guaranteed hosted scheduler. Configure a dedicated persistent database and scheduled job for reliable private deployment.

After deployment, verify the sign-in gate, all six workspace sections, notes/watchlist behavior, Research desk citations and platform access restrictions. Seed companies, metrics, events, evidence and findings remain fictional. OpenAI calls are optional and only run after explicit user action or opt-in monitoring.

## Existing Render deployment

The earlier Render service is configured to start the original HTTP interface with `python server.py`; it does not automatically serve the Streamlit interface. The existing service configuration and state path are in `render.yaml`. To deploy the new interface on Streamlit Community Cloud, use the Streamlit setup above rather than changing Render's start command. The standalone HTTP interface and its tests remain available for local use and as a backend reference.

`BrokerDataProvider` uses the Interactive Brokers TWS API in read-only mode. It fetches positions, snapshot quotes and available `ReportSnapshot` fundamentals only after the user clicks the fetch button. It does not place orders, show account IDs, or persist holdings. The scheduler is opt-in, local-process-bound, and records run state, time and per-company failures. Keep calculations in explicit tested tools and label data with its source and retrieval timestamp.

## Connect Interactive Brokers locally

The IBKR connection is deliberately local. Streamlit Community Cloud cannot reach TWS or IB Gateway running on your computer, so use the local Streamlit app to view your actual account data:

1. Install and sign in to Trader Workstation (TWS) or IB Gateway.
2. In its API settings, enable socket clients, allow localhost connections, and keep **Read-Only API** enabled. Do not expose the socket port publicly.
3. For TWS paper trading, the default API port is `7497`; for IB Gateway paper trading it is usually `4002`. Set `PORTFOLIO_RADAR_IBKR_PORT` to the configured local port if needed. Live TWS/IB Gateway ports are typically `7496`/`4001`; selecting one is an explicit local configuration choice.
4. Start Portfolio Radar on that same computer:

   ```powershell
   $env:PORTFOLIO_RADAR_PASSWORD = "use-a-unique-local-password"
   streamlit run streamlit_app.py
   ```

5. Sign in and click **Fetch IBKR holdings and market data**. Nothing is fetched automatically.

Optional non-secret connection settings are `PORTFOLIO_RADAR_IBKR_HOST` (must be localhost), `PORTFOLIO_RADAR_IBKR_PORT` (default `7497`), and `PORTFOLIO_RADAR_IBKR_CLIENT_ID` (default `42`). The app does not request or store IBKR login credentials. IBKR may return live, frozen, delayed, or no quote depending on market-data permissions; available company ratios are also subject to IBKR report/entitlement availability. Snapshot values are labelled with their retrieval time and returned market-data type.

An optional OpenAI analysis is available for one selected holding only after an explicit consent checkbox. It sends the selected symbol, quantity, cost, returned quote/fundamentals and retrieval time, but not account IDs, notes, or other holdings. Results are held only in the current app session. `OPENAI_API_KEY` is a separate API credential; a ChatGPT subscription does not provide API access. Configure the key through local environment variables or Streamlit secrets, never in chat or source control.

The sample company trackers and discovery content remain fictional and separate from IBKR account data. No broker holdings are used to alter those sample theses or findings. The Streamlit Cloud deployment can continue to show fictional demo content, but it cannot display your local IBKR account.

User notes and watchlists are written as plain JSON to `data/user_state.json`; avoid storing confidential information in this demo. Delete that specific file to reset local user state (the app recreates the starter watchlist on next launch).

## Tests

Run `python -m unittest discover -s tests -v` using Python 3.10 or newer. The backend uses only the Python standard library; the Streamlit front end is installed from `requirements.txt`.
