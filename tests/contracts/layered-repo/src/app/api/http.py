"""HTTP boundary. Validates input before anything else sees it."""

from app.core.service import OrderService


class Handler:
    def __init__(self):
        self.service = OrderService()

    def post(self, body):
        if "sku" not in body:
            raise ValueError("sku is required")
        return self.service.record([body["sku"]])
