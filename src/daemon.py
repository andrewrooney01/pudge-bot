"""Long-running daemon for the orb.

Two cadences in one process:

- **Chat thread** (main thread) — long-polls Telegram for new replies.
  `get_updates(timeout=25)` blocks server-side until a message arrives or
  the timeout fires, so commands feel sub-second and the daemon sits
  idle at ~0 CPU otherwise.

- **Scanner thread** (background) — once a minute, scans iCloud for new
  voice notes and Apple Notes for newly-quiet entries. This work is
  fundamentally batch (files appear; you don't sit waiting), so a 60s
  cadence is correct.

Replaces the launchd `StartInterval=60` plist that re-spawned `orb.py`
every minute. The new plist uses `KeepAlive=true` so launchd restarts
the daemon on crash.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import traceback

from config import LOGS_DIR

import db
import inbox
import notes_inbox
import orb


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "orb.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("orb.daemon")


# Telegram long-poll timeout. Kept under launchd's default ExitTimeOut (20s)
# so a SIGTERM during an idle wait still drains within budget — the chat
# thread can't be interrupted mid-request from another thread.
LONG_POLL_SECS = 15
SCANNER_INTERVAL_SECS = 60
POLL_BACKOFF_SECS = 5  # back off briefly after an inbox failure to avoid hot-looping


stop = threading.Event()


def _scanner_loop() -> None:
    """Voice-note + Apple-Note ingest, every SCANNER_INTERVAL_SECS."""
    log.info("scanner thread started (interval=%ds)", SCANNER_INTERVAL_SECS)
    while not stop.is_set():
        try:
            new = orb.find_new_recordings()
            if new:
                log.info("scanner: %d new recording(s)", len(new))
                for path in new:
                    if stop.is_set():
                        break
                    try:
                        orb.process(path)
                    except Exception:
                        log.error("failed processing %s\n%s", path, traceback.format_exc())
        except Exception:
            log.error("scanner: recording scan failed\n%s", traceback.format_exc())

        try:
            ready = notes_inbox.find_ready_notes(db.already_processed_note)
            if ready:
                log.info("scanner: %d ready note(s)", len(ready))
                for note in ready:
                    if stop.is_set():
                        break
                    try:
                        orb.process_note(note)
                    except Exception:
                        log.error(
                            "failed processing note %s\n%s",
                            note.get("id"),
                            traceback.format_exc(),
                        )
        except Exception:
            log.error("scanner: note scan failed\n%s", traceback.format_exc())

        stop.wait(SCANNER_INTERVAL_SECS)
    log.info("scanner thread stopped")


def _chat_loop() -> None:
    """Telegram long-poll → answer. Runs on the main thread."""
    log.info("chat thread started (long-poll timeout=%ds)", LONG_POLL_SECS)
    while not stop.is_set():
        try:
            messages = inbox.poll_all(timeout=LONG_POLL_SECS)
        except Exception:
            log.error("chat: poll_all failed\n%s", traceback.format_exc())
            stop.wait(POLL_BACKOFF_SECS)
            continue

        if not messages:
            continue

        log.info("chat: %d new message(s)", len(messages))
        for msg in messages:
            try:
                orb.answer_question(msg)
            except Exception:
                log.error(
                    "failed answering update_id=%s\n%s",
                    msg.get("update_id"),
                    traceback.format_exc(),
                )
    log.info("chat thread stopped")


def _install_signal_handlers() -> None:
    def _handle(signum, _frame):
        log.info("received signal %d, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main() -> int:
    log.info("orb daemon starting (pid=%d)", os.getpid())
    db.init()
    _install_signal_handlers()

    scanner = threading.Thread(target=_scanner_loop, name="scanner", daemon=True)
    scanner.start()

    try:
        _chat_loop()
    finally:
        stop.set()
        scanner.join(timeout=10)
        log.info("orb daemon exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
