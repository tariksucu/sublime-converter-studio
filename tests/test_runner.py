import os
import sys
import threading
import time
import unittest

from converterstudio import runner

from .helpers import PYTHON, TempDirTest

POSIX = os.name != "nt"


def alive(pid):
    """Whether a process runs (a zombie waiting for its parent counts as ended)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as handle:
            return handle.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


class RunnerTest(TempDirTest):
    def test_success_and_output(self):
        result = runner.run([PYTHON, "-c", "print('hello'); import sys; sys.stderr.write('warn')"], 30)
        self.assertTrue(result.ok)
        self.assertIn("hello", result.output)
        self.assertIn("warn", result.output)

    def test_failure_keeps_the_last_lines(self):
        result = runner.run([PYTHON, "-c", "import sys; print('x' * 9000); print('the end'); sys.exit(3)"], 30)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 3)
        self.assertTrue(result.summary().endswith("the end"))
        self.assertLessEqual(len(result.summary()), 601)

    def test_a_missing_program(self):
        result = runner.run([os.path.join(self.dir, "no-such-tool")], 30)
        self.assertFalse(result.ok)
        self.assertIn("could not be started", result.error)

    def test_environment_and_folder(self):
        result = runner.run(
            [PYTHON, "-c", "import os; print(os.environ['CS_X'], os.getcwd())"], 30, cwd=self.dir, env={"CS_X": "42"}
        )
        self.assertIn("42", result.output)
        self.assertIn(os.path.realpath(self.dir), os.path.realpath(result.output.split()[-1]))

    def test_timeout_stops_it(self):
        started = time.monotonic()
        result = runner.run([PYTHON, "-c", "import time; time.sleep(60)"], 0.5)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.ok)
        self.assertLess(time.monotonic() - started, 10)

    @unittest.skipUnless(POSIX, "process groups")
    def test_cancel_stops_the_tool_and_what_it_started(self):
        marker = os.path.join(self.dir, "child.pid")
        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "open(%r, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n" % marker
        )
        flag = threading.Event()
        threading.Timer(1.5, flag.set).start()
        result = runner.run([PYTHON, "-c", script], 60, cancelled=flag.is_set)
        self.assertTrue(result.canceled)
        with open(marker) as handle:
            child = int(handle.read())
        time.sleep(0.3)
        self.assertFalse(alive(child))  # what the tool started is gone too

    def test_python_used_by_tests_exists(self):
        self.assertTrue(os.path.exists(PYTHON), PYTHON)
        self.assertTrue(sys.version_info >= (3, 8))


if __name__ == "__main__":
    unittest.main()
