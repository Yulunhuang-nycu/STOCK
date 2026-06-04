from __future__ import annotations

import datetime as dt
import threading
import time
from pathlib import Path

import pytest

from src.core.clock import UTC
from src.core.config import Config
from src.data.feed_base import Tick
from src.data.multi_fugle_feed import MultiFugleFeed
from src.main import build_feed


def _tick(symbol: str, serial: int) -> Tick:
    return Tick(
        symbol=symbol,
        ts=dt.datetime.now(tz=UTC),
        price=100.0 + serial,
        volume=1,
        serial=serial,
    )


def test_subscribe_groups_symbols_by_key_capacity() -> None:
    feed_10 = MultiFugleFeed(api_keys=["k1", "k2"], symbols_per_key=5)
    symbols_10 = [f"S{i}" for i in range(10)]
    feed_10.subscribe(symbols_10)
    assert [group for _, group in feed_10._key_symbol_groups] == [symbols_10[:5], symbols_10[5:]]

    feed_7 = MultiFugleFeed(api_keys=["k1", "k2"], symbols_per_key=5)
    symbols_7 = [f"S{i}" for i in range(7)]
    feed_7.subscribe(symbols_7)
    assert [group for _, group in feed_7._key_symbol_groups] == [symbols_7[:5], symbols_7[5:]]


def test_subscribe_raises_when_capacity_insufficient() -> None:
    feed = MultiFugleFeed(api_keys=[f"k{i}" for i in range(5)], symbols_per_key=5)
    symbols = [f"S{i}" for i in range(30)]
    with pytest.raises(ValueError, match="需要更多 key"):
        feed.subscribe(symbols)


def test_start_fan_in_delivers_all_ticks_single_consumer_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.data.multi_fugle_feed as multi_mod

    class DummyFugleFeed:
        _serial = 0

        def __init__(self, api_key: str, reconnect_delay_sec: float = 5.0) -> None:
            self.api_key = api_key
            self.symbols: list[str] = []
            self.callback = None
            self._stop = threading.Event()

        def subscribe(self, symbols: list[str]) -> None:
            self.symbols = list(symbols)

        def on_tick(self, callback) -> None:
            self.callback = callback

        def start(self) -> None:
            assert self.callback is not None
            for symbol in self.symbols:
                type(self)._serial += 1
                self.callback(_tick(symbol, type(self)._serial))
                time.sleep(0.002)
            self._stop.wait()

        def stop(self) -> None:
            self._stop.set()

    monkeypatch.setattr(multi_mod, "FugleFeed", DummyFugleFeed)

    feed = MultiFugleFeed(api_keys=["key-a", "key-b"], symbols_per_key=2)
    symbols = ["2330", "2317", "2303", "2382"]
    feed.subscribe(symbols)

    received: list[Tick] = []
    callback_thread_ids: set[int] = set()
    caller_thread_id = threading.get_ident()
    expected = len(symbols)

    def on_tick(tick: Tick) -> None:
        callback_thread_ids.add(threading.get_ident())
        received.append(tick)
        if len(received) == expected:
            feed.stop()

    feed.on_tick(on_tick)
    feed.start()

    assert len(received) == expected
    assert {tick.symbol for tick in received} == set(symbols)
    assert callback_thread_ids == {caller_thread_id}


def test_stop_unblocks_start_and_stops_all_underlying_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.data.multi_fugle_feed as multi_mod

    class BlockingDummyFeed:
        instances: list["BlockingDummyFeed"] = []
        started_event = threading.Event()

        def __init__(self, api_key: str, reconnect_delay_sec: float = 5.0) -> None:
            self.stop_called = False
            self.callback = None
            self._stop = threading.Event()
            type(self).instances.append(self)

        def subscribe(self, symbols: list[str]) -> None:
            pass

        def on_tick(self, callback) -> None:
            self.callback = callback

        def start(self) -> None:
            type(self).started_event.set()
            self._stop.wait()

        def stop(self) -> None:
            self.stop_called = True
            self._stop.set()

    monkeypatch.setattr(multi_mod, "FugleFeed", BlockingDummyFeed)

    feed = MultiFugleFeed(api_keys=["k1", "k2"], symbols_per_key=1)
    feed.subscribe(["2330", "2317"])
    feed.on_tick(lambda tick: None)

    start_thread = threading.Thread(target=feed.start, daemon=True)
    start_thread.start()
    assert BlockingDummyFeed.started_event.wait(timeout=1.0)

    feed.stop()
    start_thread.join(timeout=1.0)
    assert not start_thread.is_alive()
    assert len(BlockingDummyFeed.instances) == 2
    assert all(inst.stop_called for inst in BlockingDummyFeed.instances)


def test_build_feed_fugle_live_multi_reads_keys_file_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.data.multi_fugle_feed as multi_mod

    class StubMultiFugleFeed:
        def __init__(self, api_keys: list[str], symbols_per_key: int = 5, reconnect_delay_sec: float = 5.0) -> None:
            self.api_keys = api_keys
            self.symbols_per_key = symbols_per_key

    monkeypatch.setattr(multi_mod, "MultiFugleFeed", StubMultiFugleFeed)
    monkeypatch.setenv("FUGLE_API_KEY_1", "env-key-1")

    keys_file = tmp_path / "KEY.txt"
    keys_file.write_text("\n# comment\n file-key-1 \n\nfile-key-2\n", encoding="utf-8")

    cfg = Config(
        raw={
            "data_feed": {
                "type": "fugle_live_multi",
                "fugle_live_multi": {
                    "keys_file": str(keys_file),
                    "symbols_per_key": 5,
                },
            }
        }
    )

    feed = build_feed(cfg)
    assert feed.api_keys == ["file-key-1", "file-key-2"]
    assert feed.symbols_per_key == 5


def test_build_feed_fugle_live_multi_reads_env_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.data.multi_fugle_feed as multi_mod

    class StubMultiFugleFeed:
        def __init__(self, api_keys: list[str], symbols_per_key: int = 5, reconnect_delay_sec: float = 5.0) -> None:
            self.api_keys = api_keys
            self.symbols_per_key = symbols_per_key

    monkeypatch.setattr(multi_mod, "MultiFugleFeed", StubMultiFugleFeed)
    monkeypatch.setenv("FUGLE_API_KEY_1", "env-key-1")
    monkeypatch.setenv("FUGLE_API_KEY_2", "env-key-2")
    monkeypatch.delenv("FUGLE_API_KEY_3", raising=False)

    cfg = Config(raw={"data_feed": {"type": "fugle_live_multi", "fugle_live_multi": {"keys_file": ""}}})
    feed = build_feed(cfg)
    assert feed.api_keys == ["env-key-1", "env-key-2"]


def test_build_feed_fugle_live_multi_raises_when_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FUGLE_API_KEY_1", raising=False)
    cfg = Config(raw={"data_feed": {"type": "fugle_live_multi", "fugle_live_multi": {"keys_file": ""}}})
    with pytest.raises(ValueError, match="未讀到任何 API key"):
        build_feed(cfg)

