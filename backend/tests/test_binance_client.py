import httpx
import pytest

from app.exchange.binance import BinanceClient, ExchangeError, sign_query


def test_signature_matches_binance_documentation_example():
    """Binance belgelerindeki resmi HMAC SHA256 örneği."""
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    qs = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert sign_query(qs, secret) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def _client(handler):
    return BinanceClient("https://example.test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_parses_documented_response_formats():
    def handler(req: httpx.Request):
        p = req.url.path
        if p == "/api/v3/exchangeInfo":
            return httpx.Response(200, json={"symbols": [{
                "symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT", "isSpotTradingAllowed": True,
                "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}, {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
                            {"filterType": "NOTIONAL", "minNotional": "5.00"}]}]})
        if p == "/api/v3/ticker/24hr":
            return httpx.Response(200, json=[{"symbol": "BTCUSDT", "lastPrice": "60000.0", "bidPrice": "59999.9", "askPrice": "60000.1",
                                              "quoteVolume": "1000000000", "priceChangePercent": "1.5", "count": 900000}])
        if p == "/api/v3/klines":
            return httpx.Response(200, json=[[1499040000000, "0.01634790", "0.80000000", "0.01575800", "0.01577100", "148976.11427815",
                                              1499644799999, "2434.19055334", 308, "1756.87402397", "28.46694368", "0"]])
        return httpx.Response(404, json={"code": -1, "msg": "yok"})

    c = _client(handler)
    info = (await c.exchange_info())["BTCUSDT"]
    assert (info.tick_size, info.step_size, info.min_notional, info.base) == (0.01, 0.00001, 5.0, "BTC")
    t = (await c.tickers_24h())["BTCUSDT"]
    assert t.last == 60000.0 and 0 < t.spread_pct < 0.01
    k = await c.klines("BTCUSDT", "1h", 1)
    assert len(k) == 1 and k.close[0] == 0.015771 and k.close_time[0] == 1499644799999


async def test_api_error_is_reported_without_retry_storm():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    c = _client(handler)
    with pytest.raises(ExchangeError) as e:
        await c.klines("XXX", "1h")
    assert e.value.code == -1121 and len(calls) == 1


async def test_signed_request_requires_keys_and_never_puts_secret_in_url():
    c = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ExchangeError):
        await c.account()

    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-mbx-apikey")
        return httpx.Response(200, json={"canTrade": True})

    c2 = BinanceClient("https://example.test", "APIKEY1234567890", "SUPERSECRETVALUE123", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await c2.account()
    assert "signature=" in seen["url"] and "SUPERSECRETVALUE123" not in seen["url"] and seen["key"] == "APIKEY1234567890"


async def test_server_error_is_retried():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(503) if n["c"] < 2 else httpx.Response(200, json={})

    k = await _client(handler).klines("BTCUSDT", "1h", 1)  # 503 -> yeniden dene -> 200 []
    assert n["c"] == 2 and len(k) == 0
