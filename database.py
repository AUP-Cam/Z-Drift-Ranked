from pathlib import Path
import sqlite3
import json
DATABASE_FILE = Path(__file__).resolve().parent / "bot.db"
PROJECT_ROOT = DATABASE_FILE.parent

def initialize_database() -> None:
	with sqlite3.connect(DATABASE_FILE) as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS bans (
				user_id INTEGER PRIMARY KEY
			)
			"""
		)
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS storage (
				key TEXT PRIMARY KEY,
				value TEXT NOT NULL
			)
			"""
		)
		connection.commit()


def _get_value(key: str, default: str) -> str:
	initialize_database()
	with sqlite3.connect(DATABASE_FILE) as connection:
		row = connection.execute(
			"SELECT value FROM storage WHERE key = ?", (key,)
		).fetchone()
	return row[0] if row else default


def _set_value(key: str, value: str) -> None:
	initialize_database()
	with sqlite3.connect(DATABASE_FILE) as connection:
		connection.execute(
			"INSERT INTO storage (key, value) VALUES (?, ?) "
			"ON CONFLICT(key) DO UPDATE SET value = excluded.value",
			(key, value),
		)
		connection.commit()


def get_json(key: str, default):
	try:
		return json.loads(_get_value(key, json.dumps(default)))
	except json.JSONDecodeError:
		return default


def set_json(key: str, value) -> None:
	_set_value(key, json.dumps(value))


def get_int(key: str, default: int = 0) -> int:
	try:
		return int(_get_value(key, str(default)))
	except ValueError:
		return default


def set_int(key: str, value: int) -> None:
	_set_value(key, str(value))


def get_bans() -> set[str]:
	initialize_database()
	with sqlite3.connect(DATABASE_FILE) as connection:
		rows = connection.execute("SELECT user_id FROM bans").fetchall()
	return {str(row[0]) for row in rows}


def add_ban(user_id: int) -> None:
	initialize_database()
	with sqlite3.connect(DATABASE_FILE) as connection:
		connection.execute(
			"INSERT OR IGNORE INTO bans (user_id) VALUES (?)",
			(user_id,),
		)
		connection.commit()


def remove_ban(user_id: int) -> None:
	initialize_database()
	with sqlite3.connect(DATABASE_FILE) as connection:
		connection.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
		connection.commit()

