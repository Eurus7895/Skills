"""Configuration loading."""

import os


def load():
    return {"path": os.environ.get("ORDERLOG_PATH", "orders.json")}
