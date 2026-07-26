import hashlib
import threading
import time

import pytest

from fisher.config.hot_reload import ConfigReloader


@pytest.fixture
def config_dir(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    return d


def _write(path, content: str):
    # Write raw bytes so '\n' is preserved (Path.write_text would translate to
    # '\r\n' on Windows and corrupt the md5-based change detection under test).
    path.write_bytes(content.encode("utf-8"))


def test_initial_hashes_computed(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "key: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    expected = hashlib.md5(b"key: 1\n").hexdigest()
    assert reloader._hashes.get("a.yaml") == expected


def test_no_change_does_not_invoke_callback(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "key: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    calls = []
    reloader.on_change(lambda name: calls.append(name))
    reloader._check_changes()
    assert calls == []


def test_change_invokes_callback_and_updates_hash(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "key: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    calls = []
    reloader.on_change(lambda name: calls.append(name))

    _write(f, "key: 2\n")
    reloader._check_changes()

    assert calls == ["a.yaml"]
    expected = hashlib.md5(b"key: 2\n").hexdigest()
    assert reloader._hashes["a.yaml"] == expected
    assert reloader._hashes["a.yaml"] != hashlib.md5(b"key: 1\n").hexdigest()


def test_old_value_replaced_by_new_after_change(config_dir):
    """Demonstrate that the observed config value flips from old to new."""
    f = config_dir / "a.yaml"
    _write(f, "value: old\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)

    observed = {}
    reloader.on_change(lambda name: observed.setdefault("value", _read(f)))

    _write(f, "value: new\n")
    reloader._check_changes()

    assert observed["value"] == "value: new\n"


def test_partial_change_only_reports_modified_file(config_dir):
    fa = config_dir / "a.yaml"
    fb = config_dir / "b.yaml"
    _write(fa, "a: 1\n")
    _write(fb, "b: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)

    calls = []
    reloader.on_change(lambda name: calls.append(name))

    _write(fb, "b: 2\n")
    reloader._check_changes()

    assert calls == ["b.yaml"]
    assert "a.yaml" not in calls


def test_multiple_callbacks_all_invoked(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "x: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    c1, c2 = [], []
    reloader.on_change(lambda n: c1.append(n))
    reloader.on_change(lambda n: c2.append(n))

    _write(f, "x: 2\n")
    reloader._check_changes()

    assert c1 == ["a.yaml"]
    assert c2 == ["a.yaml"]


def test_callback_exception_does_not_propagate(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "x: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)

    def boom(name):
        raise RuntimeError("callback failed")

    ok = []
    reloader.on_change(boom)
    reloader.on_change(lambda name: ok.append(name))

    _write(f, "x: 2\n")
    # Should not raise despite the first callback blowing up.
    reloader._check_changes()

    assert ok == ["a.yaml"]


def test_empty_config_dir_is_safe(config_dir):
    # config_dir exists but contains no *.yaml files.
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    assert reloader._hashes == {}
    # No files -> checking is a no-op (no callback, no error).
    calls = []
    reloader.on_change(lambda name: calls.append(name))
    reloader._check_changes()
    assert calls == []


def test_nonexistent_config_dir_is_safe(tmp_path):
    missing = tmp_path / "does_not_exist"
    # Module never raises on a missing directory; it simply finds no files.
    reloader = ConfigReloader(str(missing), polling_interval=1.0)
    assert reloader._hashes == {}


def test_invalid_yaml_still_tracked_as_bytes(config_dir):
    """ConfigReloader hashes raw bytes, so even unparseable YAML is watched."""
    f = config_dir / "broken.yaml"
    _write(f, "this: : : not valid yaml\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=1.0)
    assert "broken.yaml" in reloader._hashes

    _write(f, "this: : : changed\n")
    calls = []
    reloader.on_change(lambda name: calls.append(name))
    reloader._check_changes()
    assert calls == ["broken.yaml"]


def test_start_detects_change_within_polling_interval(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "v: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=0.02)

    event = threading.Event()
    reloader.on_change(lambda name: event.set())

    # Modify after construction so the running poll detects the delta.
    _write(f, "v: 2\n")
    reloader.start()
    try:
        assert event.wait(timeout=2.0), "reloader did not detect change while polling"
    finally:
        reloader.stop()

    assert reloader._hashes["a.yaml"] == hashlib.md5(b"v: 2\n").hexdigest()


def test_stop_terminates_polling_thread(config_dir):
    f = config_dir / "a.yaml"
    _write(f, "v: 1\n")
    reloader = ConfigReloader(str(config_dir), polling_interval=0.02)
    reloader.start()
    reloader.stop()
    assert reloader._running is False
    assert reloader._thread is not None
    assert not reloader._thread.is_alive()


def _read(path):
    return path.read_text(encoding="utf-8")
