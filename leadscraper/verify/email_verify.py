"""Verify email deliverability using only free methods.

Levels:
  1. syntax        -> regex
  2. domain / MX   -> DNS lookup (always on, free, fast)
  3. SMTP probe    -> RCPT TO handshake + catch-all detection (opt-in via
                      --verify-smtp, because outbound port 25 is frequently
                      blocked by ISPs and probing can hurt sender reputation)

Status values: bad_syntax | no_mx | mx_ok | valid | invalid | catch_all | unknown
Only an SMTP-confirmed deliverable address sets verified=True.
"""
from __future__ import annotations

import logging
import random
import re
import smtplib
import string
import threading

from ..config import Settings

log = logging.getLogger(__name__)

_SYNTAX_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}$")
_mx_cache: dict[str, list[str]] = {}
_catchall_cache: dict[str, bool] = {}
_lock = threading.Lock()


class EmailVerifier:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def verify(self, address: str) -> tuple[str, bool]:
        if not address or not _SYNTAX_RE.match(address):
            return "bad_syntax", False
        domain = address.partition("@")[2]
        mx = self._mx(domain)
        if not mx:
            return "no_mx", False
        if not self.s.verify_smtp:
            return "mx_ok", False
        return self._smtp(mx, address, domain)

    # -- DNS -------------------------------------------------------------
    def _mx(self, domain: str) -> list[str]:
        with _lock:
            if domain in _mx_cache:
                return _mx_cache[domain]
        hosts = self._resolve_mx(domain)
        with _lock:
            _mx_cache[domain] = hosts
        return hosts

    @staticmethod
    def _resolve_mx(domain: str) -> list[str]:
        try:
            import dns.resolver
        except ImportError:  # pragma: no cover
            log.warning("dnspython not installed; skipping MX checks")
            return []
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 8.0
        resolver.timeout = 4.0
        try:
            answers = resolver.resolve(domain, "MX")
            recs = sorted(answers, key=lambda r: r.preference)
            hosts = [str(r.exchange).rstrip(".") for r in recs]
            if hosts:
                return hosts
        except Exception:
            pass
        # Fallback: an A record means the domain can receive mail directly.
        try:
            resolver.resolve(domain, "A")
            return [domain]
        except Exception:
            return []

    # -- SMTP ------------------------------------------------------------
    def _smtp(self, mx_hosts: list[str], address: str, domain: str) -> tuple[str, bool]:
        for host in mx_hosts[:2]:
            try:
                server = smtplib.SMTP(host, 25, timeout=self.s.smtp_timeout)
                server.ehlo_or_helo_if_needed()
                server.mail(self.s.smtp_from)
                code, _ = server.rcpt(address)
                catchall = self._is_catchall(server, domain)
                server.quit()
            except Exception as exc:
                log.debug("SMTP to %s failed: %s", host, exc)
                continue
            if catchall:
                return "catch_all", False
            if code in (250, 251):
                return "valid", True
            if code in (550, 551, 553, 554):
                return "invalid", False
            return "mx_ok", False
        # could not talk to any MX (likely port 25 blocked) -> unknown-but-has-MX
        return "mx_ok", False

    def _is_catchall(self, server: smtplib.SMTP, domain: str) -> bool:
        with _lock:
            if domain in _catchall_cache:
                return _catchall_cache[domain]
        rnd = "".join(random.choices(string.ascii_lowercase, k=16))
        result = False
        try:
            server.mail(self.s.smtp_from)
            code, _ = server.rcpt(f"{rnd}@{domain}")
            result = code in (250, 251)
        except Exception:
            result = False
        with _lock:
            _catchall_cache[domain] = result
        return result
