"""Client for the chess.com public data API (read-only, no auth required).

Docs: https://www.chess.com/news/view/published-data-api
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

BASE = "https://api.chess.com/pub"

# chess.com asks API consumers to send a descriptive User-Agent so they can
# contact you if a script misbehaves. A generic browser UA can get throttled.
_HEADERS = {
    "User-Agent": "chess-stats/0.1 (local analysis tool; contact: user@example.com)",
    "Accept": "application/json",
}


class ChessComError(Exception):
    """Raised when the chess.com API returns an error or a user is not found."""


class ChessComClient:
    def __init__(self, timeout: float = 20.0):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self.timeout = timeout

    # -- low level ---------------------------------------------------------
    def _get(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            raise ChessComError(f"Not found: {url}")
        if resp.status_code == 429:
            # Be polite: brief backoff then a single retry.
            time.sleep(1.5)
            resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # -- public endpoints --------------------------------------------------
    def profile(self, username: str) -> Dict[str, Any]:
        return self._get(f"{BASE}/player/{username.lower()}")

    def stats(self, username: str) -> Dict[str, Any]:
        return self._get(f"{BASE}/player/{username.lower()}/stats")

    def archives(self, username: str) -> List[str]:
        data = self._get(f"{BASE}/player/{username.lower()}/games/archives")
        return data.get("archives", [])

    def month(self, archive_url: str) -> List[Dict[str, Any]]:
        return self._get(archive_url).get("games", [])

    # -- convenience -------------------------------------------------------
    def recent_games(
        self,
        username: str,
        limit: int = 60,
        time_classes: Optional[List[str]] = None,
        rules: str = "chess",
    ) -> List[Dict[str, Any]]:
        """Return up to `limit` of the player's most recent finished games.

        Walks monthly archives newest-first until enough games are collected.
        Optionally filter by time_class (e.g. ['blitz','rapid']) and rules.
        """
        username = username.lower()
        archives = self.archives(username)
        if not archives:
            raise ChessComError(
                f"No game archives found for '{username}'. "
                "Check the username, or the account may have no public games."
            )

        collected: List[Dict[str, Any]] = []
        for url in reversed(archives):  # newest month first
            games = self.month(url)
            for g in reversed(games):  # newest game first within the month
                if rules and g.get("rules") != rules:
                    continue
                if time_classes and g.get("time_class") not in time_classes:
                    continue
                collected.append(g)
                if len(collected) >= limit:
                    return collected
        return collected
