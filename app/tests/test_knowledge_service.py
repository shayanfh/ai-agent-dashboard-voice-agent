import pytest

from app.backend.schemas import KnowledgeEntry, KnowledgeSnapshot
from app.services.knowledge_service import KnowledgeCache, KnowledgeIndex


def _snapshot(version: int = 1) -> KnowledgeSnapshot:
    return KnowledgeSnapshot(
        company_id="company",
        agent_id="agent",
        version=version,
        entries=[
            KnowledgeEntry(
                id="pizza",
                source="qa",
                title="Do you have vegan pizza?",
                content=(
                    "Question: Do you have vegan pizza?\n"
                    "Answer: Yes, vegan Margherita is available."
                ),
                category="menu",
            ),
            KnowledgeEntry(
                id="deposit",
                source="qa",
                title="Is a security deposit required?",
                content="A refundable security deposit of 200 dollars is required.",
                category="deposit",
            ),
            KnowledgeEntry(
                id="persian-hours",
                source="qa",
                title="ساعت کاری رستوران چیست؟",
                content="رستوران هر روز از ساعت ۹ صبح تا ۱۰ شب باز است.",
                category="hours",
            ),
        ],
    )


def test_local_retrieval_selects_relevant_knowledge_without_network():
    index = KnowledgeIndex(_snapshot())
    matches = index.search("Can I order a vegan pizza?", top_k=2, max_chars=2000)
    assert matches
    assert matches[0].id == "pizza"
    assert all(item.id != "deposit" for item in matches)


def test_local_retrieval_normalizes_persian_characters():
    index = KnowledgeIndex(_snapshot())
    matches = index.search("ساعت كاري شما چیه؟", top_k=2, max_chars=2000)
    assert matches
    assert matches[0].id == "persian-hours"


@pytest.mark.asyncio
async def test_cache_only_loads_once_for_same_agent_version():
    cache = KnowledgeCache()
    calls = 0

    async def loader() -> KnowledgeSnapshot:
        nonlocal calls
        calls += 1
        return _snapshot()

    first = await cache.get(agent_id="agent", version=1, max_entries=8, loader=loader)
    second = await cache.get(agent_id="agent", version=1, max_entries=8, loader=loader)
    assert first is second
    assert calls == 1
