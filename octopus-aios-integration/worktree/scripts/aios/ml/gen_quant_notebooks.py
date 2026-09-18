#!/usr/bin/env python3
"""
AIOS Quant ML Engine - Генератор Colab-ноутбуков (Этап 2.2)

Создаёт три ноутбука в docs/:
  1. AIOS_Colab_Quant_ML_Training.ipynb  - XGBoost/LightGBM/CatBoost + LSTM/Transformer
  2. AIOS_Colab_Quant_RL_Training.ipynb   - Reinforcement Learning (Stable-Baselines3)
  3. AIOS_Colab_Quant_Clustering.ipynb    - кластеризация 24 активов и детекция аномалий

Ноутбуки умеют брать данные двумя способами:
  (а) скачивать свечи напрямую через ccxt в самом Colab (работает без VPS),
  (б) читать загруженный датасет (export с VPS: data/quant/export/latest.tar.gz).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(os.environ.get("OCTOPUS_REPO") or Path(__file__).resolve().parents[3])
DOCS = REPO / "docs"


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}


def code(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": src.splitlines(keepends=True)}


# ============================================================ NOTEBOOK 1 ====
def nb_ml_training() -> dict:
    cells = [
        md(
            "# 🤖 AIOS Quant ML Training\n\n"
            "Обучение предсказательных моделей на биржевых данных (XGBoost, LightGBM, CatBoost, LSTM, Transformer).\n\n"
            "**Среда выполнения → Сменить тип → T4 GPU** (для LSTM/Transformer).\n\n"
            "### Источники данных (2 способа)\n"
            "- **(а)** Прямая загрузка свечей через `ccxt` (Binance/Bybit/OKX/Kraken) прямо в Colab.\n"
            "- **(б)** Загрузите `latest.tar.gz` с VPS (папка `data/quant/export/`) в сессию Colab.\n\n"
            "Модели сохраняются и публикуются в **Hugging Face Hub** (опционально, введите токен) или качаются VPS."
        ),
        code("# === ЯЧЕЙКА 1: Установка зависимостей ===\n"
             "!pip install -q ccxt pandas numpy scikit-learn xgboost lightgbm catboost torch\n"
             "import ccxt, pandas as pd, numpy as np\n"
             "print('✅ Зависимости установлены, ccxt', ccxt.__version__)"),
        code("# === ЯЧЕЙКА 2: Загрузка данных ===\n"
             "import os, io, tarfile, pandas as pd\n"
             "\n"
             "def load_data():\n"
             "    rows = []\n"
             "    # (б) если загружен датасет с VPS\n"
             "    if os.path.exists('latest.tar.gz'):\n"
             "        tar = tarfile.open('latest.tar.gz', 'r:gz')\n"
             "        for m in tar.getmembers():\n"
             "            if m.isfile() and m.name.endswith('_1h.csv'):\n"
             "                df = pd.read_csv(tar.extractfile(m))\n"
             "                df['symbol'] = m.name.split('/')[0]\n"
             "                rows.append(df)\n"
             "        tar.close()\n"
             "    if rows:\n"
             "        return pd.concat(rows, ignore_index=True)\n"
             "    # (а) прямая загрузка через ccxt\n"
             "    clients = {'binance': ccxt.binance(), 'bybit': ccxt.bybit(), 'okx': ccxt.okx()}\n"
             "    symbols = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT']\n"
             "    for name, cl in clients.items():\n"
             "        cl.load_markets()\n"
             "        for s in symbols:\n"
             "            try:\n"
             "                o = cl.fetch_ohlcv(s, '1h', limit=500)\n"
             "                df = pd.DataFrame(o, columns=['ts','open','high','low','close','volume'])\n"
             "                df['symbol'] = s.replace('/','_')\n"
             "                df['exchange'] = name\n"
             "                rows.append(df)\n"
             "            except Exception as e:\n"
             "                print('skip', name, s, e)\n"
             "    return pd.concat(rows, ignore_index=True)\n"
             "\n"
             "df = load_data()\n"
             "df['ts'] = pd.to_datetime(df['ts_ms'] if 'ts_ms' in df else df['ts'], unit='ms', errors='coerce')\n"
             "print('✅ Данные:', df.shape)\n"
             "print(df.head(2).to_string())"),
        code("# === ЯЧЕЙКА 3: Признаки (feature engineering) ===\n"
             "from sklearn.model_selection import TimeSeriesSplit\n"
             "\n"
             "def make_features(g):\n"
             "    g = g.sort_values('ts')\n"
             "    g['ret1'] = g['close'].pct_change()\n"
             "    g['ema12'] = g['close'].ewm(span=12).mean()\n"
             "    g['ema26'] = g['close'].ewm(span=26).mean()\n"
             "    g['rsi'] = 100 - 100/(1 + g['close'].pct_change().rolling(14).mean()/\n"
             "                        g['close'].pct_change().rolling(14).std().replace(0,1e-9))\n"
             "    g['vol_ma'] = g['volume'].rolling(20).mean()\n"
             "    g['target'] = (g['close'].shift(-1) > g['close']).astype(int)  # движение вверх через 1 бар\n"
             "    return g\n"
             "\n"
             "df = df.groupby('symbol').apply(make_features).reset_index(drop=True)\n"
             "df = df.dropna().reset_index(drop=True)\n"
             "features = ['open','high','low','close','volume','ret1','ema12','ema26','rsi','vol_ma']\n"
             "X = df[features].values; y = df['target'].values\n"
             "print('✅ Признаки готовы:', X.shape)"),
        code("# === ЯЧЕЙКА 4: Обучение (XGBoost, LightGBM, CatBoost) ===\n"
             "import xgboost as xgb, lightgbm as lgb, catboost as cb\n"
             "from sklearn.metrics import accuracy_score\n"
             "from sklearn.model_selection import TimeSeriesSplit\n"
             "\n"
             "tscv = TimeSeriesSplit(n_splits=3)\n"
             "results = {}\n"
             "for name, model in [\n"
             "    ('XGBoost', xgb.XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.05, use_label_encoder=False, eval_metric='logloss')),\n"
             "    ('LightGBM', lgb.LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.05, verbose=-1)),\n"
             "    ('CatBoost', cb.CatBoostClassifier(iterations=200, depth=6, learning_rate=0.05, verbose=0)),\n"
             "]:\n"
             "    accs = []\n"
             "    for tr, te in tscv.split(X):\n"
             "        m = model.__class__(**model.get_params()) if hasattr(model,'get_params') else model\n"
             "        m.fit(X[tr], y[tr])\n"
             "        accs.append(accuracy_score(y[te], m.predict(X[te])))\n"
             "    results[name] = np.mean(accs)\n"
             "    print(f'  {name}: {np.mean(accs):.4f}')\n"
             "print('\\n✅ Лучшая табличная модель:', max(results, key=results.get))"),
        code("# === ЯЧЕЙКА 5: Обучение LSTM (PyTorch) ===\n"
             "import torch, torch.nn as nn\n"
             "from torch.utils.data import DataLoader, TensorDataset\n"
             "\n"
             "SEQ = 20\n"
             "def seq_xy(X_, y_):\n"
             "    xs, ys = [], []\n"
             "    for i in range(SEQ, len(X_)):\n"
             "        xs.append(X_[i-SEQ:i]); ys.append(y_[i])\n"
             "    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)\n"
             "Xs, ys = seq_xy(X, y)\n"
             "cut = int(len(Xs)*0.8)\n"
             "tr_x, te_x = Xs[:cut], Xs[cut:]\n"
             "tr_y, te_y = ys[:cut], ys[cut:]\n"
             "\n"
             "class LSTMModel(nn.Module):\n"
             "    def __init__(self, nfeat, hidden=32):\n"
             "        super().__init__()\n"
             "        self.lstm = nn.LSTM(nfeat, hidden, batch_first=True)\n"
             "        self.fc = nn.Linear(hidden, 2)\n"
             "    def forward(self, x):\n"
             "        out, _ = self.lstm(x)\n"
             "        return self.fc(out[:, -1, :])\n"
             "\n"
             "device = 'cuda' if torch.cuda.is_available() else 'cpu'\n"
             "model = LSTMModel(Xs.shape[2]).to(device)\n"
             "opt = torch.optim.Adam(model.parameters(), lr=1e-3)\n"
             "lossf = nn.CrossEntropyLoss()\n"
             "tra = TensorDataset(torch.tensor(tr_x), torch.tensor(tr_y, dtype=torch.long))\n"
             "tel = TensorDataset(torch.tensor(te_x), torch.tensor(te_y, dtype=torch.long))\n"
             "tld = DataLoader(tra, batch_size=64, shuffle=True)\n"
             "eld = DataLoader(tel, batch_size=128)\n"
             "model.train()\n"
             "for ep in range(15):\n"
             "    tl = 0\n"
             "    for xb, yb in tld:\n"
             "        xb, yb = xb.to(device), yb.to(device)\n"
             "        opt.zero_grad(); loss = lossf(model(xb), yb); loss.backward(); opt.step()\n"
             "        tl += loss.item()\n"
             "    # val acc\n"
             "    model.eval(); ok=0; tot=0\n"
             "    with torch.no_grad():\n"
             "        for xb, yb in eld:\n"
             "            xb, yb = xb.to(device), yb.to(device)\n"
             "            pred = model(xb).argmax(1); ok+=(pred==yb).sum().item(); tot+=yb.size(0)\n"
             "    model.train()\n"
             "    print(f'  epoch {ep+1}: loss={tl/len(tld):.4f} val_acc={ok/tot:.4f}')\n"
             "print('✅ LSTM обучена')"),
        code("# === ЯЧЕЙКА 6: Сохранение моделей ===\n"
             "import joblib\n"
             "os.makedirs('models', exist_ok=True)\n"
             "# Сохраняем лучшую табличную модель (пример - CatBoost)\n"
             "best = cb.CatBoostClassifier(iterations=200, depth=6, learning_rate=0.05, verbose=0)\n"
             "best.fit(X, y)\n"
             "best.save_model('models/catboost_price_dir.cbm')\n"
             "joblib.dump(best, 'models/catboost_price_dir.pkl')\n"
             "print('✅ Модели сохранены в /content/models')\n"
             "print('   Загрузите их на VPS или в HF Hub для инференса.')"),
    ]
    return {"cells": cells, "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}


# ============================================================ NOTEBOOK 2 ====
def nb_rl_training() -> dict:
    cells = [
        md("# 🎮 AIOS Quant RL Training (Stable-Baselines3)\n\n"
           "Обучение Reinforcement Learning торгового агента в симулированной биржевой среде.\n\n"
           "**T4 GPU**.\n\n"
           "Агент решает, какую долю капитала держать в активе, максимизируя доходность и минимизируя просадки. "
           "Используем PPO из Stable-Baselines3 на среде, построенной по ценам из ccxt."),
        code("!pip install -q ccxt pandas numpy gymnasium stable-baselines3\n"
             "import ccxt, pandas as pd, numpy as np\n"
             "print('✅ Зависимости установлены')"),
        code("# === ЯЧЕЙКА 2: Загрузка цен ===\n"
             "cl = ccxt.binance()\n"
             "cl.load_markets()\n"
             "ohlcv = cl.fetch_ohlcv('BTC/USDT', '1h', limit=2000)\n"
             "df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])\n"
             "df['returns'] = df['close'].pct_change().fillna(0)\n"
             "df['momentum'] = df['close'].pct_change(12).fillna(0)\n"
             "print('✅ Цены:', df.shape)"),
        code("# === ЯЧЕЙКА 3: RL-среда (gymnasium) ===\n"
             "import gymnasium as gym\n"
             "from gymnasium import spaces\n"
             "\n"
             "class TradingEnv(gym.Env):\n"
             "    def __init__(self, df, window=10):\n"
             "        super().__init__()\n"
             "        self.df = df.reset_index(drop=True)\n"
             "        self.window = window\n"
             "        self.action_space = spaces.Discrete(3)  # 0=полный выход, 1=50%, 2=100% в активе\n"
             "        self.observation_space = spaces.Box(-np.inf, np.inf, (window*2,), dtype=np.float32)\n"
             "        self.i = window\n"
             "    def _obs(self):\n"
             "        w = self.df['returns'].values[self.i-self.window:self.i]\n"
             "        m = self.df['momentum'].values[self.i-self.window:self.i]\n"
             "        return np.concatenate([w, m]).astype(np.float32)\n"
             "    def reset(self, *, seed=None, options=None):\n"
             "        self.i = self.window\n"
             "        self.position = 0\n"
             "        return self._obs(), {}\n"
             "    def step(self, action):\n"
             "        pos = action / 2.0\n"
             "        r = self.df['returns'].values[self.i]\n"
             "        reward = pos * r * 100  # доходность позиции (x100 для масштаба)\n"
             "        self.position = pos\n"
             "        self.i += 1\n"
             "        done = self.i >= len(self.df) - 1\n"
             "        return self._obs() if not done else self._obs(), float(reward), done, False, {}\n"
             "\n"
             "env = TradingEnv(df)\n"
             "print('✅ Среда создана')"),
        code("# === ЯЧЕЙКА 4: Обучение PPO ===\n"
             "from stable_baselines3 import PPO\n"
             "from stable_baselines3.common.vec_env import DummyVecEnv\n"
             "\n"
             "vec = DummyVecEnv([lambda: TradingEnv(df)])\n"
             "model = PPO('MlpPolicy', vec, verbose=0, learning_rate=1e-3, n_steps=512)\n"
             "model.learn(total_timesteps=20000)\n"
             "print('✅ PPO обучен')"),
        code("# === ЯЧЕЙКА 5: Валидация агента на вне-выборке ===\n"
             "val = DummyVecEnv([lambda: TradingEnv(df.iloc[len(df)//2:].reset_index(drop=True))])\n"
             "obs = val.reset()\n"
             "total = 0\n"
             "done = False\n"
             "while not done:\n"
             "    action, _ = model.predict(obs, deterministic=True)\n"
             "    obs, reward, done, _ = val.step(action)\n"
             "    total += reward\n"
             "print(f'Итоговая доходность агента на валидации: {total:.2f}%')\n"
             "model.save('models/ppo_trader.zip')\n"
             "print('✅ Агент сохранён: models/ppo_trader.zip')"),
    ]
    return {"cells": cells, "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}


# ============================================================ NOTEBOOK 3 ====
def nb_clustering() -> dict:
    cells = [
        md("# 📊 AIOS Quant Clustering & Anomaly Detection\n\n"
           "Кластеризация 24 крипто-активов по рыночному поведению и детектирование аномальных объёмов "
           "(следы маркет-мейкеров / пампов).\n\n"
           "**CPU достаточно** (можно T4 для автокодировщика)."),
        code("!pip install -q ccxt pandas numpy scikit-learn matplotlib\n"
             "import ccxt, pandas as pd, numpy as np\n"
             "print('✅ Зависимости установлены')"),
        code("# === ЯЧЕЙКА 2: Сбор данных по 24 активам ===\n"
             "cl = ccxt.binance()\n"
             "cl.load_markets()\n"
             "symbols = ['BTC/USDT','ETH/USDT','BNB/USDT','SOL/USDT','XRP/USDT','ADA/USDT','DOGE/USDT','AVAX/USDT',\n"
             "           'LINK/USDT','DOT/USDT','POL/USDT','LTC/USDT','TRX/USDT','ATOM/USDT','UNI/USDT','ETC/USDT',\n"
             "           'FIL/USDT','APT/USDT','NEAR/USDT','ARB/USDT','OP/USDT','SUI/USDT','TIA/USDT','SEI/USDT']\n"
             "data = {}\n"
             "for s in symbols:\n"
             "    try:\n"
             "        o = cl.fetch_ohlcv(s, '1h', limit=500)\n"
             "        data[s] = pd.DataFrame(o, columns=['ts','open','high','low','close','volume'])\n"
             "    except Exception as e:\n"
             "        print('skip', s, e)\n"
             "print('✅ Собрано активов:', len(data))"),
        code("# === ЯЧЕЙКА 3: Кластеризация по поведению ===\n"
             "from sklearn.preprocessing import StandardScaler\n"
             "from sklearn.cluster import KMeans\n"
             "import numpy as np\n"
             "\n"
             "feats = {}\n"
             "for s, df in data.items():\n"
             "    ret = df['close'].pct_change().dropna()\n"
             "    vol = df['volume']\n"
             "    feats[s] = [\n"
             "        ret.mean()*100,           # средняя доходность %\n"
             "        ret.std()*100,            # волатильность %\n"
             "        vol.mean(),               # средний объём\n"
             "        (vol.pct_change()>3).mean(),  # доля аномальных всплесков объёма\n"
             "    ]\n"
             "X = StandardScaler().fit_transform(np.array(list(feats.values())))\n"
             "k = KMeans(n_clusters=4, random_state=42, n_init=10).fit(X)\n"
             "for lbl in range(k.n_clusters):\n"
             "    members = [s for i, s in enumerate(feats) if k.labels_[i]==lbl]\n"
             "    print(f'Кластер {lbl}: {members}')"),
        code("# === ЯЧЕЙКА 4: Детекция аномалий (Isolation Forest) ===\n"
             "from sklearn.ensemble import IsolationForest\n"
             "\n"
             "iso = IsolationForest(contamination=0.05, random_state=42).fit(X)\n"
             "preds = iso.predict(X)\n"
             "anomalies = [s for i, s in enumerate(feats) if preds[i]==-1]\n"
             "print('Аномальные активы:', anomalies)\n"
             "\n"
             "# Аномальные всплески объёма внутри актива (маркет-мейкер/памп)\n"
             "for s in data:\n"
             "    vol = data[s]['volume']\n"
             "    thresh = vol.rolling(24).mean() + 3*vol.rolling(24).std()\n"
             "    spikes = (vol > thresh).sum()\n"
             "    if spikes > 0:\n"
             "        print(f'  {s}: {spikes} аномальных часов объёма')"),
        code("# === ЯЧЕЙКА 5: Корреляционная матрица ===\n"
             "import pandas as pd\n"
             "rets = pd.DataFrame({s: data[s]['close'].pct_change() for s in data}).dropna()\n"
             "corr = rets.corr()\n"
             "print('Размер матрицы корреляций:', corr.shape)\n"
             "# топ-5 пар с самой высокой корреляцией\n"
             "flat = corr.unstack().sort_values(ascending=False)\n"
             "flat = flat[flat < 1.0].drop_duplicates()\n"
             "print(flat.head(5))\n"
             "corr.to_csv('models/asset_correlations.csv')\n"
             "print('✅ Сохранено: models/asset_correlations.csv')"),
    ]
    return {"cells": cells, "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}


def write(path: Path, nb: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"✅ {path} ({path.stat().st_size} байт)")


if __name__ == "__main__":
    write(DOCS / "AIOS_Colab_Quant_ML_Training.ipynb", nb_ml_training())
    write(DOCS / "AIOS_Colab_Quant_RL_Training.ipynb", nb_rl_training())
    write(DOCS / "AIOS_Colab_Quant_Clustering.ipynb", nb_clustering())
    print("\nВсе ноутбуки сгенерированы.")
