"""Tests for the login/role module (no gradio, no server)."""

from lyric_agent.auth import (
    add_user,
    hash_password,
    login_enabled,
    role_of,
    verify,
)


def test_hash_roundtrip_and_verify(tmp_path):
    users = tmp_path / "users.json"
    add_user("alice", "s3cret", "admin", users)
    add_user("bob", "pw", "viewer", users)
    assert login_enabled(users)
    assert verify("alice", "s3cret", users)
    assert not verify("alice", "wrong", users)
    assert not verify("nobody", "s3cret", users)


def test_salt_differs_between_users(tmp_path):
    s1, h1 = hash_password("same")
    s2, h2 = hash_password("same")
    assert s1 != s2 and h1 != h2  # fresh salt every time


def test_roles_and_disabled_mode(tmp_path):
    users = tmp_path / "users.json"
    # no file -> login disabled -> everyone admin (dev / probe mode)
    assert not login_enabled(users)
    assert role_of("anyone", users) == "admin"
    assert role_of(None, users) == "admin"
    add_user("alice", "pw", "admin", users)
    add_user("bob", "pw", "viewer", users)
    assert role_of("alice", users) == "admin"
    assert role_of("bob", users) == "viewer"
    # unknown names fall to the safe side once login is on
    assert role_of("mallory", users) == "viewer"


def test_add_user_validation(tmp_path):
    users = tmp_path / "users.json"
    import pytest
    with pytest.raises(ValueError):
        add_user("x", "pw", "root", users)
    with pytest.raises(ValueError):
        add_user("", "pw", "admin", users)
