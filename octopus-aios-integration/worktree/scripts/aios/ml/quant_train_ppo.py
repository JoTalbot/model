#!/usr/bin/env python3
# REFERENCE ONLY (Wave 5, item 5): ported from AIOS clean-code-production.
# NOT imported by octopus code, NOT covered by CI.
# Reason: requires numpy/pandas/torch (not in prod venv); runs on ML hosts
"""Train LSTM-PPO v9 exactly following data/kg_v8/aios-rl-v8.ipynb.

Differences from v8: asset universe uses POL instead of delisted MATIC
(same sorted 32-asset order everywhere), data comes from local binance 1h
CSVs (last 1000 bars per asset) instead of live fetch, and the run is on CPU.

Artifacts:
  - data/quant/models/ppo_v9.pt  ({"policy": state_dict, "assets": NAMES})
  - data/reports/ppo_v9_eval.json (validation vs current ppo_v8.pt)
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_DIR = REPO_ROOT / "data" / "quant"
MODELS_DIR = QUANT_DIR / "models"

torch.manual_seed(42)
np.random.seed(42)
random.seed(42)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("device:", device)


# ------------------------------------------------------------------ env ----
def build_assets(names: list[str], bars: int = 1000) -> dict:
    """Replicate v8 feature engineering on local binance CSVs."""
    assets = {}
    for name in names:
        path = QUANT_DIR / name / "binance" / f"{name}_1h.csv"
        if not path.exists():
            print("  missing", name)
            continue
        df = pd.read_csv(path)
        if len(df) < 200:
            print("  short", name, len(df))
            continue
        df = df.tail(bars).reset_index(drop=True)
        df["ret"] = df["close"].pct_change().fillna(0)
        df["mom5"] = df["close"].pct_change(5).fillna(0)
        df["mom12"] = df["close"].pct_change(12).fillna(0)
        df["vol_chg"] = df["volume"].pct_change().fillna(0)
        df["vol_ma"] = df["volume"].rolling(10).mean().fillna(df["volume"].mean())
        df["vol_ratio"] = df["volume"] / (df["vol_ma"] + 1e-9)
        df["ret_vol"] = df["ret"].rolling(10).std().fillna(0.01)
        df["vol_norm"] = df["ret_vol"] / (df["ret_vol"].mean() + 1e-9)
        assets[name] = df
    return assets


class MultiAssetEnv:
    """1:1 copy of the v8 training environment."""

    def __init__(self, assets, window=10, max_steps=300, commission=0.0005, risk_penalty=0.01):
        self.assets = assets
        self.names = sorted(assets.keys())
        self.window = window
        self.n_assets = len(self.names)
        self.n_feats = window + 4
        self.dim = self.n_feats + self.n_assets
        self.max_steps = max_steps
        self.commission = commission
        self.risk_penalty = risk_penalty
        self.step_count = 0
        self.pos = 0.0
        self.asset_idx = 0
        self.df = None
        self.i = 0

    def reset(self):
        self.asset_idx = np.random.randint(0, self.n_assets)
        self.df = self.assets[self.names[self.asset_idx]]
        self.i = self.window
        self.step_count = 0
        self.pos = 0.0
        return self._obs()

    def _obs(self):
        if self.i >= len(self.df):
            self.i = len(self.df) - 1
        rets = self.df["ret"].values[self.i - self.window:self.i]
        if len(rets) < self.window:
            rets = np.pad(rets, (self.window - len(rets), 0))
        mom5 = self.df["mom5"].values[self.i]
        mom12 = self.df["mom12"].values[self.i]
        vr = self.df["vol_ratio"].values[self.i]
        vn = self.df["vol_norm"].values[self.i]
        feats = np.concatenate([rets, [mom5, mom12, vr, vn]]).astype(np.float32)
        onehot = np.zeros(self.n_assets, dtype=np.float32)
        onehot[self.asset_idx] = 1.0
        return np.concatenate([feats, onehot]).astype(np.float32)

    def step(self, action):
        new_pos = action / 2.0
        cost = self.commission * abs(new_pos - self.pos)
        self.pos = new_pos
        r = self.df["ret"].values[self.i]
        reward = new_pos * r * 100.0 - cost * 100.0 - self.risk_penalty * new_pos * self.df["vol_norm"].values[self.i]
        self.i += 1
        self.step_count += 1
        done = (self.step_count >= self.max_steps) or (self.i >= len(self.df) - 1)
        if done:
            self.asset_idx = np.random.randint(0, self.n_assets)
            self.df = self.assets[self.names[self.asset_idx]]
            self.i = self.window
            self.step_count = 0
            self.pos = 0.0
        return self._obs(), float(reward), done, {}


# ---------------------------------------------------------------- model ----
class LSTMPolicy(nn.Module):
    """1:1 copy of the v8 LSTM policy."""

    def __init__(self, obs_dim, act_dim, hidden=128, seq=10):
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
        seq_part = x[:, :self.seq].unsqueeze(-1)
        lstm_out, _ = self.lstm(seq_part)
        lstm_last = lstm_out[:, -1, :]
        static = x[:, self.seq:]
        h = torch.cat([lstm_last, static], dim=-1)
        h = torch.relu(self.fc_pre(h))
        h = torch.relu(self.fc1(h))
        return self.mean(h), self.logstd.exp(), self.value(h)


def compute_gae(rewards, values, dones, gamma=0.99, lam=0.97):
    T = len(rewards)
    gaes = np.zeros(T)
    last_adv = 0.0
    last_val = 0.0
    for t in reversed(range(T)):
        if dones[t]:
            last_adv = 0.0
            last_val = 0.0
        delta = rewards[t] + gamma * last_val - values[t]
        gaes[t] = delta + gamma * lam * last_adv
        last_adv = gaes[t]
        last_val = values[t]
    return gaes


def rollout(policy, env, steps=800):
    obs_list, act_list, rew_list, val_list, don_list, logp_list = [], [], [], [], [], []
    obs = env.reset()
    ep_rewards = []
    ep_total = 0
    for _ in range(steps):
        o_t = torch.tensor(obs, device=device).float().unsqueeze(0)
        mean, std, val = policy(o_t)
        dist = torch.distributions.Normal(mean, std)
        act = dist.sample().clamp(-1, 1)
        logp = dist.log_prob(act).sum(-1).item()
        obs_list.append(obs)
        act_list.append(act.detach().cpu().numpy()[0])
        val_list.append(val.item())
        logp_list.append(logp)
        a0 = int((act[0][0].item() + 1) / 2 * 2)
        obs2, rew, done, _ = env.step(a0)
        rew_list.append(rew)
        don_list.append(done)
        ep_total += rew
        if done:
            ep_rewards.append(ep_total)
            ep_total = 0
        obs = obs2
    return (obs_list, act_list, rew_list, val_list, don_list, logp_list), ep_rewards


def update(policy, opt, obs, act, adv, ret, old_logp, clip=0.2):
    obs = torch.tensor(np.array(obs), device=device).float()
    act = torch.tensor(np.array(act), device=device).float()
    adv = torch.tensor(np.array(adv), device=device).float()
    ret = torch.tensor(np.array(ret), device=device).float()
    old_logp = torch.tensor(np.array(old_logp), device=device).float()
    for _ in range(5):
        mean, std, val = policy(obs)
        dist = torch.distributions.Normal(mean, std)
        logp = dist.log_prob(act).sum(-1)
        ratio = (logp - old_logp).exp()
        adv_n = (adv - adv.mean()) / (adv.std() + 1e-8)
        surr1 = ratio * adv_n
        surr2 = torch.clamp(ratio, 1 - clip, 1 + clip) * adv_n
        loss = -torch.min(surr1, surr2).mean() + 0.5 * ((val.squeeze() - ret) ** 2).mean() - 0.01 * dist.entropy().mean()
        opt.zero_grad()
        loss.backward()
        opt.step()


# ------------------------------------------------------------ validation ----
def val_on_asset(policy, assets, name, names):
    df = assets[name].iloc[len(assets[name]) // 2:].reset_index(drop=True)
    ai = names.index(name)
    window = 10
    onehot = np.zeros(len(names), dtype=np.float32)
    onehot[ai] = 1.0
    total = 0.0
    bh = 0.0
    i = window
    pos = 0.0
    n_long = n_flat = n_half = n_steps = 0
    while i < len(df) - 1:
        rets = df["ret"].values[i - window:i]
        if len(rets) < window:
            rets = np.pad(rets, (window - len(rets), 0))
        feats = np.concatenate([rets, [df["mom5"].values[i], df["mom12"].values[i],
                                       df["vol_ratio"].values[i], df["vol_norm"].values[i]]]).astype(np.float32)
        obs = np.concatenate([feats, onehot]).astype(np.float32)
        o_t = torch.tensor(obs, device=device).float().unsqueeze(0)
        with torch.no_grad():
            mean, _, _ = policy(o_t)
            act = mean[0][0].item()
            # Clamp exactly like the inference bridge (rl_signal_bridge.py):
            # without it, act < -1.5 silently becomes a SHORT position (-0.5)
            # that is impossible in the deployed discrete {0, 0.5, 1} policy.
            act = max(-1.0, min(1.0, act))
            new_pos = int((act + 1) / 2 * 2) / 2.0
        if new_pos > 0.5:
            n_long += 1
        elif new_pos < 0.1:
            n_flat += 1
        else:
            n_half += 1
        r = df["ret"].values[i]
        total += new_pos * r * 100.0 - 0.05 * abs(new_pos - pos)
        bh += r * 100.0
        pos = new_pos
        i += 1
        n_steps += 1
    return total, bh, n_long, n_flat, n_half, n_steps


def validate(policy, assets, names):
    total_all = bh_all = 0.0
    nl = nf = nh = ns = 0
    per_asset = {}
    for name in names:
        v, bh, n1, n2, n3, n4 = val_on_asset(policy, assets, name, names)
        total_all += v
        bh_all += bh
        nl += n1
        nf += n2
        nh += n3
        ns += n4
        per_asset[name] = {"rl": round(v, 2), "bh": round(bh, 2)}
    return {
        "sum_rl": round(float(total_all), 2),
        "sum_bh": round(float(bh_all), 2),
        "better_than_bh": bool(total_all > bh_all),
        "positions": {"long": int(nl), "flat": int(nf), "half": int(nh), "steps": int(ns)},
        "per_asset": {k: {"rl": round(float(v["rl"]), 2), "bh": round(float(v["bh"]), 2)}
                      for k, v in per_asset.items()},
    }


# ------------------------------------------------------------------ main ----
ASSETS_32 = sorted([
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
    "POL", "LTC", "TRX", "ATOM", "UNI", "ETC", "FIL", "APT", "NEAR", "ARB",
    "OP", "SUI", "TIA", "SEI", "TON", "INJ", "KAS", "FET", "WIF", "BONK",
    "PEPE", "SHIB",
])


def main() -> int:
    t0 = time.time()
    assets = build_assets(ASSETS_32)
    missing = [n for n in ASSETS_32 if n not in assets]
    if missing:
        print("missing assets:", missing)
    print("assets loaded:", len(assets), "names:", sorted(assets.keys()))

    env = MultiAssetEnv(assets)
    print("env dim:", env.dim, "n_assets:", env.n_assets)

    policy = LSTMPolicy(env.dim, 3).to(device)
    opt = optim.Adam(policy.parameters(), lr=2e-4)

    n_episodes = 300
    steps = 800
    for ep in range(n_episodes):
        data, ep_rew = rollout(policy, env, steps)
        obs, act, rew, val, don, logp = data
        gae = compute_gae(rew, [v for v in val], don)
        returns = [g + v for g, v in zip(gae, val, strict=False)]
        update(policy, opt, obs, act, gae, returns, logp)
        avg = float(np.mean(ep_rew)) if ep_rew else 0.0
        if (ep + 1) % 25 == 0:
            print(f"episode {ep + 1}/{n_episodes} avg={avg:.3f} elapsed={time.time() - t0:.0f}s")

    print("validation of new ppo_v9:")
    res_v9 = validate(policy, assets, sorted(assets.keys()))
    print(json.dumps(res_v9, ensure_ascii=False, indent=2))

    # Compare with the current deployed model.
    current_path = MODELS_DIR / "ppo_v8.pt"
    res_v8 = None
    if current_path.exists():
        ckpt = torch.load(current_path, map_location="cpu")
        sd = ckpt.get("policy", ckpt)
        names_v8 = sorted(ckpt.get("assets") or ASSETS_32)
        # Rebuild assets for the same names the v8 model saw.
        assets_v8 = build_assets(names_v8)
        policy_v8 = LSTMPolicy(env.dim, 3).to(device)
        policy_v8.load_state_dict(sd)
        policy_v8.eval()
        print("validation of current ppo_v8:")
        res_v8 = validate(policy_v8, assets_v8, sorted(assets_v8.keys()))
        print(json.dumps(res_v8, ensure_ascii=False, indent=2))

    report = {
        "n_episodes": n_episodes,
        "steps": steps,
        "assets": sorted(assets.keys()),
        "ppo_v9": res_v9,
        "ppo_v8": res_v8,
    }
    out = REPO_ROOT / "data" / "reports" / "ppo_v9_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    better = res_v8 is None or res_v9["sum_rl"] >= res_v8["sum_rl"]
    if better:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        torch.save({"policy": policy.state_dict(), "assets": sorted(assets.keys())},
                   MODELS_DIR / "ppo_v9.pt")
        print("✅ saved ppo_v9.pt (sum_rl", res_v9["sum_rl"], ")")
    else:
        print("ℹ️ ppo_v9 not saved: sum_rl", res_v9["sum_rl"], "<", res_v8["sum_rl"])
    print("elapsed:", round(time.time() - t0), "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
