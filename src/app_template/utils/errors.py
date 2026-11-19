"""Error wrapping — the Python counterpart of Go's ``fmt.Errorf("context: %w", err)``."""


class WrappedError(Exception):
    """An error with added context that keeps the original as ``cause``.

    ``str()`` reads like a Go wrapped error (``"get user 1: connection refused"``),
    and ``__cause__`` is set so a logged traceback shows the original exception.
    """

    def __init__(self, context: str, cause: BaseException) -> None:
        super().__init__(f"{context}: {cause}")
        self.context = context
        self.cause = cause
        self.__cause__ = cause


def wrap(context: str, cause: BaseException) -> WrappedError:
    return WrappedError(context, cause)
