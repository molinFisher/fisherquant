import pytest
import tempfile
import os
from pathlib import Path


class TestFullSystemStartup:
    @pytest.mark.asyncio
    async def test_config_loader(self):
        from fisher.config.loader import ConfigLoader
        configs_dir = Path(__file__).parent.parent.parent / "configs"
        cfg = ConfigLoader.load(str(configs_dir))
        assert cfg.system.mode.value in ("paper", "backtest", "live")

    @pytest.mark.asyncio
    async def test_event_bus_create(self):
        from fisher.event.bus import create_event_bus
        from fisher.config.schemas import EventConfig
        bus = create_event_bus(EventConfig(backend="asyncio"))
        assert bus is not None

    @pytest.mark.asyncio
    async def test_store_init(self):
        import tempfile
        import os
        from fisher.store.engine import DuckDBEngine
        from fisher.store.schema import init_schema
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(db_path)
        try:
            engine = DuckDBEngine(db_path)
            init_schema(engine)
            result = engine.query_df("SELECT COUNT(*) AS c FROM bars_daily")
            assert result["c"][0] >= 0
            engine.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_oms_engine_init(self):
        from fisher.oms.engine import OMSEngine
        engine = OMSEngine()
        assert engine is not None
        assert len(engine.get_pending()) == 0

    @pytest.mark.asyncio
    async def test_paper_engine_init(self):
        from fisher.paper.engine import PaperEngine
        from fisher.config.schemas import AssetFeeConfig
        fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
        engine = PaperEngine(fee)
        assert engine is not None
        acct = engine.get_account()
        assert acct["capital"] > 0

    @pytest.mark.asyncio
    async def test_position_service_init(self):
        from fisher.position.service import PositionService
        svc = PositionService()
        assert svc is not None
        assert svc.get_position("ANY") is None

    @pytest.mark.asyncio
    async def test_risk_engine_init(self):
        from fisher.risk.engine import RiskEngine
        from fisher.risk.pre_trade import MaxPositionRule
        engine = RiskEngine(rules=[MaxPositionRule(max_pct=0.2)])
        assert engine is not None

    @pytest.mark.asyncio
    async def test_scheduler_init(self):
        from fisher.scheduler.engine import SchedulerEngine
        engine = SchedulerEngine()
        assert engine is not None
        calls = []
        def hook(m): calls.append(m)
        engine.on_market_open(hook)
        assert len(calls) == 0

    @pytest.mark.asyncio
    async def test_alert_service_init(self):
        from fisher.alert.service import AlertService
        svc = AlertService()
        assert svc is not None

    @pytest.mark.asyncio
    async def test_auth_init(self):
        import tempfile
        import os
        from fisher.monitor.auth import create_default_admin, authenticate
        import fisher.monitor.auth as auth_mod
        tmp = tempfile.mkdtemp()
        cred_dir = os.path.join(tmp, ".fisher")
        os.makedirs(cred_dir, exist_ok=True)
        old_dir = auth_mod.CREDENTIALS_DIR
        old_file = auth_mod.CREDENTIALS_FILE
        try:
            auth_mod.CREDENTIALS_DIR = cred_dir
            auth_mod.CREDENTIALS_FILE = os.path.join(cred_dir, "credentials.json")
            create_default_admin(password="test123")
            assert authenticate("admin", "test123")
        finally:
            auth_mod.CREDENTIALS_DIR = old_dir
            auth_mod.CREDENTIALS_FILE = old_file

    @pytest.mark.asyncio
    async def test_monitor_app_init(self):
        import tempfile
        import os
        from fisher.monitor.app import create_app
        from fastapi.testclient import TestClient
        import fisher.monitor.app as app_mod
        import fisher.monitor.auth as auth_mod
        tmp = tempfile.mkdtemp()
        cred_dir = os.path.join(tmp, ".fisher")
        os.makedirs(cred_dir, exist_ok=True)
        old_app_dir = app_mod.CREDENTIALS_DIR
        old_app_file = app_mod.CREDENTIALS_FILE
        old_auth_dir = auth_mod.CREDENTIALS_DIR
        old_auth_file = auth_mod.CREDENTIALS_FILE
        try:
            cred_file = os.path.join(cred_dir, "credentials.json")
            app_mod.CREDENTIALS_DIR = cred_dir
            app_mod.CREDENTIALS_FILE = cred_file
            auth_mod.CREDENTIALS_DIR = cred_dir
            auth_mod.CREDENTIALS_FILE = cred_file
            app = create_app()
            client = TestClient(app)
            resp = client.get("/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["app"] == "FisherQuant"
        finally:
            app_mod.CREDENTIALS_DIR = old_app_dir
            app_mod.CREDENTIALS_FILE = old_app_file
            auth_mod.CREDENTIALS_DIR = old_auth_dir
            auth_mod.CREDENTIALS_FILE = old_auth_file

    @pytest.mark.asyncio
    async def test_full_pipeline_smoke(self):
        from fisher.oms.engine import OMSEngine
        from fisher.oms.orders import create_order, Order
        from fisher.event.types import OrderSide, OrderStatus, Bar
        from fisher.paper.engine import PaperEngine
        from fisher.position.service import PositionService
        from fisher.risk.engine import RiskEngine
        from fisher.risk.pre_trade import MaxPositionRule
        from fisher.config.schemas import AssetFeeConfig

        fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
        oms = OMSEngine()
        paper = PaperEngine(fee, initial_capital=100000.0)
        positions = PositionService()
        risk = RiskEngine(rules=[MaxPositionRule(max_pct=0.2)])

        order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)

        approved, reasons = risk.check(order, positions, 100000.0)
        assert approved, f"Risk check failed: {reasons}"

        oms.submit(order)
        paper.submit_order(order)

        bar = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=10.0, high=10.2, low=9.9, close=10.0,
            volume=100000, amount=1000000.0, bar_time=1234567890.0,
        )

        filled = paper.on_bar(bar)
        assert len(filled) == 1

        positions.update_on_fill(filled[0], 10.0)
        pos = positions.get_position("000001.SZ")
        assert pos is not None
        assert pos["quantity"] == 100

    @pytest.mark.asyncio
    async def test_backtest_engine_smoke(self):
        import polars as pl
        from fisher.backtest.engine import BacktestEngine
        from fisher.paper.engine import PaperEngine
        from fisher.position.service import PositionService
        from fisher.config.schemas import AssetFeeConfig

        df = pl.DataFrame({
            "ticker": ["A", "B"],
            "trade_date": ["2024-01-01", "2024-01-01"],
            "open": [10.0, 20.0],
            "high": [10.5, 20.5],
            "low": [9.5, 19.5],
            "close": [10.2, 20.2],
            "volume": [1000, 2000],
            "amount": [10000.0, 20000.0],
            "market": ["a_share", "a_share"],
        })

        fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
        paper = PaperEngine(fee, initial_capital=100000.0)
        positions = PositionService()
        engine = BacktestEngine(df, paper, positions)

        class DummyStrategy:
            name = "dummy"
            async def on_init(self): pass
            async def on_bar(self, bar): pass
            def on_signal(self): return []

        result = await engine.run(DummyStrategy())
        assert "nav_history" in result
        assert len(result["nav_history"]) > 0
        assert result["nav_history"][0] == 100000.0
