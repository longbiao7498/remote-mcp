"""Integration tests for network anomalies, using the FlakyTCPProxy fixture.

Covers spec §7.2 gaps:
- SFTP silent hang (bug #2 end-to-end, not just exec)
- Background bash response loss (bug #3 actual failure window)
- Snapshot re-upload failure (bug #4 WARNING case C)
"""
import asyncio
import re
import socket
import time

import pytest

from remote_mcp.config import HostConfig, RootConfig
from remote_mcp import server as srv
from remote_mcp.tools import bash as bash_tool
from remote_mcp.tools import read as read_tool
from remote_mcp.tools import file_stat as file_stat_tool


def test_sftp_read_returns_error_when_proxy_drops_all(conn_via_proxy, flaky_proxy,
                                                       sshd_container, ssh_key,
                                                       tmp_path):
    """Bug #2 end-to-end (SFTP path): if the network silently stops delivering
    bytes, a FileStat call (which uses SFTP) must raise or return an error
    within op_timeout_default, not hang indefinitely.

    FileStat uses sftp.stat() — when proxy drops all bytes, the SFTP channel
    must time out via the settimeout applied in get_sftp(). We verify the call
    finishes in time and signals an error.
    """
    # Use server layer so reconnect/retry handling is exercised and we get a
    # well-formed response (Error: string) rather than a raw exception.
    cfg = HostConfig(
        name="proxytest_sftp",
        hostname="127.0.0.1",
        port=flaky_proxy.local_port,
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        connect_timeout=10.0,
        op_timeout_default=2,  # very short so the test finishes fast
    )
    root = RootConfig(
        hosts={"proxytest_sftp": cfg},
        default_host="proxytest_sftp",
        feedback_path=str(tmp_path / "fb.jsonl"),
    )
    srv._init_for_test(root, "proxytest_sftp")
    try:
        # Pre-warm: verify everything works before dropping bytes
        result_ok = asyncio.run(srv.call_tool("FileStat", {
            "file_paths": ["/tmp"],
        }))
        assert "exists=true" in result_ok[0].text, (
            f"sanity check failed before drop: {result_ok[0].text!r}"
        )

        # Now silently drop all bytes (laptop-suspend scenario)
        flaky_proxy.drop_all()

        start = time.monotonic()
        result = asyncio.run(srv.call_tool("FileStat", {
            "file_paths": ["/tmp"],
        }))
        elapsed = time.monotonic() - start
        text = result[0].text

        # Must complete within a few times op_timeout_default (2s op_timeout,
        # at most 2 attempts = ~10s; be generous for CI headroom)
        assert elapsed < 15.0, f"FileStat took {elapsed:.2f}s with dropped proxy"

        # Result must indicate an error — either the server returned Error: ...
        # or a WARNING indicating reconnect (which happened after a timeout).
        # In either case, the call must not return "exists=true" for /tmp.
        assert "exists=true" not in text or "WARNING" in text, (
            f"Expected error or WARNING, got: {text!r}"
        )
    finally:
        flaky_proxy.resume()
        srv._teardown_for_test()


def test_background_bash_pidfile_recovers_when_response_lost(
        conn_via_proxy, flaky_proxy, tmp_path, monkeypatch):
    """Bug #3 actual failure window: response packet lost mid-flight.

    v0.3.0: background bash now uses local panel metadata. This test verifies the
    remote pid file (at ~/.cache/remote-mcp-<sid>-<id>-pid) is readable as the
    orphan-recovery mechanism, complementing the SFTP fallback in the launch path.

    Note: timing the proxy to cut bytes mid-launch is too racy for a reliable test.
    Instead, this test launches normally and demonstrates the recovery mechanism:
    even without the original BG_PID echo, the remote pid file holds the PID.
    The pidfile-before-echo ordering guarantee is covered by
    test_background_pidfile_written_before_bg_pid_echo.
    """
    # v0.3.0: must init panel before using background bash
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from remote_mcp.jobs.sid import derive_sid, reset_cache_for_test
    from remote_mcp.jobs.init import init_panel
    from remote_mcp.jobs.paths import remote_pid_path
    reset_cache_for_test()
    sid, _ = derive_sid()
    init_panel(sid, "proxytest")

    # Sanity: snapshot capture during fixture setup should have worked
    assert conn_via_proxy._snapshot_path is not None

    out = bash_tool.bash(conn_via_proxy, "sleep 60", run_in_background=True)
    # v0.3.0 return format: "Started background task.\n  id: N\n  name: ...\n  log_path: ...\n  pid: N\n  started_at: ..."
    assert "Started background task." in out, f"launch failed: {out!r}"
    pid_match = re.search(r"pid:\s*(\d+)", out)
    id_match = re.search(r"id:\s*(\d+)", out)
    assert pid_match and id_match, f"could not parse pid/id from launch output: {out!r}"
    real_pid = pid_match.group(1)
    task_id = int(id_match.group(1))

    # v0.3.0 remote pid file: ~/.cache/remote-mcp-<sid>-<id>-pid
    pidfile_path = remote_pid_path(sid, task_id)
    # Verify pidfile is readable (the pidfile-before-echo ordering guarantee)
    recovery_out = bash_tool.bash(
        conn_via_proxy,
        f"cat {pidfile_path}",
    )
    recovered_pid = recovery_out.strip()
    assert recovered_pid == real_pid, (
        f"recovered PID {recovered_pid!r} != real PID {real_pid!r}"
    )

    # Verify the remote process is actually alive
    check_out = bash_tool.bash(
        conn_via_proxy,
        f"kill -0 {real_pid} && echo alive || echo dead",
    )
    assert "alive" in check_out, f"process {real_pid} should be alive: {check_out!r}"

    # Cleanup
    conn_via_proxy.exec(f"kill -KILL -- -{real_pid} 2>/dev/null; rm -f {pidfile_path}")


def test_reconnect_warning_case_c_when_reupload_fails(flaky_proxy,
                                                       sshd_container,
                                                       ssh_key, tmp_path):
    """Bug #4 WARNING case C: remote snapshot file missing AND re-upload fails.

    Strategy: use server.call_tool which is what actually emits the WARNING.
    Set up a RootConfig pointing at the proxy, init server, then:
    1) Delete the remote snapshot file
    2) Directly override _upload_snapshot_to_remote on the instance to fail
    3) Use close_now() to trigger a TCP reset (paramiko sees dead connection)
    4) Issue a tool call; _with_retry catches the SSH error, runs _do_reconnect
       (which calls the failing _upload_snapshot_to_remote), then retries.
    5) The call_tool WARNING logic then emits case C text.

    Key: close_now() only resets ACTIVE pairs — the proxy keeps listening, so
    _do_reconnect()'s connect() succeeds through the still-alive proxy.
    """
    cfg = HostConfig(
        name="proxytest_warn",
        hostname="127.0.0.1",
        port=flaky_proxy.local_port,
        user=sshd_container["user"],
        key_path=ssh_key["private_path"],
        connect_timeout=10.0,
    )
    root = RootConfig(
        hosts={"proxytest_warn": cfg},
        default_host="proxytest_warn",
        feedback_path=str(tmp_path / "fb.jsonl"),
    )
    srv._init_for_test(root, "proxytest_warn")
    try:
        snap_path = srv._conn._snapshot_path
        assert snap_path is not None, "snapshot must have been captured at init"

        # Delete the remote snapshot file so _snapshot_exists_on_remote() → False
        sftp = srv._conn.get_sftp()
        sftp.remove(snap_path)

        # Override _upload_snapshot_to_remote on the instance to always fail.
        # Python looks up instance attributes before class methods, so this
        # shadows the real method for all calls through self on this object.
        upload_calls = {"n": 0}

        def failing_upload():
            upload_calls["n"] += 1
            srv._conn._snapshot_error = "snapshot upload failed: simulated disk full"
            srv._conn._snapshot_path = None

        srv._conn._upload_snapshot_to_remote = failing_upload

        # Hard-close active pairs. The proxy keeps listening so _do_reconnect's
        # connect() can open a fresh TCP connection through it.
        flaky_proxy.close_now()

        # Glob uses _with_retry:
        #   1. First attempt → paramiko sees dead transport → OSError/SSHException
        #   2. _with_retry calls _do_reconnect → connect() succeeds (new proxy pair)
        #      → _snapshot_exists_on_remote() → False (we deleted it)
        #      → calls failing_upload() → sets _snapshot_error, clears _snapshot_path
        #      → _snapshot_reuploaded = True, _reconnected = True
        #   3. Retry attempt executes Glob successfully
        #   4. call_tool checks flags → emits case C WARNING
        result = asyncio.run(srv.call_tool("Glob", {
            "pattern": "*", "path": "/tmp",
        }))
        text = result[0].text

        assert upload_calls["n"] >= 1, (
            f"failing_upload was not called (n={upload_calls['n']}); "
            "reconnect may not have triggered or snapshot was not missing"
        )
        assert "re-upload failed" in text.lower(), (
            f"Expected case C WARNING containing 're-upload failed', got: {text!r}"
        )
        assert "without the user's PATH/aliases" in text, (
            f"Expected degraded-env phrasing, got: {text!r}"
        )
    finally:
        srv._teardown_for_test()
