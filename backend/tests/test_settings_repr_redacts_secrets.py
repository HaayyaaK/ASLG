"""Credentials must never appear in a Settings repr.

This exists because it already happened. During the Sept 2026 test work a
fixture raised while `Settings` was in scope, and pytest's traceback printed
the model's repr, which at the time included the LIVE production database
password in cleartext:

    model = Settings(db_host='127.0.0.1', ..., db_password='<real value>'

Nothing was logged, nothing failed, and the value went into terminal
scrollback -- and would go into CI logs verbatim if this suite were ever run
in CI. Any unhandled exception with a Settings object in the frame does the
same thing: a startup failure, a misconfigured environment, a bad fixture.

pydantic's SecretStr fixes it by reprs-ing as '**********' while carrying the
real value for `.get_secret_value()`. These tests make sure nobody undoes
that by changing a field back to a plain `str` -- which would be an easy,
invisible regression, since every other test would still pass.

Deliberately constructed with fabricated values rather than reading the real
settings: a test that asserted "the production password is absent" would
have to know the production password, which is precisely the thing that
should not be in the repo.
"""

import pytest
from pydantic import SecretStr

from app.config import Settings

# Distinctive, obviously-fake sentinels. If any of these shows up in a repr,
# the corresponding field is no longer protected.
FAKE = {
    "DB_PASSWORD": "db-pw-SENTINEL-8f3a",
    "JWT_SECRET": "jwt-secret-SENTINEL-1c7b",
    "ASLG_SEED_ADMIN_PASSWORD": "seed-admin-SENTINEL-4e2d",
    "ASLG_SEED_STAFF_PASSWORD": "seed-staff-SENTINEL-9a6c",
    "ASLG_INTERNAL_TASK_TOKEN": "task-token-SENTINEL-2b5f",
}


@pytest.fixture()
def settings(monkeypatch, tmp_path):
    """A Settings built purely from fabricated environment values.

    `_env_file=None` stops pydantic-settings reading the real backend/.env,
    so this test neither depends on nor can leak the actual deployment's
    configuration.
    """
    for key, value in FAKE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DB_USER", "test-user")
    return Settings(_env_file=None)


@pytest.mark.parametrize("secret", sorted(FAKE.values()))
def test_repr_does_not_contain_any_secret_value(settings, secret):
    assert secret not in repr(settings), (
        f"{secret!r} appears in repr(Settings) -- a credential field was "
        f"changed back to a plain str, and any traceback that touches "
        f"Settings will now print it"
    )


@pytest.mark.parametrize("secret", sorted(FAKE.values()))
def test_str_does_not_contain_any_secret_value(settings, secret):
    """`str()` is a separate dunder from `__repr__` on pydantic models and
    is what an f-string or a log call would reach for."""
    assert secret not in str(settings)


def test_repr_shows_the_redaction_marker(settings):
    assert "**********" in repr(settings), (
        "no redaction marker in the repr at all -- expected SecretStr's "
        "'**********' in place of each credential"
    )


def test_the_values_are_still_actually_usable(settings):
    """Redaction must not have been achieved by dropping the values.

    The DB URL, the JWT signing key and the task-token comparison all need
    the real string; a Settings that hid its secrets by losing them would
    pass every assertion above and break the entire application.
    """
    assert settings.db_password.get_secret_value() == FAKE["DB_PASSWORD"]
    assert settings.jwt_secret.get_secret_value() == FAKE["JWT_SECRET"]
    assert settings.seed_admin_password.get_secret_value() == FAKE["ASLG_SEED_ADMIN_PASSWORD"]
    assert settings.seed_staff_password.get_secret_value() == FAKE["ASLG_SEED_STAFF_PASSWORD"]
    assert settings.internal_task_token.get_secret_value() == FAKE["ASLG_INTERNAL_TASK_TOKEN"]


def test_database_url_still_embeds_the_real_password(settings):
    """`database_url` interpolates the password into a connection string.
    If that ever stops unwrapping the SecretStr it would silently try to
    connect with the literal text 'SecretStr(...)' and fail at runtime,
    not here -- so it is checked explicitly."""
    url = settings.database_url
    assert FAKE["DB_PASSWORD"] in url
    assert "SecretStr" not in url
    assert "**********" not in url


def test_every_declared_secret_field_is_a_secret_type():
    """Catches a NEW credential field added as a plain `str`.

    The tests above only cover the five fields that exist today. This one
    fails when someone adds, say, an SMTP password next to them without
    reaching for SecretStr.
    """
    suspicious = ("password", "secret", "token", "api_key", "apikey")
    offenders = []
    for name, field in Settings.model_fields.items():
        if not any(word in name.lower() for word in suspicious):
            continue
        annotation = str(field.annotation)
        if "SecretStr" not in annotation:
            offenders.append(f"{name}: {annotation}")
    assert not offenders, (
        "credential-looking Settings fields that are not SecretStr and will "
        f"therefore print in tracebacks: {offenders}"
    )
