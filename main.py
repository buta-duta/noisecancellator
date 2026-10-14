import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        from clarity.tray import run_check

        return run_check()
    from clarity.tray import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
