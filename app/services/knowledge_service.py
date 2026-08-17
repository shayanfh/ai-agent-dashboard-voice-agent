import asyncio
import math
import re
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from app.backend.schemas import KnowledgeEntry, KnowledgeSnapshot

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "do", "for", "from", "how",
    "i", "in", "is", "it", "of", "on", "or", "the", "to", "what", "when", "where",
    "which", "with", "you", "your", "از", "است", "این", "با", "به", "برای", "در", "را",
    "که", "من", "می", "و", "چه", "چطور", "کجا", "آیا",
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return value.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")


def _tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[^\W_]+", _normalize(value), flags=re.UNICODE)
        if len(token) > 1 and token not in _STOP_WORDS
    ]


def _trigrams(value: str) -> frozenset[str]:
    compact = re.sub(r"\s+", " ", _normalize(value)).strip()
    if len(compact) < 3:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + 3] for index in range(len(compact) - 2))


@dataclass(slots=True)
class _IndexedEntry:
    entry: KnowledgeEntry
    frequencies: Counter[str]
    length: int
    title_trigrams: frozenset[str]


class KnowledgeIndex:
    def __init__(self, snapshot: KnowledgeSnapshot) -> None:
        self.version = snapshot.version
        self._entries = [
            _IndexedEntry(
                entry=entry,
                frequencies=Counter(_tokens(f"{entry.title} {entry.content}")),
                length=max(1, len(_tokens(f"{entry.title} {entry.content}"))),
                title_trigrams=_trigrams(entry.title),
            )
            for entry in snapshot.entries
        ]
        self._average_length = (
            sum(item.length for item in self._entries) / len(self._entries)
            if self._entries
            else 1.0
        )
        self._document_frequency = Counter(
            token for item in self._entries for token in item.frequencies
        )

    @property
    def empty(self) -> bool:
        return not self._entries

    def search(self, query: str, *, top_k: int, max_chars: int) -> list[KnowledgeEntry]:
        query_tokens = _tokens(query)
        if not query_tokens or not self._entries:
            return []
        query_trigrams = _trigrams(query)
        entry_count = len(self._entries)
        scored: list[tuple[float, KnowledgeEntry]] = []
        for indexed in self._entries:
            score = 0.0
            for token in query_tokens:
                frequency = indexed.frequencies.get(token, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[token]
                inverse_frequency = math.log(
                    1 + (entry_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + 1.2 * (
                    0.25 + 0.75 * indexed.length / self._average_length
                )
                score += inverse_frequency * frequency * 2.2 / denominator
            if query_trigrams and indexed.title_trigrams:
                overlap = len(query_trigrams & indexed.title_trigrams)
                similarity = 2 * overlap / (len(query_trigrams) + len(indexed.title_trigrams))
                if similarity >= 0.18:
                    score += 1.5 * similarity
            if score > 0.15:
                scored.append((score, indexed.entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected: list[KnowledgeEntry] = []
        used_chars = 0
        for _, entry in scored[:top_k]:
            if used_chars + len(entry.content) > max_chars:
                continue
            selected.append(entry)
            used_chars += len(entry.content)
        return selected


class KnowledgeCache:
    def __init__(self) -> None:
        self._items: OrderedDict[tuple[str, int], KnowledgeIndex] = OrderedDict()
        self._inflight: dict[tuple[str, int], asyncio.Task[KnowledgeSnapshot]] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        *,
        agent_id: str,
        version: int,
        max_entries: int,
        loader: Callable[[], Coroutine[Any, Any, KnowledgeSnapshot]],
    ) -> KnowledgeIndex:
        key = (agent_id, version)
        async with self._lock:
            cached = self._items.get(key)
            if cached:
                self._items.move_to_end(key)
                return cached
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(loader())
                self._inflight[key] = task
        try:
            snapshot = await task
        finally:
            async with self._lock:
                self._inflight.pop(key, None)
        async with self._lock:
            cached = self._items.get(key)
            if cached:
                self._items.move_to_end(key)
                return cached
            index = KnowledgeIndex(snapshot)
            self._items[key] = index
            self._items.move_to_end(key)
            while len(self._items) > max_entries:
                self._items.popitem(last=False)
            stale_keys = [item for item in self._items if item[0] == agent_id and item != key]
            for stale_key in stale_keys:
                self._items.pop(stale_key, None)
            return index


knowledge_cache = KnowledgeCache()
