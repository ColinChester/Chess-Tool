# Chess Stats ♟

A local web dashboard that pulls your **chess.com** game history, analyzes it, and
gives skill scores, an opening breakdown, time-management insights, and
personalized tips — inspired by [Aimchess](https://aimchess.com).

No account, API key, or login required: it uses the free, read-only
[chess.com public data API](https://www.chess.com/news/view/published-data-api).

## Skills measured

Like Aimchess, it scores six areas (0–100):

| Skill | How it's measured | Confidence |
|-------|-------------------|------------|
| **Time Management** | Per-move clock data (`%clk`): flagging, time scrambles, moves under 5s | High |
| **Openings** | Results & accuracy grouped by opening family (ECO) | Medium |
| **Endgames** | Outcome in games that reached an endgame | Medium |
| **Advantage Capitalization** | Do you win when you out-accuracy your opponent? | Estimate |
| **Resourcefulness** | Do you save points when out-played? | Estimate |
| **Tactics** | Accuracy + quick wins/losses as a proxy | Estimate |

### Personalized tips — click for the full coaching detail

The **Personalized tips** card lists your highest-priority focus areas. Click any
tip to open a detailed coaching view with two parts:

- **Why this is worth your attention** — a rationale grounded in *your* numbers
  (e.g. "Tactics is your lowest skill at 2.9/100… 4.1 blunders/game… you reached a
  winning position in 32 games but converted only 50%").
- **Concrete steps to improve** — specific, actionable advice with drills, habits,
  and a trackable target (e.g. "cut blunders/game from 4.1 to ~2.0").

### Drill-down detail panels

Click any skill card (or the Record card) to open an in-depth breakdown — modeled
on the Aimchess report sections — with a chart, an **Interpretation** (✅/🔥/⚠️
callouts), and **How to improve** steps:

- **Win Rate** — win/draw/loss split for White, Black, and overall.
- **Openings** — average engine score after move 15 (overall + per colour),
  your openings grouped **by name** and split into **White / Black** lists with
  win/draw/loss bars, plus **gameplay-specific, colour-aware tips** for your
  single most-played White and Black opening (drawn from a built-in plan
  knowledge base combined with where your errors actually cluster).
- **Tactics** — blunders / mistakes / inaccuracies per game vs. your opponents,
  plus where your errors happen (opening / middlegame / endgame) and avg centipawn loss.
- **Advantage Capitalization** — % of games converted when you reached +1.5 / +2 / +3 / +4.
- **Resourcefulness** — % of games saved when you fell to −1.5 / −2 / −3 / −4.
- **Time Management** — time spent per phase and flagging.
- **Endgames** — a dedicated breakdown of how you convert winning, hold equal,
  and save losing endgames, with the specific games where you threw a win or
  pulled off a save (linked to chess.com).

### Move-by-move game review (chess.com-style)

Every game in the **Recent games** list has a **Review** button that opens a
full move-by-move breakdown powered by Stockfish (depth 14):

- a board you can step through (← / → keys or the nav buttons) with the last
  move highlighted and a live **evaluation bar**;
- each move **classified** — Best / Excellent / Good / Book / Inaccuracy /
  Mistake / Blunder — with a colour-coded summary;
- for every move: the **engine's recommended move** and principal line;
- **plain-language explanations** for the key moves (what Stockfish preferred,
  the eval swing it caused, and whether it hung material).

### Practice — early/mid-game drills

A standalone **Practice** tab teaches opening/middlegame fundamentals (center,
development, king safety, common plans) as a curated guide, then drills them:
you're shown a position and asked to find the right idea, your move is graded
by Stockfish, and you get a hint / retry / next-position flow with a running
score. No chess.com account needed — drill FENs are generated from short,
known-legal move sequences. See [`chessstats/practice.py`](chessstats/practice.py).

### Board — analysis sandbox

A **Board** tab is a free-form analysis board: set up any position with
drag-and-drop pieces (or paste a FEN), pick the side to move, then play it out
with full legal-move validation and game-over detection (checkmate, stalemate,
insufficient material, etc.).

### Background pre-warming

When you load a report, the app immediately starts analyzing your most recent
games with Stockfish **in the background** (up to `WARM_THRESHOLD`, default 40) —
even if “Deep” is unchecked. A status badge shows progress
(`⚙ Analyzing… 12/40 ready` → `✅ ready`). By the time you tick **Deep** or open
a **Review**, the work is usually already cached, so it returns instantly. The
warmer is a daemon thread, de-duplicated per user, and writes to the same
per-game cache as the deep pass.

### Hybrid design — statistical now, engine optional

The base analysis needs **no chess engine**. The skills marked *Estimate* are
proxies derived from chess.com's own post-game accuracy data. For true move-quality
scoring you can plug in **Stockfish** (the "hybrid" deep pass):

```bash
brew install stockfish        # or set STOCKFISH_PATH
```

Then tick **“Deep (Stockfish)”** in the UI (or pass `engine=true` to the API).
The engine evaluates every position to compute real centipawn loss, move-15
scores, advantage/disadvantage buckets, and endgame evals — powering the
tactics / advantage / resourcefulness / endgame panels and scores. The first
deep run takes ~1–2 minutes (depth 12); **results are cached per game** in
`.cache/engine/`, so re-runs only analyze new games and return instantly. See
[`chessstats/engine.py`](chessstats/engine.py) and
[`chessstats/details.py`](chessstats/details.py).

## Setup & run

```bash
cd "Chess Stats"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # or: uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>, enter a username, click **Analyze**.
Deep-link: `http://127.0.0.1:8000/?u=YOUR_USERNAME`.

## Deploy (Docker)

The included `Dockerfile` bundles **Stockfish**, so the engine features work out
of the box. The server binds `0.0.0.0` and reads the listen port from `$PORT`,
which is what most hosts inject.

```bash
docker build -t chess-stats .
docker run -p 8000:8000 chess-stats     # then open http://127.0.0.1:8000
```

This image runs on any host that builds from a Dockerfile (e.g. Hugging Face
Spaces, Render, Fly.io). The on-disk engine cache (`.cache/`) is ephemeral on
such hosts and is simply recomputed after a restart. If Stockfish ever isn't
present, the app still runs and disables the deep-analysis endpoints.

## API

- `GET /api/report?username=NAME&limit=60&time_class=blitz,rapid&engine=false`
  → `overall_skill`, `skills[]`, `overall`, `details`, `games[]`, `tips[]`, `player`.
  Also kicks off background engine pre-warming for the user.
- `GET /api/engine-status?username=NAME`
  → `{available, total, cached, warming}` — how many recent games are engine-cached.
- `GET /api/review?username=NAME&uuid=GAME_UUID&depth=14`
  → move-by-move review: classified moves, engine best move + line, evals, explanations.
- `GET /api/practice`
  → the curated fundamentals guide + drill positions (no account needed).
- `GET /api/practice/grade?fen=FEN&move=e2e4&depth=14`
  → grades a move (UCI) played from a drill position using Stockfish.
- `GET /api/board/validate?fen=FEN`
  → legality/game-over check for a sandbox position.
- `GET /api/board/move?fen=FEN&move=e2e4&depth=12`
  → applies a move (UCI) on the analysis board server-side (handles castling,
  en passant, promotion) and returns the new FEN, check/game-over state, and
  an engine grade for the move when Stockfish is available.

## Project layout

```
app.py                  FastAPI app: report/status/review APIs + serves the dashboard
chessstats/
  chesscom.py           chess.com API client (archives, profile, stats)
  pgn.py                PGN + clock parsing (python-chess)
  analysis.py           the six-skill statistical engine + tips
  details.py            per-skill drill-down panels + endgame analysis
  engine.py             Stockfish: per-game eval, caching, and game review
  practice.py           curated fundamentals guide + drill positions
static/                 dashboard (HTML/CSS/JS, Chart.js) — Analysis / Practice / Board tabs
.cache/engine/          per-game engine results (auto-created)
```

## Notes & honesty

- Scores are **heuristics**, not true rating-band percentiles (Aimchess compares
  you against peers; that data isn't public). They're calibrated so ~50 ≈ average.
- Accuracy-based skills only use games chess.com has analyzed (most rated live games).
- The tool is read-only and never logs in or modifies your account.
