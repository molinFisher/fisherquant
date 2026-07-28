import sys
import tempfile
from pathlib import Path
import pytest
from fisher.store.engine import DuckDBManager
from fisher.market.rate_limiter import RateLimiter
from fisher.dash_app.services.data_center_service import DataCenterService
from fisher.dash_app.services.auto_load_service import AutoLoadService

# Make tests/ importable so `from helpers.dash_harness import ...` works in unit tests.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)



@pytest.fixture
def in_memory_db(tmp_path):
    DuckDBManager._instance = None
    db_path = str(tmp_path / "test.db")
    db = DuckDBManager(db_path, read_pool_size=1)
    # 用完整 init_schema 建库（v5：含 cache_catalog / financials / snapshots 新主键等），
    # 与线上启动路径一致，避免 fetch_bars 等依赖 catalog 的用例因表缺失而失败。
    from fisher.store.schema import init_schema
    init_schema(db)
    yield db
    DuckDBManager._instance = None


# 标的字典样本（供搜索单测）：贵州茅台 / 平安银行 / 宁德时代 / 腾讯控股 / 中国移动
_SYMBOL_DICT_ROWS = [
    ("600519.SH", "600519", "贵州茅台", "a_share", "GUIZHOUMAOTAI", "GZMT"),
    ("000001.SZ", "000001", "平安银行", "a_share", "PINGANYINHANG", "PAYH"),
    ("300750.SZ", "300750", "宁德时代", "a_share", "NINGDESHIDAI", "NDSD"),
    ("00700.HK", "00700", "腾讯控股", "hk_connect", "TENGXUNKONGGU", "TXKG"),
    ("00941.HK", "00941", "中国移动", "hk_connect", "ZHONGGUOYIDONG", "ZGYD"),
]


@pytest.fixture
def seeded_dict_service(in_memory_db, limiter):
    """已灌入样本 symbol_dict 且强制走新搜索链路（legacy=False）的服务。"""
    in_memory_db.execute_many(
        "INSERT INTO symbol_dict (ticker, code, name, market, pinyin_full, pinyin_abbr) "
        "VALUES (?,?,?,?,?,?)",
        [list(r) for r in _SYMBOL_DICT_ROWS],
    )
    svc = DataCenterService(in_memory_db, limiter)
    svc._legacy_search = False
    return svc


@pytest.fixture
def limiter():
    return RateLimiter(max_per_minute=1000)


@pytest.fixture
def data_service(in_memory_db, limiter):
    return DataCenterService(in_memory_db, limiter)


@pytest.fixture
def mock_scheduler():
    class MockScheduler:
        def add_job(self, *args, **kwargs):
            pass

        def start(self, *args, **kwargs):
            pass

        def shutdown(self, *args, **kwargs):
            pass
    return MockScheduler()


@pytest.fixture
def mock_index_cons(monkeypatch):
    class MockDF:
        def __init__(self, data):
            self._data = data

        @property
        def columns(self):
            return list(self._data[0].keys()) if self._data else []

        def iterrows(self):
            for i, row in enumerate(self._data):
                yield i, row

        def head(self, n):
            return MockDF(self._data[:n])

        @property
        def empty(self):
            return len(self._data) == 0

        def __len__(self):
            return len(self._data)

        def to_list(self):
            return [r.get("value", "") for r in self._data]

    import akshare as ak

    def mock_csi300(*args, **kwargs):
        return MockDF([
            {"stock_code": "600519"},
            {"stock_code": "000001"},
            {"stock_code": "300750"},
        ])

    def mock_hsi(*args, **kwargs):
        return MockDF([
            {"stock_code": "00700"},
            {"stock_code": "00941"},
        ])

    def mock_empty_csi300(*args, **kwargs):
        return MockDF([])

    def mock_zh_a_hist_auto(symbol=None, period="daily", start_date="", end_date="", adjust="qfq"):
        """Return mock bars that match the auto_load_service's expectations."""
        mock_data = [
            {"日期": "2024-01-02", "开盘": 100.0, "最高": 101.0, "最低": 99.0,
             "收盘": 100.5, "成交量": 1000000, "成交额": 100500000.0},
            {"日期": "2024-01-03", "开盘": 100.5, "最高": 102.0, "最低": 100.0,
             "收盘": 101.0, "成交量": 1200000, "成交额": 121200000.0},
        ]
        return MockAKShareDF(mock_data)

    def mock_stock_zh_a_daily(symbol=None, start_date="", end_date="", adjust=""):
        """auto_load_service.initial_load() 逐股下载日线走此接口，必须 mock 以免触网。"""
        daily = [
            {"date": "2024-01-02", "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.5, "volume": 1000000, "amount": 100500000.0},
            {"date": "2024-01-03", "open": 100.5, "high": 102.0, "low": 100.0,
             "close": 101.0, "volume": 1200000, "amount": 121200000.0},
        ]
        return MockAKShareDF(daily)

    def mock_stock_hk_daily(symbol=None, start_date="", end_date="", adjust=""):
        hk = [
            {"date": "2024-01-02", "open": 200.0, "high": 201.0, "low": 199.0,
             "close": 200.5, "volume": 500000, "amount": 100250000.0},
        ]
        return MockAKShareDF(hk)

    def mock_stock_hk_spot(*args, **kwargs):
        """_load_index_codes 用 stock_hk_spot 拉港股列表，必须 mock 以免触网。"""
        rows = [{"name": f"HK{i:05d}", "code": f"{i:05d}"} for i in range(80)]
        return MockDF(rows)

    monkeypatch.setattr(ak, "index_stock_cons", mock_csi300, raising=False)
    monkeypatch.setattr(ak, "hk_index_cons", mock_hsi, raising=False)
    monkeypatch.setattr(ak, "stock_zh_a_hist", mock_zh_a_hist_auto, raising=False)
    monkeypatch.setattr(ak, "stock_zh_a_daily", mock_stock_zh_a_daily, raising=False)
    monkeypatch.setattr(ak, "stock_hk_daily", mock_stock_hk_daily, raising=False)
    monkeypatch.setattr(ak, "stock_hk_spot", mock_stock_hk_spot, raising=False)
    return {"csi300": mock_csi300, "hsi": mock_hsi, "zh_a_hist": mock_zh_a_hist_auto,
            "zh_a_daily": mock_stock_zh_a_daily, "hk_daily": mock_stock_hk_daily,
            "hk_spot": mock_stock_hk_spot}


@pytest.fixture
def auto_load_service(in_memory_db, limiter, mock_scheduler, mock_index_cons):
    return AutoLoadService(in_memory_db, limiter, mock_scheduler)


class MockBoolList:
    def __init__(self, data):
        self._data = data

    def __or__(self, other):
        if isinstance(other, MockBoolList):
            return MockBoolList([a or b for a, b in zip(self._data, other._data)])
        return MockBoolList([a or other for a in self._data])

    def __and__(self, other):
        if isinstance(other, MockBoolList):
            return MockBoolList([a and b for a, b in zip(self._data, other._data)])
        return MockBoolList([a and other for a in self._data])

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def __len__(self):
        return len(self._data)


class MockAKShareDF:
    def __init__(self, data):
        self._data = data
        self.columns = list(data[0].keys()) if data else []

    def iterrows(self):
        for i, row in enumerate(self._data):
            yield i, row

    @property
    def empty(self):
        return len(self._data) == 0

    def __len__(self):
        return len(self._data)

    def head(self, n):
        return self

    def __getitem__(self, key):
        if isinstance(key, str):
            return MockAKShareSeries([r[key] for r in self._data])
        if isinstance(key, (list, MockBoolList)):
            filtered = [self._data[i] for i, v in enumerate(key) if v]
            return MockAKShareDF(filtered)
        return self._data


class MockAKShareSeries:
    def __init__(self, data):
        self._data = data

    def __iter__(self):
        return iter(self._data)

    def to_list(self):
        return self._data

    def __getitem__(self, idx):
        return self._data[idx]

    def __len__(self):
        return len(self._data)

    @property
    def str(self):
        return self

    def astype(self, dtype=None):
        return self

    def contains(self, pat, na=False):
        return MockBoolList([pat in str(v) for v in self._data])


@pytest.fixture
def mock_akshare(monkeypatch):
    import akshare as ak

    mock_stocks = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
        {"code": "300750", "name": "宁德时代"},
    ]

    mock_bars = [
        {"日期": "2024-01-02", "开盘": 100.0, "最高": 101.0, "最低": 99.0,
         "收盘": 100.5, "成交量": 1000000, "成交额": 100500000.0},
        {"日期": "2024-01-03", "开盘": 100.5, "最高": 102.0, "最低": 100.0,
         "收盘": 101.0, "成交量": 1200000, "成交额": 121200000.0},
    ]

    def mock_stock_info(*args, **kwargs):
        return MockAKShareDF(mock_stocks)

    def mock_zh_a_hist(symbol=None, period="daily", start_date="", end_date="", adjust="qfq"):
        return MockAKShareDF(mock_bars)

    def mock_financial_abstract(symbol=""):
        return MockAKShareDF([{"报告期": "2024-12-31", "营业收入": 100000000}])

    def mock_stock_hk_spot(*args, **kwargs):
        return MockAKShareDF([
            {"代码": "00700", "名称": "腾讯控股"},
            {"代码": "00941", "名称": "中国移动"},
        ])

    def mock_zh_a_hist_min_em(symbol=None, period="1", start_date="", end_date="", adjust=""):
        return MockAKShareDF(mock_bars)

    monkeypatch.setattr(ak, "stock_info_a_code_name", mock_stock_info)
    monkeypatch.setattr(ak, "stock_zh_a_hist", mock_zh_a_hist)
    monkeypatch.setattr(ak, "stock_financial_abstract", mock_financial_abstract)
    monkeypatch.setattr(ak, "stock_hk_spot", mock_stock_hk_spot, raising=False)
    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", mock_zh_a_hist_min_em, raising=False)
    return {"stock_info": mock_stock_info, "zh_a_hist": mock_zh_a_hist,
            "hk_spot": mock_stock_hk_spot, "zh_a_hist_min_em": mock_zh_a_hist_min_em}
