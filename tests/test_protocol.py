import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bootcode.protocol import bind_collector, encode_json, submit, submit_batch, unbind


@pytest.fixture(autouse=True)
def _reset_session():
    unbind()
    yield
    unbind()


def test_encode_json_passthrough_for_json_native_types():
    assert encode_json(1) == 1
    assert encode_json(1.5) == 1.5
    assert encode_json("x") == "x"
    assert encode_json(None) is None
    assert encode_json([1, {"a": 2}]) == [1, {"a": 2}]


def test_encode_json_ndarray():
    assert encode_json(np.array([1, 2, 3])) == {"_encoded_type": "np.ndarray", "data": [1, 2, 3]}


def test_encode_json_nested_ndarray_in_a_list():
    assert encode_json([np.array([1.0, 2.0])]) == [{"_encoded_type": "np.ndarray", "data": [1.0, 2.0]}]


def test_encode_json_datetime():
    dt = datetime.datetime(2026, 1, 1, 12, 0, 0)
    assert encode_json(dt) == {"_encoded_type": "datetime", "data": dt.isoformat()}


def test_encode_json_type():
    assert encode_json(int) == {"_encoded_type": "type", "data": repr(int)}


def test_encode_json_numpy_integer_scalar_becomes_plain_int():
    encoded = encode_json(np.int64(5))
    assert encoded == 5
    assert isinstance(encoded, int)


def test_encode_json_numpy_float_scalar_becomes_plain_float():
    encoded = encode_json(np.float32(1.5))
    assert encoded == pytest.approx(1.5)
    assert isinstance(encoded, float)


def test_submit_without_a_bound_session_raises():
    with pytest.raises(RuntimeError):
        submit(1)


def test_bind_collector_records_encoded_values_without_any_network_call():
    collected = []
    bind_collector(collected.append)

    assert submit(np.array([1, 2])) is True
    assert submit(5) is True

    assert collected == [{"_encoded_type": "np.ndarray", "data": [1, 2]}, 5]


def test_submit_batch_posts_the_whole_values_list_in_a_single_request():
    fake_response = MagicMock()
    with patch("bootcode.protocol.requests.post", return_value=fake_response) as mock_post:
        result = submit_batch("http://api.test", "tok123", "modernai-hw", "hw0-add", [5, 2])

    assert result is fake_response
    mock_post.assert_called_once_with(
        "http://api.test/api/cli/courses/modernai-hw/stages/hw0-add/submit",
        headers={"Authorization": "Bearer tok123"},
        json={"values": [5, 2]},
        timeout=30,
    )
