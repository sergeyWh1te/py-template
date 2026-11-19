from app_template.utils.errors import WrappedError, wrap


def test_wrap_adds_context_and_keeps_the_cause() -> None:
    cause = ConnectionError("connection refused")

    err = wrap("get user 1", cause)

    assert isinstance(err, WrappedError)
    assert str(err) == "get user 1: connection refused"
    assert err.context == "get user 1"
    assert err.cause is cause
    assert err.__cause__ is cause
