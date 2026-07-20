# Chess Stats — container image for web hosting.
#
# Includes the Stockfish binary so the optional "deep" features (game review,
# practice grading, drills) work out of the box. The app still runs without it
# and simply disables those endpoints if the binary is missing.
FROM python:3.11-slim

# Stockfish for the engine pass. The Debian package installs the binary to
# /usr/games, which isn't on the default PATH, so point STOCKFISH_PATH at it
# directly (engine.py reads this env var first).
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
ENV STOCKFISH_PATH=/usr/games/stockfish

# Keep Python output unbuffered so logs show up promptly in hosting dashboards.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first so they're cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Most hosts inject the listen port via $PORT; default to 8000 for local runs.
ENV PORT=8000
EXPOSE 8000

# Shell form so ${PORT} is expanded at runtime.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
