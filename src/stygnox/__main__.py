"""Allow ``python -m stygnox`` to use the installed neutral CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
