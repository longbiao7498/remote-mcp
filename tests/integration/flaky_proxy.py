"""In-process TCP proxy for simulating network anomalies in integration tests.

Listens on 127.0.0.1:<ephemeral-port>, forwards bytes to (target_host, target_port).
Control methods let test code interrupt forwarding mid-stream without touching the
remote-mcp code under test.
"""
import select
import socket
import threading
from typing import Optional


class FlakyTCPProxy:
    """A TCP proxy with externally-controllable failure modes.

    Lifecycle:
        proxy = FlakyTCPProxy("192.168.10.20", 22)
        # ... use proxy.local_port as paramiko's port ...
        proxy.shutdown()

    The proxy always keeps listening and accepting new connections.
    close_now() tears down active forwarding pairs (simulating a mid-session
    TCP reset) but leaves the proxy ready to accept the next connection.
    shutdown() stops the proxy entirely.
    """

    def __init__(self, target_host: str, target_port: int):
        self.target = (target_host, target_port)
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(("127.0.0.1", 0))
        self.local_port = self._listen_sock.getsockname()[1]
        self._listen_sock.listen(5)
        self._mode = "forward"
        self._bytes_from_remote_limit: Optional[int] = None
        self._bytes_from_remote_count = 0
        self._lock = threading.Lock()
        self._active_pairs = []  # list of (local_sock, remote_sock) currently forwarding
        self._shutdown = False
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    # --- control API used by tests ---

    def drop_all(self) -> None:
        """Silently stop forwarding in both directions. Sockets stay open
        (simulates 'TCP socket appears alive but no bytes flow' = laptop suspend).
        New connections established through the proxy will also be silently dropped.
        Call resume() to restore forwarding."""
        with self._lock:
            self._mode = "drop"

    def resume(self) -> None:
        """Resume normal forwarding (both for existing and new pairs)."""
        with self._lock:
            self._mode = "forward"

    def close_now(self) -> None:
        """Hard-close all CURRENTLY-ACTIVE forwarding pairs (simulates TCP reset
        mid-session, e.g. network cable pulled). The proxy keeps listening and
        will forward new connections normally, so reconnect attempts succeed.

        This is the primary mechanism for triggering paramiko reconnect in tests:
        after close_now(), the next tool call sees a dead transport and calls
        _do_reconnect(), which opens a new SSH connection through the still-
        listening proxy.
        """
        with self._lock:
            pairs_to_close = list(self._active_pairs)
        for local_sock, remote_sock in pairs_to_close:
            try:
                local_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                remote_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

    def limit_bytes_from_remote(self, n: int) -> None:
        """Allow only the first N bytes from remote to pass through; drop the rest.
        Useful for bug #3: cut the channel after the pidfile write but before
        the BG_PID echo response reaches local."""
        with self._lock:
            self._bytes_from_remote_limit = n
            self._bytes_from_remote_count = 0

    def reset_limits(self) -> None:
        """Clear any byte limit; full forwarding resumes."""
        with self._lock:
            self._bytes_from_remote_limit = None
            self._bytes_from_remote_count = 0
            self._mode = "forward"

    def shutdown(self) -> None:
        """Stop accepting new connections and tear down all active pairs.
        After shutdown() the proxy cannot be reused.
        """
        self._shutdown = True
        try:
            self._listen_sock.close()
        except Exception:
            pass
        # Close all active pairs so _forward() loops exit
        with self._lock:
            pairs_to_close = list(self._active_pairs)
        for local_sock, remote_sock in pairs_to_close:
            try:
                local_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                remote_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

    # --- internal forwarding logic ---

    def _accept_loop(self) -> None:
        while not self._shutdown:
            try:
                local_sock, _ = self._listen_sock.accept()
            except Exception:
                return
            t = threading.Thread(
                target=self._handle_one_connection,
                args=(local_sock,),
                daemon=True,
            )
            t.start()

    def _handle_one_connection(self, local_sock: socket.socket) -> None:
        try:
            remote_sock = socket.create_connection(self.target, timeout=5)
        except Exception:
            local_sock.close()
            return
        with self._lock:
            self._active_pairs.append((local_sock, remote_sock))
        try:
            self._forward(local_sock, remote_sock)
        finally:
            try:
                local_sock.close()
            except Exception:
                pass
            try:
                remote_sock.close()
            except Exception:
                pass
            with self._lock:
                if (local_sock, remote_sock) in self._active_pairs:
                    self._active_pairs.remove((local_sock, remote_sock))

    def _forward(self, local_sock: socket.socket, remote_sock: socket.socket) -> None:
        """Bidirectional forwarding with select() so we can interleave the two
        directions and check _mode / byte limits per chunk."""
        local_sock.setblocking(False)
        remote_sock.setblocking(False)
        while not self._shutdown:
            with self._lock:
                mode = self._mode
                limit = self._bytes_from_remote_limit
                count = self._bytes_from_remote_count
            try:
                rlist, _, xlist = select.select(
                    [local_sock, remote_sock], [], [local_sock, remote_sock], 0.1
                )
            except Exception:
                return
            if xlist:
                return
            for sock in rlist:
                try:
                    data = sock.recv(4096)
                except Exception:
                    return
                if not data:
                    return  # peer closed
                if mode == "drop":
                    continue  # silently discard
                if sock is remote_sock and limit is not None:
                    remaining = limit - count
                    if remaining <= 0:
                        # we've delivered all permitted bytes from remote;
                        # drop further data silently (the channel will appear
                        # to hang until op_timeout fires)
                        continue
                    if len(data) > remaining:
                        data = data[:remaining]
                    with self._lock:
                        self._bytes_from_remote_count += len(data)
                # forward to the other side
                target_sock = remote_sock if sock is local_sock else local_sock
                try:
                    target_sock.sendall(data)
                except Exception:
                    return
