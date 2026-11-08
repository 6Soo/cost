"""Hidden scheduled-task entry point for one owned WebLedger supervisor."""

from tools.webledger_windows_lifecycle import main


if __name__ == "__main__":
    raise SystemExit(main())
