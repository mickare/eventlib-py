# Copyright 2026 Michael Käser
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""Entry point of the benchmark suite (``python -m benchmark``)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
