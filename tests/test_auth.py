from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cli
from game_localizer.hanengine.auth import AuthError, UserStore


class AuthStoreTests(unittest.TestCase):
    def test_first_run_status_create_login_and_logout(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "auth.db"
            store = UserStore(database)
            self.assertEqual(store.status(), {"needs_setup": True, "user_count": 0})

            session = store.create_user("operator", "correct horse battery", "本地操作员")
            self.assertFalse(store.status()["needs_setup"])
            self.assertEqual(session.user.username, "operator")
            self.assertEqual(store.current_user(session.token), session.user)

            logged_in = store.authenticate("OPERATOR", "correct horse battery")
            self.assertEqual(logged_in.user, session.user)
            self.assertNotEqual(logged_in.token, session.token)
            store.logout(logged_in.token)
            self.assertIsNone(store.current_user(logged_in.token))

    def test_passwords_and_tokens_are_not_stored_in_plaintext(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "auth.db"
            password = "private-password-123"
            token = UserStore(database).create_user("operator", password).token
            raw_database = database.read_bytes()

            self.assertNotIn(password.encode("utf-8"), raw_database)
            self.assertNotIn(token.encode("utf-8"), raw_database)

    def test_wrong_password_duplicate_user_and_expired_session_fail_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "auth.db"
            store = UserStore(database)
            session = store.create_user("operator", "correct horse battery")
            with self.assertRaisesRegex(AuthError, "用户名或密码错误"):
                store.authenticate("operator", "wrong-password")
            with self.assertRaisesRegex(AuthError, "用户名已经存在"):
                store.create_user("OPERATOR", "another-password")

            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE sessions SET expires_at='2000-01-01T00:00:00Z' WHERE token_hash IS NOT NULL"
                )
                connection.commit()
            self.assertIsNone(store.current_user(session.token))

    def test_cli_auth_commands_return_json_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "auth.db"
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                self.assertEqual(cli.run_auth(["status", "--db", str(database)]), 0)
            self.assertTrue(json.loads(status_output.getvalue())["needs_setup"])

            register_output = io.StringIO()
            with (
                patch("sys.stdin", io.StringIO(json.dumps({
                    "username": "operator",
                    "password": "correct horse battery",
                    "display_name": "操作员",
                }, ensure_ascii=False))),
                redirect_stdout(register_output),
            ):
                self.assertEqual(cli.run_auth(["register", "--db", str(database)]), 0)
            registered = json.loads(register_output.getvalue())
            self.assertEqual(registered["user"]["display_name"], "操作员")
            self.assertNotIn("correct horse battery", register_output.getvalue())

            login_output = io.StringIO()
            with (
                patch("sys.stdin", io.StringIO(json.dumps({
                    "username": "operator",
                    "password": "correct horse battery",
                }))),
                redirect_stdout(login_output),
            ):
                self.assertEqual(cli.run_auth(["login", "--db", str(database)]), 0)
            self.assertIn("token", json.loads(login_output.getvalue()))

            errors = io.StringIO()
            with (
                patch("sys.stdin", io.StringIO(json.dumps({
                    "username": "operator",
                    "password": "wrong-password",
                }))),
                redirect_stderr(errors),
            ):
                self.assertEqual(cli.run_auth(["login", "--db", str(database)]), 1)
            self.assertIn("用户名或密码错误", errors.getvalue())
            self.assertNotIn("correct horse battery", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
