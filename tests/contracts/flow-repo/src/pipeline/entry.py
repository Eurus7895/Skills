"""Command line entry point. Hands the argument straight to the pipeline."""

from pipeline.transform import normalise


def main(raw):
    return normalise(raw)


if __name__ == "__main__":
    main("")
