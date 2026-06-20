"""Statistical skill analysis over a set of parsed games.

We compute six skill areas inspired by Aimchess — Openings, Tactics, Endgames,
Advantage Capitalization, Resourcefulness, and Time Management — plus overall
stats and personalized tips.

Important honesty note: without a chess engine we cannot measure true move
quality. These scores are *heuristics* derived from results, chess.com's own
post-game accuracy figures, clock usage, and game phase. The architecture
exposes an optional `engine` hook (see chessstats/engine.py) so a Stockfish
pass can refine the tactics/advantage/resourcefulness scores later — that is
the "hybrid" design. Each skill reports a `confidence` flag so the UI can show
which numbers are solid (time, openings) vs. estimated (tactics).
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Dict, List, Optional

import chess

from .pgn import ParsedGame

# A score on a 0-100 scale where 50 == "about average for this heuristic".
Score = float


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _rate(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


def _material(fen: str) -> int:
    """Non-king, non-pawn material count remaining (both sides), from a FEN."""
    board_part = fen.split(" ")[0]
    vals = {"q": 9, "r": 5, "b": 3, "n": 3, "Q": 9, "R": 5, "B": 3, "N": 3}
    return sum(vals.get(c, 0) for c in board_part)


def _is_endgame(g: ParsedGame) -> bool:
    """Heuristic: queens off or low heavy-piece material, or a long game."""
    mat = _material(g.final_fen)
    fen0 = g.final_fen.split(" ")[0]
    queens = fen0.count("q") + fen0.count("Q")
    return mat <= 16 or (queens == 0 and mat <= 24) or g.total_plies >= 80


def _result_value(r: str) -> float:
    return {"win": 1.0, "draw": 0.5, "loss": 0.0}[r]


# --------------------------------------------------------------------------
# Individual skill scorers. Each returns a dict the dashboard renders.
# --------------------------------------------------------------------------

def score_time_management(games: List[ParsedGame]) -> Dict:
    """High confidence: built from real per-move clock data."""
    timed = [g for g in games if g.base and g.moves]
    flagged = sum(1 for g in timed if g.lost_on_time)
    scramble_games = 0          # games where user dropped below 10% of base clock
    low_time_blunderzone = 0    # user moves made with < 5s on the clock
    total_user_moves = 0
    avg_spent_samples: List[float] = []

    for g in timed:
        low_threshold = max(g.base * 0.10, 10)
        hit_scramble = False
        for m in g.user_moves:
            total_user_moves += 1
            if m.clock is not None and m.clock < low_threshold:
                hit_scramble = True
            if m.clock is not None and m.clock < 5:
                low_time_blunderzone += 1
            if m.spent is not None:
                avg_spent_samples.append(m.spent)
        if hit_scramble:
            scramble_games += 1

    n = len(timed)
    flag_rate = _rate(flagged, n)
    scramble_rate = _rate(scramble_games, n)
    blunderzone_rate = _rate(low_time_blunderzone, total_user_moves)

    # Penalize flagging heavily, time scrambles moderately.
    score = 100 - (flag_rate * 220) - (scramble_rate * 70) - (blunderzone_rate * 120)
    return {
        "key": "time_management",
        "label": "Time Management",
        "score": round(_clamp(score), 1),
        "confidence": "high",
        "stats": {
            "games_analyzed": n,
            "lost_on_time": flagged,
            "lost_on_time_pct": round(flag_rate * 100, 1),
            "time_scramble_games_pct": round(scramble_rate * 100, 1),
            "moves_under_5s_pct": round(blunderzone_rate * 100, 1),
            "avg_seconds_per_move": round(statistics.mean(avg_spent_samples), 1)
            if avg_spent_samples else None,
        },
    }


def score_openings(games: List[ParsedGame]) -> Dict:
    """Medium-high confidence: results + opening accuracy by opening family."""
    by_opening: Dict[str, List[ParsedGame]] = defaultdict(list)
    for g in games:
        name = g.opening_name or "Unknown"
        by_opening[name].append(g)

    families = []
    for name, gs in by_opening.items():
        if name == "Unknown":
            continue
        wins = sum(1 for g in gs if g.user_result == "win")
        draws = sum(1 for g in gs if g.user_result == "draw")
        score_pts = sum(_result_value(g.user_result) for g in gs)
        accs = [g.user_accuracy for g in gs if g.user_accuracy is not None]
        families.append({
            "name": name,
            "games": len(gs),
            "win_pct": round(_rate(wins, len(gs)) * 100, 1),
            "score_pct": round(_rate(score_pts, len(gs)) * 100, 1),
            "avg_accuracy": round(statistics.mean(accs), 1) if accs else None,
        })

    families.sort(key=lambda f: (-f["games"], -f["score_pct"]))
    played = [f for f in families if f["games"] >= 3]
    best = max(played, key=lambda f: f["score_pct"], default=None)
    worst = min(played, key=lambda f: f["score_pct"], default=None)

    overall_score = sum(_result_value(g.user_result) for g in games)
    overall_pct = _rate(overall_score, len(games)) * 100
    # Center on 50: a 50% score rate -> ~50 skill points.
    score = overall_pct
    return {
        "key": "openings",
        "label": "Openings",
        "score": round(_clamp(score), 1),
        "confidence": "medium",
        "stats": {
            "distinct_openings": len(played),
            "best_opening": best,
            "worst_opening": worst,
            "top_families": families[:8],
        },
    }


def score_endgames(games: List[ParsedGame], evals=None) -> Dict:
    """Outcome in games that reached an endgame.

    With engine data: weighted toward converting winning / holding equal endings.
    Without: plain score rate in endgames detected from the final position.
    """
    if evals:
        rows = [(g, evals[g.uuid]) for g in games
                if g.uuid in evals and evals[g.uuid].reached_endgame
                and evals[g.uuid].endgame_entry_eval is not None]
        if rows:
            # Reward results relative to the endgame you entered.
            pts = 0.0
            for g, e in rows:
                rv = _result_value(g.user_result)
                if e.endgame_entry_eval >= 150:      # should win
                    pts += rv
                elif e.endgame_entry_eval <= -150:   # should lose; saving is bonus
                    pts += 0.5 + rv * 0.5
                else:                                 # equal
                    pts += rv
            pct = _rate(pts, len(rows)) * 100
            return {
                "key": "endgames", "label": "Endgames",
                "score": round(_clamp(pct), 1), "confidence": "high",
                "stats": {"games_reached_endgame": len(rows),
                          "endgame_score_pct": round(_rate(
                              sum(_result_value(g.user_result) for g, _ in rows), len(rows)) * 100, 1),
                          "endgame_rate_pct": round(_rate(len(rows), len(games)) * 100, 1)},
            }
    eg = [g for g in games if _is_endgame(g)]
    if not eg:
        return {
            "key": "endgames", "label": "Endgames", "score": 50.0,
            "confidence": "low",
            "stats": {"games_reached_endgame": 0, "note": "Too few endgames seen."},
        }
    wins = sum(1 for g in eg if g.user_result == "win")
    draws = sum(1 for g in eg if g.user_result == "draw")
    losses = sum(1 for g in eg if g.user_result == "loss")
    score_pts = sum(_result_value(g.user_result) for g in eg)
    pct = _rate(score_pts, len(eg)) * 100
    return {
        "key": "endgames",
        "label": "Endgames",
        "score": round(_clamp(pct), 1),
        "confidence": "medium",
        "stats": {
            "games_reached_endgame": len(eg),
            "endgame_score_pct": round(pct, 1),
            "wins": wins, "draws": draws, "losses": losses,
            "endgame_rate_pct": round(_rate(len(eg), len(games)) * 100, 1),
        },
    }


def score_advantage_capitalization(games: List[ParsedGame], evals=None) -> Dict:
    """When you reach a winning position, do you convert it?

    With engine data: % of games won among those where you reached +1.5 pawns.
    Without: a proxy from chess.com accuracy differential.
    """
    if evals:
        qual = [g for g in games if g.uuid in evals and evals[g.uuid].max_adv >= 150]
        if qual:
            won = sum(1 for g in qual if g.user_result == "win")
            pct = _rate(won, len(qual)) * 100
            return {
                "key": "advantage_capitalization", "label": "Advantage Capitalization",
                "score": round(_clamp(pct), 1), "confidence": "high",
                "stats": {"qualifying_games": len(qual), "converted_wins": won,
                          "failed_to_convert": len(qual) - won, "conversion_pct": round(pct, 1)},
            }
    rated = [g for g in games
             if g.user_accuracy is not None and g.opp_accuracy is not None]
    # Games where you played clearly more accurately than the opponent.
    ahead = [g for g in rated if g.user_accuracy - g.opp_accuracy >= 8]
    if not ahead:
        return {
            "key": "advantage_capitalization", "label": "Advantage Capitalization",
            "score": 50.0, "confidence": "low",
            "stats": {"qualifying_games": 0,
                      "note": "Need games with chess.com accuracy data to estimate."},
        }
    converted = sum(1 for g in ahead if g.user_result == "win")
    slipped = sum(1 for g in ahead if g.user_result != "win")
    pct = _rate(converted, len(ahead)) * 100
    return {
        "key": "advantage_capitalization",
        "label": "Advantage Capitalization",
        "score": round(_clamp(pct), 1),
        "confidence": "estimate",
        "stats": {
            "qualifying_games": len(ahead),
            "converted_wins": converted,
            "failed_to_convert": slipped,
            "conversion_pct": round(pct, 1),
        },
    }


def score_resourcefulness(games: List[ParsedGame], evals=None) -> Dict:
    """When you reach a losing position, do you save it?

    With engine data: % win-or-draw among games where you fell to -1.5 pawns.
    Without: a proxy from chess.com accuracy differential.
    """
    if evals:
        qual = [g for g in games if g.uuid in evals and evals[g.uuid].min_adv <= -150]
        if qual:
            saved = sum(1 for g in qual if g.user_result != "loss")
            pct = _rate(saved, len(qual)) * 100
            return {
                "key": "resourcefulness", "label": "Resourcefulness",
                "score": round(_clamp(pct * 2.2), 1), "confidence": "high",
                "stats": {"qualifying_games": len(qual), "points_saved_games": saved,
                          "save_pct": round(pct, 1)},
            }
    rated = [g for g in games
             if g.user_accuracy is not None and g.opp_accuracy is not None]
    behind = [g for g in rated if g.opp_accuracy - g.user_accuracy >= 8]
    if not behind:
        return {
            "key": "resourcefulness", "label": "Resourcefulness",
            "score": 50.0, "confidence": "low",
            "stats": {"qualifying_games": 0,
                      "note": "Need games with chess.com accuracy data to estimate."},
        }
    saved = sum(1 for g in behind if g.user_result != "loss")  # win or draw
    pct = _rate(saved, len(behind)) * 100
    # Saving even ~30% of lost-looking games is strong; scale up.
    score = pct * 1.6
    return {
        "key": "resourcefulness",
        "label": "Resourcefulness",
        "score": round(_clamp(score), 1),
        "confidence": "estimate",
        "stats": {
            "qualifying_games": len(behind),
            "points_saved_games": saved,
            "save_pct": round(pct, 1),
        },
    }


def score_tactics(games: List[ParsedGame], evals=None) -> Dict:
    """How clean is your play tactically?

    With engine data: derived from average centipawn loss and blunder rate.
    Without: a proxy from chess.com accuracy and quick wins/losses.
    """
    if evals:
        ge = [evals[g.uuid] for g in games if g.uuid in evals]
        if ge:
            avg_cpl = statistics.mean(e.user_cpl for e in ge)
            blunders_pg = sum(e.user_blunders for e in ge) / len(ge)
            # cpl 10 -> ~92, 30 -> ~76, 60 -> ~52, 100 -> ~20; minus blunder penalty.
            score = _clamp(100 - avg_cpl * 0.8 - blunders_pg * 6)
            return {
                "key": "tactics", "label": "Tactics", "score": round(score, 1),
                "confidence": "high",
                "stats": {"avg_cpl": round(avg_cpl, 1),
                          "blunders_per_game": round(blunders_pg, 2),
                          "mistakes_per_game": round(sum(e.user_mistakes for e in ge) / len(ge), 2)},
            }
    accs = [g.user_accuracy for g in games if g.user_accuracy is not None]
    # Quick wins (sharp tactical conversions) vs quick losses (getting hit).
    quick_wins = sum(1 for g in games
                     if g.user_result == "win" and g.total_plies <= 50)
    quick_losses = sum(1 for g in games
                       if g.user_result == "loss" and g.total_plies <= 50)
    quick = quick_wins + quick_losses
    quick_win_share = _rate(quick_wins, quick) if quick else 0.5

    if accs:
        avg_acc = statistics.mean(accs)
        # Map accuracy 60->~35, 75->~62, 90->~88 then blend with tactical edge.
        acc_component = _clamp((avg_acc - 50) * 2.4)
        score = 0.7 * acc_component + 0.3 * (quick_win_share * 100)
        confidence = "estimate"
    else:
        score = quick_win_share * 100
        avg_acc = None
        confidence = "low"
    return {
        "key": "tactics",
        "label": "Tactics",
        "score": round(_clamp(score), 1),
        "confidence": confidence,
        "stats": {
            "avg_accuracy": round(avg_acc, 1) if avg_acc is not None else None,
            "quick_wins": quick_wins,
            "quick_losses": quick_losses,
        },
    }


# --------------------------------------------------------------------------
# Overall stats + tips
# --------------------------------------------------------------------------

def overall_stats(games: List[ParsedGame]) -> Dict:
    n = len(games)
    wins = sum(1 for g in games if g.user_result == "win")
    draws = sum(1 for g in games if g.user_result == "draw")
    losses = sum(1 for g in games if g.user_result == "loss")

    def color_record(color: bool) -> Dict:
        gs = [g for g in games if g.user_color == color]
        w = sum(1 for g in gs if g.user_result == "win")
        d = sum(1 for g in gs if g.user_result == "draw")
        return {"games": len(gs), "win_pct": round(_rate(w, len(gs)) * 100, 1),
                "score_pct": round(_rate(w + 0.5 * d, len(gs)) * 100, 1)}

    by_class = Counter(g.time_class for g in games)
    accs = [g.user_accuracy for g in games if g.user_accuracy is not None]

    # Rating trajectory (oldest -> newest) for a sparkline.
    chrono = sorted([g for g in games if g.user_rating], key=lambda g: g.end_time)
    rating_series = [{"t": g.end_time, "r": g.user_rating} for g in chrono]

    # Current win/loss streak (newest first).
    newest = sorted(games, key=lambda g: g.end_time, reverse=True)
    streak_type, streak_len = None, 0
    for g in newest:
        if streak_type is None:
            streak_type, streak_len = g.user_result, 1
        elif g.user_result == streak_type:
            streak_len += 1
        else:
            break

    return {
        "games": n,
        "wins": wins, "draws": draws, "losses": losses,
        "win_pct": round(_rate(wins, n) * 100, 1),
        "score_pct": round(_rate(wins + 0.5 * draws, n) * 100, 1),
        "as_white": color_record(chess.WHITE),
        "as_black": color_record(chess.BLACK),
        "by_time_class": dict(by_class),
        "avg_accuracy": round(statistics.mean(accs), 1) if accs else None,
        "rating_series": rating_series,
        "current_streak": {"type": streak_type, "length": streak_len},
    }


def build_tips(skills: List[Dict], overall: Dict) -> List[Dict]:
    """Turn the weakest skills and notable findings into actionable advice."""
    tips: List[Dict] = []
    ranked = sorted(skills, key=lambda s: s["score"])

    advice = {
        "time_management": "You're losing points on the clock. Set a per-move "
            "budget (e.g. ~time/40) and bank time in the opening so you have a "
            "cushion for critical middlegame decisions.",
        "openings": "Your results swing by opening. Lean into your best line and "
            "spend a focused session learning the first ~10 moves of your worst one.",
        "endgames": "You're leaking points in endgames. Drill king-and-pawn and "
            "rook endgame fundamentals — they decide most close games.",
        "advantage_capitalization": "You reach better positions but don't always "
            "close them out. When ahead, simplify into clearly winning endings and "
            "avoid unnecessary complications.",
        "resourcefulness": "When worse, you tend to fold. Practice setting traps and "
            "creating complications instead of passively defending lost positions.",
        "tactics": "Sharpen pattern recognition with daily tactics puzzles; many of "
            "your quick losses likely come from missed or allowed tactics.",
    }

    for s in ranked[:3]:
        tips.append({
            "skill": s["label"],
            "key": s["key"],
            "score": s["score"],
            "priority": "high" if s["score"] < 45 else "medium",
            "text": advice.get(s["key"], "Focus practice here."),
        })

    # Specific data-driven callouts.
    tm = next((s for s in skills if s["key"] == "time_management"), None)
    if tm and tm["stats"].get("lost_on_time", 0) > 0:
        tips.append({
            "skill": "Time Management", "key": "flagging", "score": tm["score"],
            "priority": "high",
            "text": f"You flagged (lost on time) in "
                    f"{tm['stats']['lost_on_time']} game(s). Play a touch faster in "
                    f"won/equal positions to avoid throwing away whole points.",
        })

    op = next((s for s in skills if s["key"] == "openings"), None)
    worst = op["stats"].get("worst_opening") if op else None
    if worst and worst["score_pct"] < 40:
        tips.append({
            "skill": "Openings", "key": "worst_opening", "score": op["score"],
            "priority": "medium",
            "text": f"Your weakest opening is “{worst['name']}” "
                    f"({worst['score_pct']}% score over {worst['games']} games). "
                    f"Either study it or steer toward a line you score better in.",
            "_worst": worst,
        })

    color = "as_white" if overall["as_white"]["score_pct"] < overall["as_black"]["score_pct"] \
        else "as_black"
    other = "as_black" if color == "as_white" else "as_white"
    gap = overall[other]["score_pct"] - overall[color]["score_pct"]
    if gap >= 12 and overall[color]["games"] >= 5:
        side = "White" if color == "as_white" else "Black"
        tips.append({
            "skill": "Color Balance", "key": "color_balance",
            "score": overall[color]["score_pct"], "priority": "medium",
            "text": f"You score {gap:.0f} points lower with {side} "
                    f"({overall[color]['score_pct']}% vs {overall[other]['score_pct']}%). "
                    f"Your {side} opening repertoire is the place to invest.",
            "_side": side, "_gap": round(gap),
        })

    return tips


def analyze(
    games: List[ParsedGame],
    evals: Optional[Dict[str, "object"]] = None,  # {uuid: GameEval} from Stockfish
) -> Dict:
    """Run the full skill analysis. When `evals` is supplied (deep pass), the
    engine-dependent skills are computed from real evaluations."""
    skills = [
        score_openings(games),
        score_tactics(games, evals),
        score_endgames(games, evals),
        score_advantage_capitalization(games, evals),
        score_resourcefulness(games, evals),
        score_time_management(games),
    ]

    overall = overall_stats(games)
    overall_skill = round(statistics.mean(s["score"] for s in skills), 1)
    tips = build_tips(skills, overall)

    return {
        "overall_skill": overall_skill,
        "skills": skills,
        "overall": overall,
        "tips": tips,
        "engine_used": bool(evals),
    }
