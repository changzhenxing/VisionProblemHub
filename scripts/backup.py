from datetime import datetime
from pathlib import Path
import sqlite3
import sys
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import DB_PATH, DATA_DIR

out=DATA_DIR/"backups"; out.mkdir(parents=True,exist_ok=True)
dst=out/f"vision_knowledge_{datetime.now():%Y%m%d_%H%M%S}.db"
src=sqlite3.connect(DB_PATH); tar=sqlite3.connect(dst)
with tar: src.backup(tar)
src.close(); tar.close(); print(dst)
files = [path for name in ("uploads", "private_feedback")
         for path in (DATA_DIR / name).rglob("*") if path.is_file()]
agent_key = DATA_DIR / "agent-credentials.key"
if agent_key.is_file():
    files.append(agent_key)
if files:
    archive = dst.with_suffix(".attachments.zip")
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(DATA_DIR))
    print(archive)
