"""Chess Stats — local web dashboard.

Run:  uvicorn app:app --reload   (or: python app.py)
Open: http://127.0.0.1:8000
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import chess
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from chessstats import __version__
from chessstats.analysis import analyze
from chessstats.chesscom import ChessComClient, ChessComError
from chessstats.details import build_details, enrich_tips
from chessstats.engine import EngineAnalyzer
from chessstats.pgn import ParsedGame, parse_game
from chessstats.practice import DRILLS, GUIDE

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# How many recent games to pre-warm with the engine in the background.
WARM_THRESHOLD = 40
ENGINE_DEPTH = 12
REVIEW_DEPTH = 14

app = FastAPI(title="Chess Stats", version=__version__)
client = ChessComClient()

# Tiny in-process cache so repeated dashboard loads don't re-hit the API.
_CACHE: Dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # seconds

# Recently-fetched raw games per user, so /api/review and the warmer can find a
# game's PGN without re-hitting chess.com. Value: (ts, {uuid: raw}, [parsed]).
_GAMES: Dict[str, tuple] = {}
_GAMES_TTL = 1800

# Background pre-warming bookkeeping.
_WARM_LOCK = threading.Lock()
_WARMING: set[str] = set()


def _warm_async(username: str, parsed: List[ParsedGame]) -> None:
    """Fill the engine cache for a user's recent games in a background thread,
    regardless of whether the deep pass was requested. Cheap if already cached."""
    if EngineAnalyzer.create() is None:
        return
    uname = username.lower()
    with _WARM_LOCK:
        if uname in _WARMING:
            return
        _WARMING.add(uname)

    def run():
        try:
            analyzer = EngineAnalyzer.create(depth=ENGINE_DEPTH, max_games=WARM_THRESHOLD)
            if analyzer is not None:
                analyzer.analyze(parsed)
        except Exception:
            pass
        finally:
            with _WARM_LOCK:
                _WARMING.discard(uname)

    threading.Thread(target=run, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/report")
def report(
    username: str = Query(..., min_length=1),
    limit: int = Query(60, ge=5, le=300),
    time_class: Optional[str] = Query(None, description="comma list: blitz,rapid,..."),
    engine: bool = Query(False, description="run optional Stockfish deep pass"),
):
    username = username.strip().lstrip("@")
    classes = [c.strip() for c in time_class.split(",")] if time_class else None
    cache_key = f"{username.lower()}|{limit}|{time_class}|{engine}"

    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    try:
        profile = client.profile(username)
        try:
            stats = client.stats(username)
        except ChessComError:
            stats = {}
        raw_games = client.recent_games(username, limit=limit, time_classes=classes)
    except ChessComError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # network etc.
        raise HTTPException(status_code=502, detail=f"chess.com request failed: {e}")

    parsed = []
    for g in raw_games:
        try:
            pg = parse_game(g, username)
            if pg:
                parsed.append(pg)
        except Exception:
            continue

    if not parsed:
        raise HTTPException(
            status_code=404,
            detail=f"No analyzable standard-chess games found for '{username}'.",
        )

    # Remember the raw games so the review endpoint can fetch a PGN cheaply.
    _GAMES[username.lower()] = (now, {g.get("uuid", ""): g for g in raw_games}, parsed)

    # Deep pass: run Stockfish when requested and available (cached per game).
    evals = {}
    if engine:
        analyzer = EngineAnalyzer.create(depth=ENGINE_DEPTH, max_games=min(limit, WARM_THRESHOLD))
        if analyzer is not None:
            evals = analyzer.analyze(parsed)

    result = analyze(parsed, evals=evals)
    result["details"] = build_details(parsed, evals)
    result["tips"] = enrich_tips(result["tips"], result["skills"],
                                 result["overall"], result["details"])
    result["games"] = _games_list(parsed)

    # Always pre-warm the engine cache in the background (even if Deep is off),
    # so a later deep analysis / review returns quickly.
    _warm_async(username, parsed)

    result["player"] = {
        "username": profile.get("username", username),
        "name": profile.get("name"),
        "avatar": profile.get("avatar"),
        "url": profile.get("url"),
        "country": profile.get("country", "").rsplit("/", 1)[-1],
        "title": profile.get("title"),
        "ratings": _extract_ratings(stats),
    }
    result["meta"] = {
        "games_analyzed": len(parsed),
        "engine_games": len(evals),
        "requested_limit": limit,
        "time_class_filter": classes,
        "engine_available": EngineAnalyzer.create() is not None,
        "generated_at": int(now),
    }

    _CACHE[cache_key] = (now, result)
    return result


def _games_list(parsed: List[ParsedGame]) -> List[dict]:
    """Compact per-game rows for the 'recent games' list / review picker."""
    rows = []
    for g in sorted(parsed, key=lambda x: x.end_time, reverse=True):
        rows.append({
            "uuid": g.uuid, "url": g.url, "end_time": g.end_time,
            "time_class": g.time_class, "opening_name": g.opening_name or "—",
            "color": "white" if g.user_color else "black",
            "result": g.user_result, "user_rating": g.user_rating,
            "opp_rating": g.opp_rating, "plies": g.total_plies,
        })
    return rows


@app.get("/api/engine-status")
def engine_status(username: str = Query(..., min_length=1)):
    """How many of the user's recent games are already engine-analyzed (cached)."""
    uname = username.strip().lstrip("@").lower()
    entry = _GAMES.get(uname)
    analyzer = EngineAnalyzer.create(depth=ENGINE_DEPTH, max_games=WARM_THRESHOLD)
    if not entry or analyzer is None:
        return {"available": analyzer is not None, "total": 0, "cached": 0,
                "warming": uname in _WARMING}
    parsed = entry[2][:WARM_THRESHOLD]
    cached = sum(1 for g in parsed if analyzer._cache_path(g).exists())
    return {"available": True, "total": len(parsed), "cached": cached,
            "warming": uname in _WARMING}


@app.get("/api/review")
def review(
    username: str = Query(..., min_length=1),
    uuid: str = Query(..., min_length=1),
    depth: int = Query(REVIEW_DEPTH, ge=8, le=20),
):
    """Move-by-move engine review of a single game."""
    uname = username.strip().lstrip("@").lower()
    analyzer = EngineAnalyzer.create()
    if analyzer is None:
        raise HTTPException(status_code=503,
                            detail="Stockfish is not installed; game review is unavailable.")

    raw = None
    entry = _GAMES.get(uname)
    if entry and uuid in entry[1]:
        raw = entry[1][uuid]
    if raw is None:
        # Fallback: re-fetch the user's recent games and look for this uuid.
        try:
            for g in client.recent_games(uname, limit=100):
                if g.get("uuid") == uuid:
                    raw = g
                    break
        except ChessComError as e:
            raise HTTPException(status_code=404, detail=str(e))
    if raw is None:
        raise HTTPException(status_code=404, detail="Game not found for this user.")

    pg = parse_game(raw, uname)
    if pg is None:
        raise HTTPException(status_code=422, detail="Could not parse that game.")
    review = analyzer.review_game(pg, depth=depth)
    review["white"] = raw.get("white", {})
    review["black"] = raw.get("black", {})
    review["time_class"] = raw.get("time_class")
    return review


@app.get("/api/practice")
def practice():
    """Curated early/mid-game guide + drill positions (no account needed)."""
    return {
        "guide": GUIDE,
        "drills": DRILLS,
        "engine_available": EngineAnalyzer.create() is not None,
    }


@app.get("/api/practice/grade")
def practice_grade(
    fen: str = Query(..., min_length=10),
    move: str = Query(..., min_length=4, max_length=5, description="UCI, e.g. e2e4"),
    depth: int = Query(REVIEW_DEPTH, ge=8, le=20),
):
    """Grade a single move the player chose in a practice position."""
    analyzer = EngineAnalyzer.create()
    if analyzer is None:
        raise HTTPException(status_code=503,
                            detail="Stockfish is not installed; drills are unavailable.")
    result = analyzer.grade_move(fen, move, depth=depth)
    if result.get("error"):
        code = 422 if result.get("illegal") else 400
        raise HTTPException(status_code=code, detail=result["error"])
    return result


def _fen_error(board: chess.Board) -> Optional[str]:
    """Human-readable reason a set-up position can't be played, or None."""
    status = board.status()
    if status == chess.STATUS_VALID:
        return None
    checks = [
        (chess.STATUS_NO_WHITE_KING, "White needs a king."),
        (chess.STATUS_NO_BLACK_KING, "Black needs a king."),
        (chess.STATUS_TOO_MANY_KINGS, "Each side can only have one king."),
        (chess.STATUS_TOO_MANY_WHITE_PIECES, "White has more than 16 pieces."),
        (chess.STATUS_TOO_MANY_BLACK_PIECES, "Black has more than 16 pieces."),
        (chess.STATUS_TOO_MANY_WHITE_PAWNS, "White has more than 8 pawns."),
        (chess.STATUS_TOO_MANY_BLACK_PAWNS, "Black has more than 8 pawns."),
        (chess.STATUS_PAWNS_ON_BACKRANK, "Pawns can't stand on the first or eighth rank."),
        (chess.STATUS_OPPOSITE_CHECK,
         "The side not to move is in check — switch the side to move."),
        (chess.STATUS_TOO_MANY_CHECKERS, "This check isn't possible."),
        (chess.STATUS_IMPOSSIBLE_CHECK, "This check isn't possible."),
    ]
    for flag, msg in checks:
        if status & flag:
            return msg
    return "That position isn't playable."


def _game_over_info(board: chess.Board) -> Optional[dict]:
    """{"reason", "winner", "text"} if the game is over at `board`, else None."""
    outcome = board.outcome()
    if outcome is None:
        return None
    reason = outcome.termination.name.replace("_", " ").lower()
    winner = None if outcome.winner is None else \
        ("white" if outcome.winner == chess.WHITE else "black")
    text = (f"Checkmate — {winner.capitalize()} wins!" if winner
            else f"Draw by {reason}.")
    return {"reason": reason, "winner": winner, "text": text}


@app.get("/api/board/validate")
def board_validate(fen: str = Query(..., min_length=10)):
    """Check that a manually set-up position is playable (the sandbox board)."""
    try:
        board = chess.Board(fen)
    except Exception:
        return {"valid": False, "reason": "Could not read that FEN."}
    reason = _fen_error(board)
    if reason:
        return {"valid": False, "reason": reason}
    return {
        "valid": True,
        "turn": "white" if board.turn == chess.WHITE else "black",
        "game_over": _game_over_info(board),
        "engine_available": EngineAnalyzer.create() is not None,
    }


@app.get("/api/board/move")
def board_move(
    fen: str = Query(..., min_length=10),
    move: str = Query(..., min_length=4, max_length=5, description="UCI, e.g. e2e4"),
    depth: int = Query(12, ge=8, le=20),
):
    """Play a move on the sandbox board: apply it server-side (so castling,
    en passant and promotion stay correct) and have Stockfish grade it."""
    try:
        board = chess.Board(fen)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read that position.")
    reason = _fen_error(board)
    if reason:
        raise HTTPException(status_code=422, detail=reason)
    if board.is_game_over():
        raise HTTPException(status_code=409, detail="The game is already over.")

    try:
        mv = chess.Move.from_uci(move)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read that move.")
    # Auto-promote to a queen if the player didn't specify a promotion piece.
    if mv not in board.legal_moves and len(move) == 4:
        promo = chess.Move.from_uci(move + "q")
        if promo in board.legal_moves:
            mv = promo
    if mv not in board.legal_moves:
        raise HTTPException(status_code=422, detail="That isn't a legal move here.")

    san = board.san(mv)
    after = board.copy()
    after.push(mv)
    out = {
        "san": san, "uci": mv.uci(), "new_fen": after.fen(),
        "turn": "white" if after.turn == chess.WHITE else "black",
        "check": after.is_check(),
        "game_over": _game_over_info(after),
        "graded": False,
    }

    # Grade with the engine unless it's unavailable or the move ended the game
    # (a game-ending move needs no grade, and engines can't search a finished game).
    analyzer = EngineAnalyzer.create()
    if analyzer is not None and out["game_over"] is None:
        result = analyzer.grade_move(fen, mv.uci(), depth=depth)
        if not result.get("error"):
            out.update(result)
            out["graded"] = True
    return out


def _extract_ratings(stats: dict) -> Dict[str, dict]:
    out = {}
    for key in ("chess_blitz", "chess_rapid", "chess_bullet", "chess_daily"):
        block = stats.get(key) or {}
        last = block.get("last") or {}
        best = block.get("best") or {}
        rec = block.get("record") or {}
        if last or best:
            out[key.replace("chess_", "")] = {
                "rating": last.get("rating"),
                "best": best.get("rating"),
                "record": {"w": rec.get("win"), "l": rec.get("loss"),
                           "d": rec.get("draw")},
            }
    return out


# Serve the static assets (css/js). Mounted last so /api and / take precedence.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import os

    import uvicorn

    # Bind to all interfaces inside a container; hosts inject the port via $PORT.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
