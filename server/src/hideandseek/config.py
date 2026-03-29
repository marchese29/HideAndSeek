"""Push notification configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PushConfig:
    """APNS credentials and settings."""

    key_path: str
    key_id: str
    team_id: str
    topic: str
    use_sandbox: bool


@dataclass(frozen=True)
class FcmConfig:
    """Firebase Cloud Messaging credentials."""

    credentials_path: str


def load_push_config() -> PushConfig | None:
    """Load APNS config from env vars. Returns None when any required var is missing."""
    key_path = os.environ.get('APNS_KEY_PATH')
    key_id = os.environ.get('APNS_KEY_ID')
    team_id = os.environ.get('APNS_TEAM_ID')
    topic = os.environ.get('APNS_TOPIC')

    if not all([key_path, key_id, team_id, topic]):
        return None

    assert key_path is not None
    assert key_id is not None
    assert team_id is not None
    assert topic is not None

    return PushConfig(
        key_path=key_path,
        key_id=key_id,
        team_id=team_id,
        topic=topic,
        use_sandbox=os.environ.get('APNS_USE_SANDBOX', '').lower() in ('1', 'true', 'yes'),
    )


def load_fcm_config() -> FcmConfig | None:
    """Load FCM config from env vars. Returns None when the credential path is missing."""
    credentials_path = os.environ.get('FCM_CREDENTIALS_PATH')
    if not credentials_path:
        return None
    return FcmConfig(credentials_path=credentials_path)
