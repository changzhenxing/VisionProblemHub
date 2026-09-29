import os
import sqlite3
import subprocess
import sys


def test_existing_users_are_migrated_without_data_loss(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, role VARCHAR(40) NOT NULL, created_at DATETIME NOT NULL)")
        db.execute("INSERT INTO users VALUES (1, '管理员', '团队负责人', '2026-01-01 00:00:00')")
        db.execute("INSERT INTO users VALUES (2, '工程师甲', '工程师', '2026-01-01 00:00:00')")

    environment = os.environ.copy()
    environment["VISION_KNOWLEDGE_DB"] = f"sqlite:///{database.as_posix()}"
    environment["VISION_KNOWLEDGE_DATA"] = str(tmp_path)
    subprocess.run([sys.executable, "-c", "import app.main"], check=True, env=environment, capture_output=True)

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 9
        assert db.execute("SELECT COUNT(*) FROM user_roles").fetchone()[0] == 2
        rows = db.execute("SELECT users.name, roles.name, users.password_hash FROM users JOIN roles ON roles.id=users.role_id ORDER BY users.id").fetchall()
        assert rows == [("管理员", "管理员", None), ("工程师甲", "团队成员", None)]
