import sys
import traceback

from osc_doctor.cli import main


def launched_by_double_click() -> bool:
    return len(sys.argv) == 1


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
    except Exception:
        traceback.print_exc()
        code = 2
    if launched_by_double_click():
        # Keep the console open so the results can be read.
        try:
            input("\nEnter キーを押すと閉じます…")
        except EOFError:
            pass
    sys.exit(code)
