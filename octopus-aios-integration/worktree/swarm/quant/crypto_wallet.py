"""
AIOS Multi-Chain Crypto Wallet & 4-Way Profit Distribution Manager
Модуль криптокошельков и распределения прибыли AIOS.

ПОЛИТИКА РАСПРЕДЕЛЕНИЯ ПРИБЫЛИ (25% / 25% / 25% / 25%):
Вся прибыль проекта от любого источника автоматически делится на 4 равные части
и распределяется по 4 отдельным кошелькам:
1. 25% - Разработчик (Developer Wallet)
2. 25% - Инвестор (Investor Wallet)
3. 25% - Персонал (Personnel/Staff Wallet)
4. 25% - Система (System Autonomous Wallet) — средства, которые AIOS может тратить
   по своему усмотрению (VPS серверы, LLM API ключи, домены, новое железо).
"""

import json
import logging
import os
import time
from typing import Any

from swarm.quant.paths import resolve_data_dir

try:
    from web3 import Web3
except ImportError:  # optional: EVM balance/tx features need `web3`
    Web3 = None  # type: ignore[assignment]

logger = logging.getLogger("Octopus.CryptoWallet")

PUBLIC_RPC_NODES = {
    "ethereum": [
        "https://cloudflare-eth.com",
        "https://ethereum-rpc.publicnode.com",
        "https://1rpc.io/eth",
    ],
    "polygon": [
        "https://polygon.drpc.org",
        "https://polygon-bor-rpc.publicnode.com",
        "https://1rpc.io/matic",
    ],
    "arbitrum": [
        "https://arbitrum.drpc.org",
        "https://arbitrum-one-rpc.publicnode.com",
        "https://arbitrum-one.publicnode.com",
        "https://arb1.arbitrum.io/rpc",
    ],  # 1rpc.io/arb rate-limited, removed 2026-08-08
    "base": [
        "https://base.drpc.org",
        "https://base-rpc.publicnode.com",
        "https://mainnet.base.org",
        "https://1rpc.io/base",
    ],
    "bsc": ["https://bsc-rpc.publicnode.com", "https://1rpc.io/bnb"],
}

DEFAULT_COSTS = {
    "vps_hosting_usd": 15.0,  # Стоимость VPS сервера в месяц ($)
    "llm_budget_usd": 20.0,  # Порог бюджета на платные LLM в месяц ($)
    "domain_dns_usd": 2.0,  # Поддержка доменов / инфраструктуры ($)
}


class AIOSWalletManager:
    """Управление 4 кошельками прибыли и бюджетом самообеспечения AIOS."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = resolve_data_dir(data_dir)

        self.vault_file = self.data_dir / ".wallet_vault.json"
        self.ledger_file = self.data_dir / "self_funding_ledger.json"
        self._ensure_files()

    def _ensure_files(self):
        """Создание файлов хранения с конфигурацией 4 кошельков при их отсутствии."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.vault_file.exists():
            default_vault = {
                "rule": "PROFIT_SPLIT_4_WAY_25_PERCENT",
                "wallets": {
                    "developer": {
                        "label": "1. Разработчик",
                        "evm_address": "0x000000000000000000000000000000000DEVAIOS",
                        "trc20_address": "T_AIOS_DEVELOPER_WALLET_ADDRESS",
                    },
                    "investor": {
                        "label": "2. Инвестор",
                        "evm_address": "0x000000000000000000000000000000000INVAIOS",
                        "trc20_address": "T_AIOS_INVESTOR_WALLET_ADDRESS",
                    },
                    "personnel": {
                        "label": "3. Персонал",
                        "evm_address": "0x00000000000000000000000000000000STAFFAIOS",
                        "trc20_address": "T_AIOS_PERSONNEL_WALLET_ADDRESS",
                    },
                    "system": {
                        "label": "4. Система (Автономный бюджет)",
                        "evm_address": "0x00000000000000000000000000000000000SYSTEM",
                        "trc20_address": "T_AIOS_SYSTEM_AUTONOMOUS_WALLET",
                    },
                },
            }
            with open(self.vault_file, "w", encoding="utf-8") as f:
                json.dump(default_vault, f, indent=2, ensure_ascii=False)
            os.chmod(self.vault_file, 0o600)

        if not self.ledger_file.exists():
            default_ledger = {
                "total_earned_usd": 0.0,
                "total_spent_system_usd": 0.0,
                "distribution_shares_usd": {
                    "developer": 0.0,
                    "investor": 0.0,
                    "personnel": 0.0,
                    "system": 0.0,
                },
                "monthly_costs": DEFAULT_COSTS,
                "transactions": [],
            }
            with open(self.ledger_file, "w", encoding="utf-8") as f:
                json.dump(default_ledger, f, indent=2, ensure_ascii=False)

    def load_vault(self) -> dict[str, Any]:
        """Загрузка данных кошельков из хранилища."""
        try:
            with open(self.vault_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения wallet vault: {e}")
            return {}

    def save_vault(self, data: dict[str, Any]):
        """Сохранение данных в хранилище с защитой прав доступа."""
        with open(self.vault_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.chmod(self.vault_file, 0o600)

    def load_ledger(self) -> dict[str, Any]:
        """Загрузка реестра доходов/расходов."""
        try:
            with open(self.ledger_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения ledger: {e}")
            return {"total_earned_usd": 0.0, "transactions": []}

    def save_ledger(self, ledger: dict[str, Any]):
        """Сохранение реестра доходов/расходов."""
        with open(self.ledger_file, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2, ensure_ascii=False)

    def get_public_addresses(self) -> dict[str, Any]:
        """Возвращает публичные адреса 4 кошельков системы."""
        vault = self.load_vault()
        return vault.get("wallets", {})

    def check_erc20_balance(
        self, network: str = "polygon", token_symbol: str = "USDT"
    ) -> dict[str, Any]:
        if Web3 is None:
            return {
                "network": network,
                "token": token_symbol,
                "address": "",
                "balance": 0.0,
                "error": "web3 not installed: ERC-20 balance check unavailable",
            }
        """Проверка реального баланса ERC20 токена на EVM-сети через публичные RPC."""
        vault = self.load_vault()
        wallets = vault.get("wallets", {})
        system_wallet = wallets.get("system", {})
        address = system_wallet.get("evm_address", "")

        if not address or address.endswith("SYSTEM"):
            return {
                "network": network,
                "token": token_symbol,
                "address": address,
                "balance": 0.0,
                "is_mock": True,
            }

        # Определяем адрес контракта в зависимости от сети и символа
        contract_addr = None
        if network == "polygon":
            if token_symbol.upper() == "USDT":
                contract_addr = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
            elif token_symbol.upper() == "USDC":
                contract_addr = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
            elif token_symbol.upper() == "APOLUSDT":
                contract_addr = "0x6ab707Aca953eDAeFBc4fD23bA73294241490620"
        elif network == "base":
            if token_symbol.upper() == "USDC":
                contract_addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
            elif token_symbol.upper() == "USDT":
                contract_addr = "0xfde4c96c8593536e31f229ea8f37b2ad3e12726c"

        if not contract_addr:
            return {
                "network": network,
                "token": token_symbol,
                "address": address,
                "balance": 0.0,
                "error": f"Неизвестный контракт для токена {token_symbol} в сети {network}",
            }

        rpc_urls = PUBLIC_RPC_NODES.get(network, PUBLIC_RPC_NODES["polygon"])

        # Минимальный ABI для balanceOf и decimals
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "decimals", "type": "uint8"}],
                "type": "function",
            },
        ]

        for rpc in rpc_urls:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
                if w3.is_connected():
                    contract = w3.eth.contract(
                        address=Web3.to_checksum_address(contract_addr), abi=erc20_abi
                    )
                    raw_balance = contract.functions.balanceOf(
                        Web3.to_checksum_address(address)
                    ).call()
                    decimals = contract.functions.decimals().call()
                    balance = raw_balance / (10**decimals)

                    return {
                        "network": network,
                        "token": token_symbol.upper(),
                        "contract_address": contract_addr,
                        "wallet_address": address,
                        "balance": float(balance),
                        "is_mock": False,
                    }
            except Exception as e:
                logger.warning(f"⚠️ ERC20 RPC {rpc} недоступен: {e}")

        return {
            "network": network,
            "token": token_symbol,
            "address": address,
            "balance": 0.0,
            "is_mock": True,
            "error": "All RPCs timed out",
        }

    def send_evm_tokens(
        self,
        network: str = "polygon",
        token_symbol: str = "USDT",
        recipient: str = "",
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Физическая отправка транзакции перевода EVM-токенов (USDT/USDC или нативного MATIC/ETH) со счетов системы."""
        try:
            from web3 import Web3
        except ImportError:
            return {
                "status": "error",
                "error": "web3 not installed: EVM transfers unavailable",
            }

        vault = self.load_vault()
        wallets = vault.get("wallets", {})
        system_wallet = wallets.get("system", {})
        sender_address = system_wallet.get("evm_address", "")

        # Получаем приватный ключ из сейфа
        private_key = vault.get("evm_private_key") or vault.get("private_key", "")

        if not private_key or not sender_address or sender_address.endswith("SYSTEM"):
            return {
                "status": "error",
                "error": "Отправка заблокирована: отсутствует приватный ключ или адрес системы.",
            }

        # Определяем адрес контракта токена
        is_native = token_symbol.upper() in ["MATIC", "ETH", "POL"]
        contract_addr = None
        decimals = 18

        if not is_native:
            if network == "polygon":
                if token_symbol.upper() == "USDT":
                    contract_addr = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
                    decimals = 6
                elif token_symbol.upper() == "USDC":
                    contract_addr = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
                    decimals = 6
            elif network == "base":
                if token_symbol.upper() == "USDC":
                    contract_addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
                    decimals = 6
                elif token_symbol.upper() == "USDT":
                    contract_addr = "0xfde4c96c8593536e31f229ea8f37b2ad3e12726c"
                    decimals = 6

            if not contract_addr:
                return {
                    "status": "error",
                    "error": f"Неизвестный контракт для токена {token_symbol} в сети {network}",
                }

        # Получаем RPC ноды
        rpc_urls = PUBLIC_RPC_NODES.get(network, PUBLIC_RPC_NODES["polygon"])
        w3 = None
        for rpc in rpc_urls:
            try:
                temp_w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 8}))
                if temp_w3.is_connected():
                    w3 = temp_w3
                    break
            except Exception:
                continue

        if not w3:
            return {
                "status": "error",
                "error": f"Все RPC ноды для сети {network} недоступны.",
            }

        # Проверяем перегрузку сети перед отправкой (Gas Sentry Guard)
        try:
            from swarm.quant.signals.gas_sentry import Web3GasSentry

            gas_check = Web3GasSentry.is_gas_safe(w3, network)
            if not gas_check.get("is_safe"):
                logger.warning(
                    f"⚠️ [EVM Yield Dispatcher] Транзакция отложена: высокая комиссия в сети {network.upper()} ({gas_check['current_gas_gwei']} Gwei > лимит {gas_check['max_allowed_gwei']} Gwei)"
                )
                return {
                    "status": "error",
                    "error": f"Gas congestion: current gas {gas_check['current_gas_gwei']} Gwei exceeds limit of {gas_check['max_allowed_gwei']} Gwei",
                }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки Gas Sentry: {e}")

        try:
            sender_checksum = Web3.to_checksum_address(sender_address)
            recipient_checksum = Web3.to_checksum_address(recipient)

            # Сверяем адрес из приватного ключа
            account = w3.eth.account.from_key(private_key)
            if account.address.lower() != sender_checksum.lower():
                return {
                    "status": "error",
                    "error": "Критическое несовпадение: приватный ключ не соответствует адресу отправителя.",
                }

            # Расчет сырой суммы перевода
            raw_amount = int(amount_usd * (10**decimals))

            # Построение транзакции
            tx_params = {
                "chainId": w3.eth.chain_id,
                "nonce": w3.eth.get_transaction_count(sender_checksum),
            }

            # Оценка Gas Price (EIP-1559 с legacy fallback)
            try:
                fee_history = w3.eth.fee_history(1, "latest", [25.0])
                base_fee = fee_history["baseFeePerGas"][-1]
                priority_fee = fee_history["reward"][-1][0]
                tx_params["maxFeePerGas"] = int((base_fee * 1.35) + priority_fee)
                tx_params["maxPriorityFeePerGas"] = priority_fee
            except Exception:
                tx_params["gasPrice"] = int(w3.eth.gas_price * 1.25)

            if is_native:
                tx_params["to"] = recipient_checksum
                tx_params["value"] = raw_amount
                tx_params["gas"] = 21000
            else:
                erc20_abi = [
                    {
                        "constant": False,
                        "inputs": [
                            {"name": "_to", "type": "address"},
                            {"name": "_value", "type": "uint256"},
                        ],
                        "name": "transfer",
                        "outputs": [{"name": "success", "type": "bool"}],
                        "type": "function",
                    }
                ]
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(contract_addr), abi=erc20_abi
                )

                built_tx = contract.functions.transfer(
                    recipient_checksum, raw_amount
                ).build_transaction(
                    {
                        "from": sender_checksum,
                        "nonce": tx_params["nonce"],
                        "chainId": tx_params["chainId"],
                    }
                )

                if "gasPrice" in tx_params:
                    built_tx["gasPrice"] = tx_params["gasPrice"]
                else:
                    built_tx["maxFeePerGas"] = tx_params["maxFeePerGas"]
                    built_tx["maxPriorityFeePerGas"] = tx_params["maxPriorityFeePerGas"]

                try:
                    built_tx["gas"] = int(w3.eth.estimate_gas(built_tx) * 1.2)
                except Exception:
                    built_tx["gas"] = 100000

                tx_params = built_tx

            signed_tx = w3.eth.account.sign_transaction(tx_params, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(
                f"📲 [EVM Transaction Sent!] {network.upper()} {token_symbol.upper()}: {amount_usd:.2f} -> {recipient}. TxHash: {tx_hash.hex()}"
            )

            return {
                "status": "success",
                "network": network,
                "token": token_symbol.upper(),
                "amount_usd": amount_usd,
                "recipient": recipient,
                "tx_hash": tx_hash.hex(),
            }

        except Exception as e:
            logger.error(f"❌ Ошибка отправки EVM транзакции ({network}): {e}")
            return {"status": "error", "error": str(e)}

    def check_evm_balance(self, network: str = "polygon") -> dict[str, Any]:
        """Проверка реального баланса на EVM-сети через публичные RPC."""
        if Web3 is None:
            return {
                "network": network,
                "address": "",
                "native_balance": 0.0,
                "symbol": "ETH",
                "is_mock": True,
                "error": "web3 not installed: EVM balance check unavailable",
            }
        vault = self.load_vault()
        wallets = vault.get("wallets", {})
        system_wallet = wallets.get("system", {})
        address = system_wallet.get("evm_address", "")

        if not address or address.endswith("SYSTEM"):
            return {
                "network": network,
                "address": address,
                "native_balance": 0.0,
                "symbol": "ETH" if network != "polygon" else "MATIC",
                "is_mock": True,
            }

        rpc_urls = PUBLIC_RPC_NODES.get(network, PUBLIC_RPC_NODES["polygon"])
        for rpc in rpc_urls:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
                if w3.is_connected():
                    balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
                    balance_eth = balance_wei / 10**18
                    symbol = (
                        "MATIC"
                        if network == "polygon"
                        else ("BNB" if network == "bsc" else "ETH")
                    )
                    return {
                        "network": network,
                        "address": address,
                        "native_balance": float(balance_eth),
                        "symbol": symbol,
                        "is_mock": False,
                    }
            except Exception as e:
                logger.warning(f"⚠️ RPC {rpc} недоступен: {e}")

        return {
            "network": network,
            "address": address,
            "native_balance": 0.0,
            "symbol": "ETH",
            "is_mock": True,
            "error": "All RPCs timed out",
        }

    def record_income(
        self, amount_usd: float, source: str, task_id: str, network_token: str = "USDT"
    ) -> dict[str, Any]:
        """
        Фиксация поступившей прибыли и строгое разделение на 4 равные части (25% каждому):
        1. Разработчик - 25%
        2. Инвестор - 25%
        3. Персонал - 25%
        4. Система - 25% (расходуется системой по своему усмотрению)
        """
        ledger = self.load_ledger()
        ledger["total_earned_usd"] = ledger.get("total_earned_usd", 0.0) + amount_usd

        share = amount_usd * 0.25  # Ровно 25% каждой из 4 сторон

        shares = ledger.get(
            "distribution_shares_usd",
            {"developer": 0.0, "investor": 0.0, "personnel": 0.0, "system": 0.0},
        )

        shares["developer"] = shares.get("developer", 0.0) + share
        shares["investor"] = shares.get("investor", 0.0) + share
        shares["personnel"] = shares.get("personnel", 0.0) + share
        shares["system"] = shares.get("system", 0.0) + share

        ledger["distribution_shares_usd"] = shares

        tx = {
            "type": "INCOME_SPLIT_4_WAY",
            "total_amount_usd": amount_usd,
            "share_per_wallet_usd": share,
            "breakdown": {
                "developer_25pct": share,
                "investor_25pct": share,
                "personnel_25pct": share,
                "system_25pct": share,
            },
            "source": source,
            "task_id": task_id,
            "token": network_token,
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        if "transactions" not in ledger:
            ledger["transactions"] = []
        ledger["transactions"].append(tx)
        self.save_ledger(ledger)

        logger.info(
            f"💰 [CryptoWallet 4-Way Split] Зачислено ${amount_usd:.2f} ({source}). "
            f"Распределено по 25% (${share:.2f}): Разработчик, Инвестор, Персонал, Система."
        )
        return tx

    def spend_system_budget(self, amount_usd: float, purpose: str) -> dict[str, Any]:
        """
        Расход средств Системы (часть 4) по её собственному усмотрению
        (оплата VPS серверов, LLM API ключей, доменов).
        """
        ledger = self.load_ledger()
        shares = ledger.get("distribution_shares_usd", {})
        system_available = shares.get("system", 0.0)

        if system_available < amount_usd:
            return {
                "status": "insufficient_funds",
                "requested": amount_usd,
                "available": system_available,
                "message": f"Недостаточно средств в автономном бюджете Системы (${system_available:.2f})",
            }

        shares["system"] -= amount_usd
        ledger["distribution_shares_usd"] = shares
        ledger["total_spent_system_usd"] = (
            ledger.get("total_spent_system_usd", 0.0) + amount_usd
        )

        tx = {
            "type": "SYSTEM_EXPENSE",
            "amount_usd": amount_usd,
            "purpose": purpose,
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        ledger["transactions"].append(tx)
        self.save_ledger(ledger)

        logger.info(
            f'💸 [System Budget Expense] Система потратила ${amount_usd:.2f} на "{purpose}". Остаток системного кошелька: ${shares["system"]:.2f}'
        )
        return {
            "status": "success",
            "spent_usd": amount_usd,
            "remaining_system_budget": shares["system"],
        }

    def get_financial_summary(self) -> dict[str, Any]:
        """Сводка балансов по всем 4 кошелькам и уровень самообеспечения."""
        ledger = self.load_ledger()
        costs = ledger.get("monthly_costs", DEFAULT_COSTS)
        total_monthly_need = sum(costs.values())

        total_earned = ledger.get("total_earned_usd", 0.0)
        shares = ledger.get(
            "distribution_shares_usd",
            {"developer": 0.0, "investor": 0.0, "personnel": 0.0, "system": 0.0},
        )

        system_budget = shares.get("system", 0.0)
        system_sustainability_ratio = (
            (system_budget / total_monthly_need) if total_monthly_need > 0 else 0.0
        )

        wallets = self.get_public_addresses()

        return {
            "policy": "4_WAY_25_PERCENT_PROFIT_SPLIT",
            "total_earned_all_time_usd": round(total_earned, 2),
            "monthly_operating_cost_usd": round(total_monthly_need, 2),
            "system_sustainability_pct": round(system_sustainability_ratio * 100, 1),
            "wallet_balances_usd": {
                "1_developer_25pct": round(shares.get("developer", 0.0), 2),
                "2_investor_25pct": round(shares.get("investor", 0.0), 2),
                "3_personnel_25pct": round(shares.get("personnel", 0.0), 2),
                "4_system_autonomous_25pct": round(shares.get("system", 0.0), 2),
            },
            "wallets_addresses": wallets,
        }


# Совместимость
class AIOSWallet(AIOSWalletManager):
    def check_balance(self):
        res = self.check_evm_balance("polygon")
        return res.get("native_balance", 0.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    wm = AIOSWalletManager()
    print("=== AIOS 4-WAY PROFIT DISTRIBUTION SUMMARY ===")
    print(json.dumps(wm.get_financial_summary(), indent=2, ensure_ascii=False))
