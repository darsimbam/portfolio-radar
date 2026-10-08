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
- Search and category filters for discovery cards, with expandable evidence trails.
- Company trackers with theses, sample metrics, risks, evidence provenance and change history.
- Consistent discovery, earnings, deterioration and weekly-review outlines.
- Local notes and watchlist toggles persisted in `data/user_state.json`.
- Responsive desktop/mobile interface.
- A tested metric-change calculation exposed as a backend research tool.
- Manual, per-company OpenAI analysis of the supplied tracker data when locally configured.
- Opt-in local scheduler: once daily at 09:00 local time, analyzing saved-watchlist companies only.
- Monitoring controls for enabling, pausing and running immediately, with timestamps and per-company outcomes.

## What is simulated

Every company, metric, finding, event, evidence source, timestamp and history entry in `data/seed.json` is fictional sample content. It is not live research, a recommendation, or a real portfolio. The OpenAI integration performs a real model call only when manually triggered or when you explicitly enable the daily monitor; analysis is limited to supplied tracker content, fictional in this starter dataset. It does not browse or fetch current facts. Broker data remains disabled. The dashboard's sample dates are illustrative and should not be relied on.

No trading functionality is implemented. Without manually triggering analysis or explicitly enabling monitoring, the app makes no outbound provider calls. It does not collect credentials in the UI or chat.

## OpenAI research provider

Set `OPENAI_API_KEY` in the local environment before starting the app; optionally set `OPENAI_MODEL` (default `gpt-4.1-mini`). For example, in PowerShell, set `$env:OPENAI_API_KEY` in the same terminal session used to run `python server.py`. Never paste credentials into chat or commit them.

Before each manual run or monitoring opt-in, the interface asks for confirmation and explains that company name, ticker, sector, thesis, metrics, risks and evidence are sent to OpenAI. Notes and watchlist membership are not sent. Manual runs are per-company. The opt-in scheduler checks daily at 09:00 local time while the app server is running, and analyzes the saved watchlist sequentially. Enable/pause and “Run now” controls are on the dashboard. The next run is shown with the local timezone; runs while the app is stopped are not queued, and an enabled schedule resumes when the app restarts. Reports distinguish supplied facts, assumptions, interpretation, risks and open questions; they are stored locally in `data/user_state.json` with provider, model, trigger, scope and timestamp. The app does not independently verify model output. Per-company provider errors appear in monitoring outcomes; failed reports are not saved as successful results.

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
# Optional: enable manually triggered OpenAI analysis and opt-in monitoring.
# OPENAI_API_KEY = "..."
# OPENAI_MODEL = "gpt-4.1-mini"
```

Set `PORTFOLIO_RADAR_PASSWORD` before sharing the deployment. Keep the app's platform visibility/access controls appropriately restricted as well; the in-app password is an additional gate, not a replacement for platform access controls. Never put credentials in GitHub source files or chat.

The Streamlit app saves notes and watchlists to `data/user_state.json`. Streamlit Community Cloud does not provide durable local-file storage as an application database; local state can be lost when the app restarts, rebuilds, or is moved. Use a persistent database and backups before relying on saved research. The opt-in daily scheduler runs only while the app process is alive and is not a guaranteed hosted scheduler. Configure a dedicated persistent database and scheduled job for reliable private deployment.

After deployment, verify the sign-in gate, all five workspace sections, notes/watchlist behavior, and platform access restrictions. Seed companies, metrics, events, evidence and findings remain fictional. OpenAI analysis is optional and only runs after explicit user action or opt-in monitoring.

## Existing Render deployment

The earlier Render service is configured to start the original HTTP interface with `python server.py`; it does not automatically serve the Streamlit interface. The existing service configuration and state path are in `render.yaml`. To deploy the new interface on Streamlit Community Cloud, use the Streamlit setup above rather than changing Render's start command. The standalone HTTP interface and its tests remain available for local use and as a backend reference.

`BrokerDataProvider` in `server.py` remains an unconfigured seam and fails explicitly. The scheduler is opt-in, local-process-bound, and records run state, time and per-company failures. Keep calculations in explicit tested tools and label any future data with its actual source and retrieval timestamp.

User notes and watchlists are written as plain JSON to `data/user_state.json`; avoid storing confidential information in this demo. Delete that specific file to reset local user state (the app recreates the starter watchlist on next launch).

## Tests

Run `python -m unittest discover -s tests -v` using Python 3.10 or newer. The backend uses only the Python standard library; the Streamlit front end is installed from `requirements.txt`.
