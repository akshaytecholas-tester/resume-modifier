"""Server-sent events (spec-04 §4, §5).

Two channels. Run progress is per-run; knowledge-base changes are global.

Streaming rather than polling (AC-R14.2), and stage events carry token counts
so cost accrues visibly during a run instead of being discovered afterwards.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Filesystem events are coalesced over this window. A single editor save
#: produces several — a write, a rename, sometimes a chmod — and forwarding
#: each one makes the UI reload three times for one save.
DEBOUNCE_SECONDS = 0.2


def format_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class Channel:
    """A fan-out queue. Subscribers that fall behind are dropped, not blocked.

    A browser tab that stops reading must never stall a pipeline run, so a full
    queue loses events rather than applying backpressure to the producer.
    """

    maxsize: int = 100

    def __post_init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def publish(self, event: str, data: Any) -> None:
        message = format_event(event, data)
        for queue in list(self._subscribers):
            # Dropped, not awaited: a browser tab that stopped reading must
            # never stall a pipeline run.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    async def subscribe(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.maxsize)
        self._subscribers.add(queue)
        try:
            # An immediate event so the client knows the stream is live rather
            # than waiting on a connection that may have silently failed.
            yield format_event("open", {"ok": True})
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    # Comment frame: keeps proxies and browsers from closing an
                    # idle connection.
                    yield ": keep-alive\n\n"
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class Hub:
    """Every channel in the process: one per run, plus a global KB channel."""

    def __init__(self) -> None:
        self.kb = Channel()
        self._runs: dict[str, Channel] = defaultdict(Channel)

    def run(self, run_id: str) -> Channel:
        return self._runs[run_id]

    def publish_stage(self, run_id: str, stage: str, status: str, detail: dict) -> None:
        self.run(run_id).publish("stage", {"stage": stage, "status": status, **detail})


class KbWatcher:
    """Watches `kb/` and republishes changes to the global channel (AC-R8.2).

    Editing in the browser, editing in vim and an agent proposal are three
    paths to the same bytes (spec-01 P1), so the UI has to learn about the
    other two.
    """

    def __init__(self, kb_dir: Path, hub: Hub) -> None:
        self.kb_dir = kb_dir
        self.hub = hub
        self._observer = None
        self._pending: dict[str, float] = {}

    def start(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return

        loop = asyncio.get_event_loop()
        hub, kb_dir, pending = self.hub, self.kb_dir, self._pending

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:
                if event.is_directory:
                    return
                path = Path(event.src_path)
                if path.suffix not in (".md", ".yaml") or path.name.endswith(".tmp"):
                    return

                now = loop.time() if loop.is_running() else 0.0
                last = pending.get(str(path), 0.0)
                if now - last < DEBOUNCE_SECONDS:
                    return
                pending[str(path)] = now

                try:
                    relative = str(path.relative_to(kb_dir))
                except ValueError:
                    relative = path.name
                loop.call_soon_threadsafe(
                    hub.kb.publish, "kb-change", {"path": relative, "kind": event.event_type}
                )

        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.kb_dir), recursive=True)
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
