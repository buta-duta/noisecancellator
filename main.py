import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    from clarity.report import install_crash_report, report_exception

    install_crash_report()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if "--check" in args:
            from clarity.tray import run_check

            return run_check()
        from clarity.tray import run

        return run()
    except Exception as exc:
        report_exception(exc, crash=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
