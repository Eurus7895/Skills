"""Domain types."""


class Record:
    key = 0


class Order(Record):
    def __init__(self, sku):
        self.sku = sku

    def total(self):
        return len(self.sku)
