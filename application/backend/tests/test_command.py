import json

import pytest

from app.hub import parse_command


def test_valid_command_is_clamped():
    text = json.dumps({"type": "command", "data": [-0.5, 0.25, 1, 1.5, 0]})
    assert parse_command(text) == [0.0, 0.25, 1.0, 1.0, 0.0]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"type": "other", "data": [0, 0, 0, 0, 0]}',
        '{"type": "command"}',
        '{"type": "command", "data": [0, 0, 0, 0]}',
        '{"type": "command", "data": [0, 0, 0, 0, 0, 0]}',
        '{"type": "command", "data": [0, 0, "1", 0, 0]}',
        '{"type": "command", "data": [0, 0, true, 0, 0]}',
        '{"type": "command", "data": [0, 0, NaN, 0, 0]}',
        '{"type": "command", "data": ' + "[" * 100_000 + "]" * 100_000 + "}",
        '{"type": "command", "data": [0, 0, 0, 0, 0], "pad": "' + "x" * 600 + '"}',
    ],
)
def test_malformed_commands_are_ignored(text):
    assert parse_command(text) is None
