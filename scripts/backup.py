from datetime import datetime
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import DB_PATH, DATA_DIR

out=DATA_DIR/"backups"; out.mkdir(parents=True,exist_ok=True)
dst=out/f"vision_knowledge_{datetime.now():%Y%m%d_%H%M%S}.db"
src=sqlite3.connect(DB_PATH); tar=sqlite3.connect(dst)
with tar: src.backup(tar)
src.close(); tar.close(); print(dst)
