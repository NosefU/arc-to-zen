"""Steps that walk Zen's session files cope with each layout of them."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arc2zen.folder_states import set_folder_states  # noqa: E402
from arc2zen.sessions import session_window  # noqa: E402
from arc2zen.workspace_icons import update_space_icons  # noqa: E402
from arc2zen.workspace_themes import spaces_from_session  # noqa: E402

SPACE = {"uuid": "{s1}", "name": "Work"}
FOLDER = {"id": "f1", "name": "Docs", "workspaceId": "{s1}", "collapsed": True}
STATES = {("Work", ("Docs",)): True}


class SessionLayouts(unittest.TestCase):
    def test_recovery_file_without_windows(self):
        # Zen leaves sessionstore-backups/recovery.jsonlz4 with no window (issue #1)
        data = {"windows": []}
        self.assertEqual(session_window(data), {})
        self.assertEqual(set_folder_states(data, STATES), (0, 0))
        self.assertEqual(spaces_from_session(data), [])
        self.assertEqual(update_space_icons(session_window(data).get("spaces", []), {"Work": "📁"}), 0)

    def test_folder_state_in_each_layout(self):
        for data in ({"spaces": [dict(SPACE)], "folders": [dict(FOLDER)]},
                     {"windows": [{"spaces": [dict(SPACE)], "folders": [dict(FOLDER)]}]}):
            self.assertEqual(set_folder_states(data, STATES), (1, 1))
            self.assertFalse(session_window(data)["folders"][0]["collapsed"])


if __name__ == "__main__":
    unittest.main()
