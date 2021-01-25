import time

import pytest


@pytest.fixture(autouse=True)
def faketime(mocker):
    mocker.patch.dict("os.environ", TZ="UTC")
    time.tzset()
    mocked_time = mocker.patch("time.time")
    start = 1609459200  # 2021-01-01T00:00:00Z
    mocked_time.return_value = start
    return start
