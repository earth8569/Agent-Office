from __future__ import annotations

import unittest

from agent_office.models import Side
from agent_office.okx import OkxCredentials, OkxDemoAdapter


class OkxDemoAdapterTests(unittest.TestCase):
    def test_demo_market_order_uses_one_way_position_mode(self) -> None:
        exchange = FakeOkxExchange(pos_mode="net_mode")
        adapter = OkxDemoAdapter(
            OkxCredentials(api_key="key", api_secret="secret", passphrase="pass", demo=True),
            exchange=exchange,
        )

        result = adapter.place_demo_market_with_stop(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            amount=1.0,
            leverage=1.0,
            stop_pct=0.05,
        )

        self.assertEqual(result.order_id, "demo-order-1")
        self.assertEqual(exchange.created_order["params"]["tdMode"], "isolated")
        self.assertEqual(exchange.created_order["params"]["marginMode"], "isolated")
        self.assertEqual(exchange.created_order["params"]["positionSide"], "net")
        self.assertFalse(exchange.created_order["params"]["hedged"])

    def test_demo_market_order_uses_hedge_position_side_when_account_is_hedged(self) -> None:
        exchange = FakeOkxExchange(pos_mode="long_short_mode")
        adapter = OkxDemoAdapter(
            OkxCredentials(api_key="key", api_secret="secret", passphrase="pass", demo=True),
            exchange=exchange,
        )

        adapter.place_demo_market_with_stop(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            amount=1.0,
            leverage=1.0,
            stop_pct=0.05,
        )

        self.assertEqual(exchange.created_order["params"]["positionSide"], "long")
        self.assertTrue(exchange.created_order["params"]["hedged"])
        self.assertEqual(exchange.leverage["params"]["posSide"], "long")

    def test_fetch_open_stop_orders_parses_top_level_okx_algo_stop(self) -> None:
        exchange = FakeOkxExchange(pos_mode="long_short_mode")
        exchange.pending_algo_orders = [
            {
                "algoId": "algo-1",
                "instId": "BTC-USDT-SWAP",
                "ordType": "conditional",
                "slTriggerPx": "63198.6",
                "posSide": "long",
            }
        ]
        adapter = OkxDemoAdapter(
            OkxCredentials(api_key="key", api_secret="secret", passphrase="pass", demo=True),
            exchange=exchange,
        )

        stops = adapter.fetch_open_stop_orders(("BTC/USDT:USDT",))

        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].symbol, "BTC/USDT:USDT")
        self.assertEqual(stops[0].order_id, "algo-1")
        self.assertEqual(stops[0].stop_price, 63198.6)

class FakeOkxExchange:
    def __init__(self, pos_mode: str | None = None) -> None:
        self.created_order: dict = {}
        self.pos_mode = pos_mode
        self.pending_algo_orders: list[dict] = []

    def load_markets(self) -> None:
        return None

    def set_leverage(self, leverage: int, symbol: str, params: dict) -> None:
        self.leverage = {"leverage": leverage, "symbol": symbol, "params": params}

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": 100_000.0}

    def private_get_account_config(self) -> dict:
        if self.pos_mode is None:
            raise RuntimeError("account config unavailable")
        return {"data": [{"posMode": self.pos_mode}]}

    def fetch_open_orders(self, symbol: str) -> list:
        return []

    def private_get_trade_orders_algo_pending(self, params: dict) -> dict:
        return {"data": self.pending_algo_orders}
    def create_order(self, **kwargs: object) -> dict:
        self.created_order = dict(kwargs)
        return {"id": "demo-order-1", "info": {"ordId": "demo-order-1"}}


class OkxOcoStopOrderTests(unittest.TestCase):
    def test_fetch_open_stop_orders_recognizes_okx_oco_attached_stop(self) -> None:
        exchange = OcoOnlyFakeOkxExchange()
        adapter = OkxDemoAdapter(
            OkxCredentials(api_key="key", api_secret="secret", passphrase="pass", demo=True),
            exchange=exchange,
        )

        stops = adapter.fetch_open_stop_orders(("BTC/USDT:USDT",))

        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].symbol, "BTC/USDT:USDT")
        self.assertEqual(stops[0].order_id, "oco-1")
        self.assertEqual(stops[0].stop_price, 63198.6)
        self.assertEqual([request["ordType"] for request in exchange.algo_requests], ["conditional", "oco"])


class OcoOnlyFakeOkxExchange(FakeOkxExchange):
    def __init__(self) -> None:
        super().__init__()
        self.algo_requests: list[dict] = []

    def private_get_trade_orders_algo_pending(self, params: dict) -> dict:
        self.algo_requests.append(params)
        if params.get("ordType") != "oco":
            return {"data": []}
        return {"data": [{
            "algoId": "oco-1",
            "instId": "BTC-USDT-SWAP",
            "ordType": "oco",
            "slTriggerPx": "63198.6",
        }]}


if __name__ == "__main__":
    unittest.main()