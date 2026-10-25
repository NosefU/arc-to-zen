"""What the window's log gets when a step fails."""

import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arc2zen.migration import CallbackLogHandler  # noqa: E402
from arc2zen.zen_runner import log_output_tail  # noqa: E402


class StepErrors(unittest.TestCase):
    def test_traceback_on_lines_of_its_own(self):
        lines = []
        logger = logging.getLogger("test.step")
        logger.addHandler(CallbackLogHandler(lines.append))
        try:
            raise OSError("locked")
        except OSError as exc:
            logger.error(f"❌ Could not read: {exc}", exc_info=True)
        # The window takes the "❌" line as the step's note, so it stays one short line
        self.assertEqual(lines[0], "❌ Could not read: locked")
        self.assertTrue(lines[1].startswith("Traceback (most recent call last):"))
        self.assertIn("OSError: locked", lines[1])


class HeadlessZenOutput(unittest.TestCase):
    def test_last_lines_and_exit_code(self):
        output = tempfile.TemporaryFile()
        process = subprocess.Popen([sys.executable, "-c", "for i in range(60): print('line', i)"],
                                   stdout=output, stderr=subprocess.STDOUT)
        process.wait()
        with self.assertLogs("arc2zen.zen_runner", level="INFO") as logs:
            log_output_tail(output, process, lines=3)
        output.close()
        message = logs.output[0]
        self.assertIn("exited with code 0", message)
        self.assertIn("line 59", message)
        self.assertNotIn("line 56", message)


if __name__ == "__main__":
    unittest.main()
