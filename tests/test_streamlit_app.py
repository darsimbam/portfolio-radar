import json
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import streamlit_app
import server


class StreamlitStateMutationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.state_path_patch = patch.object(server, "STATE_PATH", root / "state" / "user_state.json")
        self.data_path_patch = patch.object(server, "DATA_DIR", root)
        self.state_path_patch.start()
        self.data_path_patch.start()
        self.addCleanup(self.state_path_patch.stop)
        self.addCleanup(self.data_path_patch.stop)

    def test_save_note_persists_note_for_selected_company(self):
        streamlit_app.save_note("NOVA", "  Revisit the renewal assumption.  ")
        note = server.load_state()["notes"][0]
        self.assertEqual(note["companyId"], "NOVA")
        self.assertEqual(note["companyName"], "Novaline Systems")
        self.assertEqual(note["text"], "Revisit the renewal assumption.")
        self.assertIn("createdAt", note)

    def test_open_research_run_is_saved_with_query_and_sources(self):
        run = streamlit_app.save_open_research_run(
            "Recent earnings developments",
            {
                "model": "test-model",
                "report": {"text": "Facts\nA cited update."},
                "sources": [{"title": "Source", "url": "https://example.com"}],
            },
        )
        saved = server.load_state()["researchRuns"][0]
        self.assertEqual(run["query"], "Recent earnings developments")
        self.assertEqual(saved["kind"], "web_research")
        self.assertEqual(saved["sources"][0]["url"], "https://example.com")
        self.assertTrue(saved["createdAt"])

    def test_research_citations_are_rendered_as_clickable_https_links(self):
        text = "Facts: Reported update."
        start = text.index("Reported update.")
        linked = streamlit_app.link_research_citations(
            text,
            [
                {
                    "startIndex": start,
                    "endIndex": len(text),
                    "url": "https://example.com/research",
                }
            ],
        )
        self.assertIn("[Reported update.](<https://example.com/research>)", linked)
        self.assertEqual(
            streamlit_app.link_research_citations(
                text,
                [{"startIndex": start, "endIndex": len(text), "url": "javascript:alert(1)"}],
            ),
            text,
        )

    def test_fetch_action_research_uses_configured_https_read_token(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"researchRuns": [{"id": "chatgpt-test"}]}).encode()

        with (
            patch.dict(
                os.environ,
                {
                    "PORTFOLIO_RADAR_ACTION_API_URL": "https://radar.example",
                    "PORTFOLIO_RADAR_DASHBOARD_TOKEN": "b" * 48,
                },
                clear=True,
            ),
            patch(
                "streamlit_app.configured_secret",
                side_effect=lambda key: os.getenv(key, ""),
            ),
            patch("streamlit_app.urlopen", return_value=FakeResponse()) as request_mock,
        ):
            self.assertTrue(streamlit_app.dashboard_action_sync_configured())
            runs = streamlit_app.fetch_action_research_runs()

        request = request_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://radar.example/api/dashboard/research-runs")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "b" * 48)
        self.assertEqual(runs, [{"id": "chatgpt-test"}])

    def test_fetch_action_research_rejects_non_https_api_url(self):
        with (
            patch.dict(
                os.environ,
                {
                    "PORTFOLIO_RADAR_ACTION_API_URL": "http://radar.example",
                    "PORTFOLIO_RADAR_DASHBOARD_TOKEN": "b" * 48,
                },
                clear=True,
            ),
            patch(
                "streamlit_app.configured_secret",
                side_effect=lambda key: os.getenv(key, ""),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "valid HTTPS"):
                streamlit_app.fetch_action_research_runs()

    def test_save_note_rejects_empty_text_and_unknown_company(self):
        with self.assertRaisesRegex(ValueError, "1–2000 characters"):
            streamlit_app.save_note("NOVA", " ")
        with self.assertRaisesRegex(ValueError, "valid company"):
            streamlit_app.save_note("UNKNOWN", "A note")

    def test_watchlist_toggle_adds_and_removes_valid_company(self):
        self.assertTrue(streamlit_app.toggle_watchlist("ORBT"))
        self.assertIn("ORBT", server.load_state()["watchlist"])
        self.assertFalse(streamlit_app.toggle_watchlist("ORBT"))
        self.assertNotIn("ORBT", server.load_state()["watchlist"])

    def test_watchlist_toggle_rejects_unknown_company(self):
        with self.assertRaisesRegex(ValueError, "valid company"):
            streamlit_app.toggle_watchlist("UNKNOWN")

    def test_password_gate_and_all_workspace_pages_render(self):
        app_path = Path(streamlit_app.__file__)
        with patch.dict(
            os.environ,
            {"PORTFOLIO_RADAR_PASSWORD": "streamlit-test-password", "OPENAI_API_KEY": ""},
        ):
            app = AppTest.from_file(str(app_path)).run(timeout=20)
            self.assertEqual(len(app.text_input), 1)
            app.text_input[0].set_value("streamlit-test-password")
            app.button[0].click().run(timeout=20)
            self.assertEqual(len(app.exception), 0)

            next(button for button in app.button if button.label == "Open tracker").click().run(timeout=20)
            self.assertEqual(app.sidebar.radio[0].value, "Company trackers")
            self.assertEqual(app.session_state["selected_company"], "NOVA")
            self.assertEqual(len(app.exception), 0)

            for page in (
                "Research desk",
                "Discovery",
                "Notes & watchlists",
                "Review templates",
                "Overview",
            ):
                app.sidebar.radio[0].set_value(page).run(timeout=20)
                self.assertEqual(len(app.exception), 0, page)

            app.sidebar.radio[0].set_value("Notes & watchlists").run(timeout=20)
            app.text_area[0].set_value("Validate the sample retention assumption.")
            next(button for button in app.button if button.label == "Save note").click().run(timeout=20)
            self.assertEqual(
                server.load_state()["notes"][0]["text"],
                "Validate the sample retention assumption.",
            )
            next(button for button in app.button if button.label == "Add").click().run(timeout=20)
            self.assertIn("ORBT", server.load_state()["watchlist"])
            self.assertEqual(len(app.exception), 0)

    def test_research_desk_renders_saved_web_report_and_citation(self):
        cited_text = "A company filed an update."
        report = f"## Facts\n{cited_text}"
        start = report.index(cited_text)
        streamlit_app.save_open_research_run(
            "Recent company filing",
            {
                "model": "test-model",
                "report": {"text": report},
                "sources": [
                    {
                        "title": "Company filing",
                        "url": "https://example.com/filing",
                        "startIndex": start,
                        "endIndex": start + len(cited_text),
                        "citedText": cited_text,
                    }
                ],
            },
        )

        app_path = Path(streamlit_app.__file__)
        with patch.dict(
            os.environ,
            {"PORTFOLIO_RADAR_PASSWORD": "streamlit-test-password", "OPENAI_API_KEY": ""},
        ):
            app = AppTest.from_file(str(app_path)).run(timeout=20)
            app.text_input[0].set_value("streamlit-test-password")
            app.button[0].click().run(timeout=20)
            app.sidebar.radio[0].set_value("Research desk").run(timeout=20)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("A company filed an update." in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
