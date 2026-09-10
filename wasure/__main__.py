import sys

from .wasure import main

if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
