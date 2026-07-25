import pytest
from tests.factories import DataFactory


@pytest.fixture
def factory():
    return DataFactory(seed=42)


@pytest.fixture
def single_symbol_data(factory):
    return factory.generate_ohlcv("TEST.SZ", days=252, trend="random")


@pytest.fixture
def multi_symbol_data(factory):
    symbols = [f"TEST{i:03d}.SZ" for i in range(10)]
    data = {}
    for sym in symbols:
        data[sym] = factory.generate_ohlcv(sym, days=252, trend="random")
    return data
