"""Builds the per-skill *detail panels* shown when a skill card is clicked, plus
the dedicated endgame analysis — modeled on Aimchess's report sections.

Each panel returns:
  * chart-ready data,
  * `interpretation`: a list of {status, title, text} callouts
    (status in good|bad|warn|neutral, rendered with ✅/🔥/etc.), and
  * `how_to_improve`: a list of concrete suggestions.

Panels that need engine evals degrade gracefully: when no engine data is
present they set `engine_required: true` so the UI can prompt for a deep pass.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Dict, List, Optional

import chess

from .pgn import ParsedGame

# Centipawn thresholds for "advantage / disadvantage" buckets (in cp).
ADV_BUCKETS = [150, 200, 300, 400]      # 1.5, 2, 3, 4 pawns


def _pct(a: float, b: float) -> float:
    return round((a / b) * 100, 1) if b else 0.0


def _good(title, text):  return {"status": "good", "title": title, "text": text}
def _bad(title, text):   return {"status": "bad", "title": title, "text": text}
def _warn(title, text):  return {"status": "warn", "title": title, "text": text}
def _neut(title, text):  return {"status": "neutral", "title": title, "text": text}


# --------------------------------------------------------------------------
def win_rate_detail(games: List[ParsedGame]) -> Dict:
    def split(gs):
        n = len(gs)
        w = sum(1 for g in gs if g.user_result == "win")
        d = sum(1 for g in gs if g.user_result == "draw")
        l = sum(1 for g in gs if g.user_result == "loss")
        return {"games": n, "win": _pct(w, n), "draw": _pct(d, n), "lose": _pct(l, n)}

    white = [g for g in games if g.user_color == chess.WHITE]
    black = [g for g in games if g.user_color == chess.BLACK]
    data = {"white": split(white), "black": split(black), "both": split(games)}

    interp = []
    wr = data["both"]["win"]
    if wr >= 55:
        interp.append(_good("Overall", f"Your win rate over the last {len(games)} games is "
                                       f"{wr}%. Excellent — you may be a bit underrated right now."))
    elif wr >= 45:
        interp.append(_neut("Overall", f"Your win rate over the last {len(games)} games is "
                                       f"{wr}%. Solid and balanced."))
    else:
        interp.append(_warn("Overall", f"Your win rate over the last {len(games)} games is "
                                       f"{wr}%. There's room to climb."))

    for color, label in (("white", "white pieces"), ("black", "black pieces")):
        cw = data[color]["win"]
        if data[color]["games"] < 3:
            continue
        if cw >= 52:
            interp.append(_good(f"With {label}", f"You're doing great with the {label}: "
                                                 f"win rate {cw}%."))
        else:
            interp.append(_bad(f"With {label}", f"Your win rate with {label.split()[0]} is "
                                                f"{cw}%. Worth strengthening this side."))

    weaker = "white" if data["white"]["win"] <= data["black"]["win"] else "black"
    improve = [
        f"Review your {weaker}-side openings below to spot which lines drag your score down.",
        f"Study the common middlegame motifs of your weak {weaker} openings (books, YouTube, Chessable).",
        f"If a {weaker} opening keeps failing, switch to one that better fits your style.",
    ]
    return {"key": "win_rate", "label": "Win Rate", "data": data,
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
# Concrete plans for common openings, matched by substring of the opening name.
# Each entry gives advice for the *side the user is playing* ("w"/"b"), since an
# opening named for a defense (e.g. "Sicilian Defense") can occur in a White game
# (you played 1.e4 and got a Sicilian) or a Black game. "any" = side-agnostic.
OPENING_PLANS = [
    ("Sicilian", {
        "w": "you're scoring fine out of the opening — the leak comes later. Commit to ONE "
             "anti-Sicilian system and learn its plan: Open Sicilian (d4, then a kingside "
             "pawn storm with f3/g4 or piece play) or the calmer Alapin (2.c3, aiming for d4) "
             "or Closed (Nc3, g3, f4). Random moves get punished — have a concrete plan.",
        "b": "know your variation's thematic break (...d5 or ...b5) and play for it; Sicilians "
             "punish slow, planless moves — every move needs a purpose."}),
    ("Petrov", {
        "w": "against the Petrov don't expect a knockout — take a small, lasting edge: develop, "
             "castle, and use your extra central space (d4) patiently. Your evals say you're "
             "already on top out of the opening, so the work is in converting, not the opening.",
        "b": "after ...Nxe4 retreat the knight in time, complete development, and stay solid — "
             "the Petrov rarely loses by force, only by drifting."}),
    ("Philidor", {
        "w": "the Philidor hands you a free space edge — play d4, develop naturally, castle, and "
             "squeeze; don't rush, just keep improving pieces.",
        "b": "you're solid but cramped — prepare the ...d5 (or ...c6+...d5) break to free your "
             "game, and don't leave your king in the center."}),
    ("Pirc", {
        "w": "take the full center (e4+d4), develop, and castle before expanding; don't lunge "
             "forward and walk into the ...e5/...c5 counterstrike — patient White play keeps an edge.",
        "b": "let your opponent over-extend, then hit the center with a timed ...e5 or ...c5; "
             "finish development before you open lines, and don't sit passively."}),
    ("Modern", {
        "w": "occupy the center and develop solidly; meet the ...c5/...e5 breaks with calm "
             "central support rather than over-extending.",
        "b": "fianchetto and stay flexible, then break with ...c5/...e5 once your opponent "
             "commits — don't passively wait and get squashed."}),
    ("Caro", {
        "w": "play the Advance (e5) or Exchange and aim for c3 + space; the Caro is rock-solid, "
             "so look for a slow squeeze, not a quick mate.",
        "b": "get your light-squared bishop OUT to f5 *before* ...e6, then break with ...c5."}),
    ("French", {
        "w": "grab space with e5 and play on the kingside; support d4 with c3 so the ...c5/...f6 "
             "breaks don't blow up your center, and develop harmoniously.",
        "b": "your light-squared bishop is the problem child — plan ...b6/...Ba6 or ...Bd7–b5 to "
             "trade it, and hit the center with ...c5 and ...f6."}),
    ("Scandinavian", {
        "w": "develop with tempo against the early queen (Nc3, d4, Nf3, Bc4/Bd2) and seize the "
             "center — you get a free tempo or two, so just develop and castle into an edge.",
        "b": "after ...Qxd5 and Nc3 retreat to a5 or d6, then ...Nf6, ...c6, ...Bf5 — never leave "
             "the queen where a knight or bishop hits it with tempo."}),
    ("Alekhine", {
        "w": "you can grab space (Four Pawns) or play solidly (Exchange/Modern); keep your big "
             "center supported and don't let the knight provoke you into weaknesses.",
        "b": "provoke the pawns forward, then undermine them with ...d6 and ...c5/...f6 — don't "
             "let the center become a stable asset for White."}),
    ("Italian", {
        "w": "develop c3 then d4 for a classical center, castle early, and don't throw in "
             "Ng5/Bxf7 sacrifices unless you've concretely calculated them.",
        "b": "meet it with ...Nf6 and ...Bc5 or ...Be7, castle quickly, and prepare the ...d5 "
             "break to equalize comfortably."}),
    ("Ruy Lopez", {
        "w": "build the big center with c3+d4 and play the slow maneuvering game (Nbd2–f1–g3); "
             "patience and piece improvement are the whole point of the Ruy.",
        "b": "answer the pin with ...a6/...b5 to gain queenside space, reroute via ...Na5–c4 or "
             "...Nd7–f8–g6, then break with ...d5."}),
    ("Vienna", {"any": "use the f4 break for the attack, but castle before you open the f-file."}),
    ("Scotch", {"any": "complete development after the d4 break; don't grab the e-pawn at the "
                       "cost of king safety."}),
    ("King's Gambit", {"any": "give the gambit pawn back at the right moment for fast "
                              "development, and tuck your king away before attacking."}),
    ("Four Knights", {"any": "play for the d4 break and keep pieces on the board — don't trade "
                             "into a dull, dead-equal position; you want winning chances."}),
    ("Queen's Gambit Declined", {"any": "solve the bad bishop with ...b6/...Bb7 or a timely "
                                        "...dxc4 + ...c5; aim for the ...c5 or ...e5 freeing break."}),
    ("Queen's Gambit", {"any": "if you take on c4 don't try to hold the pawn — give it back for "
                               "...c5 and free development."}),
    ("Slav", {"any": "develop the c8-bishop to f5 or g4 BEFORE ...e6, then ...dxc4 and ...b5 to "
                     "keep the pawn with tempo."}),
    ("London", {"w": "watch the ...c5 + ...Qb6 hit on b2 (answer with Nc3/Qb3 or c3), and look "
                     "for the e4 break to bring the position to life.",
                "b": "hit it early with ...c5 and ...Qb6 pressuring b2, and trade off the "
                     "annoying dark-squared bishop with ...Nh5 or ...Bd6."}),
    ("English", {"any": "treat it as a reversed Sicilian — grab the center with a timed "
                        "...e5/...d5 and don't let the g2-bishop own the long diagonal."}),
    ("King's Pawn", {"any": "this is just the open game: develop knights before bishops, castle "
                            "by move ~6, and don't move the same piece twice. Your losses here "
                            "trace back to skipping development, not the opening choice."}),
    ("King's Knight", {"any": "a classic open game — get every minor piece out and castle before "
                             "starting anything; trouble starts when you chase a pawn instead of "
                             "finishing development."}),
    ("Englund", {"b": "this gambit is objectively dubious — switch to a sounder reply to 1.d4 "
                      "(...d5 or ...Nf6) so you're not down material from move 2.",
                 "w": "just decline the gambit, return the pawn for easy development, and you're "
                      "simply better — don't get greedy."}),
    ("Bishop's Opening", {"any": "it usually transposes to an Italian — head for c3+d4 and the "
                                 "same classical setup."}),
    ("Van't Kruijs", {"any": "1.e3 is passive and hands over the center for free — switch to "
                             "1.e4 or 1.d4 so you fight for the middle from move one."}),
    ("Hungarian", {"any": "...Be7 is solid but passive — still contest the center with ...d5 or "
                          "...d6 + ...Nf6 rather than drifting into a cramped game."}),
]


def _opening_plan(name: str, color: str) -> str:
    side = "w" if color == "White" else "b"
    low = name.lower()
    for key, plans in OPENING_PLANS:
        if key.lower() in low:
            return plans.get(side) or plans.get("any") or next(iter(plans.values()))
    return ("apply the universal opening rules here — develop every minor piece, castle "
            "early, and contest the center before launching anything.")


def _stage_errors(games: List[ParsedGame], evals) -> tuple:
    """Aggregate the user's error counts by game phase across a set of games."""
    from .engine import INACCURACY, MISTAKE, BLUNDER, CLAMP
    stage = {s: {"b": 0, "m": 0, "i": 0} for s in ("opening", "middlegame", "endgame")}
    cpls = []
    for g in games:
        e = evals.get(g.uuid) if evals else None
        if not e or not e.user_eval_curve:
            continue
        cpls.append(e.user_cpl)
        curve = e.user_eval_curve
        user_white = e.user_color == "white"
        total = len(curve) - 1
        for i in range(total):
            if (i % 2 == 0) != user_white:
                continue
            before = max(-CLAMP, min(CLAMP, curve[i]))
            after = max(-CLAMP, min(CLAMP, curve[i + 1]))
            loss = max(0, before - after)
            st = _stage_of(i, total, e.endgame_entry_ply)
            if loss >= BLUNDER: stage[st]["b"] += 1
            elif loss >= MISTAKE: stage[st]["m"] += 1
            elif loss >= INACCURACY: stage[st]["i"] += 1
    worst = max(stage, key=lambda s: stage[s]["b"] * 2 + stage[s]["m"])
    acpl = round(statistics.mean(cpls), 1) if cpls else None
    return stage, worst, acpl


def _specific_opening_tip(color: str, row: dict, sub: List[ParsedGame], evals, move15_avg) -> Dict:
    """A gameplay-informed, opening-specific tip for the user's most-played line."""
    name, n, win = row["name"], row["games"], row["win"]
    draws = sum(1 for g in sub if g.user_result == "draw")
    wins = sum(1 for g in sub if g.user_result == "win")
    score_pct = _pct(wins + 0.5 * draws, n)
    m15 = move15_avg(sub)
    plan = _opening_plan(name, color)

    obs = f"You score {score_pct:.0f}% with it."
    if evals:
        _stage, worst, acpl = _stage_errors(sub, evals)
        cpl_txt = f" (avg centipawn loss {acpl} there)" if acpl is not None else ""
        if m15 is not None and m15 >= 0.3 and score_pct < 50:
            obs = (f"You actually come out of it fine — about {m15:+.1f} pawns at move 15 — "
                   f"then fall apart: most of your errors in this line land in the {worst}"
                   f"{cpl_txt}. The opening isn't the problem; the plan *after* it is.")
        elif m15 is not None and m15 <= -0.2:
            obs = (f"You're already {m15:+.1f} pawns down by move 15 — you're playing the "
                   f"moves in the wrong order. Re-drill the first 8–10 moves until they're "
                   f"automatic, because you keep starting the middlegame on the back foot.")
        else:
            lead = f"Roughly level out of the opening ({m15:+.1f} pawns); " if m15 is not None else ""
            obs = (f"{lead}your results here hinge on the {worst}, where most of your "
                   f"mistakes happen{cpl_txt}.")
    text = (f"Your most-played {color} opening is the {name} — {n} games, {win:.0f}% wins "
            f"({score_pct:.0f}% score). {obs} Concretely: {plan}")
    return {"color": color, "name": name, "games": n, "win": win,
            "score_pct": round(score_pct, 1), "move15": m15, "text": text}


def openings_detail(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    has_engine = bool(evals)

    def move15_avg(gs):
        vals = [evals[g.uuid].move15_eval for g in gs
                if g.uuid in evals and evals[g.uuid].move15_eval is not None]
        return round(statistics.mean(vals) / 100, 1) if vals else None

    white = [g for g in games if g.user_color == chess.WHITE]
    black = [g for g in games if g.user_color == chess.BLACK]
    move15 = {"both": move15_avg(games), "white": move15_avg(white), "black": move15_avg(black)}

    # Group by opening *title* (not ECO), separately for each colour.
    def by_title(gs):
        groups: Dict[str, List[ParsedGame]] = defaultdict(list)
        for g in gs:
            groups[g.opening_name or "Unknown"].append(g)
        rows = []
        for name, sub in groups.items():
            if name == "Unknown":
                continue
            k = len(sub)
            rows.append({
                "name": name, "games": k,
                "win": _pct(sum(1 for g in sub if g.user_result == "win"), k),
                "draw": _pct(sum(1 for g in sub if g.user_result == "draw"), k),
                "lose": _pct(sum(1 for g in sub if g.user_result == "loss"), k),
                "move15": move15_avg(sub),
            })
        rows.sort(key=lambda r: (-r["games"], -r["win"]))
        return rows

    white_openings = by_title(white)
    black_openings = by_title(black)

    # Popular openings (overall) with verdicts — shown on the right side.
    popular = []
    for row in by_title(games):
        if row["games"] < 2:
            continue
        win, m15, k = row["win"], row["move15"], row["games"]
        status, text = "neutral", ""
        if m15 is not None:
            if m15 >= 0.5 and win >= 50:
                status, text = "good", (f"Strong opening for you — ~{m15:+.1f} pts ahead by "
                                        f"move 15 and you convert it ({win:.0f}% wins).")
            elif m15 >= 0.5 and win < 50:
                status, text = "bad", (f"You get an early edge (+{m15:.1f} pts) but win only "
                                       f"{win:.0f}% — study the middlegame plans.")
            elif m15 < 0:
                status, text = "bad", (f"You come out worse ({m15:+.1f} pts by move 15). "
                                       f"Re-drill the move order or swap it out.")
            else:
                status, text = "neutral", f"Balanced out of the opening ({m15:+.1f} pts, {win:.0f}% wins)."
        else:
            status = "good" if win >= 55 else ("bad" if win < 40 else "neutral")
            text = f"{win:.0f}% win rate over {k} games."
        popular.append({"name": row["name"], "games": k, "win": win,
                        "move15": m15, "status": status, "text": text})

    # Gameplay-specific tips for the single most-played White and Black opening.
    specific_tips = []
    for color_label, rows, subset in (("White", white_openings, white),
                                      ("Black", black_openings, black)):
        if not rows:
            continue
        top = rows[0]
        sub = [g for g in subset if (g.opening_name or "Unknown") == top["name"]]
        specific_tips.append(_specific_opening_tip(color_label, top, sub, evals, move15_avg))

    interp = []
    if has_engine and move15["both"] is not None:
        m = move15["both"]
        s = _good if m >= 0.3 else (_warn if m < -0.2 else _neut)
        interp.append(s("Average score after move 15",
                        f"On average you are {m:+} points "
                        f"{'ahead of' if m >= 0 else 'behind'} your opponent after the opening."))
        for color in ("white", "black"):
            if move15[color] is not None:
                mc = move15[color]
                s = _good if mc >= 0.3 else (_warn if mc < -0.2 else _neut)
                interp.append(s(f"With the {color} pieces",
                                f"{mc:+} points {'ahead' if mc >= 0 else 'behind'} after move 15."))
    elif not has_engine:
        interp.append(_neut("Move-15 score", "Enable deep (Stockfish) analysis to see how "
                                             "far ahead/behind you are after the opening phase."))

    improve = [
        "Lean into your green (strong) openings and play them more often.",
        "For openings where you're ahead but not winning, drill the resulting middlegame plans.",
        "Replace openings where you're behind by move 15 with lines that suit your style.",
    ]
    return {"key": "openings", "label": "Openings", "engine_required": not has_engine,
            "move15": move15, "white_openings": white_openings, "black_openings": black_openings,
            "popular_openings": popular[:8], "specific_tips": specific_tips,
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
def advantage_detail(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    if not evals:
        return {"key": "advantage_capitalization", "label": "Advantage Capitalization",
                "engine_required": True, "buckets": [],
                "interpretation": [_neut("Needs engine",
                    "Enable deep (Stockfish) analysis to measure how well you convert "
                    "winning positions.")], "how_to_improve": []}
    buckets = []
    for thr in ADV_BUCKETS:
        qual = [g for g in games if g.uuid in evals and evals[g.uuid].max_adv >= thr]
        won = sum(1 for g in qual if g.user_result == "win")
        buckets.append({"threshold": thr / 100, "games": len(qual),
                        "won": won, "pct": _pct(won, len(qual))})

    base = buckets[0]  # 1.5+ pawns
    interp = []
    if base["games"]:
        s = _good if base["pct"] >= 70 else (_warn if base["pct"] >= 50 else _bad)
        interp.append(s("Conversion",
            f"In the {base['games']} games where you reached a significant advantage "
            f"(+1.5 or more), you won {base['won']} of them ({base['pct']}%). Aim to "
            f"convert nearly all of these as you improve."))
    else:
        interp.append(_neut("Conversion", "You rarely reached a clear advantage in this sample."))
    improve = [
        "When clearly ahead, simplify: trade pieces (not pawns) toward a winning endgame.",
        "Avoid unnecessary complications — keep it simple once you're winning.",
        "Replay your won-but-drawn positions against the engine to see the cleanest path.",
    ]
    return {"key": "advantage_capitalization", "label": "Advantage Capitalization",
            "engine_required": False, "buckets": buckets,
            "interpretation": interp, "how_to_improve": improve}


def resourcefulness_detail(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    if not evals:
        return {"key": "resourcefulness", "label": "Resourcefulness",
                "engine_required": True, "buckets": [],
                "interpretation": [_neut("Needs engine",
                    "Enable deep (Stockfish) analysis to measure how often you save "
                    "worse positions.")], "how_to_improve": []}
    buckets = []
    for thr in ADV_BUCKETS:
        qual = [g for g in games if g.uuid in evals and evals[g.uuid].min_adv <= -thr]
        saved = sum(1 for g in qual if g.user_result != "loss")
        buckets.append({"threshold": -thr / 100, "games": len(qual),
                        "saved": saved, "pct": _pct(saved, len(qual))})

    base = buckets[0]
    interp = []
    if base["games"]:
        s = _good if base["pct"] >= 18 else _warn
        interp.append(s("Saves",
            f"You won or drew {base['pct']}% of the {base['games']} games where you fell to "
            f"a clear disadvantage (-1.5 or worse)."))
    else:
        interp.append(_neut("Saves", "You were rarely in a clearly worse position — nice."))
    improve = [
        "When worse, set practical problems: create threats and complications, don't go passive.",
        "Aim for fortresses and opposite-colored-bishop draws in losing endgames.",
        "Keep your composure under time pressure — many losses come from rushing when worse.",
    ]
    return {"key": "resourcefulness", "label": "Resourcefulness",
            "engine_required": False, "buckets": buckets,
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
def _stage_of(ply_idx: int, total: int, eg_ply: Optional[int]) -> str:
    if ply_idx < 20:
        return "opening"
    if eg_ply is not None and ply_idx >= eg_ply:
        return "endgame"
    if eg_ply is None and ply_idx >= total - 16:
        return "endgame"
    return "middlegame"


def tactics_detail(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    if not evals:
        return {"key": "tactics", "label": "Tactics", "engine_required": True,
                "interpretation": [_neut("Needs engine",
                    "Enable deep (Stockfish) analysis to count your blunders, mistakes "
                    "and inaccuracies per game.")], "how_to_improve": []}
    ge = [evals[g.uuid] for g in games if g.uuid in evals]
    n = len(ge) or 1
    user = {
        "blunders": round(sum(e.user_blunders for e in ge) / n, 1),
        "mistakes": round(sum(e.user_mistakes for e in ge) / n, 1),
        "inaccuracies": round(sum(e.user_inaccuracies for e in ge) / n, 1),
        "avg_cpl": round(statistics.mean([e.user_cpl for e in ge]), 1) if ge else 0,
    }
    opp = {
        "blunders": round(sum(e.opp_blunders for e in ge) / n, 1),
        "mistakes": round(sum(e.opp_mistakes for e in ge) / n, 1),
        "inaccuracies": round(sum(e.opp_inaccuracies for e in ge) / n, 1),
        "avg_cpl": round(statistics.mean([e.opp_cpl for e in ge]), 1) if ge else 0,
    }

    # Per-stage user error counts, recomputed from the stored user-POV curve.
    stage = {s: {"blunders": 0, "mistakes": 0, "inaccuracies": 0, "games": 0}
             for s in ("opening", "middlegame", "endgame")}
    from .engine import INACCURACY, MISTAKE, BLUNDER, CLAMP
    for g in games:
        e = evals.get(g.uuid)
        if not e or not e.user_eval_curve:
            continue
        curve = e.user_eval_curve
        user_white = e.user_color == "white"
        total = len(curve) - 1
        seen = set()
        for i in range(total):
            mover_white = (i % 2 == 0)
            if mover_white != user_white:
                continue
            before = max(-CLAMP, min(CLAMP, curve[i]))
            after = max(-CLAMP, min(CLAMP, curve[i + 1]))
            loss = max(0, before - after)
            st = _stage_of(i, total, e.endgame_entry_ply)
            seen.add(st)
            if loss >= BLUNDER: stage[st]["blunders"] += 1
            elif loss >= MISTAKE: stage[st]["mistakes"] += 1
            elif loss >= INACCURACY: stage[st]["inaccuracies"] += 1
        for st in seen:
            stage[st]["games"] += 1

    interp = []
    if user["blunders"] <= opp["blunders"]:
        interp.append(_good("Comparison with opponents",
            f"You make fewer tactical mistakes than your opponents on average "
            f"({user['blunders']} vs {opp['blunders']} blunders/game)."))
    else:
        interp.append(_bad("Comparison with opponents",
            f"You blunder more than your opponents on average "
            f"({user['blunders']} vs {opp['blunders']} blunders/game)."))
    worst_stage = max(stage, key=lambda s: stage[s]["blunders"] + stage[s]["mistakes"])
    interp.append(_neut("Where it goes wrong",
        f"Most of your errors happen in the {worst_stage}. Average centipawn loss: "
        f"{user['avg_cpl']}."))

    improve = [
        "Do daily tactics puzzles to sharpen pattern recognition.",
        f"Slow down in the {worst_stage} — that's where you lose the most centipawns.",
        "Before every move, check all checks, captures and threats (yours and theirs).",
    ]
    return {"key": "tactics", "label": "Tactics", "engine_required": False,
            "user": user, "opponent": opp, "per_stage": stage,
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
def time_detail(games: List[ParsedGame]) -> Dict:
    timed = [g for g in games if g.base and g.moves]
    # Average time spent by phase (thirds of the game) as % of moves.
    phase_spent = {"opening": [], "middlegame": [], "endgame": []}
    flagged = 0
    for g in timed:
        if g.lost_on_time:
            flagged += 1
        um = g.user_moves
        third = max(1, len(um) // 3)
        for i, m in enumerate(um):
            if m.spent is None:
                continue
            if i < third: phase_spent["opening"].append(m.spent)
            elif i < 2 * third: phase_spent["middlegame"].append(m.spent)
            else: phase_spent["endgame"].append(m.spent)
    phases = {k: round(statistics.mean(v), 1) if v else 0 for k, v in phase_spent.items()}

    interp = []
    if flagged:
        interp.append(_bad("Flagging",
            f"You lost on time in {flagged} game(s). Those are whole points handed over."))
    else:
        interp.append(_good("Flagging", "You didn't lose a single game on time. Great clock discipline."))
    biggest = max(phases, key=phases.get) if any(phases.values()) else None
    if biggest:
        interp.append(_neut("Where your time goes",
            f"You spend the most time in the {biggest} "
            f"(~{phases[biggest]}s/move there)."))
    improve = [
        "Budget your time: roughly base_time / 40 per move, more for critical positions.",
        "Play the opening briskly to bank time for the middlegame.",
        "In won or equal positions under low time, simplify and make safe moves.",
    ]
    return {"key": "time_management", "label": "Time Management",
            "phases": phases, "lost_on_time": flagged,
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
def endgame_detail(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    if not evals:
        return {"key": "endgames", "label": "Endgames", "engine_required": True,
                "interpretation": [_neut("Needs engine",
                    "Enable deep (Stockfish) analysis to evaluate how you handle endgames.")],
                "how_to_improve": []}
    eg = [(g, evals[g.uuid]) for g in games
          if g.uuid in evals and evals[g.uuid].reached_endgame
          and evals[g.uuid].endgame_entry_eval is not None]

    cats = {
        "winning": {"games": 0, "good": 0},   # entered +1.5: did you win?
        "equal":   {"games": 0, "good": 0},   # entered -1.5..1.5: did you score?
        "losing":  {"games": 0, "good": 0},   # entered -1.5: did you save?
    }
    notable = []
    for g, e in eg:
        ev = e.endgame_entry_eval / 100
        if e.endgame_entry_eval >= 150:
            cats["winning"]["games"] += 1
            if g.user_result == "win":
                cats["winning"]["good"] += 1
            else:
                notable.append({"type": "threw_win", "opening": g.opening_name,
                                "entry": round(ev, 1), "result": g.user_result, "url": g.url})
        elif e.endgame_entry_eval <= -150:
            cats["losing"]["games"] += 1
            if g.user_result != "loss":
                cats["losing"]["good"] += 1
                notable.append({"type": "saved", "opening": g.opening_name,
                                "entry": round(ev, 1), "result": g.user_result, "url": g.url})
        else:
            cats["equal"]["games"] += 1
            if g.user_result != "loss":
                cats["equal"]["good"] += 1

    summary = {
        "reached": len(eg),
        "winning_conversion": _pct(cats["winning"]["good"], cats["winning"]["games"]),
        "equal_hold": _pct(cats["equal"]["good"], cats["equal"]["games"]),
        "losing_save": _pct(cats["losing"]["good"], cats["losing"]["games"]),
        "cats": cats,
    }

    interp = []
    wc = summary["winning_conversion"]
    if cats["winning"]["games"]:
        s = _good if wc >= 80 else (_warn if wc >= 60 else _bad)
        interp.append(s("Converting winning endgames",
            f"You entered a winning endgame {cats['winning']['games']} times and won "
            f"{cats['winning']['good']} ({wc}%)."))
    if cats["equal"]["games"]:
        interp.append(_neut("Holding equal endgames",
            f"From level endgames you avoided defeat {summary['equal_hold']}% of the time "
            f"({cats['equal']['games']} games)."))
    if cats["losing"]["games"]:
        s = _good if summary["losing_save"] >= 20 else _warn
        interp.append(s("Saving lost endgames",
            f"You rescued {cats['losing']['good']} of {cats['losing']['games']} lost "
            f"endgames ({summary['losing_save']}%)."))
    if not eg:
        interp.append(_neut("Endgames", "Few of your games reached an endgame in this sample."))

    improve = [
        "Drill king-and-pawn endgames: opposition, the rule of the square, key squares.",
        "Learn the Lucena and Philidor rook-endgame positions — they decide most rook endings.",
        "When winning an endgame, activate your king and push your passed pawn with support.",
        "When defending, look for fortress setups and trade pawns toward known draws.",
    ]
    return {"key": "endgames", "label": "Endgames", "engine_required": False,
            "summary": summary, "notable": notable[:8],
            "interpretation": interp, "how_to_improve": improve}


# --------------------------------------------------------------------------
def build_details(games: List[ParsedGame], evals: Dict[str, "object"]) -> Dict:
    """Assemble all detail panels, keyed by skill, for the drill-down UI."""
    return {
        "win_rate": win_rate_detail(games),
        "openings": openings_detail(games, evals),
        "tactics": tactics_detail(games, evals),
        "advantage_capitalization": advantage_detail(games, evals),
        "resourcefulness": resourcefulness_detail(games, evals),
        "time_management": time_detail(games),
        "endgames": endgame_detail(games, evals),
    }


# ==========================================================================
# Expanded personalized tips: a grounded *rationale* (why) + *concrete steps*
# (how) for each headline tip, drawn from the user's actual numbers.
# ==========================================================================

def _worst_phase(details: Dict) -> str:
    ps = (details.get("tactics") or {}).get("per_stage") or {}
    if not ps:
        return "middlegame"
    return max(ps, key=lambda s: ps[s]["blunders"] * 2 + ps[s]["mistakes"])


def _tip_tactics(tip, sk, overall, details):
    td = details.get("tactics") or {}
    user, opp = td.get("user") or {}, td.get("opponent") or {}
    worst = _worst_phase(details)
    blun, mist, cpl = user.get("blunders"), user.get("mistakes"), user.get("avg_cpl")
    adv = (details.get("advantage_capitalization") or {}).get("buckets") or []
    adv0 = adv[0] if adv else None
    score = sk.get("tactics", {}).get("score")

    rationale = []
    if blun is not None:
        rationale.append(
            f"Tactics is your lowest skill at {score}/100. Across your analyzed games "
            f"Stockfish counted an average of {blun} blunders and {mist} mistakes per "
            f"game (avg centipawn loss {cpl}), and most of them happen in the {worst}.")
        rationale.append(
            f"Your opponents blunder about as often ({opp.get('blunders')}/game), so at "
            f"your level the player who blunders *last* usually wins. That makes cutting "
            f"blunders the single highest-leverage thing you can work on — worth more "
            f"rating than any amount of opening study.")
    else:
        rationale.append(
            "A large share of your losses come from missed or allowed tactics rather "
            "than from strategic misunderstandings — i.e. one-move oversights.")
    if adv0 and adv0.get("games"):
        rationale.append(
            f"It compounds downstream: you reached a winning position in {adv0['games']} "
            f"games but converted only {adv0['pct']}% — usually a single tactic thrown away.")

    steps = [
        "Before EVERY move, run a 3-second blunder check: name every check, capture, and "
        "threat your opponent has in reply. This one habit eliminates most one-move blunders.",
        f"Do 15 minutes of tactics puzzles daily and weight them toward the {worst}, where "
        f"you leak the most — use themes like ‘hanging piece’, ‘fork’, and ‘pin’.",
        "After each session, open Game Review here on your worst loss and step to your "
        "single biggest eval drop; say out loud what pattern you missed so it sticks.",
        f"Spend a little more time entering the {worst} (slow down for 2–3 key moves) "
        "instead of spreading your clock evenly.",
    ]
    if blun is not None:
        target = max(0.5, round(blun * 0.5, 1))
        steps.append(f"Track it: aim to cut blunders/game from {blun} to ~{target}. "
                     f"Re-run this report weekly to watch the number fall.")
    return rationale, steps


def _tip_openings(tip, sk, overall, details):
    od = details.get("openings") or {}
    specifics = od.get("specific_tips") or []
    rationale = [
        "Your results swing a lot depending on the opening — in some lines you’re "
        "effectively starting the middlegame from a worse position, which quietly costs "
        "points before you’ve had a chance to outplay anyone."]
    for st in specifics:
        m = st.get("move15")
        if m is not None and m < 0:
            rationale.append(
                f"As {st['color']} in the {st['name']} you’re {m:+.1f} pawns by move 15 — "
                f"that’s a move-order problem, not weak chess.")
    steps = [
        "Narrow your repertoire: pick ONE opening for White and one defense each against "
        "1.e4 and 1.d4. At your level depth beats variety.",
        "For each, memorize the first ~10 moves cold AND the one main plan (where your "
        "pieces belong and which pawn break you’re aiming for).",
    ]
    for st in specifics:
        concrete = st["text"].split("Concretely:")[-1].strip()
        steps.append(f"{st['color']} – {st['name']}: {concrete}")
    steps.append("Use chess.com’s Opening Explorer (or a Lichess study) to walk the main "
                 "line and see the typical middlegame that follows.")
    return rationale, steps


def _tip_worst_opening(tip, sk, overall, details):
    worst = tip.get("_worst") or {}
    rationale = [
        f"“{worst.get('name')}” is your worst-scoring opening "
        f"({worst.get('score_pct')}% over {worst.get('games')} games). Repeatedly losing "
        f"in the same line is the easiest leak to plug because it’s so concentrated."]
    name = worst.get("name", "")
    steps = [
        f"Decide: are you going to *fix* {name} or *avoid* it? Both are valid.",
        f"If fixing: spend one focused session on {name} — learn the main line 10 moves "
        f"deep and the single key idea, then play 5 games deliberately steering into it.",
        f"If avoiding: choose a different first move / response that sidesteps {name} "
        f"entirely, and drill that instead.",
        "Either way, review your last two losses in this line move-by-move to find the "
        "exact point it went wrong — it’s usually the same moment each game.",
    ]
    return rationale, steps


def _tip_advantage(tip, sk, overall, details):
    b = (details.get("advantage_capitalization") or {}).get("buckets") or []
    b0 = b[0] if b else None
    rationale = []
    if b0 and b0.get("games"):
        rationale.append(
            f"You get winning positions plenty — +1.5 pawns or more in {b0['games']} of "
            f"your games — but win only {b0['pct']}% of them. Your problem isn’t *getting* "
            f"an advantage; it’s *closing it out*.")
    rationale.append(
        "Blowing won positions is the most rating-expensive mistake there is: it’s a full "
        "point you had already earned, handed back.")
    steps = [
        "When you’re clearly winning, switch your mindset from ‘attack’ to ‘no "
        "counterplay’: before each move ask what your opponent wants, and stop it first.",
        "Trade pieces, not pawns, when you’re ahead in material — every trade takes you "
        "closer to a trivially winning endgame.",
        "Resist the flashy move. The simple, safe consolidating move wins won positions; "
        "you don’t need to force mate.",
        "Practice converting: replay 3 of your own ‘threw it away’ games against the "
        "engine starting from the winning moment, and try to bring them home.",
    ]
    return rationale, steps


def _tip_resourcefulness(tip, sk, overall, details):
    b = (details.get("resourcefulness") or {}).get("buckets") or []
    b0 = b[0] if b else None
    score = sk.get("resourcefulness", {}).get("score")
    rationale = []
    if b0 and b0.get("games"):
        rationale.append(
            f"When you fell to a clearly worse position (-1.5+), you still salvaged a "
            f"win or draw {b0['pct']}% of the time across {b0['games']} games "
            f"(score {score}/100). Points rescued from lost games are pure upside.")
    rationale.append(
        "Most players at your level give up mentally when worse and lose on autopilot. "
        "Fighting on is a cheap source of rating because your opponents err too.")
    steps = [
        "When worse, stop trying to ‘equalize’ and start setting *practical problems*: "
        "make threats that force your opponent to find precise replies.",
        "Aim for known drawing tools — opposite-colored-bishop endings, fortresses, and "
        "perpetual-check setups — rather than passive defense.",
        "Don’t resign early at your level; many opponents return the favor. Keep playing "
        "until the position is truly hopeless.",
        "Use your opponent’s clock: in worse positions, pose complicated choices that eat "
        "their time and invite a slip.",
    ]
    return rationale, steps


def _tip_endgames(tip, sk, overall, details):
    s = (details.get("endgames") or {}).get("summary") or {}
    cats = s.get("cats") or {}
    rationale = []
    if cats.get("winning", {}).get("games"):
        rationale.append(
            f"You reached an endgame in {s.get('reached')} games and converted "
            f"{cats['winning']['good']} of {cats['winning']['games']} winning ones "
            f"({s.get('winning_conversion')}%). Endgames decide close games, and a few "
            f"percent of conversion is several rating points.")
    else:
        rationale.append(
            "Endgames are where evenly-matched games are won and lost, and they reward "
            "knowledge more than talent — a great area to bank quick gains.")
    steps = [
        "Master king-and-pawn fundamentals first: opposition, the rule of the square, and "
        "key squares. These underpin every other endgame.",
        "Learn the two must-know rook endings — the Lucena (winning) and Philidor "
        "(drawing) — since rook endgames are by far the most common.",
        "When winning, activate your king (march it up the board) and push your passed "
        "pawn only with support behind it.",
        "Drill 10 minutes of endgame studies a week (chess.com Lessons → Endgames, or "
        "Lichess Practice). Little and often beats cramming.",
    ]
    return rationale, steps


def _tip_time(tip, sk, overall, details):
    tdm = details.get("time_management") or {}
    phases = tdm.get("phases") or {}
    flagged = tdm.get("lost_on_time", 0)
    biggest = max(phases, key=phases.get) if any(phases.values()) else None
    rationale = []
    if flagged:
        rationale.append(
            f"You lost {flagged} game(s) on time outright — those are whole points given "
            f"away regardless of how well you played the board.")
    if biggest:
        rationale.append(
            f"Your time goes disproportionately into the {biggest} "
            f"(~{phases[biggest]}s/move there), which leaves less for other critical moments.")
    if not rationale:
        rationale.append("Clock trouble turns good positions into losses independent of "
                         "your chess strength, so it’s worth a little structure.")
    steps = [
        "Set a rough per-move budget: about base_time ÷ 40 per move, and consciously spend "
        "extra only on genuinely critical positions.",
        "Play the opening briskly (you should mostly know it) to bank time for the "
        "middlegame, where the real decisions are.",
        "Under 30 seconds, simplify: make safe, solid moves and trade into clear positions "
        "instead of calculating long lines.",
        "In daily/online games, pre-move only obvious recaptures — pre-moving in sharp "
        "spots is a common way to blunder.",
    ]
    return rationale, steps


def _tip_flagging(tip, sk, overall, details):
    return _tip_time(tip, sk, overall, details)


def _tip_color(tip, sk, overall, details):
    side = tip.get("_side", "your weaker side")
    gap = tip.get("_gap", "")
    rationale = [
        f"You score about {gap} points lower as {side} than with the other colour. A gap "
        f"that size almost always traces to an under-prepared opening repertoire on one "
        f"side rather than a general weakness.",
        f"Because it’s isolated to {side}, it’s an efficient fix: improving one repertoire "
        f"lifts roughly half of your games."]
    steps = [
        f"Audit your {side} games in the Openings panel: find which specific lines score "
        f"worst and start there.",
        f"Build a tight {side} repertoire — one main system, learned 10 moves deep with "
        f"its plan — rather than improvising.",
        f"Play a focused batch of games as {side} only, reviewing each one here to see "
        f"where the {side} games diverge from your better colour.",
    ]
    return rationale, steps


_TIP_GEN = {
    "tactics": _tip_tactics,
    "openings": _tip_openings,
    "worst_opening": _tip_worst_opening,
    "advantage_capitalization": _tip_advantage,
    "resourcefulness": _tip_resourcefulness,
    "endgames": _tip_endgames,
    "time_management": _tip_time,
    "flagging": _tip_flagging,
    "color_balance": _tip_color,
}


def enrich_tips(tips: List[Dict], skills: List[Dict], overall: Dict, details: Dict) -> List[Dict]:
    """Attach a grounded `rationale` (why) and `steps` (how) to each tip."""
    sk = {s["key"]: s for s in skills}
    for t in tips:
        gen = _TIP_GEN.get(t.get("key"))
        try:
            rationale, steps = gen(t, sk, overall, details) if gen else ([], [])
        except Exception:
            rationale, steps = [], []
        t["rationale"] = rationale or [t.get("text", "")]
        t["steps"] = steps or ["Use the Game Review on a recent game to see concrete examples "
                               "of this in your own play."]
        # Drop the private helper fields before serializing.
        t.pop("_worst", None)
    return tips
