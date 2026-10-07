"""Local Portfolio Radar application server.

Run with: python server.py
All seeded research is fictional and all state remains in this folder.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time as monotonic_time
from collections import defaultdict, deque
from datetime import date, datetime, time, timezone, timedelta
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
SEED_PATH = DATA_DIR / "seed.json"
STATE_PATH = Path(os.getenv("PORTFOLIO_RADAR_STATE_PATH", str(DATA_DIR / "user_state.json")))
STATE_LOCK = threading.RLock()
AUTH_LOCK = threading.RLock()
AUTH_PASSWORD_SALT = secrets.token_bytes(16)
AUTH_SESSIONS: dict[str, dict[str, Any]] = {}
LOGIN_FAILURES: dict[str, deque[float]] = defaultdict(deque)
SESSION_LIFETIME_SECONDS = 12 * 60 * 60
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_LOCKOUT_SECONDS = 15 * 60


def auth_required() -> bool:
    return bool(os.getenv("PORTFOLIO_RADAR_PASSWORD", ""))


def secure_cookies_enabled() -> bool:
    return os.getenv("PORTFOLIO_RADAR_SECURE_COOKIES", "").lower() == "true"


def valid_password_configuration(password: str | None = None) -> bool:
    configured_password = password if password is not None else os.getenv("PORTFOLIO_RADAR_PASSWORD", "")
    return len(configured_password) >= 12


def password_digest(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), AUTH_PASSWORD_SALT, 310_000)


def get_session(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    with AUTH_LOCK:
        session = AUTH_SESSIONS.get(session_id)
        if session is None:
            return None
        if session["expiresAt"] <= monotonic_time.monotonic():
            AUTH_SESSIONS.pop(session_id, None)
            return None
        session["expiresAt"] = monotonic_time.monotonic() + SESSION_LIFETIME_SECONDS
        return session


def clear_expired_sessions() -> None:
    now = monotonic_time.monotonic()
    expired = [key for key, value in AUTH_SESSIONS.items() if value["expiresAt"] <= now]
    for key in expired:
        AUTH_SESSIONS.pop(key, None)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = STATE_PATH.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        temporary_path.replace(STATE_PATH)


def default_monitoring_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "status": "disabled",
        "schedule": "Daily at 09:00 local time",
        "lastScheduledDate": None,
        "lastRunAt": None,
        "lastCompletedAt": None,
        "lastError": None,
        "lastOutcomes": [],
    }


def load_state() -> dict[str, Any]:
    with STATE_LOCK:
        if STATE_PATH.exists():
            state = load_json(STATE_PATH)
            state.setdefault("researchRuns", [])
            state.setdefault("monitoring", default_monitoring_state())
            return state
        state = {
            "notes": [],
            "watchlist": ["NOVA", "LUMA"],
            "researchRuns": [],
            "monitoring": default_monitoring_state(),
        }
        save_state(state)
        return state


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scheduled_time_for_local_date(day: date) -> datetime:
    return datetime.combine(day, time(hour=9)).astimezone()


def calculate_metric_change(current: float, previous: float) -> float | None:
    """Return the percentage change, or None where a meaningful denominator is absent."""
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


class ProviderConfiguration:
    """Integration settings are read from the local environment, never from chat."""

    @staticmethod
    def openai_configured() -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

class ResearchAgent:
    """Manual OpenAI analysis of supplied tracker data, without web or broker access."""

    def run(self, company: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY in the local environment.")

        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
        input_data = {
            "company": company["name"],
            "ticker": company["ticker"],
            "sector": company["sector"],
            "thesis": company["thesis"],
            "metrics": company["metrics"],
            "risks": company["risks"],
            "evidence": company["evidence"],
        }
        request_body = {
            "model": model,
            "instructions": (
                "You are a careful investment research analyst. Analyze only the supplied tracker data. "
                "Do not claim to browse, verify current facts, or use sources that were not provided. "
                "Treat supplied metrics and evidence as unverified input, not established truth. "
                "Return a JSON object with keys facts (array of objects with statement and source), "
                "assumptions (array of strings), interpretation (string), risks (array of strings), "
                "and openQuestions (array of strings). Facts must be directly traceable to supplied "
                "data; mark absent source details as unavailable. Clearly distinguish analysis from facts."
            ),
            "input": json.dumps(input_data, ensure_ascii=False),
            "max_output_tokens": 1200,
            "text": {"format": {"type": "json_object"}},
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                response_body = json.loads(response.read())
        except HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("OpenAI rejected the local API key. Check its validity and permissions.") from None
            raise RuntimeError(f"OpenAI request failed with HTTP {error.code}.") from None
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"Could not reach OpenAI: {error.reason if isinstance(error, URLError) else 'request timed out'}.") from None
        except OSError as error:
            raise RuntimeError(f"Could not contact OpenAI: {error}.") from None
        except json.JSONDecodeError:
            raise RuntimeError("OpenAI returned an invalid JSON response.") from None

        if not isinstance(response_body, dict):
            raise RuntimeError("OpenAI returned an unexpected response structure.")
        output_text = response_body.get("output_text")
        if not output_text:
            output_text = next(
                (
                    content["text"]
                    for item in response_body.get("output", [])
                    for content in item.get("content", [])
                    if content.get("type") == "output_text" and isinstance(content.get("text"), str)
                ),
                None,
            )
        if not isinstance(output_text, str):
            raise RuntimeError("OpenAI response did not contain a research report.")
        try:
            report = json.loads(output_text)
        except json.JSONDecodeError:
            raise RuntimeError("OpenAI returned a report in an unexpected format.") from None

        required_fields = ("facts", "assumptions", "interpretation", "risks", "openQuestions")
        if not isinstance(report, dict) or any(field not in report for field in required_fields):
            raise RuntimeError("OpenAI report is missing required fact/assumption/interpretation sections.")
        if (
            not isinstance(report["facts"], list)
            or not all(isinstance(item, dict) and isinstance(item.get("statement"), str) for item in report["facts"])
            or not all(isinstance(report[field], list) for field in ("assumptions", "risks", "openQuestions"))
            or not isinstance(report["interpretation"], str)
        ):
            raise RuntimeError("OpenAI report has invalid section types.")
        return {"model": model, "report": report}


class BrokerDataProvider:
    """Interface for a future broker data adapter; no broker connection is made."""

    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError("No broker provider is configured.")


class MonitoringScheduler:
    """Opt-in daily local-time analysis of saved-watchlist companies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def next_scheduled_time(now: datetime | None = None) -> datetime:
        local_now = (now or datetime.now().astimezone()).astimezone()
        scheduled = scheduled_time_for_local_date(local_now.date())
        if scheduled <= local_now:
            scheduled = scheduled_time_for_local_date(local_now.date() + timedelta(days=1))
        return scheduled

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._schedule_loop, name="portfolio-radar-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def enable(self) -> dict[str, Any]:
        if not ProviderConfiguration.openai_configured():
            raise RuntimeError("Set OPENAI_API_KEY locally before enabling scheduled monitoring.")
        with self._lock:
            with STATE_LOCK:
                state = load_state()
                if not state["watchlist"]:
                    raise RuntimeError("The saved watchlist is empty; add a company before enabling monitoring.")
                state["monitoring"]["enabled"] = True
                now = datetime.now().astimezone()
                if now >= scheduled_time_for_local_date(now.date()):
                    state["monitoring"]["lastScheduledDate"] = now.date().isoformat()
                if state["monitoring"]["status"] == "disabled":
                    state["monitoring"]["status"] = "waiting"
                state["monitoring"]["lastError"] = None
                save_state(state)
                return state["monitoring"]

    def disable(self) -> dict[str, Any]:
        with self._lock:
            with STATE_LOCK:
                state = load_state()
                state["monitoring"]["enabled"] = False
                if state["monitoring"]["status"] == "waiting":
                    state["monitoring"]["status"] = "disabled"
                save_state(state)
                return state["monitoring"]

    def run_now(self) -> dict[str, Any]:
        return self._start_run("manual")

    def _start_run(self, source: str) -> dict[str, Any]:
        if not ProviderConfiguration.openai_configured():
            raise RuntimeError("Set OPENAI_API_KEY locally before running monitoring.")
        with self._lock:
            with STATE_LOCK:
                state = load_state()
                monitoring = state["monitoring"]
                if monitoring["status"] == "running":
                    raise RuntimeError("A monitoring run is already in progress.")
                if source == "scheduled" and not monitoring["enabled"]:
                    raise RuntimeError("Scheduled monitoring has been paused.")
                seed = load_json(SEED_PATH)
                companies = {company["id"]: company for company in seed["companies"]}
                targets = [companies[company_id] for company_id in state["watchlist"] if company_id in companies]
                if not targets:
                    raise RuntimeError("The saved watchlist is empty; add a company before running monitoring.")
                started_at = utc_now()
                monitoring.update(
                    {
                        "status": "running",
                        "lastRunAt": started_at,
                        "lastError": None,
                        "lastOutcomes": [],
                    }
                )
                save_state(state)
        worker = threading.Thread(
            target=self._execute_run,
            args=(source, targets, started_at),
            name="portfolio-radar-research-run",
            daemon=True,
        )
        worker.start()
        return {"status": "running", "startedAt": started_at, "companies": [company["id"] for company in targets]}

    def _execute_run(self, source: str, targets: list[dict[str, Any]], started_at: str) -> None:
        outcomes = []
        research_runs = []
        for company in targets:
            try:
                result = ResearchAgent().run(company)
                research_runs.append(
                    {
                        "id": f"research-{int(datetime.now().timestamp() * 1000)}-{company['id']}",
                        "companyId": company["id"],
                        "companyName": company["name"],
                        "ticker": company["ticker"],
                        "provider": "OpenAI API",
                        "model": result["model"],
                        "createdAt": utc_now(),
                        "scope": "Analysis of supplied fictional tracker data only; no external sources were searched.",
                        "trigger": source,
                        "report": result["report"],
                    }
                )
                outcomes.append({"companyId": company["id"], "status": "completed"})
            except (RuntimeError, OSError) as error:
                outcomes.append({"companyId": company["id"], "status": "failed", "error": str(error)})

        with self._lock:
            with STATE_LOCK:
                state = load_state()
                state["researchRuns"].extend(research_runs)
                monitoring = state["monitoring"]
                errors = [outcome for outcome in outcomes if outcome["status"] == "failed"]
                monitoring.update(
                    {
                        "status": "failed" if len(errors) == len(outcomes) else (
                            "completed_with_errors" if errors else "completed"
                        ),
                        "lastRunAt": started_at,
                        "lastCompletedAt": utc_now(),
                        "lastError": "; ".join(f"{item['companyId']}: {item['error']}" for item in errors) or None,
                        "lastOutcomes": outcomes,
                    }
                )
                save_state(state)

    def _schedule_loop(self) -> None:
        while not self._stop.wait(15):
            try:
                state = load_state()
                monitoring = state["monitoring"]
                if not monitoring["enabled"] or monitoring["status"] == "running":
                    continue
                now = datetime.now().astimezone()
                scheduled_at = scheduled_time_for_local_date(now.date())
                if now >= scheduled_at and monitoring["lastScheduledDate"] != now.date().isoformat():
                    with self._lock:
                        with STATE_LOCK:
                            current_state = load_state()
                            current_state["monitoring"]["lastScheduledDate"] = now.date().isoformat()
                            save_state(current_state)
                    try:
                        self._start_run("scheduled")
                    except RuntimeError as error:
                        with self._lock:
                            with STATE_LOCK:
                                current_state = load_state()
                                current_state["monitoring"].update(
                                    {"status": "failed", "lastError": str(error), "lastCompletedAt": utc_now()}
                                )
                                save_state(current_state)
            except OSError as error:
                print(f"Monitoring scheduler state error: {error}")


monitoring_scheduler = MonitoringScheduler()


def api_payload() -> dict[str, Any]:
    seed = load_json(SEED_PATH)
    state = load_state()
    companies = seed["companies"]
    return {
        "seedDataFictional": True,
        "asOf": seed["asOf"],
        "dashboard": seed["dashboard"],
        "events": seed["events"],
        "companies": companies,
        "discoveries": seed["discoveries"],
        "templates": seed["templates"],
        "notes": sorted(state["notes"], key=lambda note: note["createdAt"], reverse=True),
        "researchRuns": sorted(state["researchRuns"], key=lambda run: run["createdAt"], reverse=True),
        "watchlist": state["watchlist"],
        "monitoring": {
            **state["monitoring"],
            "nextRunAt": monitoring_scheduler.next_scheduled_time().isoformat(timespec="minutes")
            if state["monitoring"]["enabled"]
            else None,
            "scope": "Saved watchlist only",
            "openaiConfigured": ProviderConfiguration.openai_configured(),
        },
        "integrations": {
            "openai": {
                "configured": ProviderConfiguration.openai_configured(),
                "status": "ready_for_manual_run" if ProviderConfiguration.openai_configured() else "not_configured",
                "manualOnly": True,
                "externalDataDisclosure": "Selected tracker thesis, metrics, risks and evidence are sent to OpenAI when you run analysis.",
            },
            "broker": {"configured": bool(os.getenv("PORTFOLIO_RADAR_BROKER_URL")), "status": "disabled"},
            "scheduledMonitoring": {
                "configured": ProviderConfiguration.openai_configured(),
                "status": state["monitoring"]["status"],
                "enabled": state["monitoring"]["enabled"],
                "schedule": state["monitoring"]["schedule"],
            },
        },
        "tools": {
            "metricChange": "calculate_metric_change",
            "metricChangeExample": calculate_metric_change(125, 100),
        },
    }


class RadarHandler(BaseHTTPRequestHandler):
    server_version = "PortfolioRadar"
    sys_version = ""

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )

    def send_json(self, payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def request_session(self) -> dict[str, Any] | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("radar_session")
        return get_session(morsel.value if morsel else None)

    def require_authenticated_session(self) -> dict[str, Any] | None:
        if not auth_required():
            return {"csrfToken": None}
        session = self.request_session()
        if session is None:
            self.send_json({"error": "Login required.", "authRequired": True}, 401)
            return None
        return session

    def login(self) -> None:
        if not auth_required():
            self.send_json({"error": "Authentication is not enabled for this local-only instance."}, 404)
            return
        if not valid_password_configuration():
            self.send_json({"error": "The configured password is too short; use at least 12 characters."}, 503)
            return
        peer = self.client_address[0]
        now = monotonic_time.monotonic()
        with AUTH_LOCK:
            clear_expired_sessions()
            failures = LOGIN_FAILURES[peer]
            while failures and failures[0] <= now - LOGIN_FAILURE_WINDOW_SECONDS:
                failures.popleft()
            if len(failures) >= LOGIN_FAILURE_LIMIT:
                retry_after = max(1, int(LOGIN_FAILURE_LOCKOUT_SECONDS - (now - failures[0])))
                self.send_json(
                    {"error": "Too many failed login attempts. Try again later."},
                    429,
                    {"Retry-After": str(retry_after)},
                )
                return
        try:
            body = self.read_body()
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
            return
        supplied_password = body.get("password")
        if not isinstance(supplied_password, str) or len(supplied_password) > 1024:
            self.send_json({"error": "Enter a valid password."}, 400)
            return
        password_ok = hmac.compare_digest(
            password_digest(supplied_password),
            password_digest(os.getenv("PORTFOLIO_RADAR_PASSWORD", "")),
        )
        if not password_ok:
            with AUTH_LOCK:
                LOGIN_FAILURES[peer].append(now)
            self.send_json({"error": "Incorrect password."}, 401)
            return
        with AUTH_LOCK:
            LOGIN_FAILURES.pop(peer, None)
            session_id = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            AUTH_SESSIONS[session_id] = {
                "csrfToken": csrf_token,
                "expiresAt": monotonic_time.monotonic() + SESSION_LIFETIME_SECONDS,
            }
        cookie = f"radar_session={session_id}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_LIFETIME_SECONDS}"
        if secure_cookies_enabled():
            cookie += "; Secure"
        self.send_json(
            {"authenticated": True, "csrfToken": csrf_token},
            headers={"Set-Cookie": cookie},
        )

    def require_csrf(self, session: dict[str, Any] | None) -> bool:
        if session is None or not auth_required():
            return True
        token = self.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(token, session["csrfToken"]):
            self.send_json({"error": "CSRF token is missing or invalid."}, 403)
            return False
        return True

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384:
            raise ValueError("Request body is too large.")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("A JSON object is required.")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self.send_json({"status": "ok"})
            return
        if path == "/api":
            session = self.require_authenticated_session()
            if session is None:
                return
            payload = api_payload()
            payload["authRequired"] = auth_required()
            payload["csrfToken"] = session["csrfToken"]
            self.send_json(payload)
            return
        if path.startswith("/api/"):
            self.send_json({"error": "API endpoint not found."}, 404)
            return
        relative_path = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.is_file():
            self.send_json({"error": "Not found."}, 404)
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else (
            "text/css; charset=utf-8" if target.suffix == ".css" else "text/javascript; charset=utf-8"
        )
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_security_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/login":
            self.login()
            return
        session = self.require_authenticated_session()
        if session is None or not self.require_csrf(session):
            return
        if path == "/api/logout":
            cookie = "radar_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            if secure_cookies_enabled():
                cookie += "; Secure"
            cookie_header = SimpleCookie()
            cookie_header.load(self.headers.get("Cookie", ""))
            session_cookie = cookie_header.get("radar_session")
            if session_cookie:
                with AUTH_LOCK:
                    AUTH_SESSIONS.pop(session_cookie.value, None)
            self.send_json({"authenticated": False}, headers={"Set-Cookie": cookie})
            return
        try:
            body = self.read_body()
            state = load_state()
            if path == "/api/notes":
                text = str(body.get("text", "")).strip()
                company_id = str(body.get("companyId", "")).strip()
                if not text or len(text) > 2_000:
                    self.send_json({"error": "Note must contain 1–2000 characters."}, 400)
                    return
                company = next((item for item in load_json(SEED_PATH)["companies"] if item["id"] == company_id), None)
                if company is None:
                    self.send_json({"error": "Choose a valid company for this note."}, 400)
                    return
                note = {
                    "id": f"note-{int(datetime.now().timestamp() * 1000)}",
                    "companyId": company_id,
                    "companyName": company["name"],
                    "text": text,
                    "createdAt": utc_now(),
                }
                with STATE_LOCK:
                    state = load_state()
                    state["notes"].append(note)
                    save_state(state)
                self.send_json({"note": note}, 201)
                return
            if path == "/api/watchlist":
                company_id = str(body.get("companyId", "")).strip()
                valid_ids = {item["id"] for item in load_json(SEED_PATH)["companies"]}
                if company_id not in valid_ids:
                    self.send_json({"error": "Choose a valid company."}, 400)
                    return
                with STATE_LOCK:
                    state = load_state()
                    if company_id in state["watchlist"]:
                        state["watchlist"].remove(company_id)
                        action = "removed"
                    else:
                        state["watchlist"].append(company_id)
                        action = "added"
                    save_state(state)
                self.send_json({"watchlist": state["watchlist"], "action": action})
                return
            if path == "/api/research/openai":
                if not ProviderConfiguration.openai_configured():
                    self.send_json({"error": "OpenAI is not configured. Set OPENAI_API_KEY in the local environment."}, 503)
                    return
                company_id = str(body.get("companyId", "")).strip()
                company = next((item for item in load_json(SEED_PATH)["companies"] if item["id"] == company_id), None)
                if company is None:
                    self.send_json({"error": "Choose a valid company."}, 400)
                    return
                result = ResearchAgent().run(company)
                run = {
                    "id": f"research-{int(datetime.now().timestamp() * 1000)}",
                    "companyId": company_id,
                    "companyName": company["name"],
                    "ticker": company["ticker"],
                    "provider": "OpenAI API",
                    "model": result["model"],
                    "createdAt": utc_now(),
                    "scope": "Analysis of supplied fictional tracker data only; no external sources were searched.",
                    "report": result["report"],
                }
                with STATE_LOCK:
                    state = load_state()
                    state["researchRuns"].append(run)
                    save_state(state)
                self.send_json({"run": run}, 201)
                return
            if path == "/api/monitoring/settings":
                enabled = body.get("enabled")
                if not isinstance(enabled, bool):
                    self.send_json({"error": "The enabled field must be true or false."}, 400)
                    return
                try:
                    monitoring = monitoring_scheduler.enable() if enabled else monitoring_scheduler.disable()
                except RuntimeError as error:
                    self.send_json({"error": str(error)}, 503)
                    return
                self.send_json({"monitoring": monitoring})
                return
            if path == "/api/monitoring/run":
                try:
                    run = monitoring_scheduler.run_now()
                except RuntimeError as error:
                    self.send_json({"error": str(error)}, 409)
                    return
                self.send_json({"run": run}, 202)
                return
            self.send_json({"error": "API endpoint not found."}, 404)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, 502)
        except OSError as error:
            self.send_json({"error": f"Could not persist local state: {error}"}, 500)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def validate_server_configuration(host: str) -> None:
    configured_password = os.getenv("PORTFOLIO_RADAR_PASSWORD")
    if configured_password and not valid_password_configuration(configured_password):
        raise RuntimeError("PORTFOLIO_RADAR_PASSWORD must be at least 12 characters.")
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback or host.lower() == "localhost"
    except ValueError:
        is_loopback = host.lower() == "localhost"
    if is_loopback:
        return
    if not auth_required():
        raise RuntimeError("Non-loopback binding requires PORTFOLIO_RADAR_PASSWORD (12+ characters).")
    if not valid_password_configuration():
        raise RuntimeError("PORTFOLIO_RADAR_PASSWORD must be at least 12 characters.")
    if not secure_cookies_enabled():
        raise RuntimeError("Non-loopback binding requires PORTFOLIO_RADAR_SECURE_COOKIES=true behind HTTPS.")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    host = os.getenv("PORTFOLIO_RADAR_HOST", "127.0.0.1")
    port = int(os.getenv("PORTFOLIO_RADAR_PORT", os.getenv("PORT", "8000")))
    validate_server_configuration(host)
    server = ThreadingHTTPServer((host, port), RadarHandler)
    monitoring_scheduler.start()
    print(f"Portfolio Radar running at http://{host}:{port} (fictional demo data)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Portfolio Radar.")
    finally:
        monitoring_scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    main()
