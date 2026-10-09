import http.client
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, call, patch

import server
import ibkr_provider


class MetricCalculationTests(unittest.TestCase):
    def test_percentage_change_is_calculated_by_tool(self):
        self.assertEqual(server.calculate_metric_change(125, 100), 25.0)

    def test_percentage_change_handles_negative_baseline(self):
        self.assertEqual(server.calculate_metric_change(5, -10), 150.0)

    def test_zero_baseline_has_no_percentage_change(self):
        self.assertIsNone(server.calculate_metric_change(5, 0))


class LocalStateTests(unittest.TestCase):
    def test_state_path_parent_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "persistent" / "user_state.json"
            with patch.object(server, "STATE_PATH", state_path):
                server.save_state({"notes": [], "watchlist": []})
            self.assertTrue(state_path.exists())

    def test_state_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "user_state.json"
            with patch.object(server, "STATE_PATH", state_path), patch.object(server, "DATA_DIR", Path(directory)):
                expected = {
                    "notes": [{"id": "note-1"}],
                    "watchlist": ["NOVA"],
                    "researchRuns": [],
                    "monitoring": server.default_monitoring_state(),
                }
                server.save_state(expected)
                self.assertEqual(server.load_state(), expected)

    def test_new_workspace_gets_fictional_seed_watchlist(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "user_state.json"
            with patch.object(server, "STATE_PATH", state_path), patch.object(server, "DATA_DIR", Path(directory)):
                state = server.load_state()
                self.assertEqual(
                    state,
                    {
                        "notes": [],
                        "watchlist": ["NOVA", "LUMA"],
                        "researchRuns": [],
                        "monitoring": server.default_monitoring_state(),
                    },
                )
                self.assertTrue(state_path.exists())


class PayloadTests(unittest.TestCase):
    def test_payload_marks_all_sample_research_as_fictional(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "user_state.json"
            with patch.object(server, "STATE_PATH", state_path), patch.object(server, "DATA_DIR", Path(directory)):
                payload = server.api_payload()
        self.assertTrue(payload["seedDataFictional"])
        self.assertEqual(len(payload["companies"]), 3)
        self.assertEqual(payload["integrations"]["scheduledMonitoring"]["status"], "disabled")
        self.assertFalse(payload["monitoring"]["enabled"])
        self.assertEqual(payload["monitoring"]["scope"], "Saved watchlist only")
        self.assertTrue(payload["integrations"]["openai"]["manualOnly"])
        self.assertTrue(all("timestamp" in row for company in payload["companies"] for row in company["evidence"]))

    def test_unconfigured_provider_seams_fail_explicitly(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            server.ResearchAgent().run({})
        with patch.dict("os.environ", {"PORTFOLIO_RADAR_IBKR_HOST": "192.168.1.10"}, clear=True):
            with self.assertRaisesRegex(ibkr_provider.IBKRConnectionError, "this computer"):
                server.BrokerDataProvider()


class DeploymentHealthCheckTests(unittest.TestCase):
    def test_health_check_does_not_require_authentication(self):
        server_instance = ThreadingHTTPServer(("127.0.0.1", 0), server.RadarHandler)
        thread = threading.Thread(target=server_instance.serve_forever)
        thread.start()
        try:
            with patch.dict("os.environ", {"PORTFOLIO_RADAR_PASSWORD": "deployment-test-password"}, clear=True):
                connection = http.client.HTTPConnection("127.0.0.1", server_instance.server_port, timeout=3)
                connection.request("GET", "/healthz")
                response = connection.getresponse()
                result = json.loads(response.read())
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(result, {"status": "ok"})
        finally:
            server_instance.shutdown()
            server_instance.server_close()
            thread.join()


class OpenAIWebResearchTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.payload

    def test_research_uses_web_search_and_returns_citations(self):
        text = (
            "## Facts\nA company announced a new product today.\n\n"
            "## Assumptions\nThe launch may contribute to growth.\n\n"
            "## Interpretation\nThe strategic impact remains uncertain.\n\n"
            "## Risks and open questions\nAdoption and margins remain unknown."
        )
        cited_claim = "A company announced a new product today."
        start = text.index(cited_claim)
        fake_response = self.FakeResponse(
            {
                "output_text": text,
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": text,
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "start_index": start,
                                        "end_index": start + len(cited_claim),
                                        "url": "https://example.com/news",
                                        "title": "Example company announcement",
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        )
        with (
            patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "unit-test-key", "OPENAI_RESEARCH_MODEL": "test-research-model"},
                clear=True,
            ),
            patch("server.urlopen", return_value=fake_response) as openai_request,
        ):
            result = server.ResearchAgent().run_research("What happened at the company today?")

        request = openai_request.call_args.args[0]
        request_body = json.loads(request.data)
        self.assertEqual(request_body["model"], "test-research-model")
        self.assertEqual(request_body["tools"], [{"type": "web_search"}])
        self.assertIn("What happened at the company today?", request_body["input"])
        self.assertEqual(result["report"]["text"], text)
        self.assertEqual(
            result["sources"],
            [
                {
                    "url": "https://example.com/news",
                    "title": "Example company announcement",
                    "startIndex": start,
                    "endIndex": start + len(cited_claim),
                    "citedText": cited_claim,
                }
            ],
        )

    def test_research_question_must_not_be_empty_or_oversized(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "1–2000 characters"):
                server.ResearchAgent().run_research(" ")
            with self.assertRaisesRegex(ValueError, "1–2000 characters"):
                server.ResearchAgent().run_research("x" * 2_001)


class MonitoringSchedulerTests(unittest.TestCase):
    def with_local_state(self, directory):
        state_path = Path(directory) / "user_state.json"
        return patch.object(server, "STATE_PATH", state_path), patch.object(server, "DATA_DIR", Path(directory))

    def test_daily_schedule_is_nine_local_and_rolls_to_tomorrow_after_due_time(self):
        local_now = datetime.now().astimezone()
        before_nine = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
        after_nine = local_now.replace(hour=10, minute=0, second=0, microsecond=0)
        today_at_nine = server.MonitoringScheduler.next_scheduled_time(before_nine)
        tomorrow_at_nine = server.MonitoringScheduler.next_scheduled_time(after_nine)
        self.assertEqual((today_at_nine.hour, today_at_nine.minute), (9, 0))
        self.assertEqual(today_at_nine.date(), before_nine.date())
        self.assertEqual((tomorrow_at_nine.hour, tomorrow_at_nine.minute), (9, 0))
        self.assertEqual(tomorrow_at_nine.date(), after_nine.date() + timedelta(days=1))

    def test_enable_requires_key_and_schedule_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path_patch, data_path_patch = self.with_local_state(directory)
            with state_path_patch, data_path_patch, patch.dict("os.environ", {}, clear=True):
                scheduler = server.MonitoringScheduler()
                with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                    scheduler.enable()
            with state_path_patch, data_path_patch, patch.dict("os.environ", {"OPENAI_API_KEY": "local-test-key"}):
                monitoring = server.MonitoringScheduler().enable()
                self.assertTrue(monitoring["enabled"])
                self.assertEqual(monitoring["schedule"], "Daily at 09:00 local time")
                self.assertEqual(server.load_state()["monitoring"]["status"], "waiting")

    def test_run_now_analyzes_only_watchlist_and_persists_outcomes(self):
        report = {
            "facts": [{"statement": "Example fact.", "source": "supplied sample"}],
            "assumptions": [],
            "interpretation": "Example interpretation.",
            "risks": [],
            "openQuestions": [],
        }
        fake_agent = Mock()
        fake_agent.run.return_value = {"model": "test-model", "report": report}
        with tempfile.TemporaryDirectory() as directory:
            state_path_patch, data_path_patch = self.with_local_state(directory)
            with (
                state_path_patch,
                data_path_patch,
                patch.dict("os.environ", {"OPENAI_API_KEY": "local-test-key"}),
                patch("server.ResearchAgent", return_value=fake_agent),
            ):
                scheduler = server.MonitoringScheduler()
                started = scheduler.run_now()
                self.assertEqual(started["companies"], ["NOVA", "LUMA"])
                deadline = time.monotonic() + 3
                while server.load_state()["monitoring"]["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.01)
                state = server.load_state()
        fake_agent.run.assert_has_calls(
            [call(server.load_json(server.SEED_PATH)["companies"][0]), call(server.load_json(server.SEED_PATH)["companies"][1])]
        )
        self.assertEqual(len(state["researchRuns"]), 2)
        self.assertTrue(all(run["trigger"] == "manual" for run in state["researchRuns"]))
        self.assertEqual([outcome["status"] for outcome in state["monitoring"]["lastOutcomes"]], ["completed", "completed"])
        self.assertEqual(state["monitoring"]["status"], "completed")

    def test_run_now_fails_if_watchlist_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path_patch, data_path_patch = self.with_local_state(directory)
            with state_path_patch, data_path_patch, patch.dict("os.environ", {"OPENAI_API_KEY": "local-test-key"}):
                state = {"notes": [], "watchlist": [], "researchRuns": [], "monitoring": server.default_monitoring_state()}
                server.save_state(state)
                with self.assertRaisesRegex(RuntimeError, "watchlist is empty"):
                    server.MonitoringScheduler().run_now()


class PrivateDeploymentAuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.environ_patch = patch.dict(
            "os.environ",
            {
                "PORTFOLIO_RADAR_PASSWORD": "Unit-Test-Only-Password-48",
                "PORTFOLIO_RADAR_SECURE_COOKIES": "true",
            },
            clear=True,
        )
        self.state_patch = patch.object(server, "STATE_PATH", self.directory / "user_state.json")
        self.data_patch = patch.object(server, "DATA_DIR", self.directory)
        self.environ_patch.start()
        self.state_patch.start()
        self.data_patch.start()
        server_instance = ThreadingHTTPServer(("127.0.0.1", 0), server.RadarHandler)
        self.server = server_instance
        self.thread = threading.Thread(target=server_instance.serve_forever)
        self.thread.start()
        self.connection = http.client.HTTPConnection("127.0.0.1", server_instance.server_port, timeout=3)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.data_patch.stop()
        self.state_patch.stop()
        self.environ_patch.stop()
        self.temporary_directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        request_headers = dict(headers or {})
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(body)
            request_headers["Content-Type"] = "application/json"
        self.connection.request(method, path, encoded_body, request_headers)
        response = self.connection.getresponse()
        result = json.loads(response.read()) if response.getheader("Content-Type", "").startswith("application/json") else None
        return response.status, result, dict(response.getheaders())

    def test_login_protects_api_sets_secure_cookie_and_requires_csrf(self):
        status, result, _ = self.request("GET", "/api")
        self.assertEqual(status, 401)
        self.assertTrue(result["authRequired"])

        status, result, _ = self.request("POST", "/api/login", {"password": "wrong-password"})
        self.assertEqual(status, 401)
        self.assertIn("Incorrect", result["error"])

        status, result, headers = self.request(
            "POST", "/api/login", {"password": "Unit-Test-Only-Password-48"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["csrfToken"])
        login_csrf = result["csrfToken"]
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])

        status, result, _ = self.request("GET", "/api", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(result["authRequired"])
        self.assertEqual(result["csrfToken"], login_csrf)
        csrf = result["csrfToken"]

        status, result, _ = self.request(
            "POST", "/api/watchlist", {"companyId": "ORBT"}, headers={"Cookie": cookie}
        )
        self.assertEqual(status, 403)

        status, _result, _ = self.request(
            "POST",
            "/api/watchlist",
            {"companyId": "ORBT"},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
        )
        self.assertEqual(status, 200)

        status, _result, _ = self.request(
            "POST", "/api/logout", {}, headers={"Cookie": cookie, "X-CSRF-Token": csrf}
        )
        self.assertEqual(status, 200)
        status, _result, _ = self.request("GET", "/api", headers={"Cookie": cookie})
        self.assertEqual(status, 401)

    def test_non_loopback_bind_requires_strong_password_and_secure_cookies(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires PORTFOLIO_RADAR_PASSWORD"):
                server.validate_server_configuration("0.0.0.0")
        with patch.dict("os.environ", {"PORTFOLIO_RADAR_PASSWORD": "weak"}):
            with self.assertRaisesRegex(RuntimeError, "at least 12 characters"):
                server.validate_server_configuration("0.0.0.0")
        with patch.dict("os.environ", {"PORTFOLIO_RADAR_PASSWORD": "Long-Test-Only-Password-48"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SECURE_COOKIES=true"):
                server.validate_server_configuration("0.0.0.0")
        with patch.dict(
            "os.environ",
            {
                "PORTFOLIO_RADAR_PASSWORD": "Long-Test-Only-Password-48",
                "PORTFOLIO_RADAR_SECURE_COOKIES": "true",
            },
            clear=True,
        ):
            server.validate_server_configuration("0.0.0.0")


class OpenAIResearchEndpointTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.payload

    def post(self, body, configured=False, urlopen_mock=None):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "user_state.json"
            server_instance = ThreadingHTTPServer(("127.0.0.1", 0), server.RadarHandler)
            thread = threading.Thread(target=server_instance.serve_forever)
            thread.start()
            try:
                environment = {"OPENAI_API_KEY": "unit-test-key"} if configured else {}
                provider_patch = patch("server.urlopen", urlopen_mock) if urlopen_mock else patch("server.urlopen")
                with (
                    patch.dict("os.environ", environment, clear=True),
                    patch.object(server, "STATE_PATH", state_path),
                    patch.object(server, "DATA_DIR", Path(directory)),
                    provider_patch as mocked,
                ):
                    if urlopen_mock is None:
                        mocked.side_effect = AssertionError("OpenAI must not be called without credentials")
                    connection = http.client.HTTPConnection("127.0.0.1", server_instance.server_port, timeout=3)
                    connection.request("POST", "/api/research/openai", json.dumps(body), {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    result = json.loads(response.read())
                    connection.close()
                    if response.status == 201:
                        result["saved_state"] = server.load_state()
                    return response.status, result
            finally:
                server_instance.shutdown()
                server_instance.server_close()
                thread.join()

    def test_endpoint_requires_a_locally_configured_key(self):
        status, result = self.post({"companyId": "NOVA"})
        self.assertEqual(status, 503)
        self.assertIn("OPENAI_API_KEY", result["error"])

    def test_manual_analysis_calls_openai_and_saves_timestamped_report(self):
        report = {
            "facts": [{"statement": "Sample revenue growth is 18%.", "source": "Supplied fictional metric"}],
            "assumptions": ["Growth persists."],
            "interpretation": "Renewal quality needs validation.",
            "risks": ["The sample is unverified."],
            "openQuestions": ["What are cohort renewal rates?"],
        }
        fake_response = self.FakeResponse({"output_text": json.dumps(report)})
        urlopen_mock = Mock(return_value=fake_response)
        status, result = self.post(
            {"companyId": "NOVA"},
            configured=True,
            urlopen_mock=urlopen_mock,
        )
        self.assertEqual(status, 201)
        urlopen_mock.assert_called_once()
        request = urlopen_mock.call_args.args[0]
        sent = json.loads(request.data)
        supplied_tracker = json.loads(sent["input"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-key")
        self.assertEqual(supplied_tracker["ticker"], "NOVA")
        self.assertNotIn("notes", supplied_tracker)
        self.assertNotIn("watchlist", supplied_tracker)
        run = result["run"]
        self.assertEqual(run["report"], report)
        self.assertEqual(run["provider"], "OpenAI API")
        self.assertIn("no external sources", run["scope"])
        self.assertTrue(run["createdAt"])
        self.assertEqual(len(result["saved_state"]["researchRuns"]), 1)

    def test_invalid_company_is_rejected_without_calling_provider(self):
        status, result = self.post({"companyId": "UNKNOWN"}, configured=True)
        self.assertEqual(status, 400)
        self.assertIn("valid company", result["error"])


class PortfolioRadarActionEndpointTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.payload

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_patch = patch.object(server, "STATE_PATH", root / "state" / "user_state.json")
        self.data_patch = patch.object(server, "DATA_DIR", root)
        self.environ_patch = patch.dict(
            "os.environ",
            {
                "PORTFOLIO_RADAR_ACTION_TOKEN": "a" * 48,
                "PORTFOLIO_RADAR_DASHBOARD_TOKEN": "b" * 48,
                "PORTFOLIO_RADAR_PASSWORD": "Private-Test-Password-48",
            },
            clear=True,
        )
        self.state_patch.start()
        self.data_patch.start()
        self.environ_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), server.RadarHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.environ_patch.stop()
        self.data_patch.stop()
        self.state_patch.stop()
        self.temporary_directory.cleanup()

    def request(self, method, path, body=None, token=None):
        headers = {}
        encoded_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(body)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.connection.request(method, path, encoded_body, headers)
        response = self.connection.getresponse()
        result = json.loads(response.read())
        return response.status, result

    @staticmethod
    def research_payload():
        return {
            "query": "What changed in the latest earnings report?",
            "model": "ChatGPT",
            "report": {
                "facts": [
                    {
                        "statement": "Revenue grew 12% year over year.",
                        "sourceUrls": ["https://example.com/results"],
                    }
                ],
                "assumptions": ["The reported growth is comparable."],
                "interpretation": "Growth accelerated.",
                "risks": ["One quarter may not indicate a trend."],
                "openQuestions": ["How did margins change?"],
                "sources": [
                    {
                        "title": "Company results",
                        "url": "https://example.com/results",
                        "publishedAt": "2026-10-08",
                    }
                ],
            },
        }

    def test_action_requires_bearer_authentication_and_saves_cited_research(self):
        status, result = self.request("POST", "/api/actions/research-runs", self.research_payload())
        self.assertEqual(status, 401)
        self.assertIn("bearer token", result["error"])

        status, result = self.request(
            "POST",
            "/api/actions/research-runs",
            self.research_payload(),
            token="a" * 48,
        )
        self.assertEqual(status, 201)
        run = result["run"]
        self.assertEqual(run["kind"], "chatgpt_action")
        self.assertEqual(run["report"]["facts"][0]["sourceUrls"], ["https://example.com/results"])
        self.assertEqual(len(server.load_state()["researchRuns"]), 1)

    def test_action_rejects_invalid_and_unmatched_citations(self):
        payload = self.research_payload()
        payload["report"]["facts"][0]["sourceUrls"] = ["https://unlisted.example/source"]
        status, result = self.request(
            "POST",
            "/api/actions/research-runs",
            payload,
            token="a" * 48,
        )
        self.assertEqual(status, 400)
        self.assertIn("report.sources", result["error"])
        self.assertEqual(server.load_state()["researchRuns"], [])

    def test_dashboard_uses_a_separate_read_only_token(self):
        status, _ = self.request(
            "POST",
            "/api/actions/research-runs",
            self.research_payload(),
            token="a" * 48,
        )
        self.assertEqual(status, 201)

        status, result = self.request("GET", "/api/dashboard/research-runs", token="a" * 48)
        self.assertEqual(status, 401)
        status, result = self.request("GET", "/api/dashboard/research-runs", token="b" * 48)
        self.assertEqual(status, 200)
        self.assertEqual(len(result["researchRuns"]), 1)
        self.assertEqual(result["researchRuns"][0]["kind"], "chatgpt_action")


if __name__ == "__main__":
    unittest.main()
