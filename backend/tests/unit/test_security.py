from app.infrastructure.security import (
    api_key_display_prefix,
    generate_api_key,
    hash_api_key,
    hash_password,
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
