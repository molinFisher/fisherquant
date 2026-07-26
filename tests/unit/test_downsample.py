import math

import pytest

from fisher.visualization.downsample import lttb


def _monotonic(n, start=0.0, step=1.0):
    return [(float(i), start + i * step) for i in range(n)]


def test_identity_when_under_threshold():
    data = _monotonic(50)
    result = lttb(data, threshold=100)
    assert len(result) == 50
    assert result == data


def test_exactly_threshold_returns_all():
    data = _monotonic(100)
    result = lttb(data, threshold=100)
    assert len(result) == 100
    assert result == data


def test_downsample_hits_target_count():
    data = _monotonic(1000)
    result = lttb(data, threshold=100)
    assert len(result) == 100


def test_first_and_last_preserved():
    data = [(float(i), math.sin(i / 10.0)) for i in range(500)]
    result = lttb(data, threshold=50)
    assert result[0] == data[0]
    assert result[-1] == data[-1]


def test_output_points_are_subset_of_input():
    """LTTB must select actual data points, never invent new coordinates."""
    data = _monotonic(800)
    result = lttb(data, threshold=80)
    data_set = set(data)
    assert all(pt in data_set for pt in result)


def test_empty_input_returns_empty():
    assert lttb([], threshold=100) == []


def test_single_point_returns_single():
    data = [(1.0, 2.0)]
    assert lttb(data, threshold=10) == [(1.0, 2.0)]


def test_spike_is_preserved_after_downsample():
    """A sharp outlier must survive aggressive downsampling (shape preservation)."""
    data = _monotonic(1000, start=0.0, step=1.0)
    spike_idx = 500
    spike = (float(spike_idx), 1e6)
    data[spike_idx] = spike
    result = lttb(data, threshold=20)
    assert spike in result


def test_threshold_zero_returns_empty_without_error():
    data = _monotonic(100)
    assert lttb(data, threshold=0) == []


def test_threshold_one_returns_first_point():
    data = _monotonic(100)
    result = lttb(data, threshold=1)
    assert result == [data[0]]


def test_threshold_two_no_division_error():
    """Regression: threshold <= 2 used to raise ZeroDivisionError."""
    data = _monotonic(100)
    result = lttb(data, threshold=2)
    assert len(result) == 2
    assert result[0] == data[0]
    assert result[-1] == data[-1]


def test_accepts_generator_input():
    result = lttb((float(i), float(i * i)) for i in range(200))
    assert len(result) <= 500
    assert len(result) == 200  # <= threshold -> identity, materialized


def test_downsample_preserves_y_range_bounds():
    data = [(float(i), math.cos(i / 7.0) * 50 + i * 0.01) for i in range(600)]
    result = lttb(data, threshold=40)
    src_ys = [y for _, y in data]
    out_ys = [y for _, y in result]
    assert min(out_ys) >= min(src_ys) - 1e-9
    assert max(out_ys) <= max(src_ys) + 1e-9
