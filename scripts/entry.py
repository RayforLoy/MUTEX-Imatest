import multiprocessing
if __name__=="__main__":
    multiprocessing.freeze_support()
    import sys
    from mutex_imatest.cli import main
    raise SystemExit(main())

