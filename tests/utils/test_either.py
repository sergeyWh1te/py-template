from app_template.utils.either import Either, Left, Right, is_left, is_right, left, right


def divide(a: int, b: int) -> Either[str, int]:
    if b == 0:
        return left("division by zero")
    return right(a // b)


def test_right_carries_the_value() -> None:
    result = divide(6, 3)

    assert is_right(result)
    assert result == Right(2)


def test_left_carries_the_error() -> None:
    result = divide(1, 0)

    assert is_left(result)
    assert result == Left("division by zero")


def test_is_left_narrows_for_early_return() -> None:
    def describe(result: Either[str, int]) -> str:
        if is_left(result):
            return f"error: {result.left}"
        # Narrowed to Right[int] by TypeIs — `.right` type-checks without a cast.
        return f"value: {result.right + 0}"

    assert describe(divide(1, 0)) == "error: division by zero"
    assert describe(divide(9, 3)) == "value: 3"


def test_match_works_on_both_branches() -> None:
    seen: list[str] = []
    for result in (divide(4, 2), divide(4, 0)):
        match result:
            case Left(left=err):
                seen.append(f"left:{err}")
            case Right(right=value):
                seen.append(f"right:{value}")

    assert seen == ["right:2", "left:division by zero"]
