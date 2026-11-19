"""Domain errors of the users domain.

They are returned inside ``Left`` (errors are values), never raised. Repositories
translate driver outcomes into them, so a handler can map ``NotFoundError`` to
404 without ever importing psycopg.
"""


class NotFoundError(Exception):
    """The requested user does not exist."""
