# -*- coding: utf-8 -*-
"""Regression tests for TickFlow market-review manager fallback."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import DataFetcherManager


class _DummyFetcher:
    def __init__(self, name, indices=None, stats=None):
        self.name = name
        self.priority = 1
        self.indices = indices
        self.stats = stats
        self.index_calls = 0
        self.stats_calls = 0

    def get_main_indices(self, region="cn"):
        self.index_calls += 1
        return self.indices

    def get_market_stats(self):
        self.stats_calls += 1
        return self.stats


class _DummyTickFlowFetcher:
    def __init__(self, indices=None, stats=None, error=None):
        self.indices = indices
        self.stats = stats
        self.error = error
        self.closed = False

    def get_main_indices(self, region="cn"):
        if self.error is not None:
            raise self.error
        return self.indices

    def get_market_stats(self):
        if self.error is not None:
            raise self.error
        return self.stats

    def close(self):
        self.closed = True


class TestTickFlowMarketReviewFallback(unittest.TestCase):
    def test_manager_prefers_tickflow_indices_when_available(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            indices=[
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            indices=[
                {"code": "000001", "current": 3300.0, "change_pct": 0.2},
                {"code": "000300", "current": 4100.0, "change_pct": 0.3},
            ]
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(
            data,
            [
                {"code": "000001", "current": 3300.0, "change_pct": 0.2},
                {"code": "000300", "current": 4100.0, "change_pct": 0.3},
            ],
        )
        self.assertEqual(fallback.index_calls, 0)

    def test_manager_completed_session_skips_tickflow_and_prefers_daily_fetcher(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        realtime = _DummyFetcher("EfinanceFetcher", indices=[{"code": "zero", "current": 1.0, "change_pct": 0.0}])
        daily = _DummyFetcher(
            "TushareFetcher",
            indices=[
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        manager._fetchers = [realtime, daily]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should be skipped for completed-session market review"
        )

        data = DataFetcherManager.get_main_indices(
            manager, region="cn", prefer_completed_session=True
        )

        self.assertEqual(
            data,
            [
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        self.assertEqual(daily.index_calls, 1)
        self.assertEqual(realtime.index_calls, 0)

    def test_completed_session_skips_invalid_index_payload_and_uses_next_source(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        bad_daily = _DummyFetcher(
            "YfinanceFetcher",
            indices=[
                {"code": "sh000001", "current": float("nan"), "change_pct": 0.1},
                {"code": "sh000300", "current": 4100.0, "change_pct": float("nan")},
            ],
        )
        fallback = _DummyFetcher(
            "EfinanceFetcher",
            indices=[
                {"code": "sh000001", "current": 3310.0, "change_pct": 0.15},
                {"code": "sh000300", "current": 4120.0, "change_pct": 0.25},
            ],
        )
        manager._fetchers = [fallback, bad_daily]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should be skipped for completed-session market review"
        )

        data = DataFetcherManager.get_main_indices(
            manager, region="cn", prefer_completed_session=True
        )

        self.assertEqual(data[0]["code"], "sh000001")
        self.assertEqual(data[0]["current"], 3310.0)
        self.assertEqual(bad_daily.index_calls, 1)
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_completed_session_market_stats_skips_tickflow(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        realtime = _DummyFetcher("EfinanceFetcher", stats={"up_count": 0})
        daily = _DummyFetcher("TushareFetcher", stats={"up_count": 3200})
        manager._fetchers = [realtime, daily]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should be skipped for completed-session market stats"
        )

        data = DataFetcherManager.get_market_stats(
            manager, prefer_completed_session=True
        )

        self.assertEqual(data["up_count"], 3200)
        self.assertEqual(daily.stats_calls, 1)
        self.assertEqual(realtime.stats_calls, 0)

    def test_manager_falls_back_when_tickflow_indices_fail(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            indices=[
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            error=RuntimeError("tickflow down")
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(
            data,
            [
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_falls_back_when_tickflow_indices_missing(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            indices=[
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            indices=None
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(
            data,
            [
                {"code": "000001", "current": 3300.0, "change_pct": 0.1},
                {"code": "000300", "current": 4100.0, "change_pct": 0.2},
            ],
        )
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_skips_tickflow_for_non_cn_indices(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher("YfinanceFetcher", indices=[{"code": "^GSPC", "current": 5200.0, "change_pct": 0.4}])
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should not be called for non-CN indices"
        )

        data = DataFetcherManager.get_main_indices(manager, region="us")

        self.assertEqual(data, [{"code": "^GSPC", "current": 5200.0, "change_pct": 0.4}])
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_falls_back_when_tickflow_market_stats_fails(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 1, "down_count": 2, "flat_count": 3},
        )
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            error=RuntimeError("tickflow down")
        )

        data = DataFetcherManager.get_market_stats(manager)

        self.assertEqual(data["up_count"], 1)
        self.assertEqual(fallback.stats_calls, 1)

    @patch("src.config.get_config")
    def test_manager_skips_tickflow_without_api_key(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(tickflow_api_key=None)

        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 2, "down_count": 1, "flat_count": 0},
        )
        manager._fetchers = [fallback]

        data = DataFetcherManager.get_market_stats(manager)

        self.assertEqual(data["up_count"], 2)
        self.assertEqual(fallback.stats_calls, 1)

    def test_manager_close_releases_tickflow_fetcher(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        tickflow_fetcher = _DummyTickFlowFetcher(indices=[{"code": "000001"}])
        manager._tickflow_fetcher = tickflow_fetcher
        manager._tickflow_api_key = "tf-secret"
        manager._tickflow_lock = None

        DataFetcherManager.close(manager)

        self.assertTrue(tickflow_fetcher.closed)
        self.assertIsNone(manager._tickflow_fetcher)
        self.assertIsNone(manager._tickflow_api_key)


if __name__ == "__main__":
    unittest.main()
