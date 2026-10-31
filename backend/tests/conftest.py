import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from tests.fake_binance import build_fake_binance

PASSWORD = "test-password-123"
FAKE_KEY, FAKE_SECRET = "FAKEKEY1234567890ABCDEF", "FAKESECRET1234567890ABCDEFGH"


@pytest.fixture
async def env(tmp_path):
    """Gerçek uygulama + yerel (taklit) Binance sunucusu. Bot döngüleri kapalı; testler adım adım sürer."""
    fake = build_fake_binance()
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=fake), base_url="http://fake-binance", timeout=30)
    cfg = AppConfig(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", data_dir=tmp_path, admin_password=PASSWORD,
        binance_rest_url="http://fake-binance", enable_bot_runtime=False, frontend_dist=tmp_path / "none",
    )
    app = create_app(cfg, http=http)
    async with app.router.lifespan_context(app):
        api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://panel")
        yield type("Env", (), {"app": app, "ctx": app.state.ctx, "api": api, "fake": fake, "tmp": tmp_path})
        await api.aclose()
    await http.aclose()


@pytest.fixture
async def authed(env):
    r = await env.api.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return env
