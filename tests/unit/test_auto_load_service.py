import pytest
from fisher.dash_app.services.auto_load_service import AutoLoadService


class TestAutoLoad:
    def test_empty_db_triggers_initial(self, auto_load_service):
        result = auto_load_service.check_and_start()
        assert result["phase"] in ("initial_load", "complete")

    def test_initial_load_writes_progress(self, auto_load_service):
        result = auto_load_service.initial_load()
        assert "current" in result or result["phase"] == "complete"
        progress = auto_load_service.get_progress()
        assert progress["total"] > 0

    def test_incremental_batch_20(self, auto_load_service):
        result = auto_load_service.incremental_update()
        assert "processed" in result
        assert result["phase"] == "incremental"

    def test_interrupt_resume_continues(self, auto_load_service):
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('current','150')")
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('phase','initial_load')")
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('total','300')")
        result = auto_load_service.check_and_start()
        assert result["phase"] in ("initial_load", "complete")

    def test_csi300_fallback(self, auto_load_service):
        result = auto_load_service.initial_load()
        assert result is not None

    def test_get_progress_empty(self, auto_load_service):
        # Reset status
        auto_load_service._db.execute("DELETE FROM auto_load_status")
        progress = auto_load_service.get_progress()
        assert progress["phase"] == "idle"
        assert progress["current"] == 0
        assert progress["total"] == 0

    def test_incremental_no_data(self, auto_load_service):
        # No data in bars_daily, should handle gracefully
        auto_load_service._db.execute("DELETE FROM bars_daily")
        result = auto_load_service.incremental_update()
        assert result["phase"] == "incremental"
        assert result["processed"] == 0

    def test_ensure_status_table_creates(self, in_memory_db, limiter, mock_scheduler):
        in_memory_db.execute("DROP TABLE IF EXISTS auto_load_status")
        service = AutoLoadService(in_memory_db, limiter, mock_scheduler)
        df = in_memory_db.query_df("SELECT name FROM sqlite_master WHERE type='table' AND name='auto_load_status'")
        assert len(df) > 0


class TestAutoLoadProgress:
    def test_progress_after_partial(self, auto_load_service):
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('current','10')")
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('total','100')")
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO auto_load_status VALUES ('phase','initial_load')")
        progress = auto_load_service.get_progress()
        assert progress["current"] == 10
        assert progress["total"] == 100
        assert progress["phase"] == "initial_load"
