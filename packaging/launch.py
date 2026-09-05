"""PyInstaller entry point; double-click opens offline, never auto-connects."""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if sys.argv[1:] == ['offline-smoke']:
        from hyperlab.offline_smoke import main
        raise SystemExit(main())
    from hyperlab.__main__ import main
    raise SystemExit(main(sys.argv[1:] or ['app']))
