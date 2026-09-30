import sys
import traceback

from upload_doctor.cli import main, should_pause

if __name__ == "__main__":
    argv = sys.argv[1:]
    try:
        code = main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
    except Exception:
        traceback.print_exc()
        code = 2
    if should_pause(argv):
        # Keep the console open (double-click / drag-and-drop) so the results can be read.
        try:
            input("\nEnter キーを押すと閉じます…")
        except EOFError:
            pass
    sys.exit(code)
