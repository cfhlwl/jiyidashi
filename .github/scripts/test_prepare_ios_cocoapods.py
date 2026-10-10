#!/usr/bin/env python3
"""Regression test for CocoaPods process-group cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prepare_ios_cocoapods import terminate_process_group  # noqa: E402


@unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
class ProcessGroupCleanupTest(unittest.TestCase):
    def test_child_is_killed_after_leader_exits_on_sigterm(self) -> None:
        child_code = (
            "import signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)"
        )
        leader_code = (
            "import signal,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
            "print(child.pid, flush=True); "
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
            "time.sleep(60)"
        )
        leader = subprocess.Popen(
            [sys.executable, "-c", leader_code, child_code],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert leader.stdout is not None
        child_pid = int(leader.stdout.readline().strip())

        try:
            terminate_process_group(leader)
            self.assertIsNotNone(leader.poll())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.05)
            self.fail("child downloader survived process-group cleanup")
        finally:
            if leader.poll() is None:
                terminate_process_group(leader)


if __name__ == "__main__":
    unittest.main()
