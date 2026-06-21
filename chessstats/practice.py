"""Curated early/mid-game practice content.

A hand-picked guide (opening principles, plans, what to watch for) plus a set of
fundamental drill positions. Drill FENs are generated from short move sequences
at import time, so they're guaranteed legal and easy to read/extend.
"""
from __future__ import annotations

from typing import Dict, List

import chess


# --------------------------------------------------------------------------- #
# The written guide: curated fundamentals, rendered as cards on the frontend.
# --------------------------------------------------------------------------- #
GUIDE: List[Dict] = [
    {
        "icon": "♙",
        "title": "Opening principles",
        "blurb": "The first ~10 moves are about three things: the center, "
                 "development, and king safety.",
        "items": [
            "Fight for the center with a pawn (e4/d4 — or c4/Nf3).",
            "Develop knights before bishops, toward the center (Nf3/Nc6).",
            "Castle early — usually by move 8–10 — to connect your rooks.",
            "Don't move the same piece twice in the opening without a reason.",
            "Don't bring your queen out early; it just becomes a target.",
        ],
    },
    {
        "icon": "♘",
        "title": "From opening to middlegame",
        "blurb": "Once you're developed and castled, switch from 'develop' to "
                 "'make a plan'. Every move should improve your position.",
        "items": [
            "Improve your worst-placed piece — find it a better square.",
            "Look for a pawn break (…d5, …c5, f4) to open lines for your pieces.",
            "Put knights on outposts: central squares a pawn can't attack.",
            "Aim rooks at open and half-open files.",
            "Trade pieces when you're cramped or ahead in material; keep pieces "
            "when you have more space or an attack.",
        ],
    },
    {
        "icon": "⚠",
        "title": "What to watch for from your opponent",
        "blurb": "After every opponent move, pause and ask: 'What does that move "
                 "do — what does it attack or threaten?'",
        "items": [
            "Scan for undefended pieces (yours and theirs) every move.",
            "Watch the f7/f2 square early — it's the classic attacking target.",
            "Look for knight forks, pins, and discovered attacks before you move.",
            "Don't auto-recapture — first check if there's something stronger.",
            "Mind your back rank once you've castled (give the king luft).",
        ],
    },
    {
        "icon": "✓",
        "title": "A simple thinking routine",
        "blurb": "Use the same checklist on every move to stop blundering and "
                 "to find the best plan.",
        "items": [
            "1. What changed? What did my opponent's last move threaten?",
            "2. Checks, captures, threats — for me, then for my opponent.",
            "3. Is any piece of mine (or theirs) hanging?",
            "4. What's my worst piece, and how do I improve it?",
            "5. Only then choose a move — and re-check it's safe.",
        ],
    },
]


# --------------------------------------------------------------------------- #
# Drill positions. Each is built from a short legal move sequence; the player is
# the side to move. The engine grades whatever move they choose; `principle` is
# the teaching point revealed afterward.
# --------------------------------------------------------------------------- #
_DRILL_DEFS: List[Dict] = [
    {
        "id": "develop-center",
        "moves": ["e4", "e5"],
        "theme": "Development & the center",
        "prompt": "Make a natural developing move that fights for the center.",
        "hint": "A knight belongs on its best central square.",
        "principle": "Develop knights toward the center before anything fancy. "
                     "Nf3 develops a piece, eyes the center, and pressures e5 — "
                     "exactly what move 2 should do.",
    },
    {
        "id": "castle-early",
        "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"],
        "theme": "King safety",
        "prompt": "You're developed — now make your king safe.",
        "hint": "Tuck the king away before opening the position.",
        "principle": "Castling by move 6–8 is almost always right: it safeguards "
                     "the king and brings a rook toward the center. Delaying it is "
                     "one of the most common amateur mistakes.",
    },
    {
        "id": "punish-early-queen",
        "moves": ["e4", "e5", "Nf3", "Qf6"],
        "theme": "Punishing the early queen",
        "prompt": "Black brought the queen out early. Develop and gain tempo.",
        "hint": "Grab the center and develop naturally.",
        "principle": "When the opponent commits the queen early, just develop with "
                     "healthy moves (d4, Nc3, Bc4) and seize the center. The exposed "
                     "queen becomes a target as your pieces come out, gaining you time.",
    },
    {
        "id": "recapture-develop",
        "moves": ["e4", "e5", "Nf3", "Nc6", "d4", "exd4", "Nxd4"],
        "theme": "Healthy development",
        "prompt": "You're Black. Continue developing toward the center.",
        "hint": "Bring out a knight to its natural square.",
        "principle": "After the center pawns are traded, keep developing with "
                     "purpose. A knight to f6 hits e4 and prepares to castle — "
                     "don't waste time with early pawn grabs or queen moves.",
    },
    {
        "id": "qgd-dont-hold-pawn",
        "moves": ["d4", "d5", "c4", "dxc4"],
        "theme": "Center over a pawn",
        "prompt": "Black grabbed the c4 pawn. How should White react?",
        "hint": "Don't chase the pawn — build your position.",
        "principle": "In the Queen's Gambit, the c4 pawn isn't really lost — trying "
                     "to hold it with b3?! or Qa4 wastes time. Develop (Nf3/e3) and "
                     "you'll regain it while building a strong center.",
    },
    {
        "id": "queens-gambit-develop",
        "moves": ["d4", "d5", "c4", "e6", "Nc3", "Nf6"],
        "theme": "Sound development",
        "prompt": "You're White. Keep developing soundly.",
        "hint": "Develop a piece or support your center.",
        "principle": "Classical development — bishops and knights to active squares, "
                     "supporting the center — is the backbone of the Queen's Gambit. "
                     "Bg5 pins the f6-knight; Nf3 and e3 are equally principled.",
    },
    {
        "id": "make-a-plan",
        "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6",
                  "d3", "d6", "O-O", "O-O"],
        "theme": "Middlegame planning",
        "prompt": "Fully developed and castled — now find a constructive plan.",
        "hint": "Prepare a central pawn break or improve a piece.",
        "principle": "With development done, make a plan: prepare the d3–d4 break to "
                     "open the center, reroute a knight (Nbd2–f1–g3), or improve your "
                     "worst piece. Aimless shuffling lets the opponent take over.",
    },
    {
        "id": "spot-the-threat",
        "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "Ng5"],
        "theme": "Spot the opponent's threat",
        "prompt": "You're Black. White just played Ng5 — what's threatened, and "
                  "how do you meet it?",
        "hint": "Both the bishop and the knight are eyeing f7. Hit back in the center.",
        "principle": "Always ask what the opponent's move threatens. Here Ng5 piles "
                     "onto f7 (threatening Nxf7, the Fried Liver). The sound reply is "
                     "…d5, striking the center and the c4-bishop instead of passively "
                     "defending.",
    },
]


def _build_drills() -> List[Dict]:
    out = []
    for d in _DRILL_DEFS:
        board = chess.Board()
        for san in d["moves"]:
            board.push_san(san)
        out.append({
            "id": d["id"],
            "fen": board.fen(),
            "side": "white" if board.turn == chess.WHITE else "black",
            "theme": d["theme"],
            "prompt": d["prompt"],
            "hint": d["hint"],
            "principle": d["principle"],
        })
    return out


DRILLS: List[Dict] = _build_drills()
