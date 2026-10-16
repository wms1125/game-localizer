from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from contextlib import closing
from pathlib import Path
from typing import Any


AUTH_SCHEMA_VERSION = 1
PASSWORD_ITERATIONS = 310_000
SESSION_TTL = timedelta(hours=12)
_USERNAME_RE = re.compile(r"[\w.\-@+]{3,64}\Z", re.UNICODE)
_DUMMY_SALT = b"hanengine-local-auth-dummy-salt"
_DUMMY_HASH = b"\0" * hashlib.sha256().digest_size


class AuthError(ValueError):
    """A safe, user-facing authentication error."""


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    username: str
    display_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
        }


@dataclass(frozen=True)
class AuthSession:
    token: str
    user: AuthUser
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "user": self.user.to_dict(),
            "expires_at": self.expires_at,
        }


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise AuthError("请输入用户名")
    value = username.strip()
    if _USERNAME_RE.fullmatch(value) is None:
        raise AuthError("用户名需为 3-64 个字母、数字或常用符号")
    return value


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise AuthError("密码至少需要 8 个字符")
    if len(password) > 256:
        raise AuthError("密码不能超过 256 个字符")
    if any(ord(character) < 32 for character in password):
        raise AuthError("密码包含不可用字符")
    return password


def _validate_display_name(display_name: str, username: str) -> str:
    if not isinstance(display_name, str):
        return username
    value = display_name.strip()
    if not value:
        return username
    if len(value) > 80 or any(ord(character) < 32 for character in value):
        raise AuthError("显示名称需为 1-80 个可见字符")
    return value


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UserStore:
    """Local account store. Raw passwords and session tokens never reach SQLite."""

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, Path):
            raise TypeError("database_path must be a Path")
        self.database_path = database_path.expanduser().resolve(strict=False)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT,
                    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO auth_meta(key, value) VALUES('schema_version', ?)",
                (str(AUTH_SCHEMA_VERSION),),
            )
            schema_row = connection.execute(
                "SELECT value FROM auth_meta WHERE key='schema_version'"
            ).fetchone()
            if schema_row is None or schema_row["value"] != str(AUTH_SCHEMA_VERSION):
                raise AuthError("用户数据库版本不受支持")

    def user_count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    def status(self) -> dict[str, Any]:
        count = self.user_count()
        return {"needs_setup": count == 0, "user_count": count}

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
    ) -> AuthSession:
        username = _validate_username(username)
        password = _validate_password(password)
        display_name = _validate_display_name(display_name, username)
        username_key = username.casefold()
        salt = secrets.token_bytes(32)
        password_hash = _hash_password(password, salt)
        user = AuthUser(str(uuid.uuid4()), username, display_name)
        now = _timestamp(_utc_now())
        with closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users(
                        user_id, username, username_key, display_name,
                        password_salt, password_hash, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.username,
                        username_key,
                        user.display_name,
                        salt,
                        password_hash,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthError("该用户名已经存在") from exc
        return self._create_session(user)

    def authenticate(self, username: str, password: str) -> AuthSession:
        username = _validate_username(username)
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            raise AuthError("用户名或密码错误")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT user_id, username, display_name, password_salt, password_hash, disabled
                FROM users WHERE username_key=?
                """,
                (username.casefold(),),
            ).fetchone()
            if row is None:
                hmac.compare_digest(_hash_password(password, _DUMMY_SALT), _DUMMY_HASH)
                raise AuthError("用户名或密码错误")
            candidate = _hash_password(password, bytes(row["password_salt"]))
            if bool(row["disabled"]) or not hmac.compare_digest(
                candidate, bytes(row["password_hash"])
            ):
                raise AuthError("用户名或密码错误")
            user = AuthUser(row["user_id"], row["username"], row["display_name"])
            connection.execute(
                "UPDATE users SET last_login_at=? WHERE user_id=?",
                (_timestamp(_utc_now()), user.user_id),
            )
        return self._create_session(user)

    def _create_session(self, user: AuthUser) -> AuthSession:
        token = secrets.token_urlsafe(32)
        created_at = _utc_now()
        expires_at = _timestamp(created_at + SESSION_TTL)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM sessions WHERE user_id=? OR expires_at<=?",
                (user.user_id, _timestamp(created_at)),
            )
            connection.execute(
                """
                INSERT INTO sessions(session_id, user_id, token_hash, created_at, expires_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user.user_id,
                    _hash_token(token),
                    _timestamp(created_at),
                    expires_at,
                ),
            )
        return AuthSession(token, user, expires_at)

    def current_user(self, token: str) -> AuthUser | None:
        if not isinstance(token, str) or not token:
            return None
        now = _timestamp(_utc_now())
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT users.user_id, users.username, users.display_name
                FROM sessions JOIN users ON users.user_id=sessions.user_id
                WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.disabled=0
                """,
                (_hash_token(token), now),
            ).fetchone()
        return None if row is None else AuthUser(row["user_id"], row["username"], row["display_name"])

    def logout(self, token: str) -> None:
        if not isinstance(token, str) or not token:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def auth_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthError("认证请求格式无效")
    return value


__all__ = [
    "AUTH_SCHEMA_VERSION",
    "AuthError",
    "AuthSession",
    "AuthUser",
    "PASSWORD_ITERATIONS",
    "SESSION_TTL",
    "UserStore",
    "auth_payload",
]
