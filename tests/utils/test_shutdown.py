from app_template.utils.shutdown import Shutdown


async def test_first_request_is_graceful_second_forces() -> None:
    shutdown = Shutdown()
    assert not shutdown.requested.is_set()

    shutdown.request()
    assert shutdown.requested.is_set()
    assert not shutdown.forced.is_set()

    shutdown.request()
    assert shutdown.forced.is_set()
