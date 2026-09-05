from abc import ABC, abstractmethod

from purchase_price.schemas import CollectedPrice, ProductQuery


class CollectorSkipped(RuntimeError):
    """A source was intentionally not queried because its safe preconditions were not met.

    This is different from both a successful query with zero records and an upstream failure.
    The reason must be safe to show to users and must never contain credentials.
    """


class PriceCollector(ABC):
    """External source adapter contract.

    Each source (나라장터, public institution disclosure, manufacturer, distributor)
    implements this interface. Source adapters must return evidence, not a purchase decision.
    """

    name: str

    @abstractmethod
    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        raise NotImplementedError
