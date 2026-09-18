#!/usr/bin/env python3
"""
AIOS Quant RL - Консультирующий мост RL-сигналов (PPO-агент).

Читает обученную модель PPO (data/quant/models/ppo_trader.pt), загружает
свежие цены активов и предсказывает желаемую позицию агента (0 / 0.5 / 1).
Результаты предоставляются как КОНСУЛЬТИРУЮЩИЙ источник для quant_trading_engine
и отчётов. Никакой автоторговли.

Безопасность: мост только читает данные и предсказывает; не инициирует сделки.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))
MODEL_FILE = (
    DATA / "quant" / "models" / "ppo_v9.pt"
)  # LSTM-PPO v9 (300 эп, sum_rl +96% vs BH −114%)
OUT_FILE = DATA / "quant" / "rl_signals.json"

LOG_TAG = "[RLSignalBridge]"

# 32 актива среды обучения (quant_train_ppo.py, MultiAssetEnv):
# self.names = sorted(assets.keys()) — onehot-индекс актива в этом порядке.
# Используется как fallback; предпочтительно читать assets из чекпоинта
# модели (ppo_v9.pt сохраняет {"policy", "assets"}), т.к. v8 обучалась с
# MATIC, а v9 — с POL (разные индексы в onehot).
ASSET_ORDER_DEFAULT = sorted(
    [
        "BTC",
        "ETH",
        "BNB",
        "SOL",
        "XRP",
        "ADA",
        "DOGE",
        "AVAX",
        "LINK",
        "DOT",
        "POL",
        "LTC",
        "TRX",
        "ATOM",
        "UNI",
        "ETC",
        "FIL",
        "APT",
        "NEAR",
        "ARB",
        "OP",
        "SUI",
        "TIA",
        "SEI",
        "TON",
        "INJ",
        "KAS",
        "FET",
        "WIF",
        "BONK",
        "PEPE",
        "SHIB",
    ]
)


class RLSignalBridge:
    """Консультирующий доступ к RL-сигналам (read-only)."""

    def __init__(self, model_file: Path | None = None):
        self.model_file = Path(model_file or MODEL_FILE)
        self._policy = None
        self._model_available = self.model_file.exists()
        self.asset_names = ASSET_ORDER_DEFAULT

    # ---- модель ----
    def _load_policy(self):
        if self._policy is not None:
            return self._policy
        if not self._model_available:
            return None
        try:
            import torch
            import torch.nn as nn

            # поддерживаем обе архитектуры: MLP (v3) и LSTM (v4)
            class LSTMPolicy(nn.Module):
                def __init__(self, obs_dim, act_dim=3, hidden=128, seq=10):
                    super().__init__()
                    self.seq = seq
                    self.static_dim = obs_dim - seq
                    self.lstm = nn.LSTM(1, hidden // 2, batch_first=True)
                    self.fc_pre = nn.Linear(self.static_dim + hidden // 2, hidden)
                    self.fc1 = nn.Linear(hidden, hidden)
                    self.mean = nn.Linear(hidden, act_dim)
                    self.logstd = nn.Parameter(torch.zeros(act_dim))
                    self.value = nn.Linear(hidden, 1)

                def forward(self, x):
                    seq_part = x[:, : self.seq].unsqueeze(-1)
                    lstm_out, _ = self.lstm(seq_part)
                    lstm_last = lstm_out[:, -1, :]
                    static = x[:, self.seq :]
                    h = torch.cat([lstm_last, static], dim=-1)
                    h = torch.relu(self.fc_pre(h))
                    h = torch.relu(self.fc1(h))
                    return self.mean(h), self.logstd.exp(), self.value(h)

            class MLPPolicy(nn.Module):
                def __init__(self, obs_dim, act_dim=3, hidden=128):
                    super().__init__()
                    self.fc_pre = nn.Linear(obs_dim, hidden)
                    self.fc1 = nn.Linear(hidden, hidden)
                    self.fc2 = nn.Linear(hidden, hidden)
                    self.mean = nn.Linear(hidden, act_dim)
                    self.logstd = nn.Parameter(torch.zeros(act_dim))
                    self.value = nn.Linear(hidden, 1)

                def forward(self, x):
                    x = torch.relu(self.fc_pre(x))
                    x = torch.relu(self.fc1(x))
                    x = torch.relu(self.fc2(x))
                    return self.mean(x), self.logstd.exp(), self.value(x)

            ckpt = torch.load(self.model_file, map_location="cpu")
            sd = ckpt.get("policy", ckpt)
            self.asset_names = sorted(ckpt.get("assets") or ASSET_ORDER_DEFAULT)
            # определяем архитектуру по наличию lstm-слоя
            if "lstm.weight_ih_l0" in sd:
                w = sd["fc_pre.weight"]
                static_dim = w.shape[1]
                hidden = w.shape[0]
                seq = 10
                obs_dim = seq + (static_dim - hidden // 2)
                self._obs_dim = obs_dim
                net = LSTMPolicy(obs_dim, hidden=hidden, seq=seq)
                net.load_state_dict(sd)
                self._policy = net
                self._is_lstm = True
                print(
                    f"{LOG_TAG} LSTM-PPO {MODEL_FILE.name} загружена (obs_dim={obs_dim})"
                )
            else:
                w = sd["fc_pre.weight"]
                obs_dim = w.shape[1]
                self._obs_dim = obs_dim
                net = MLPPolicy(obs_dim)
                net.load_state_dict(sd)
                self._policy = net
                self._is_lstm = False
                print(
                    f"{LOG_TAG} MLP-PPO {MODEL_FILE.name} загружена (obs_dim={obs_dim})"
                )
            net.eval()
        except Exception as e:
            print(f"{LOG_TAG} [WARN] Ошибка загрузки PPO-модели: {e}")
            self._policy = None
        return self._policy

    @property
    def available(self) -> bool:
        return self._model_available and self._load_policy() is not None

    # ---- данные ----
    def _fetch_binance(self, sym: str, interval: str = "1h", limit: int = 120) -> list:
        url = (
            f"https://api.binance.com/api/v3/klines?symbol={sym}"
            f"&interval={interval}&limit={limit}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Octopus-RL/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        return [
            [int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])]
            for x in d
        ]

    def _make_obs(
        self, rows: list, asset_name: str | None = None, window: int = 10
    ) -> list | None:
        import numpy as np

        if len(rows) < window + 1:
            return None
        closes = [r[4] for r in rows]
        vols = [r[5] for r in rows]
        n = len(closes)
        returns = [0.0]
        for i in range(1, n):
            returns.append(closes[i] / closes[i - 1] - 1.0)

        def mom(period):
            m = [0.0] * n
            for i in range(period, n):
                m[i] = closes[i] / closes[i - period] - 1.0
            return m

        mom5 = mom(5)
        mom12 = mom(12)
        # vol_ratio: volume / rolling(10)-mean — признак #3 среды обучения v8.
        # (Раньше здесь был vol_chg — несоответствие обучению: модель видела
        #  другой 3-й статический признак.)
        vol_ratio = [0.0] * n
        for i in range(n):
            lo = max(0, i - 9)
            vol_ratio[i] = vols[i] / ((sum(vols[lo : i + 1]) / (i - lo + 1)) + 1e-9)
        # vol_norm: rolling(10) std возвратов / среднее по ряду
        vol_arr = [0.01] * n
        for i in range(1, n):
            w = returns[max(0, i - 10) : i]
            vol_arr[i] = float(np.std(w)) if len(w) > 1 else 0.01
        vmean = float(np.mean(vol_arr)) or 0.01
        rets_w = returns[-window:]
        last = n - 1
        base = np.concatenate(
            [rets_w, [mom5[last], mom12[last], vol_ratio[last], vol_arr[last] / vmean]]
        ).astype(np.float32)
        exp = self._obs_dim
        if base.shape[0] == exp:
            return base
        # мультиактив-модель: base (window+4) + onehot (n_assets)
        if exp > base.shape[0]:
            n_assets = exp - base.shape[0]
            asset_names = getattr(self, "asset_names", ASSET_ORDER_DEFAULT)
            if asset_name is None or asset_name not in asset_names:
                # Актив не из обучающего универсума — честно сообщаем «нет сигнала»
                # вместо того, чтобы подставлять чужой onehot-индекс.
                return None
            onehot = np.zeros(n_assets, dtype=np.float32)
            onehot[asset_names.index(asset_name)] = 1.0
            obs = np.concatenate([base, onehot]).astype(np.float32)
            if obs.shape[0] == exp:
                return obs
        return None

    # ---- предсказание ----
    def predict_symbol(
        self, binance_symbol: str, asset_name: str | None = None
    ) -> dict | None:
        policy = self._load_policy()
        if policy is None:
            return None
        try:
            rows = self._fetch_binance(binance_symbol)
            obs = self._make_obs(rows, asset_name)
            if obs is None:
                return None
            import torch

            with torch.no_grad():
                o_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
                mean, _, _ = policy(o_t)
                act = mean[0][0].item()
                # В обучении (kg_v8) действие clamp(-1,1) до конвертации в
                # дискрету {0,1,2}; без clamp mean может выйти за [-1,1] и дать
                # недопустимую позицию (например, -0.5).
                act = max(-1.0, min(1.0, act))
                pos = int((act + 1) / 2 * 2) / 2.0  # 0, 0.5, 1
            return {
                "symbol": binance_symbol,
                "ok": True,
                "position": pos,
                "raw_action": round(act, 4),
                "direction": "LONG" if pos > 0.5 else ("FLAT" if pos == 0 else "HALF"),
                "generated_at": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            return {"symbol": binance_symbol, "ok": False, "error": str(e)[:120]}

    def run_all(self, symbols: dict | None = None) -> dict:
        """Предсказать позиции для набора активов. symbols: {name: binance_sym}"""
        if not self.available:
            return {"model_available": False, "signals": [], "generated_at": None}
        if symbols is None:
            symbols = {
                "BTC": "BTCUSDT",
                "ETH": "ETHUSDT",
                "SOL": "SOLUSDT",
                "BNB": "BNBUSDT",
                "XRP": "XRPUSDT",
                "ADA": "ADAUSDT",
                "DOGE": "DOGEUSDT",
                "LINK": "LINKUSDT",
                "DOT": "DOTUSDT",
                "POL": "POLUSDT",
            }
        signals = []
        for name, sym in symbols.items():
            try:
                res = self.predict_symbol(sym, asset_name=name)
                if res:
                    res["asset"] = name
                    signals.append(res)
                time.sleep(0.3)
            except Exception as e:
                signals.append(
                    {"asset": name, "symbol": sym, "ok": False, "error": str(e)[:80]}
                )
        return {
            "engine": "quant_rl_ppo",
            "generated_at": datetime.now(UTC).isoformat(),
            "model_available": True,
            "signals": signals,
        }

    def save(self, out_file: Path | None = None) -> Path:
        data = self.run_all()
        f = Path(out_file or OUT_FILE)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{LOG_TAG} Сохранено сигналов: {f} ({len(data.get('signals', []))})")
        return f

    def summary(self) -> dict:
        data = self.run_all()
        longs = [
            s["asset"]
            for s in data["signals"]
            if s.get("ok") and s.get("position", 0) > 0.5
        ]
        halves = [
            s["asset"]
            for s in data["signals"]
            if s.get("ok") and 0 < s.get("position", 0) <= 0.5
        ]
        return {
            "model_available": data.get("model_available", False),
            "generated_at": data.get("generated_at"),
            "total": len(data["signals"]),
            "long": longs,
            "half": halves,
        }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="сохранить rl_signals.json")
    args = ap.parse_args()
    b = RLSignalBridge()
    if args.save:
        b.save()
    else:
        print(json.dumps(b.summary(), indent=2, ensure_ascii=False))
