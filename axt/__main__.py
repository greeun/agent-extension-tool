"""``python3 -m axt`` entry point.

Equivalent to running the ``axt`` console script installed by
``pyproject.toml`` (``[project.scripts] axt = "axt:main"``). Useful when
the script bin is not on ``$PATH`` (e.g., editable installs without
``pip install -e .``).
"""

from axt import main

if __name__ == "__main__":
    raise SystemExit(main())
