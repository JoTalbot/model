from __future__ import annotations


class BudgetExceeded(Exception):
    pass


class LLMCallBudget:
    def __init__(self, max_per_session: int, selector_max: int) -> None:
        self.max_per_session = max_per_session
        self.selector_max = selector_max
        self._total = 0
        self._selector = 0

    def consume_agent(self) -> None:
        self._consume_total(1)

    def consume_summary(self) -> None:
        self._consume_total(1)

    def consume_selector(self) -> None:
        if self._selector >= self.selector_max:
            raise BudgetExceeded("selector LLM budget exhausted")
        self._selector += 1
        self._consume_total(1)

    def _consume_total(self, n: int) -> None:
        if self._total + n > self.max_per_session:
            raise BudgetExceeded("session LLM budget exhausted")
        self._total += n
