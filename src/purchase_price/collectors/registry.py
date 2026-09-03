from .base import PriceCollector
from .mock_public import MockPublicCollector


def build_collectors(include_mock: bool = True) -> list[PriceCollector]:
    collectors: list[PriceCollector] = []
    if include_mock:
        collectors.append(MockPublicCollector())
    return collectors
