from abc import ABC, abstractmethod

from purchase_price.schemas import CollectedPrice, ProductQuery


class PriceCollector(ABC):
    """External source adapter contract.

    Each source (나라장터, public institution disclosure, manufacturer, distributor)
    implements this interface. Source adapters must return evidence, not a purchase decision.
    """

    name: str

    @abstractmethod
    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        raise NotImplementedError
