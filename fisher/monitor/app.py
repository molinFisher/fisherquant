from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import os

from .auth import create_access_token, authenticate, get_current_user, CREDENTIALS_DIR, CREDENTIALS_FILE
from .auth import create_default_admin
from .ws import ws_router

bearer_scheme = HTTPBearer(auto_error=False)

templates_dir = Path(__file__).parent / "templates"
if not templates_dir.exists():
    templates_dir = Path(__file__).parent.parent.parent / "fisher" / "monitor" / "templates"

_env = None
if templates_dir.exists():
    _env = Environment(loader=FileSystemLoader(str(templates_dir)))


def _get_template_response(request: Request, name: str, **ctx) -> HTMLResponse:
    if _env:
        template = _env.get_template(name)
        content = template.render(request=request, **ctx)
        return HTMLResponse(content)
    return HTMLResponse(f"<html><body><h1>{name}</h1></body></html>")


async def _verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    if credentials:
        try:
            return get_current_user(credentials.credentials)
        except Exception:
            pass
    token = request.cookies.get("access_token") or request.query_params.get("token")
    if token:
        try:
            return get_current_user(token)
        except Exception:
            pass
    return None


async def _require_auth(user: str | None = Depends(_verify_token)) -> str:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def create_app(paper_engine=None, position_service=None, risk_engine=None) -> FastAPI:
    create_default_admin()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        os.makedirs(CREDENTIALS_DIR, exist_ok=True)
        yield

    app = FastAPI(title="FisherQuant Monitor", lifespan=lifespan)

    @app.get("/login")
    async def login_page(request: Request):
        return _get_template_response(request, "login.html")

    @app.post("/login")
    async def login_post(username: str = Form(...), password: str = Form(...)):
        if authenticate(username, password):
            token = create_access_token(username)
            return {"access_token": token, "token_type": "bearer"}
        raise HTTPException(status_code=401, detail="Invalid credentials")

    @app.get("/logout")
    async def logout(request: Request):
        response = _get_template_response(request, "login.html")
        response.delete_cookie("access_token")
        return response

    @app.get("/dashboard")
    async def dashboard(request: Request, user: str = Depends(_require_auth)):
        return _get_template_response(request, "dashboard.html")

    @app.get("/")
    async def root():
        return {"app": "FisherQuant", "version": "0.1.0"}

    @app.get("/api/overview")
    async def api_overview(user: str = Depends(_require_auth)):
        if paper_engine is not None:
            acct = paper_engine.get_account()
            return {"nav": acct.get("capital", 0.0), "capital": acct.get("capital", 0.0),
                    "available": acct.get("available", 0.0), "user": user}
        return {"nav": 1000000.0, "capital": 1000000.0, "available": 1000000.0, "user": user}

    @app.get("/api/positions")
    async def api_positions(user: str = Depends(_require_auth)):
        if position_service is not None:
            positions = position_service.snapshot()
            return {"positions": positions}
        return {"positions": []}

    @app.get("/api/orders")
    async def api_orders(user: str = Depends(_require_auth)):
        if paper_engine is not None:
            orders = paper_engine._oms.get_all_orders()
            return [{"order_id": o.order_id, "ticker": o.ticker, "status": o.status.value} for o in orders]
        return []

    @app.get("/api/risk")
    async def api_risk(user: str = Depends(_require_auth)):
        if risk_engine is not None:
            return {"status": "ok", "rules": [r.rule for r in risk_engine._pre_trade_rules]}
        return {"status": "ok", "rules": []}

    app.include_router(ws_router)

    return app
