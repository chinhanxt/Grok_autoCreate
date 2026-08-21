"""
Serialized Temp-Mail mailbox pool.

Pre-creates `count` mailboxes one at a time (never concurrently), caps the
number of mailboxes per proxy IP (`max_per_ip`), rotates to a fresh proxy IP
via `proxy_mgr.rotate_to_new_ip()` when the cap is reached, and handles
`TempMailRateLimitError` by rotating + retrying. When no `proxy_mgr` is given
but a fixed `initial_proxy` is, all mailboxes are created through that proxy
(no rotation, so no IP leaks). Consumers take mailboxes in FIFO order with
`acquire()` and hand them back with `release()`.
"""
import queue
import threading
import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from core.tempmail import TempMailClient, TempMailRateLimitError

logger = logging.getLogger("xai_mailbox_pool")

# Global serialization of mailbox creation: every MailboxPool instance (across
# all tasks/pools) shares this one lock so two concurrent pools never create
# mailboxes in parallel against the same exit IP.
MAILBOX_CREATE_LOCK = threading.Lock()

ROTATE_TIMEOUT_SEC = 20  # rotate_to_new_ip deadline
ROTATE_MAX_ATTEMPTS = 2  # bounded retries before giving up on rotation
RATE_LIMIT_MAX_ATTEMPTS = 3  # initial create + retries before giving up on a mailbox
RATE_LIMIT_FALLBACK_SLEEP = 2.0  # wait when rotation fails and we must retry on same proxy
MAX_CONSECUTIVE_CREATE_FAILURES = 3  # bounded consecutive failures before prepare() gives up


@dataclass
class MailboxEntry:
    email: str
    token: str
    proxy: Optional[str] = None


class MailboxPool:
    """
    FIFO pool of pre-created temp-mail inboxes.
    """

    def __init__(
        self,
        proxy_mgr,
        count: int,
        spacing: float = 0.5,
        max_per_ip: int = 6,
        stopped: Optional[Callable[[], bool]] = None,
        initial_proxy: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, Optional[MailboxEntry]], None]] = None,
    ):
        if max_per_ip < 1:
            raise ValueError(f"max_per_ip must be >= 1 (got {max_per_ip})")
        self._proxy_mgr = proxy_mgr
        self._initial_proxy = initial_proxy
        self.count = count
        self.spacing = spacing
        self.max_per_ip = max_per_ip
        self._stopped = stopped
        self.progress_callback = progress_callback
        self._queue: "queue.Queue[MailboxEntry]" = queue.Queue()
        self._current_proxy: Optional[str] = None
        self._made_on_current_ip = 0
        self._consecutive_failures = 0

    def prepare(self) -> int:
        """Pre-create up to `count` mailboxes serially; returns how many were made."""
        made = 0
        if self.count <= 0:
            return made

        self._current_proxy = self._resolve_initial_proxy()
        max_consec = 6 if self._is_tor() else MAX_CONSECUTIVE_CREATE_FAILURES

        while made < self.count:
            if self._is_stopped():
                logger.info(f"MailboxPool stopped early; {made}/{self.count} created")
                break

            if self._made_on_current_ip >= self.max_per_ip:
                if self._proxy_mgr is None:
                    if self._initial_proxy is None:
                        logger.error(
                            f"Could not rotate proxy after {ROTATE_MAX_ATTEMPTS} attempts; "
                            f"stopping pre-create ({made}/{self.count} created)"
                        )
                        break
                    logger.info(
                        f"No proxy manager (fixed proxy); continuing through {self._initial_proxy}"
                    )
                    self._made_on_current_ip = 0
                elif not self._rotate_with_retry():
                    logger.error(
                        f"Could not rotate proxy after {ROTATE_MAX_ATTEMPTS} attempts; "
                        f"stopping pre-create ({made}/{self.count} created)"
                    )
                    break
                else:
                    continue

            if self.progress_callback:
                try:
                    self.progress_callback(made, self.count, None)
                except Exception:
                    pass

            # Serialize mailbox creation across non-tor pools against same exit IP.
            # Tor stream isolation uses separate circuits per thread so can run concurrently.
            if self._is_tor():
                entry = self._create_mailbox()
            else:
                with MAILBOX_CREATE_LOCK:
                    entry = self._create_mailbox()
            if entry is None:
                if self._is_stopped():
                    break
                self._consecutive_failures += 1
                logger.error(
                    f"Mailbox creation failed ({self._consecutive_failures}/"
                    f"{max_consec} consecutive); {made}/{self.count} created"
                )
                if self._consecutive_failures >= max_consec:
                    logger.error(
                        f"Stopping pre-create after {max_consec} "
                        f"consecutive mailbox failures ({made}/{self.count} created)"
                    )
                    break
                # A transient failure must not discard the remaining mailboxes;
                # the shortfall is reported by the caller via made < count.
                continue

            self._consecutive_failures = 0
            self._queue.put(entry)
            made += 1
            self._made_on_current_ip += 1

            if self.progress_callback:
                try:
                    self.progress_callback(made, self.count, entry)
                except Exception:
                    pass

            if made < self.count:
                sleep_time = 0.5 if self._is_tor() else self.spacing
                time.sleep(sleep_time)

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
            if self._initial_proxy:
                logger.info(f"MailboxPool using proxy: {self._initial_proxy}")
            return self._initial_proxy
        if self._initial_proxy:
            logger.info(f"MailboxPool using proxy: {self._initial_proxy}")
            return self._initial_proxy
        try:
            # If using Tor manager with stream isolation capability, get stream proxy
            if self._is_tor() and hasattr(self._proxy_mgr, "rotate_to_new_ip"):
                ok, proxy_url, _ = self._proxy_mgr.rotate_to_new_ip()
                if ok and proxy_url:
                    logger.info(f"MailboxPool using proxy: {proxy_url}")
                    return proxy_url
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

    def _is_tor(self) -> bool:
        """Checks if current proxy manager or proxy URL is Tor-based."""
        if self._proxy_mgr and "TorProxyManager" in type(self._proxy_mgr).__name__:
            return True
        if self._current_proxy and ("9050" in self._current_proxy or "tor" in self._current_proxy):
            return True
        return False

    def _rotate_or_wait_fallback(self) -> bool:
        """Rotate to a fresh proxy for a retry. On rotation failure, waits the
        fallback sleep and retries on the same proxy — unless stopped, in which
        case False is returned so the caller gives up."""
        if self._rotate_current_proxy():
            return True
        logger.warning("Rotation failed; waiting and retrying on same proxy")
        if self._is_stopped():
            return False
        sleep_time = 1.0 if self._is_tor() else RATE_LIMIT_FALLBACK_SLEEP
        time.sleep(sleep_time)
        return True

    def _create_mailbox(self) -> Optional[MailboxEntry]:
        """
        Create one mailbox, retrying the same logical creation (bounded) on
        TempMailRateLimitError and on other transient failures (403/Cloudflare
        block, expired tokens, network blips): rotate to a fresh proxy first,
        else wait and retry on the same proxy. Gives up after
        max_attempts attempts and returns None (prepare() decides
        whether to keep pre-creating).
        """
        max_attempts = 6 if self._is_tor() else RATE_LIMIT_MAX_ATTEMPTS
        for attempt in range(1, max_attempts + 1):
            try:
                client = TempMailClient(proxy=self._current_proxy, max_retry_delay=3.0)
                email, token = client.create_inbox()
                logger.info(f"MailboxPool created mailbox {email} on proxy {self._current_proxy}")
                return MailboxEntry(email=email, token=token, proxy=self._current_proxy)
            except TempMailRateLimitError as e:
                if attempt >= max_attempts:
                    logger.error(f"Rate limited after {attempt} attempts; giving up on this mailbox")
                    return None
                logger.warning(
                    f"Rate limited (attempt {attempt}/{max_attempts}): {e}; rotating proxy"
                )
                if not self._rotate_or_wait_fallback():
                    return None
            except Exception as e:
                if attempt >= max_attempts:
                    logger.error(
                        f"Mailbox creation failed after {attempt} attempts; giving up on this mailbox ({e})"
                    )
                    return None
                logger.warning(
                    f"Mailbox creation failed (attempt {attempt}/{max_attempts}): "
                    f"{e}; rotating proxy"
                )
                if not self._rotate_or_wait_fallback():
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
