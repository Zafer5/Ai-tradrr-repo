from app.exchanges.base import BookTicker, SymbolInfo, Ticker24h
from app.exchanges.binance import parse_symbol
from app.scanner import ScanFilters, is_leveraged, scan


def sym(s, base, status="TRADING", quote="USDT"):
    return SymbolInfo(s, base, quote, status, True)


def test_filters():
    symbols = [sym("BTCUSDT", "BTC"), sym("ETHUSDT", "ETH"), sym("USDCUSDT", "USDC"), sym("BTCUPUSDT", "BTCUP"),
               sym("LOWUSDT", "LOW"), sym("WIDEUSDT", "WIDE"), sym("HALTUSDT", "HALT", "BREAK"), sym("ETHBTC", "ETH", quote="BTC"),
               sym("JUPUSDT", "JUP")]
    tick = lambda s, v: Ticker24h(s, 1.0, 1.0, v, 100_000, 1.1, 0.9)
    tickers = [tick("BTCUSDT", 900e6), tick("ETHUSDT", 500e6), tick("USDCUSDT", 1e9), tick("BTCUPUSDT", 50e6),
               tick("LOWUSDT", 1e5), tick("WIDEUSDT", 50e6), tick("HALTUSDT", 50e6), tick("JUPUSDT", 20e6)]
    books = [BookTicker(t.symbol, 0.9999, 1.0001) for t in tickers]
    books[5] = BookTicker("WIDEUSDT", 0.98, 1.02)
    ok, rejected = scan(symbols, tickers, books, ScanFilters())
    assert [r.symbol for r in ok] == ["BTCUSDT", "ETHUSDT", "JUPUSDT"]
    reasons = {r.symbol: r.reason for r in rejected}
    assert "Stablecoin" in reasons["USDCUSDT"]
    assert "Kaldıraçlı" in reasons["BTCUPUSDT"]
    assert "hacim" in reasons["LOWUSDT"]
    assert "spread" in reasons["WIDEUSDT"]
    assert "kapalı" in reasons["HALTUSDT"]


def test_leveraged_detection():
    bases = {"BTC", "ETH", "J"}
    assert is_leveraged("BTCUP", bases)
    assert is_leveraged("ETHDOWN", bases)
    assert not is_leveraged("JUP", bases)


def test_parse_binance_symbol():
    raw = {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True,
           "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                       {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
                       {"filterType": "NOTIONAL", "minNotional": "5.00"}]}
    s = parse_symbol(raw)
    assert s.step_size == 0.00001 and s.tick_size == 0.01 and s.min_notional == 5.0
