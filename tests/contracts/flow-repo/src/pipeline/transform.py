"""Normalisation. The only place input is trimmed."""

from pipeline.store import save


def normalise(raw):
    return save(raw.strip())
