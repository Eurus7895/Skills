"""Application workflow. Owns no storage of its own."""

from app.core.models import Order
from app.infra.store import Store


class OrderService:
    def __init__(self):
        self.store = Store()

    def record(self, skus):
        for sku in skus:
            self.store.put(Order(sku))
        return len(skus)
