"""Multi-account login: data/users.json holds PBKDF2 password hashes + roles.

No users.json (or an empty one) means login is DISABLED — the app runs
exactly as before and everyone counts as admin, so dev workflows and the
UI probe keep working with zero setup. Accounts are created with
`lyric-agent users-add <name> [--role admin|viewer]`, which also turns
login on for the next `lyric-agent serve`.

Roles:
  admin   — sees every tab
  viewer  — management tabs (➕ 添加歌曲 / ⚙️ 设置) are hidden
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path

USERS_PATH = Path("data/users.json")
ROLES = ("admin", "viewer")
_ITERATIONS = 120_000


def hash_password(password: str,
                  salt_hex: str | None = None) -> tuple[str, str]:
    """(salt_hex, hash_hex) via PBKDF2-HMAC-SHA256."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), salt, _ITERATIONS)
    return salt.hex(), digest.hex()


def load_users(path: Path | str = USERS_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def login_enabled(path: Path | str = USERS_PATH) -> bool:
    return bool(load_users(path))


def verify(username: str, password: str,
           path: Path | str = USERS_PATH) -> bool:
    """Gradio auth callback: True when the credentials match."""
    u = load_users(path).get(username or "")
    if not isinstance(u, dict) or "salt" not in u or "hash" not in u:
        return False
    _salt, digest = hash_password(password, u["salt"])
    return hmac.compare_digest(digest, u["hash"])


def role_of(username: str | None, path: Path | str = USERS_PATH) -> str:
    """Role used for tab gating.

    Login disabled -> everyone is admin (unchanged dev behavior).
    Login enabled  -> the account's role; unknown names fall back to the
    safe side (viewer).
    """
    users = load_users(path)
    if not users:
        return "admin"
    u = users.get(username or "")
    if isinstance(u, dict) and u.get("role") in ROLES:
        return u["role"]
    return "viewer"


def add_user(username: str, password: str, role: str = "viewer",
             path: Path | str = USERS_PATH) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username or not password:
        raise ValueError("username and password are required")
    users = load_users(path)
    salt, digest = hash_password(password)
    users[username] = {"salt": salt, "hash": digest, "role": role}
    from .jsonio import write_json_atomic
    write_json_atomic(path, users, indent=2)
