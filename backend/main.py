"""Lance l'API en local (utilise l'app FastAPI partagee dans api/index.py).

Usage:
    cd backend
    python main_local.py
    # OU depuis la racine:
    uvicorn api.index:app --reload --host 0.0.0.0 --port 8000
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from api.index import app  # noqa: E402  re-export pour uvicorn

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=8000, reload=True)
