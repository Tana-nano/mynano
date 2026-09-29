import sys
import traceback

from vsui_log.cli import main


def launched_by_double_click() -> bool:
    return len(sys.argv) == 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    if code and launched_by_double_click():
        # Keep the console open so the message can be read before the window closes.
        try:
            input("\nEnter キーを押すと閉じます…")
        except EOFError:
            pass
    sys.exit(code)
