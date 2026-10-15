import pytest
from app import greet


@pytest.mark.parametrize("name", [
    "Nika",
    "Alex",
    "John",
    "",
    "123"
])
def test_greet(name):
    assert greet(name) == f"Hello, {name}!"
