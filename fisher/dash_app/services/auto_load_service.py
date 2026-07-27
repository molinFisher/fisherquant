import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta
from typing import Optional

import akshare as ak

from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker, AUTO_LOAD_CFG

logger = logging.getLogger(__name__)

# ---- 加载计划分类 ----------------------------------------------------------
PLAN_FULL = "FULL"  # 库无数据：全量下载（initial_start ~ 今天）
PLAN_GAP = "GAP"    # 数据不新鲜：仅补 MAX(trade_date)+1 ~ 今天
PLAN_SKIP = "SKIP"  # 已新鲜：零请求

# ---- 账本状态 --------------------------------------------------------------
STATUS_PENDING = "pending"
STATUS_LOADING = "loading"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# ---- 服务阶段（写入 auto_load_status.phase，面向 UI/首页） ----------------
PHASE_IDLE = "idle"        # 空闲，可「开始」
PHASE_LOADING = "loading"  # 后台加载中
PHASE_PAUSED = "paused"    # 已暂停/可继续（含跨重启识别到的中断）
PHASE_DONE = "done"        # 本会话全部完成
PHASE_ERROR = "error"      # 致命错误（如无法获取成分股）

# 合法阶段集合（用于识别 V1.2 遗留脏值，如 'initial_load'/'complete'）
_VALID_PHASES = {PHASE_IDLE, PHASE_LOADING, PHASE_PAUSED, PHASE_DONE, PHASE_ERROR}

MARKET_A = "a_share"
MARKET_HK = "hk_connect"


# ===========================================================================
# 纯函数区（无副作用，便于单测与可注入时钟）
# ===========================================================================
def market_from_ticker(ticker: str) -> str:
    return MARKET_HK if ticker.endswith(".HK") else MARKET_A


def _market_close_time(market: str) -> dtime:
    """两市收盘界线。A股 15:00（北京）/ 港股 16:00（HKT）。两市均 UTC+8，无需时区换算。"""
    return dtime(16, 0) if market == MARKET_HK else dtime(15, 0)


def freshness_baseline(market: str, now: Optional[datetime] = None) -> date:
    """最近「已收盘」交易日（纯函数，now 可注入，对应 FR-1.6 / FR-1.7 / 验收#9）。

    - 若当前时刻早于今日收盘：今日数据未就绪 → 基准回退到上一交易日。
    - 若已收盘：基准为今日（若为交易日）。
    - 周末向前回滚到最近工作日（P0 用工作日近似；港股假期精度见 Q-01）。
    """
    if now is None:
        now = datetime.now()
    close = _market_close_time(market)
    today = now.date()
    candidate = today if now.time() >= close else today - timedelta(days=1)
    while candidate.weekday() >= 5:  # 5=周六 6=周日
        candidate -= timedelta(days=1)
    return candidate


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


@dataclass
class LoadPlan:
    ticker: str
    market: str
    kind: str            # FULL / GAP / SKIP
    gap_start: Optional[date] = None


# ===========================================================================
# 自动加载服务（DB as Source of Truth + 断点续传）
# ===========================================================================
class AutoLoadService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter, scheduler=None):
        self._db = db
        self._limiter = limiter
        self._scheduler = scheduler
        self._lock = threading.RLock()          # 互斥锁：保证单线程写账本/状态（FR-3.8）
        self._stop_event = threading.Event()    # 停止信号：替代旧 _running 布尔
        self._thread: Optional[threading.Thread] = None
        self._session_id: str = ""
        self._session_start_ts: float = 0.0
        # P1 失败重试（FR-4.2）：次数与退避可注入（测试用 monkeypatch）
        self._retry_max_attempts = int(AUTO_LOAD_CFG.get("retry_max_attempts", 4))
        self._retry_backoff = list(AUTO_LOAD_CFG.get("retry_backoff", [5, 15, 60]))
        self._ensure_status_table()
        # R-01：清理旧版基于位置索引的游标 key（current/skipped/total），由账本 ticker 取代
        try:
            self._db.execute(
                "DELETE FROM auto_load_status WHERE key IN ('current','skipped','total')"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 建表 / KV 助手
    # ------------------------------------------------------------------ #
    def _ensure_status_table(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS auto_load_status (
                key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL
            )""")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS symbol_load_state (
                ticker VARCHAR NOT NULL,
                session_id VARCHAR NOT NULL,
                plan VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                gap_start DATE,
                attempts INTEGER DEFAULT 0,
                last_error VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker)
            )""")

    def set_status(self, key: str, value: str):
        self._db.execute("INSERT OR REPLACE INTO auto_load_status VALUES (?,?)", [key, value])

    def get_status(self, key: str, default="0") -> str:
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key=?", [key])
        return row["value"].to_list()[0] if len(row) > 0 else str(default)

    def _set_kv(self, key: str, value: str):
        self.set_status(key, value)

    def _get_kv(self, key: str, default="0") -> str:
        return self.get_status(key, default)

    def _increment_kv(self, key: str, delta: int):
        self._set_kv(key, str(int(self._get_kv(key, "0")) + delta))

    # ------------------------------------------------------------------ #
    # 计划生成引擎（FR-1.x）：扫描库存 → FULL/GAP/SKIP
    # ------------------------------------------------------------------ #
    def build_plan(self, universe: list[str], force_full: bool = False) -> list[LoadPlan]:
        """对目标宇宙逐标的分类。DB as Source of Truth：仅依据 bars_daily 现有库存。"""
        existing: dict[str, date] = {}
        if not force_full:
            rows = self._db.query_df(
                "SELECT ticker, MAX(trade_date) AS last_date FROM bars_daily GROUP BY ticker"
            )
            for r in rows.iter_rows(named=True):
                if r["last_date"] is not None:
                    existing[r["ticker"]] = _parse_date(r["last_date"])

        start0 = _parse_date(AUTO_LOAD_CFG["initial_start"])
        plans: list[LoadPlan] = []
        for ticker in universe:
            market = market_from_ticker(ticker)
            last = existing.get(ticker)
            if force_full or last is None:
                plans.append(LoadPlan(ticker, market, PLAN_FULL, start0))
            else:
                base = freshness_baseline(market)
                if last < base:
                    gap_start = max(last + timedelta(days=1), start0)
                    plans.append(LoadPlan(ticker, market, PLAN_GAP, gap_start))
                else:
                    plans.append(LoadPlan(ticker, market, PLAN_SKIP, None))
        return plans

    # ------------------------------------------------------------------ #
    # 会话管理（FR-2.x）：session_id + 清单快照 + 幽灵行清理
    # ------------------------------------------------------------------ #
    def _snapshot_universe(self) -> list[str]:
        """当前加载宇宙：沪深300成分 + 港股通主要标的（与旧 _load_index_codes 口径一致）。

        去重：成分股清单偶发含重复 ticker（akshare 接口脏数据，如 600482.SH 出现两次），
        重复会导致账本 INSERT 主键冲突并让整个「开始」操作失败（见 issue 重复键）。
        """
        codes = self._load_index_codes()
        seen: set[str] = set()
        deduped: list[str] = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        return deduped

    def _stop_background(self, timeout: float = 5.0):
        """停止在途后台循环（如用户重新「开始」），避免旧会话线程污染新账本（会话隔离）。

        后台循环不持有 self._lock，故在 start_session 持锁时 join 不会死锁。
        """
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._stop_event.set()
            thread.join(timeout=timeout)
        self._stop_event.clear()
        self._thread = None

    def start_session(self, force_full: bool = False) -> dict:
        """「开始」/「重新加载」：全新会话，重建账本（幽灵行清理 + 在途循环终止）。"""
        with self._lock:
            self._stop_background()  # 先终止旧会话后台循环，避免其 UPDATE 误改新账本
            self._ensure_status_table()
            universe = self._snapshot_universe()
            if not universe:
                self._set_kv("phase", PHASE_ERROR)
                self._set_kv("message", "无法获取成分股列表")
                return {"phase": PHASE_ERROR, "message": "无法获取成分股列表"}
            plans = self.build_plan(universe, force_full=force_full)
            n_full = sum(1 for p in plans if p.kind == PLAN_FULL)
            n_gap = sum(1 for p in plans if p.kind == PLAN_GAP)
            n_skip = sum(1 for p in plans if p.kind == PLAN_SKIP)
            logger.info("load_plan_generated full=%d gap=%d skip=%d force_full=%s",
                        n_full, n_gap, n_skip, force_full)
            work = [p for p in plans if p.kind in (PLAN_FULL, PLAN_GAP)]
            session_id = uuid.uuid4().hex
            with self._db.transaction():
                # 幽灵行清理：清空旧会话账本（含崩溃遗留的 loading 行）
                self._db.execute("DELETE FROM symbol_load_state")
                for p in work:
                    # INSERT OR REPLACE：即使宇宙仍含重复 ticker 也幂等，绝不抛主键冲突
                    self._db.execute(
                        "INSERT OR REPLACE INTO symbol_load_state "
                        "(ticker, session_id, plan, status, gap_start, attempts) "
                        "VALUES (?,?,?,?,?,0)",
                        [p.ticker, session_id, p.kind, STATUS_PENDING,
                         p.gap_start.isoformat() if p.gap_start else None])
            self._session_id = session_id
            self._session_start_ts = time.time()
            self._set_kv("session_id", session_id)
            self._set_kv("force_full", "1" if force_full else "0")
            self._set_kv("phase", PHASE_LOADING)
            self._set_kv("total", str(len(work)))
            self._set_kv("done", "0")
            self._set_kv("failed", "0")
            self._start_background()
            if force_full:
                logger.info("load_reset_confirmed session_id=%s force_full=true", session_id)
            return {"phase": PHASE_LOADING, "session_id": session_id, "total": len(work)}

    def resume_session(self) -> dict:
        """「继续」：复用账本，将遗留 loading 翻回 pending 后继续（FR-3.7 中断恢复）。"""
        with self._lock:
            sid = self._get_kv("session_id", "")
            if not sid:
                return self.start_session()
            self._db.execute(
                "UPDATE symbol_load_state SET status=? WHERE session_id=? AND status=?",
                [STATUS_PENDING, sid, STATUS_LOADING])
            pending = self._count_status(sid, (STATUS_PENDING, STATUS_FAILED))
            logger.info("load_resumed session_id=%s pending=%d", sid, pending)
            if pending == 0:
                self._set_kv("phase", PHASE_DONE)
                return {"phase": PHASE_DONE, "session_id": sid, "total": 0}
            self._session_id = sid
            self._session_start_ts = time.time()
            self._set_kv("phase", PHASE_LOADING)
            self._start_background()
            return {"phase": PHASE_LOADING, "session_id": sid, "pending": pending}

    def recover(self) -> dict:
        """冷启动中断恢复：不自动开跑，仅把遗留 loading 翻回 pending 以便「继续」（FR-3.7）。"""
        self._ensure_status_table()
        sid = self._get_kv("session_id", "")
        phase = self._get_kv("phase", PHASE_IDLE)
        # 兼容 V1.2 遗留阶段值（如 'initial_load'/'complete'）：视为脏值，重置后重新规划
        if phase not in _VALID_PHASES:
            self._set_kv("phase", PHASE_IDLE)
            sid = ""
        if sid:
            self._db.execute(
                "UPDATE symbol_load_state SET status=? WHERE session_id=? AND status=?",
                [STATUS_PENDING, sid, STATUS_LOADING])
            pending = self._count_status(sid, (STATUS_PENDING, STATUS_FAILED))
            if pending > 0:
                self._set_kv("phase", PHASE_PAUSED)   # 等待用户「继续」
            else:
                self._set_kv("phase", PHASE_DONE)
            return self.get_state()
        # 全新：空库自动开始；有数据则空闲等待用户操作
        try:
            count = int(self._db.query_df("SELECT COUNT(*) AS c FROM bars_daily")["c"][0])
        except Exception:
            count = 0
        if count == 0:
            return self.start_session(force_full=False)
        self._set_kv("phase", PHASE_IDLE)
        return self.get_state()

    def _count_status(self, session_id: str, statuses) -> int:
        placeholders = ",".join("?" for _ in statuses)
        row = self._db.query_df(
            f"SELECT COUNT(*) AS c FROM symbol_load_state "
            f"WHERE session_id=? AND status IN ({placeholders})",
            [session_id, *statuses])
        return int(row["c"][0])

    # ------------------------------------------------------------------ #
    # 并发防护（FR-3.8）：互斥锁 + Event 停止信号
    # ------------------------------------------------------------------ #
    def _start_background(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._background_loop, daemon=True)
        self._thread.start()

    def pause(self) -> dict:
        """「暂停」：置位停止信号，待本轮批次结束后退出。"""
        self._stop_event.set()
        sid = self._get_kv("session_id", "")
        self._set_kv("phase", PHASE_PAUSED)
        logger.info("load_paused session_id=%s", sid)
        return {"phase": PHASE_PAUSED}

    def retry_failed(self) -> dict:
        """「重试失败项」（FR-4.3）：把全部 failed 翻回 pending 再开跑（重置 attempts 允许用户再试最终失败项）。"""
        with self._lock:
            sid = self._get_kv("session_id", "")
            if not sid:
                return self.get_state()
            self._db.execute(
                "UPDATE symbol_load_state SET status=?, attempts=0, last_error=NULL "
                "WHERE session_id=? AND status=?",
                [STATUS_PENDING, sid, STATUS_FAILED])
            self._set_kv("failed", "0")
            self._set_kv("phase", PHASE_LOADING)
            self._session_start_ts = time.time()
            self._start_background()
            logger.info("load_retry_failed session_id=%s", sid)
            return self.get_state()

    def _background_loop(self):
        try:
            self._run_rounds()
        finally:
            self._stop_event.set()
            self._reconcile_phase()

    def _run_rounds(self):
        """两阶段（FR-4.2）：① 清空 pending（首轮尝试，连续批不等待）；② 失败重试，轮间退避可注入。"""
        # 阶段1：首轮全量，批次连续无退避
        while not self._stop_event.is_set():
            self._run_batch(AUTO_LOAD_CFG["initial_batch_size"])
            if self._count_status(self._get_kv("session_id", ""), (STATUS_PENDING,)) == 0:
                break
        # 阶段2：失败重试，轮间退避（默认 5s/15s/60s，可注入为 [0,0,0] 加速 CI）
        round_idx = 0
        while not self._stop_event.is_set():
            sid = self._get_kv("session_id", "")
            if self._count_retryable_failed(sid) == 0:
                break
            backoff = self._retry_backoff[min(round_idx, len(self._retry_backoff) - 1)]
            if backoff > 0 and self._stop_event.wait(backoff):
                break  # 退避期间被暂停/停止
            self._run_batch(AUTO_LOAD_CFG["initial_batch_size"])
            round_idx += 1

    def _count_retryable_failed(self, session_id: str) -> int:
        if not session_id:
            return 0
        row = self._db.query_df(
            "SELECT COUNT(*) AS c FROM symbol_load_state "
            "WHERE session_id=? AND status=? AND attempts < ?",
            [session_id, STATUS_FAILED, self._retry_max_attempts])
        return int(row["c"][0])

    def _has_pending(self) -> bool:
        sid = self._get_kv("session_id", "")
        if not sid:
            return False
        return self._count_status(sid, (STATUS_PENDING, STATUS_FAILED)) > 0

    def _reconcile_phase(self):
        sid = self._get_kv("session_id", "")
        if not sid:
            return
        pending = self._count_status(sid, (STATUS_PENDING, STATUS_FAILED))
        failed = self._count_status(sid, (STATUS_FAILED,))
        if pending > 0 and failed < pending:
            # 仍含可继续的 pending（被暂停/打断）：保持 paused
            if self._get_kv("phase", "") != PHASE_PAUSED:
                self._set_kv("phase", PHASE_PAUSED)
        else:
            # 无 pending 或仅剩最终失败 → 会话结束（可能部分失败，UI 用 failed>0 呈现）
            self._set_kv("phase", PHASE_DONE)
            elapsed_ms = int((time.time() - self._session_start_ts) * 1000) if self._session_start_ts else 0
            reused = self._get_kv("force_full", "0") != "1"
            logger.info("load_session_done elapsed_ms=%d reused=%s failed=%d",
                        elapsed_ms, reused, failed)

    # ------------------------------------------------------------------ #
    # 加载执行器（FR-2.8 / FR-2.9）：按账本遍历 pending/failed + 单标的同事务 + 幂等
    # ------------------------------------------------------------------ #
    def _run_batch(self, batch_size: int) -> bool:
        rows = self._db.query_df(
            "SELECT ticker, plan, gap_start, attempts FROM symbol_load_state "
            "WHERE status IN (?,?) AND attempts < ? "
            "ORDER BY attempts ASC, ticker ASC LIMIT ?",
            [STATUS_PENDING, STATUS_FAILED, self._retry_max_attempts, batch_size])
        work = list(rows.iter_rows(named=True))
        if not work:
            return False
        for row in work:
            if self._stop_event.is_set():
                break
            ticker = row["ticker"]
            plan = row["plan"]
            gap_start = _parse_date(row["gap_start"])
            market = market_from_ticker(ticker)
            try:
                # 标记 in-progress，便于崩溃后识别「中断」
                self._db.execute(
                    "UPDATE symbol_load_state SET status=? WHERE ticker=?",
                    [STATUS_LOADING, ticker])
                bars = self._download(ticker, market, plan, gap_start)
                with self._db.transaction():
                    if bars:
                        self._db.execute_many(
                            "INSERT OR REPLACE INTO bars_daily "
                            "(ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)", bars)
                    self._db.execute(
                        "UPDATE symbol_load_state SET status=?, last_error=NULL, "
                        "updated_at=CURRENT_TIMESTAMP WHERE ticker=?",
                        [STATUS_DONE, ticker])
                pass
            except Exception as e:
                attempts = (int(row["attempts"] or 0)) + 1
                self._db.execute(
                    "UPDATE symbol_load_state SET status=?, attempts=?, last_error=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE ticker=?",
                    [STATUS_FAILED, attempts, str(e)[:500], ticker])
                logger.info("load_symbol_failed ticker=%s reason=%s attempts=%d",
                            ticker, self._translate_error(str(e)), attempts)
                logger.warning("Load failed %s (attempt %d): %s", ticker, attempts, e)
        # 实时同步 done/failed 计数（按账本实际状态，避免重试造成的累计虚高）
        sid = self._get_kv("session_id", "")
        if sid:
            self._set_kv("done", str(self._count_status(sid, (STATUS_DONE,))))
            self._set_kv("failed", str(self._count_status(sid, (STATUS_FAILED,))))
        return True

    def _download(self, ticker: str, market: str, plan: str,
                  gap_start: Optional[date]) -> list[list]:
        """按市场路由 akshare 接口（修复 P6），返回待写 bars 行（幂等由 INSERT OR REPLACE 保证）。"""
        self._limiter.acquire()
        if market == MARKET_HK:
            code = ticker.replace(".HK", "")
            df = ak.stock_hk_daily(symbol=code)
            if df is None or (hasattr(df, "empty") and df.empty):
                return []
            bars = []
            for _, r in df.iterrows():
                d = r["date"]
                ds = str(d) if not hasattr(d, "strftime") else d.strftime("%Y-%m-%d")
                if plan == PLAN_GAP and gap_start and ds < gap_start.isoformat():
                    continue
                if ds < AUTO_LOAD_CFG["initial_start"]:
                    continue
                bars.append([ticker, ds, float(r["open"]), float(r["high"]),
                             float(r["low"]), float(r["close"]),
                             int(r.get("volume", 0)), 0.0, market, 1.0])
            return bars

        # A 股：stock_zh_a_daily
        code = ticker.replace(".SH", "").replace(".SZ", "")
        exch = "sh" if code.startswith(("6", "5", "9")) else "sz"
        start = (gap_start.isoformat() if plan == PLAN_GAP and gap_start
                 else AUTO_LOAD_CFG["initial_start"]).replace("-", "")
        end = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_daily(symbol=f"{exch}{code}", start_date=start,
                                 end_date=end, adjust="")
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        bars = []
        for _, r in df.iterrows():
            d = r["date"]
            ds = str(d) if not hasattr(d, "strftime") else d.strftime("%Y-%m-%d")
            bars.append([ticker, ds, float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"]),
                         int(float(r.get("volume", 0))), float(r.get("amount", 0.0)),
                         market, 1.0])
        return bars

    # ------------------------------------------------------------------ #
    # 对外便捷入口（供回调调用）
    # ------------------------------------------------------------------ #
    def start(self) -> dict:
        return self.start_session(force_full=False)

    def reload(self, force_full: bool = False) -> dict:
        """「重新加载」：清账本（不清 bars_daily，历史仍复用）；force_full=True 即「彻底重下」。"""
        return self.start_session(force_full=force_full)

    # ------------------------------------------------------------------ #
    # 增量更新（定时任务）：复用同一套缺口机制，按市场正确路由 + 全量覆盖（修复 P6/P7）
    # ------------------------------------------------------------------ #
    def incremental_update(self) -> dict:
        tickers = self._db.query_df(
            "SELECT DISTINCT ticker FROM bars_daily")["ticker"].to_list()
        processed = 0
        for t in tickers:  # 遍历全部已有标的，不再截断（修复 P7）
            try:
                market = market_from_ticker(t)
                last = self._db.query_df(
                    "SELECT MAX(trade_date) AS d FROM bars_daily WHERE ticker=?", [t])
                last_date = _parse_date(last["d"][0]) if len(last) > 0 and last["d"][0] is not None \
                    else _parse_date(AUTO_LOAD_CFG["initial_start"])
                plan = PLAN_GAP if last_date < freshness_baseline(market) else PLAN_SKIP
                if plan == PLAN_SKIP:
                    processed += 1
                    continue
                bars = self._download(t, market, PLAN_GAP, last_date + timedelta(days=1))
                if bars:
                    with self._db.transaction():
                        self._db.execute_many(
                            "INSERT OR REPLACE INTO bars_daily "
                            "(ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)", bars)
                processed += 1
            except Exception as e:
                logger.warning("Incremental update failed %s: %s", t, e)
        self._set_kv("last_run", datetime.now().isoformat())
        return {"phase": "incremental", "processed": processed}

    # ------------------------------------------------------------------ #
    # 状态查询与失败清单（UI / 首页）
    # ------------------------------------------------------------------ #
    def get_failed(self) -> list[dict]:
        """失败清单数据接口（FR-4.3）：ticker / 名称 / 原因 / 已重试次数。"""
        sid = self._get_kv("session_id", "")
        if not sid:
            return []
        rows = self._db.query_df(
            "SELECT s.ticker, s.attempts, s.last_error, d.name "
            "FROM symbol_load_state s LEFT JOIN symbol_dict d ON s.ticker = d.ticker "
            "WHERE s.session_id=? AND s.status=? ORDER BY s.ticker ASC",
            [sid, STATUS_FAILED])
        return [
            {
                "ticker": r["ticker"],
                "name": r["name"] if r["name"] is not None else "—",
                "attempts": int(r["attempts"] or 0),
                "reason": self._translate_error(r["last_error"]),
                "raw_error": (r["last_error"] or "")[:200],
            }
            for r in rows.iter_rows(named=True)
        ]

    @staticmethod
    def _translate_error(raw) -> str:
        """失败原因用户可读转译（FR-4.3：不暴露堆栈）。"""
        if not raw:
            return "未知错误"
        msg = str(raw)
        low = msg.lower()
        if "timeout" in low or "timed out" in low:
            return "请求超时"
        if "rate" in low or "限频" in msg or "429" in low:
            return "接口限频"
        if "empty" in low or "无数据" in msg or "none" in low:
            return "接口无数据返回"
        if "connect" in low or "network" in low:
            return "网络连接失败"
        return msg[:60]

    def get_state(self) -> dict:
        sid = self._get_kv("session_id", "")
        phase = self._get_kv("phase", PHASE_IDLE)
        total = int(self._get_kv("total", "0"))
        done = int(self._get_kv("done", "0"))
        failed = int(self._get_kv("failed", "0"))
        pending = 0
        if sid:
            pending = self._count_status(sid, (STATUS_PENDING, STATUS_FAILED))
        can_resume = bool(sid) and pending > 0 and phase in (
            PHASE_PAUSED, PHASE_IDLE, PHASE_ERROR)
        return {
            "phase": phase, "session_id": sid, "total": total, "done": done,
            "failed": failed, "pending": pending,
            "force_full": self._get_kv("force_full", "0") == "1",
            "can_resume": can_resume,
            "last_run": self._get_kv("last_run", ""),
        }

    def get_progress(self) -> dict:
        """兼容旧调用方（首页/进度回调）的字段别名。"""
        st = self.get_state()
        return {
            "phase": st["phase"],
            "current": st["done"],     # 旧别名：已成功处理数
            "total": st["total"],
            "skipped": st["failed"],   # 旧别名：失败数
            "done": st["done"],
            "failed": st["failed"],
            "pending": st["pending"],
            "last_run": st["last_run"],
        }

    # ------------------------------------------------------------------ #
    # 成分股清单（网络；被 _snapshot_universe 调用），保持旧口径
    # ------------------------------------------------------------------ #
    def _load_index_codes(self) -> list[str]:
        codes = []
        try:
            df = ak.index_stock_cons(symbol="000300")
            col = df.columns[0]
            codes += [f"{r[col]}.SH" if r[col].startswith(("6", "5", "9"))
                      else f"{r[col]}.SZ" for _, r in df.iterrows()]
        except Exception as e:
            logger.warning("CSI300 fetch failed: %s", e)
        try:
            hk_df = ak.stock_hk_spot()
            code_col = hk_df.columns[1]
            for _, r in hk_df.head(80).iterrows():
                raw_code = str(r[code_col]).zfill(5)
                codes.append(f"{raw_code}.HK")
        except Exception as e:
            logger.warning("HK stock list fetch failed: %s", e)
        return codes
