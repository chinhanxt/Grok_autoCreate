"""
Serialized Temp-Mail mailbox pool.

Pre-creates `count` mailboxes one at a time (never concurrently), caps the
number of mailboxes per proxy IP (`max_per_ip`), rotates to a fresh proxy IP
via `proxy_mgr.rotate_to_new_ip()` when the cap is reached, and handles
`TempMailRateLimitError` by rotating + retrying. Consumers take mailboxes in
FIFO order with `acquire()` and hand them back with `release()`.
"""
import queue
import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from core.tempmail import TempMailClient, TempMailRateLimitError

logger = logging.getLogger("xai_mailbox_pool")

ROTATE_TIMEOUT_SEC = 90  # rotate_to_new_ip deadline; proxyxoay cooldowns are 37-58s
ROTATE_MAX_ATTEMPTS = 3  # bounded retries before giving up on rotation
RATE_LIMIT_MAX_ATTEMPTS = 3  # initial create + retries before giving up on a mailbox
RATE_LIMIT_FALLBACK_SLEEP = 30.0  # wait when rotation fails and we must retry on same proxy


@dataclass
class MailboxEntry:
    email: str
    token: str
    proxy: Optional[str] = None


class MailboxPool:
    """
    FIFO pool of pre-created temp-mail inboxes.

    `proxy_mgr` may be None (direct connection, no proxy). When it is None,
    `current_proxy` stays None and proxy rotation is a no-op (returns failure).
    """

    def __init__(
        self,
        proxy_mgr,
        count: int,
        spacing: float = 12,
        max_per_ip: int = 4,
        stopped: Optional[Callable[[], bool]] = None,
    ):
        assert max_per_ip >= 1, f"max_per_ip must be >= 1 (got {max_per_ip})"
        self._proxy_mgr = proxy_mgr
        self.count = count
        self.spacing = spacing
        self.max_per_ip = max_per_ip
        self._stopped = stopped
        self._queue: "queue.Queue[MailboxEntry]" = queue.Queue()
        self._current_proxy: Optional[str] = None
        self._made_on_current_ip = 0

    def prepare(self) -> int:
        """Pre-create up to `count` mailboxes serially; returns how many were made."""
        made = 0
        if self.count <= 0:
            return made

        self._current_proxy = self._resolve_initial_proxy()

        while made < self.count:
            if self._is_stopped():
                logger.info(f"MailboxPool stopped early; {made}/{self.count} created")
                break

            if self._made_on_current_ip >= self.max_per_ip:
                if not self._rotate_with_retry():
                    logger.error(
                        f"Could not rotate proxy after {ROTATE_MAX_ATTEMPTS} attempts; "
                        f"stopping pre-create ({made}/{self.count} created)"
                    )
                    break
                continue

            entry = self._create_mailbox()
            if entry is None:
                logger.error(f"Mailbox creation failed; stopping pre-create ({made}/{self.count} created)")
                break

            self._queue.put(entry)
            made += 1
            self._made_on_current_ip += 1

            if made < self.count:
                time.sleep(self.spacing)

        logger.info(f"MailboxPool pre-created {made}/{self.count} mailboxes")
        return made

    def acquire(self, timeout: Optional[float] = None) -> Optional[MailboxEntry]:
        """
        FIFO take.

        `timeout=None` (default) blocks until a mailbox is available — the
        original blocking behavior. A float timeout waits up to that many
        seconds and returns None if the pool is still empty (e.g.
        `acquire(timeout=0)` is a non-blocking take that returns None
        immediately on an empty pool). Consumers must treat a None result as
        "pool exhausted" and fail cleanly.
        """
        if timeout is None:
            return self._queue.get()
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def release(self, entry: MailboxEntry) -> None:
        """Return a mailbox to the pool for reuse."""
        self._queue.put(entry)

    def _resolve_initial_proxy(self) -> Optional[str]:
        if self._proxy_mgr is None:
            return None
        try:
            ok, proxy_url, data = self._proxy_mgr.get_proxy()
        except Exception as e:
            logger.error(f"get_proxy failed: {e}; using direct connection")
            return None
        if ok and proxy_url:
            logger.info(f"MailboxPool using proxy: {proxy_url}")
            return proxy_url
        logger.warning(f"get_proxy failed ({data}); using direct connection")
        return None

    def _rotate_current_proxy(self) -> bool:
        """Single rotation attempt. On success updates current_proxy and resets the cap counter."""
        if self._proxy_mgr is None:
            logger.warning("No proxy manager available; cannot rotate")
            return False
        try:
            ok, proxy_url, data = self._proxy_mgr.rotate_to_new_ip(timeout_sec=ROTATE_TIMEOUT_SEC)
        except Exception as e:
            logger.error(f"rotate_to_new_ip failed: {e}")
            return False
        if ok and proxy_url:
            self._current_proxy = proxy_url
            self._made_on_current_ip = 0
            logger.info(f"MailboxPool rotated to proxy: {proxy_url}")
            return True
        logger.warning(f"Proxy rotation failed: {data}")
        return False

    def _rotate_with_retry(self) -> bool:
        """Rotate with bounded retries (waiting `spacing` between attempts)."""
        for attempt in range(1, ROTATE_MAX_ATTEMPTS + 1):
            if self._rotate_current_proxy():
                return True
            if attempt < ROTATE_MAX_ATTEMPTS:
                time.sleep(self.spacing)
        return False

    def _create_mailbox(self) -> Optional[MailboxEntry]:
        """
        Create one mailbox, retrying the same logical creation (bounded) on
        TempMailRateLimitError: rotate proxy first, else wait and retry once more.
        """
        for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
            try:
                client = TempMailClient(proxy=self._current_proxy)
                email, token = client.create_inbox()
                logger.info(f"MailboxPool created mailbox {email} on proxy {self._current_proxy}")
                return MailboxEntry(email=email, token=token, proxy=self._current_proxy)
            except TempMailRateLimitError as e:
                if attempt >= RATE_LIMIT_MAX_ATTEMPTS:
                    logger.error(f"Rate limited after {attempt} attempts; giving up on this mailbox")
                    return None
                logger.warning(
                    f"Rate limited (attempt {attempt}/{RATE_LIMIT_MAX_ATTEMPTS}): {e}; rotating proxy"
                )
                if self._rotate_current_proxy():
                    continue
                logger.warning("Rotation failed; waiting and retrying on same proxy")
                time.sleep(RATE_LIMIT_FALLBACK_SLEEP)
            except Exception as e:
                logger.error(f"Mailbox creation failed: {e}")
                return None
        return None

    def _is_stopped(self) -> bool:
        if self._stopped is None:
            return False
        try:
            return bool(self._stopped())
        except Exception as e:
            logger.error(f"stopped() callable raised: {e}")
            return False
