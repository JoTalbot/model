#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""
AIOS Quant ML - генератор улучшенного ноутбука Quant ML Training v2.

Отличия от v1:
  - Загрузка данных через прямые REST API бирж с fallback и retry (устойчиво,
    не зависит от ccxt-сетевых сбоев).
  - CPU-friendly: работа и без GPU.
  - Сохранение моделей с выгрузкой в R2 (если ключи в окружении) и локально.
"""
from __future__ import annotations

import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs"


def md(s): return {"cell_type":"markdown","metadata":{},"source":s.splitlines(keepends=True)}
def code(s): return {"cell_type":"code","execution_count":None,"metadata":{},"outputs":[],"source":s.splitlines(keepends=True)}
def meta(): return {"colab":{"provenance":[]},"kernelspec":{"name":"python3","display_name":"Python 3"},"language_info":{"name":"python"}}


LOAD_DATA = r"""# === ЯЧЕЙКА 2: Загрузка данных (устойчивая, REST API бирж) ===
import os, io, time, tarfile, json, requests, pandas as pd, numpy as np

def _retry(fn, tries=3, delay=2):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries-1:
                raise
            time.sleep(delay)

def fetch_binance(sym, interval='1h', limit=500):
    url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
    d=_retry(lambda: requests.get(url,timeout=20).json())
    return [[int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])] for x in d]

def fetch_bybit(sym, interval='60', limit=500):
    # bybit interval: 60=1h
    url=f"https://api.bybit.com/v5/market/kline?category=spot&symbol={sym}&interval={interval}&limit={limit}"
    d=_retry(lambda: requests.get(url,timeout=20).json())
    return [[int(float(x[0])),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])] for x in d.get('result',{}).get('list',[])]

def fetch_okx(sym, bar='1H', limit=500):
    url=f"https://www.okx.com/api/v5/market/candles?instId={sym}&bar={bar}&limit={limit}"
    d=_retry(lambda: requests.get(url,timeout=20).json())
    # okx returns reversed
    rows=[]
    for x in d.get('data',[]):
        rows.append([int(float(x[0])),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])])
    rows.sort(key=lambda r:r[0])
    return rows

def fetch_kraken(sym, interval=60, limit=500):
    url=f"https://api.kraken.com/0/public/OHLC?pair={sym}&interval={interval}"
    d=_retry(lambda: requests.get(url,timeout=20).json())
    rows=[]
    for r in (d.get('result') or {}).values():
        if isinstance(r,list):
            for x in r:
                rows.append([int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])])
            break
    return rows[:limit]

# символы: base/quote для каждой биржи
SYMS = {
  'binance': ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT'],
  'bybit':   ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT'],
  'okx':     ['BTC-USDT','ETH-USDT','SOL-USDT','BNB-USDT'],
  'kraken':  ['XXBTZUSD','XETHZUSD','SOLUSD','XMRUSD'],
}
FETCHERS = {'binance':fetch_binance,'bybit':fetch_bybit,'okx':fetch_okx,'kraken':fetch_kraken}

def load_data():
    rows=[]
    # (б) загруженный датасет с VPS
    if os.path.exists('latest.tar.gz'):
        tar=tarfile.open('latest.tar.gz','r:gz')
        for m in tar.getmembers():
            if m.isfile() and m.name.endswith('_1h.csv'):
                df=pd.read_csv(tar.extractfile(m)); df['symbol']=m.name.split('/')[0]; rows.append(df)
        tar.close()
        if rows: return pd.concat(rows,ignore_index=True)
    # (а) прямой REST с fallback
    for ex, names in SYMS.items():
        fn=FETCHERS[ex]
        for n in names:
            try:
                o=fn(n)
                df=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
                df['symbol']=n.replace('-','_'); df['exchange']=ex
                rows.append(df)
                print(f'  {ex}/{n}: {len(o)}')
            except Exception as e:
                print(f'  skip {ex}/{n}: {e}')
            time.sleep(0.3)
    return pd.concat(rows,ignore_index=True)

df=load_data()
df['ts']=pd.to_datetime(df['ts_ms'] if 'ts_ms' in df else df['ts'], unit='ms', errors='coerce')
print('✅ Данные:', df.shape)
print(df.head(2).to_string())
"""


SAVE_DATA = r"""# === ЯЧЕЙКА 6: Сохранение моделей (+ выгрузка в R2) ===
import joblib, os, zipfile
os.makedirs('models', exist_ok=True)
# Сохраняем лучшую табличную модель (CatBoost) - на CPU
best = cb.CatBoostClassifier(iterations=200, depth=6, learning_rate=0.05, verbose=0)
best.fit(X, y)
best.save_model('models/catboost_price_dir.cbm')
joblib.dump(best, 'models/catboost_price_dir.pkl')
# LSTM
try:
    torch.save(model.state_dict(), 'models/lstm_price_dir.pt')
except Exception:
    pass
print('✅ Модели сохранены в /content/models')

# Выгрузка в Cloudflare R2 (если ключи доступны в окружении)
try:
    import boto3
    ak = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID')
    sk = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
    ep = os.environ.get('CLOUDFLARE_R2_ENDPOINT')
    if ak and sk and ep:
        s3 = boto3.client('s3', endpoint_url=ep, aws_access_key_id=ak, aws_secret_access_key=sk, region_name='auto')
        bucket = os.environ.get('CLOUDFLARE_R2_BUCKET','aios-colab-farm')
        for f in ['catboost_price_dir.cbm','catboost_price_dir.pkl','lstm_price_dir.pt']:
            p = os.path.join('models', f)
            if os.path.exists(p):
                s3.upload_file(p, bucket, 'models/'+f)
                print(f'⬆️ Загружено в R2: models/{f}')
    else:
        print('ℹ️ R2-ключи не заданы в окружении - модели только локально')
except Exception as e:
    print(f'⚠️ R2-выгрузка: {e}')
print('Модели готовы. Для переноса на VPS: загрузите папку /content/models')
"""


def nb():
    cells = [
        md(
            "# 🤖 AIOS Quant ML Training v2\n\n"
            "Обучение предсказательных моделей на биржевых данных (XGBoost, LightGBM, CatBoost, LSTM).\n\n"
            "**Работает на CPU и GPU.** Источники: прямые REST API Binance/Bybit/OKX/Kraken с fallback."
        ),
        code("!pip install -q requests pandas numpy scikit-learn xgboost lightgbm catboost torch boto3\n"
             "import requests, pandas as pd, numpy as np\n"
             "print('✅ Зависимости установлены')"),
        code(LOAD_DATA),
        code("# === ЯЧЕЙКА 3: Признаки (feature engineering) ===\n"
             "def make_features(g):\n"
             "    g = g.sort_values('ts')\n"
             "    g['ret1'] = g['close'].pct_change()\n"
             "    g['ema12'] = g['close'].ewm(span=12).mean()\n"
             "    g['ema26'] = g['close'].ewm(span=26).mean()\n"
             "    g['rsi'] = 100 - 100/(1 + g['close'].pct_change().rolling(14).mean()/\n"
             "                        g['close'].pct_change().rolling(14).std().replace(0,1e-9))\n"
             "    g['vol_ma'] = g['volume'].rolling(20).mean()\n"
             "    g['target'] = (g['close'].shift(-1) > g['close']).astype(int)\n"
             "    return g\n"
             "\n"
             "df = df.groupby('symbol').apply(make_features).reset_index(drop=True)\n"
             "df = df.dropna().reset_index(drop=True)\n"
             "features = ['open','high','low','close','volume','ret1','ema12','ema26','rsi','vol_ma']\n"
             "X = df[features].values; y = df['target'].values\n"
             "print('✅ Признаки готовы:', X.shape, '| положительных:', y.sum())"),
        code("# === ЯЧЕЙКА 4: Обучение (XGBoost, LightGBM, CatBoost) ===\n"
             "import xgboost as xgb, lightgbm as lgb, catboost as cb\n"
             "from sklearn.metrics import accuracy_score\n"
             "from sklearn.model_selection import TimeSeriesSplit\n"
             "\n"
             "tscv = TimeSeriesSplit(n_splits=3)\n"
             "results = {}\n"
             "for name, model in [\n"
             "    ('XGBoost', xgb.XGBClassifier(n_estimators=150, max_depth=6, learning_rate=0.05, use_label_encoder=False, eval_metric='logloss', n_jobs=-1)),\n"
             "    ('LightGBM', lgb.LGBMClassifier(n_estimators=150, max_depth=6, learning_rate=0.05, verbose=-1, n_jobs=-1)),\n"
             "    ('CatBoost', cb.CatBoostClassifier(iterations=150, depth=6, learning_rate=0.05, verbose=0, thread_count=-1)),\n"
             "]:\n"
             "    accs = []\n"
             "    for tr, te in tscv.split(X):\n"
             "        m = model.__class__(**model.get_params()) if hasattr(model,'get_params') else model\n"
             "        m.fit(X[tr], y[tr])\n"
             "        accs.append(accuracy_score(y[te], m.predict(X[te])))\n"
             "    results[name] = np.mean(accs)\n"
             "    print(f'  {name}: {np.mean(accs):.4f}')\n"
             "print('\\n✅ Лучшая табличная модель:', max(results, key=results.get))"),
        code("# === ЯЧЕЙКА 5: Обучение LSTM (PyTorch, CPU/GPU) ===\n"
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
             "print('Устройство:', device)\n"
             "model = LSTMModel(Xs.shape[2]).to(device)\n"
             "opt = torch.optim.Adam(model.parameters(), lr=1e-3)\n"
             "lossf = nn.CrossEntropyLoss()\n"
             "tra = TensorDataset(torch.tensor(tr_x), torch.tensor(tr_y, dtype=torch.long))\n"
             "tel = TensorDataset(torch.tensor(te_x), torch.tensor(te_y, dtype=torch.long))\n"
             "tld = DataLoader(tra, batch_size=64, shuffle=True)\n"
             "eld = DataLoader(tel, batch_size=128)\n"
             "model.train()\n"
             "for ep in range(8):\n"
             "    tl = 0\n"
             "    for xb, yb in tld:\n"
             "        xb, yb = xb.to(device), yb.to(device)\n"
             "        opt.zero_grad(); loss = lossf(model(xb), yb); loss.backward(); opt.step()\n"
             "        tl += loss.item()\n"
             "    model.eval(); ok=0; tot=0\n"
             "    with torch.no_grad():\n"
             "        for xb, yb in eld:\n"
             "            xb, yb = xb.to(device), yb.to(device)\n"
             "            pred = model(xb).argmax(1); ok+=(pred==yb).sum().item(); tot+=yb.size(0)\n"
             "    model.train()\n"
             "    print(f'  epoch {ep+1}: loss={tl/len(tld):.4f} val_acc={ok/tot:.4f}')\n"
             "print('✅ LSTM обучена')"),
        code(SAVE_DATA),
    ]
    return {"cells": cells, "metadata": meta(), "nbformat": 4, "nbformat_minor": 0}


if __name__ == "__main__":
    p = DOCS / "AIOS_Colab_Quant_ML_Training.ipynb"
    p.write_text(json.dumps(nb(), indent=1), encoding="utf-8")
    print(f"✅ {p} ({p.stat().st_size} байт)")
