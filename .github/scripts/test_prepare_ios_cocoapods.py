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
    @staticmethod
    def _start_leader(leader_code: str, child_code: str) -> tuple[subprocess.Popen[str], int]:
        leader = subprocess.Popen(
            [sys.executable, "-c", leader_code, child_code],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert leader.stdout is not None
        child_pid = int(leader.stdout.readline().strip())
        return leader, child_pid

    @staticmethod
    def _assert_dead(child_pid: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        raise AssertionError("child downloader survived process-group cleanup")

    def _child_code(self) -> str:
        return (
            "import signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)"
        )

    def _leader_code(self, exit_status: int | None = None) -> str:
        exit_clause = "sys.exit(%d); " % exit_status if exit_status is not None else ""
        return (
            "import signal,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
            "print(child.pid, flush=True); "
            f"{exit_clause}"
            "time.sleep(60)"
        )

    def test_child_is_killed_after_leader_exits_on_sigterm(self) -> None:
        leader, child_pid = self._start_leader(
            self._leader_code(), self._child_code()
        )

        try:
            process_group_id = leader.pid
            os.kill(leader.pid, signal.SIGTERM)
            leader.wait(timeout=5)
            # Exercise the race: the leader is already reaped, but its child
            # remains in the original process group.
            terminate_process_group(leader, process_group_id)
            self.assertIsNotNone(leader.poll())
            self._assert_dead(child_pid)
        finally:
            if leader.poll() is None:
                terminate_process_group(leader, leader.pid)

    def test_child_is_killed_after_nonzero_leader_exit(self) -> None:
        leader, child_pid = self._start_leader(
            self._leader_code(exit_status=17), self._child_code()
        )
        process_group_id = leader.pid
        try:
            self.assertEqual(leader.wait(timeout=5), 17)
            # This is the failure/retry path: pod has returned non-zero and
            # was reaped, while its downloader remains in the process group.
            terminate_process_group(leader, process_group_id)
            self._assert_dead(child_pid)
        finally:
            if leader.poll() is None:
                terminate_process_group(leader, process_group_id)


if __name__ == "__main__":
    unittest.main()
