"""Bridge from OS signals to a graceful shutdown — the role ``signal.NotifyContext`` plays in Go."""

import asyncio


class Shutdown:
    """Two-stage shutdown request.

    The first ``request()`` asks for a graceful drain; a second one, arriving while
    the drain is still running, asks to stop waiting (Ctrl-C twice = "I mean it").
    ``main`` wires ``request`` to SIGINT/SIGTERM; the HTTP server watches the events.
    """

    def __init__(self) -> None:
        self.requested = asyncio.Event()
        self.forced = asyncio.Event()

    def request(self) -> None:
        if self.requested.is_set():
            self.forced.set()
            return
        self.requested.set()
