"""Command line entry point."""

import sys

from app.core.service import OrderService


def main():
    service = OrderService()
    service.record(sys.argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
