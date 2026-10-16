# main.py
# This file contains the main function for the library.
def main() -> None:
    """The main function for the library."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from cli.menu import CLIApp

    CLIApp().run()


if __name__ == "__main__":
    main()
