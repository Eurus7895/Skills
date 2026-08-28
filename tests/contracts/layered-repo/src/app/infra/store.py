"""Persistence. Keeps orders in memory until flushed."""

from app.infra.config import load


class Store:
    def __init__(self):
        self.settings = load()
        self.rows = []

    def put(self, order):
        self.rows.append(order)
        return len(self.rows)
