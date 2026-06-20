"""Parse a chess.com game (PGN + metadata) into a structured form.

We rely on python-chess for robust PGN handling and pull out the per-move
clock annotations ([%clk h:mm:ss]) that chess.com embeds, which power the
time-management analysis.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import chess
import chess.pgn

_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d{2}):(\d+(?:\.\d+)?)\]")


def _clk_to_seconds(comment: str) -> Optional[float]:
    m = _CLK_RE.search(comment or "")
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def _base_increment(time_control: str) -> tuple[int, int]:
    """Parse a TimeControl tag like '180', '180+2', or '1/86400' (daily)."""
    if not time_control:
        return (0, 0)
    if "/" in time_control:  # daily games: moves/seconds
        try:
            return (int(time_control.split("/")[1]), 0)
        except (ValueError, IndexError):
            return (0, 0)
    if "+" in time_control:
        base, inc = time_control.split("+", 1)
        return (int(base), int(inc))
    try:
        return (int(time_control), 0)
    except ValueError:
        return (0, 0)


@dataclass
class MoveInfo:
    ply: int
    color: bool            # chess.WHITE / chess.BLACK
    san: str
    clock: Optional[float]  # seconds remaining after the move
    spent: Optional[float]  # seconds spent on this move


@dataclass
class ParsedGame:
    # identity / meta
    url: str = ""
    uuid: str = ""
    end_time: int = 0
    time_class: str = ""
    time_control: str = ""
    base: int = 0
    increment: int = 0
    rated: bool = True
    eco: str = ""
    opening_name: str = ""
    termination: str = ""

    # the user's perspective (filled by analysis layer)
    user_color: Optional[bool] = None
    user_result: str = ""          # 'win' | 'loss' | 'draw'
    user_rating: int = 0
    opp_rating: int = 0
    user_accuracy: Optional[float] = None
    opp_accuracy: Optional[float] = None

    # play
    moves: List[MoveInfo] = field(default_factory=list)
    total_plies: int = 0
    final_fen: str = ""
    lost_on_time: bool = False

    @property
    def user_moves(self) -> List[MoveInfo]:
        return [m for m in self.moves if m.color == self.user_color]


_OPENING_FROM_URL = re.compile(r"openings/([^/?#]+)")


def _opening_name(game: dict) -> str:
    url = game.get("eco")  # chess.com puts the opening URL under 'eco' sometimes
    eco_url = ""
    # The PGN header ECOUrl is the reliable source.
    pgn = game.get("pgn", "")
    m = re.search(r'\[ECOUrl\s+"([^"]+)"\]', pgn)
    if m:
        eco_url = m.group(1)
    elif isinstance(url, str) and "openings/" in url:
        eco_url = url
    m2 = _OPENING_FROM_URL.search(eco_url)
    if not m2:
        return ""
    slug = m2.group(1)
    # Trim the move list so we keep just the readable opening family. chess.com
    # appends the line as "...-4.g3-Nf6...", "...8.Re1...", or a bare "...-4".
    # Opening-name words never start with a digit, so cut at the first such token.
    slug = slug.split("...")[0]
    words = []
    for tok in slug.split("-"):
        if tok[:1].isdigit():
            break
        words.append(tok)
    return " ".join(words).strip()


def parse_game(game: dict, username: str) -> Optional[ParsedGame]:
    """Convert a raw chess.com game dict into a ParsedGame from `username`'s view."""
    pgn_text = game.get("pgn")
    if not pgn_text:
        return None
    node = chess.pgn.read_game(io.StringIO(pgn_text))
    if node is None:
        return None

    uname = username.lower()
    white = game.get("white", {})
    black = game.get("black", {})
    if white.get("username", "").lower() == uname:
        user_color, opp = chess.WHITE, black
        me = white
    elif black.get("username", "").lower() == uname:
        user_color, opp = chess.BLACK, white
        me = black
    else:
        return None  # game doesn't belong to this user

    base, inc = _base_increment(game.get("time_control", ""))
    pg = ParsedGame(
        url=game.get("url", ""),
        uuid=game.get("uuid", "") or game.get("url", ""),
        end_time=game.get("end_time", 0),
        time_class=game.get("time_class", ""),
        time_control=game.get("time_control", ""),
        base=base,
        increment=inc,
        rated=game.get("rated", True),
        opening_name=_opening_name(game),
        user_color=user_color,
        user_rating=me.get("rating", 0),
        opp_rating=opp.get("rating", 0),
    )

    acc = game.get("accuracies") or {}
    if acc:
        if user_color == chess.WHITE:
            pg.user_accuracy, pg.opp_accuracy = acc.get("white"), acc.get("black")
        else:
            pg.user_accuracy, pg.opp_accuracy = acc.get("black"), acc.get("white")

    headers = node.headers
    pg.eco = headers.get("ECO", "")
    pg.termination = headers.get("Termination", "")

    # Result from the user's perspective.
    res = me.get("result", "")
    if res == "win":
        pg.user_result = "win"
    elif res in {"checkmated", "resigned", "timeout", "lose", "abandoned",
                 "kingofthehill", "threecheck", "bughousepartnerlose"}:
        pg.user_result = "loss"
    else:  # agreed, repetition, stalemate, insufficient, 50move, timevsinsufficient
        pg.user_result = "draw"
    pg.lost_on_time = (res == "timeout")

    # Walk the mainline, tracking clocks and time spent per move.
    base_clock = float(base) if base else None
    prev_clock = {chess.WHITE: base_clock, chess.BLACK: base_clock}
    board = node.board()
    ply = 0
    for nd in node.mainline():
        move = nd.move
        color = board.turn
        san = board.san(move)
        clock = _clk_to_seconds(nd.comment)
        spent = None
        if clock is not None and prev_clock[color] is not None:
            # time spent = previous clock - current clock + increment gained
            spent = prev_clock[color] - clock + inc
            if spent < 0:
                spent = None
        if clock is not None:
            prev_clock[color] = clock
        ply += 1
        pg.moves.append(MoveInfo(ply=ply, color=color, san=san, clock=clock, spent=spent))
        board.push(move)

    pg.total_plies = ply
    pg.final_fen = board.fen()
    return pg
