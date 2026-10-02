"""Frozen executable entry, including spawned indexer workers."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from carma.desktop import main
    raise SystemExit(main())
