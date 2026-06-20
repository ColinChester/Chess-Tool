"""Stockfish-powered per-game analysis (the deep/engine pass).

Statistical analysis (analysis.py) runs with no engine. When Stockfish is
available, `EngineAnalyzer` evaluates every position of each game and derives
the metrics the dashboard's detail panels need:

  * centipawn loss per move -> blunders / mistakes / inaccuracies
  * evaluation after move 15 (the "opening score")
  * the best advantage / worst disadvantage the user reached
  * the evaluation at the moment a game became an endgame

Results are cached to disk per game (keyed by uuid + depth), so a re-run only
evaluates games it hasn't seen before.

Enable: `brew install stockfish` (or set STOCKFISH_PATH).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import chess

from .pgn import ParsedGame

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "engine"

# Centipawn-loss thresholds for classifying a move (chess.com / Lichess-ish).
INACCURACY = 50
MISTAKE = 100
BLUNDER = 200
# Evals are clamped to this range before computing loss so a single decisive
# move (or mate score) doesn't produce absurd centipawn-loss values.
CLAMP = 1000


def stockfish_path() -> Optional[str]:
    return os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")


def _clamp(cp: int) -> int:
    return max(-CLAMP, min(CLAMP, cp))


# Move classifications (centipawn-loss based), chess.com-flavored.
def classify_move(loss: int, is_best: bool, ply: int, in_opening: bool) -> str:
    if is_best:
        return "Best"
    if in_opening and ply < 12 and loss < 30:
        return "Book"
    if loss < 20:
        return "Excellent"
    if loss < 50:
        return "Good"
    if loss < 100:
        return "Inaccuracy"
    if loss < 200:
        return "Mistake"
    return "Blunder"


def explain_move(cls: str, loss: int, before_w: int, after_w: int, side_white: bool,
                 played_san: str, best_san: Optional[str], best_is_capture: bool,
                 best_is_check: bool, opp_capture_san: Optional[str]) -> Optional[str]:
    """A short, data-grounded note on why a move was good or bad."""
    bm = (before_w if side_white else -before_w) / 100      # mover's perspective, pawns
    am = (after_w if side_white else -after_w) / 100
    if cls in ("Inaccuracy", "Mistake", "Blunder"):
        sev = {"Inaccuracy": "inaccurate", "Mistake": "a mistake", "Blunder": "a blunder"}[cls]
        parts = [f"{played_san} is {sev}, giving up about {loss / 100:.1f} pawns."]
        if best_san:
            extra = ""
            if best_is_capture and best_is_check:
                extra = " — a capture with check"
            elif best_is_capture:
                extra = ", winning material"
            elif best_is_check:
                extra = ", with check"
            parts.append(f"Stockfish preferred {best_san}{extra}.")
        parts.append(f"The evaluation swings from {bm:+.1f} to {am:+.1f} (your side).")
        if opp_capture_san and cls in ("Mistake", "Blunder"):
            parts.append(f"It allows {opp_capture_san}, winning material.")
        return " ".join(parts)
    if cls == "Best" and (best_is_capture or best_is_check or abs(am) >= 1.5):
        why = "captures material" if best_is_capture else (
              "gives a strong check" if best_is_check else "keeps your edge")
        return f"Best move — {played_san} {why} ({am:+.1f})."
    return None


def _is_endgame_board(board: chess.Board) -> bool:
    """Queens off, or <= ~13 points of non-pawn material per the usual rule."""
    pieces = board.piece_map().values()
    nonpawn = sum(
        {chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3, chess.KNIGHT: 3}.get(p.piece_type, 0)
        for p in pieces
    )
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    return nonpawn <= 16 or (queens == 0 and nonpawn <= 24)


@dataclass
class GameEval:
    uuid: str = ""
    user_color: str = "white"          # 'white' | 'black'
    result: str = "draw"
    time_class: str = ""
    opening_name: str = ""
    user_cpl: float = 0.0              # average centipawn loss (user moves)
    opp_cpl: float = 0.0
    user_blunders: int = 0
    user_mistakes: int = 0
    user_inaccuracies: int = 0
    opp_blunders: int = 0
    opp_mistakes: int = 0
    opp_inaccuracies: int = 0
    user_moves: int = 0
    move15_eval: Optional[int] = None  # cp from user's POV after 15 full moves
    max_adv: int = 0                   # best eval user reached (cp, user POV)
    min_adv: int = 0                   # worst eval user reached (cp, user POV)
    endgame_entry_eval: Optional[int] = None   # cp user POV when endgame began
    endgame_entry_ply: Optional[int] = None     # ply index the endgame began
    reached_endgame: bool = False
    user_eval_curve: List[int] = field(default_factory=list)  # cp user POV per ply

    def to_dict(self) -> dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: dict) -> "GameEval":
        ge = cls()
        ge.__dict__.update(d)
        return ge


class EngineAnalyzer:
    def __init__(self, path: str, depth: int = 12, max_games: int = 30):
        import chess.engine  # lazy so the package imports without the binary
        self.path = path
        self.depth = depth
        self.max_games = max_games
        self._chess_engine = chess.engine
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, depth: int = 12, max_games: int = 30) -> Optional["EngineAnalyzer"]:
        path = stockfish_path()
        if not path:
            return None
        try:
            return cls(path, depth=depth, max_games=max_games)
        except Exception:
            return None

    # -- cache -------------------------------------------------------------
    def _cache_key(self, g: ParsedGame) -> str:
        raw = g.uuid or g.url or "".join(m.san for m in g.moves)
        # Bump the schema tag (v2) whenever GameEval's fields change so stale
        # cache entries are recomputed rather than loaded with missing fields.
        h = hashlib.sha1(f"{raw}|d{self.depth}|v2".encode()).hexdigest()[:20]
        return h

    def _cache_path(self, g: ParsedGame) -> Path:
        return CACHE_DIR / f"{self._cache_key(g)}.json"

    # -- engine ------------------------------------------------------------
    def _white_pov_cp(self, engine, board: chess.Board) -> int:
        """Engine eval in centipawns from White's point of view."""
        if board.is_game_over():
            outcome = board.outcome()
            if outcome is None or outcome.winner is None:
                return 0
            return CLAMP if outcome.winner == chess.WHITE else -CLAMP
        info = engine.analyse(board, self._chess_engine.Limit(depth=self.depth))
        score = info["score"].white().score(mate_score=CLAMP)
        return int(score) if score is not None else 0

    def _eval_game(self, engine, g: ParsedGame) -> GameEval:
        user_white = g.user_color == chess.WHITE
        ge = GameEval(
            uuid=g.uuid, result=g.user_result, time_class=g.time_class,
            opening_name=g.opening_name,
            user_color="white" if user_white else "black",
        )

        board = chess.Board()
        # Evaluate the starting position, then every position after each move.
        white_curve = [self._white_pov_cp(engine, board)]
        for m in g.moves:
            try:
                board.push_san(m.san)
            except Exception:
                break
            white_curve.append(self._white_pov_cp(engine, board))

        # User-POV eval curve.
        ge.user_eval_curve = [c if user_white else -c for c in white_curve]
        if ge.user_eval_curve:
            ge.max_adv = max(ge.user_eval_curve)
            ge.min_adv = min(ge.user_eval_curve)
        # Score after 15 full moves (ply 30).
        idx15 = min(30, len(ge.user_eval_curve) - 1)
        if idx15 >= 0:
            ge.move15_eval = ge.user_eval_curve[idx15]

        # Per-move centipawn loss + classification.
        user_losses: List[float] = []
        opp_losses: List[float] = []
        for i in range(len(white_curve) - 1):
            mover_white = (i % 2 == 0)
            before, after = _clamp(white_curve[i]), _clamp(white_curve[i + 1])
            loss = (before - after) if mover_white else (after - before)
            loss = max(0, loss)
            is_user = (mover_white == user_white)
            if is_user:
                user_losses.append(loss)
                if loss >= BLUNDER: ge.user_blunders += 1
                elif loss >= MISTAKE: ge.user_mistakes += 1
                elif loss >= INACCURACY: ge.user_inaccuracies += 1
            else:
                opp_losses.append(loss)
                if loss >= BLUNDER: ge.opp_blunders += 1
                elif loss >= MISTAKE: ge.opp_mistakes += 1
                elif loss >= INACCURACY: ge.opp_inaccuracies += 1

        ge.user_moves = len(user_losses)
        ge.user_cpl = round(sum(user_losses) / len(user_losses), 1) if user_losses else 0.0
        ge.opp_cpl = round(sum(opp_losses) / len(opp_losses), 1) if opp_losses else 0.0

        # Endgame entry: first ply where the board is an endgame.
        board = chess.Board()
        for i, m in enumerate(g.moves):
            try:
                board.push_san(m.san)
            except Exception:
                break
            if _is_endgame_board(board):
                ge.reached_endgame = True
                ge.endgame_entry_ply = i + 1
                # eval at the position after entering the endgame (ply i+1)
                if i + 1 < len(ge.user_eval_curve):
                    ge.endgame_entry_eval = ge.user_eval_curve[i + 1]
                break
        return ge

    def analyze(self, games: List[ParsedGame]) -> Dict[str, GameEval]:
        """Return {uuid: GameEval} for up to `max_games` games, using the cache."""
        results: Dict[str, GameEval] = {}
        todo: List[ParsedGame] = []
        for g in games[: self.max_games]:
            cp = self._cache_path(g)
            if cp.exists():
                try:
                    results[g.uuid] = GameEval.from_dict(json.loads(cp.read_text()))
                    continue
                except Exception:
                    pass
            todo.append(g)

        if todo:
            engine = self._chess_engine.SimpleEngine.popen_uci(self.path)
            try:
                for g in todo:
                    ge = self._eval_game(engine, g)
                    results[g.uuid] = ge
                    try:
                        self._cache_path(g).write_text(json.dumps(ge.to_dict()))
                    except Exception:
                        pass
            finally:
                engine.quit()
        return results

    # -- single-game deep review ------------------------------------------
    def review_game(self, g: ParsedGame, depth: int = 14) -> Dict:
        """Move-by-move review: best move + line, classification, eval, and
        explanations for the key moves (chess.com 'Game Review' style)."""
        user_white = g.user_color == chess.WHITE

        # Resolve the played moves to Move objects.
        replay = chess.Board()
        moves: List[chess.Move] = []
        for m in g.moves:
            try:
                mv = replay.parse_san(m.san)
            except Exception:
                break
            moves.append(mv)
            replay.push(mv)
        n = len(moves)

        engine = self._chess_engine.SimpleEngine.popen_uci(self.path)
        white_eval: List[int] = []
        best_move: List[Optional[chess.Move]] = []
        pvs: List[List[chess.Move]] = []
        try:
            board = chess.Board()
            for i in range(n + 1):
                if board.is_game_over():
                    oc = board.outcome()
                    white_eval.append(
                        (CLAMP if oc.winner == chess.WHITE else -CLAMP)
                        if (oc and oc.winner is not None) else 0)
                    best_move.append(None)
                    pvs.append([])
                else:
                    info = engine.analyse(board, self._chess_engine.Limit(depth=depth))
                    sc = info["score"].white().score(mate_score=CLAMP)
                    white_eval.append(int(sc) if sc is not None else 0)
                    pv = list(info.get("pv", []))
                    best_move.append(pv[0] if pv else None)
                    pvs.append(pv[:6])
                if i < n:
                    board.push(moves[i])
        finally:
            engine.quit()

        out_moves = []
        counts = {c: 0 for c in
                  ("Best", "Book", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder")}
        board = chess.Board()
        for i in range(n):
            side_white = (i % 2 == 0)
            before, after = _clamp(white_eval[i]), _clamp(white_eval[i + 1])
            loss = max(0, (before - after) if side_white else (after - before))
            bm = best_move[i]
            played = moves[i]
            played_san = board.san(played)
            best_san = board.san(bm) if bm else None
            is_best = (bm is not None and bm == played)
            best_is_capture = bool(bm and board.is_capture(bm))
            best_is_check = bool(bm and board.gives_check(bm))
            # best line in SAN
            lb = board.copy()
            best_line = []
            for mv in pvs[i]:
                try:
                    best_line.append(lb.san(mv)); lb.push(mv)
                except Exception:
                    break

            board.push(played)  # board now at position i+1
            # opponent's best reply as a capture (for "allows ..." explanations)
            opp_capture_san = None
            opp_bm = best_move[i + 1]
            if opp_bm and board.is_capture(opp_bm):
                try:
                    opp_capture_san = board.san(opp_bm)
                except Exception:
                    opp_capture_san = None

            cls = classify_move(loss, is_best, i, bool(g.opening_name))
            counts[cls] = counts.get(cls, 0) + 1
            is_user = (side_white == user_white)
            expl = explain_move(cls, loss, before, after, side_white, played_san,
                                best_san, best_is_capture, best_is_check,
                                opp_capture_san if is_user else None) if is_user else None
            out_moves.append({
                "ply": i + 1, "move_no": i // 2 + 1, "side": "w" if side_white else "b",
                "san": played_san, "uci": played.uci(), "fen": board.fen(),
                "eval": after, "cpl": loss, "cls": cls, "is_user": is_user,
                "best_san": best_san, "best_uci": bm.uci() if bm else None,
                "best_line": best_line, "explanation": expl,
            })

        user_counts = {c: 0 for c in counts}
        for m in out_moves:
            if m["is_user"]:
                user_counts[m["cls"]] += 1
        # average centipawn loss for the user
        user_losses = [m["cpl"] for m in out_moves if m["is_user"]]
        acpl = round(sum(user_losses) / len(user_losses), 1) if user_losses else 0.0

        return {
            "uuid": g.uuid, "url": g.url, "opening_name": g.opening_name,
            "user_color": "white" if user_white else "black", "result": g.user_result,
            "initial_eval": _clamp(white_eval[0]) if white_eval else 0,
            "moves": out_moves, "summary": user_counts, "acpl": acpl, "depth": depth,
        }
