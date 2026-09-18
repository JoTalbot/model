"""Paper-only quantitative trading engine ported from AIOS (Wave 4, item 1).

Deliberately import-light: importing this package must never pull the engine
chain (web3/numpy are optional). Import modules directly, e.g.
``from swarm.quant.quant_trading_engine import MultiExchangeQuantEngine``.
"""
