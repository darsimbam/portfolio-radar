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

if __name__ == "__main__":
    unittest.main()
