"""Store Gmail refresh tokens in the Mac Keychain, never in the application DB."""

from __future__ import annotations

import sys

SERVICE = "engineering-document-platform-gmail"


def _keyring():
    if sys.platform != "darwin":
        raise RuntimeError("Gmail credentials require the Mac Keychain")
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("the Mac Keychain adapter is not installed") from exc
    backend = keyring.get_keyring()
    if backend.__class__.__module__ != "keyring.backends.macOS":
        raise RuntimeError(
            "the Mac Keychain is unavailable; refusing another credential store"
        )
    return keyring


def save_refresh_token(mailbox_id: str, token: str) -> None:
    if not mailbox_id or not token:
        raise ValueError("mailbox and refresh token are required")
    _keyring().set_password(SERVICE, mailbox_id, token)


def get_refresh_token(mailbox_id: str) -> str:
    token = _keyring().get_password(SERVICE, mailbox_id)
    if not token:
        raise RuntimeError("Gmail credential is missing or revoked")
    return token


def delete_refresh_token(mailbox_id: str) -> None:
    _keyring().delete_password(SERVICE, mailbox_id)
