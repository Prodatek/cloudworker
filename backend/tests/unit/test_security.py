import uuid

import pytest

from app.infrastructure.security import (
    InvalidAccessTokenError,
    api_key_display_prefix,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    looks_like_api_key,
    verify_password,
)


def test_hash_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_hash_password_produces_different_hashes_for_same_input() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_generate_api_key_has_expected_prefix_and_is_unique() -> None:
    first = generate_api_key()
    second = generate_api_key()

    assert first.startswith("cw_live_")
    assert first != second


def test_hash_api_key_is_deterministic() -> None:
    api_key = generate_api_key()

    assert hash_api_key(api_key) == hash_api_key(api_key)
    assert hash_api_key(api_key) != hash_api_key(generate_api_key())


def test_api_key_display_prefix_is_short_and_stable() -> None:
    api_key = generate_api_key()

    prefix = api_key_display_prefix(api_key)

    assert prefix == api_key[:12]
    assert len(prefix) == 12


def test_looks_like_api_key_distinguishes_api_keys_from_jwts() -> None:
    assert looks_like_api_key(generate_api_key()) is True
    assert looks_like_api_key("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123") is False


def test_create_access_token_round_trips_to_the_same_user_id() -> None:
    user_id = uuid.uuid4()

    token = create_access_token(
        user_id, secret_key="test-secret", algorithm="HS256", expiry_minutes=60
    )

    assert decode_access_token(token, secret_key="test-secret", algorithm="HS256") == user_id


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = create_access_token(
        uuid.uuid4(), secret_key="right-secret", algorithm="HS256", expiry_minutes=60
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, secret_key="wrong-secret", algorithm="HS256")


def test_decode_access_token_rejects_expired_token() -> None:
    # A negative expiry puts `exp` in the past at creation time — no need to sleep.
    token = create_access_token(
        uuid.uuid4(), secret_key="test-secret", algorithm="HS256", expiry_minutes=-1
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, secret_key="test-secret", algorithm="HS256")


def test_decode_access_token_rejects_garbage_input() -> None:
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token("not-a-jwt-at-all", secret_key="test-secret", algorithm="HS256")
