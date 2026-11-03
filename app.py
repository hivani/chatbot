"""Vercel FastAPI entrypoint.

Vercel's Python runtime looks for a FastAPI instance named ``app`` in a
supported entrypoint file. ``app.py`` at the project root is one of those
default locations. The real application lives in ``src/app/api.py``; this
module only re-exports it so the same app works with:

    uvicorn src.app.api:app
    uvicorn app:app
"""

from src.app.api import app

__all__ = ["app"]
