import pytest

from swarm.chat.budget import BudgetExceeded, LLMCallBudget


def test_budget_blocks_total():
    b = LLMCallBudget(max_per_session=2, selector_max=5)
    b.consume_agent()
    b.consume_agent()
    with pytest.raises(BudgetExceeded):
        b.consume_agent()


def test_budget_blocks_selector():
    b = LLMCallBudget(max_per_session=10, selector_max=1)
    b.consume_selector()
    with pytest.raises(BudgetExceeded):
        b.consume_selector()


def test_summary_counts_as_agent():
    b = LLMCallBudget(max_per_session=1, selector_max=5)
    b.consume_summary()
    with pytest.raises(BudgetExceeded):
        b.consume_agent()
