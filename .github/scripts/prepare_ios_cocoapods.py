#!/usr/bin/env python3
"""Install iOS CocoaPods dependencies with bounded, cancellable retries.

This is CI infrastructure only. It deliberately does not alter Podfile
resolution or production application configuration.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop pod and any child downloader it started."""

    try:
        process_group_id = os.getpgid(process.pid)
    except ProcessLookupError:
        return

    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass

    # Do not make SIGKILL conditional on the leader still being alive.  A
    # SIGTERM handler may let the pod leader exit while a downloader child
    # remains in the same process group.
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_attempt(timeout_seconds: int, working_directory: Path) -> int:
    command = ["pod", "install", "--no-repo-update"]
    print(f"running {' '.join(command)} (timeout={timeout_seconds}s)", flush=True)
    process = subprocess.Popen(
        command,
        cwd=working_directory,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"pod install exceeded {timeout_seconds}s; terminating its process group",
            flush=True,
        )
        terminate_process_group(process)
        return 124


def main() -> int:
    attempts = int(os.environ.get("COCOAPODS_MAX_ATTEMPTS", "3"))
    timeout_seconds = int(os.environ.get("COCOAPODS_ATTEMPT_TIMEOUT_SECONDS", "420"))
    retry_delay_seconds = int(os.environ.get("COCOAPODS_RETRY_DELAY_SECONDS", "10"))
    # All current callers run with mobile/ as their working directory.
    working_directory = Path(os.environ.get("COCOAPODS_WORKING_DIRECTORY", "ios"))

    if attempts < 1 or timeout_seconds < 1 or retry_delay_seconds < 0:
        print("invalid CocoaPods retry configuration", file=sys.stderr)
        return 2

    for attempt in range(1, attempts + 1):
        print(f"CocoaPods install attempt {attempt}/{attempts}", flush=True)
        status = run_attempt(timeout_seconds, working_directory)
        if status == 0:
            print("CocoaPods install completed", flush=True)
            return 0
        if attempt == attempts:
            print(f"CocoaPods install failed with status {status}", file=sys.stderr)
            return status or 1
        delay = retry_delay_seconds * attempt
        print(f"retrying CocoaPods install after {delay}s", flush=True)
        time.sleep(delay)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
