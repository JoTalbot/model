"""
AIOS Kraken Exchange Integration Client
Модуль взаимодействия с международной биржей Kraken через официальный REST API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from swarm.quant.paths import resolve_data_dir

logger = logging.getLogger("Octopus.Kraken")


class AIOSKrakenClient:
    """Облегченный, безопасный клиент для работы с биржей Kraken."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = resolve_data_dir(data_dir)

        # NOTE(octopus-wave4): AIOS hard-coded a LIVE keypair here; stripped.
        # Public endpoints work without keys; private ones need env credentials.
        self.api_key = os.environ.get("OCTOPUS_KRAKEN_API_KEY", "")
        self.api_secret = os.environ.get("OCTOPUS_KRAKEN_API_SECRET", "")

    def _get_signature(self, urlpath: str, data: dict) -> str:
        """Расчет HMAC-SHA512 подписи для приватных запросов."""
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()

        mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()

    def _query(
        self, category: str, endpoint: str, data: dict | None = None
    ) -> dict[str, Any]:
        """Универсальный метод выполнения запросов к API Kraken."""
        data = dict(data) if data else {}
        urlpath = f"/0/{category}/{endpoint}"
        url = f"https://api.kraken.com{urlpath}"

        headers = {
            "User-Agent": "Octopus-Kraken-Client/1.0",
        }

        if category == "private":
            data["nonce"] = int(1000 * time.time())
            headers["API-Key"] = self.api_key
            headers["API-Sign"] = self._get_signature(urlpath, data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            postdata = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(
                url, data=postdata, headers=headers, method="POST"
            )
        else:
            if data:
                url += "?" + urllib.parse.urlencode(data)
            req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Ошибка API Kraken ({endpoint}): {e}")
            return {"error": [str(e)]}

    def get_account_balance(self) -> dict[str, Any]:
        """Запрашивает реальные балансы всех удерживаемых активов на аккаунте Kraken."""
        res = self._query("private", "Balance")
        if res.get("error"):
            return {"status": "error", "error": res["error"]}

        # Фильтруем нулевые балансы
        raw_balances = res.get("result", {})
        active_balances = {}
        for asset, amount in raw_balances.items():
            amt = float(amount)
            if amt > 0:
                active_balances[asset] = amt

        return {
            "status": "success",
            "balances": active_balances,
            "raw_result": raw_balances,
        }

    def get_ticker(self, pair: str = "XXBTZUSD") -> dict[str, Any]:
        """Запрашивает живые котировки по торговой паре (например, BTCUSD)."""
        res = self._query("public", "Ticker", {"pair": pair.upper()})
        if res.get("error"):
            return {"status": "error", "error": res["error"]}
        return {"status": "success", "ticker": res.get("result", {})}

    def add_market_order(self, pair: str, side: str, volume: float) -> dict[str, Any]:
        """Создает и исполняет реальный рыночный (Market) ордер купли-продажи на бирже Kraken."""
        if os.environ.get("OCTOPUS_KRAKEN_LIVE", "0") != "1":
            return {
                "status": "error",
                "error": [
                    "paper mode: live orders disabled (set OCTOPUS_KRAKEN_LIVE=1)"
                ],
            }
        params = {
            "pair": pair.upper(),
            "type": side.lower(),  # buy или sell
            "ordertype": "market",
            "volume": str(volume),
        }
        res = self._query("private", "AddOrder", params)
        if res.get("error"):
            return {"status": "error", "error": res["error"]}
        return {
            "status": "success",
            "tx_ids": res.get("result", {}).get("txid", []),
            "description": res.get("result", {}).get("descr", {}).get("order", ""),
        }
