#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-check --checkpoint: interrupt a run partway through (via `timeout`,
a real SIGTERM, not a graceful stop) and confirm resuming produces exactly
the same result set as an uninterrupted run -- no missing bricks, no
duplicates. Written after two real bugs were only found by actually doing
this, not by reasoning about the code:

  1. Duplicate rows: checkpoints save every CHECKPOINT_INTERVAL `a` values,
     not every single one, so an interruption between saves means the
     resumed run re-searches (and, without dedup, re-logs) whatever `a`
     values were already processed past the last save point.
  2. Missing rows: the --workers log file handle stays open and buffered
     for the whole worker process (unlike the single-process path, which
     opens/writes/closes per row), so a hard kill could lose buffered log
     rows for `a` values the checkpoint already claimed were done -- the
     checkpoint outran what was actually durable on disk.

Both are fixed in main.py; this script exists so a future change to the
checkpoint/logging code gets re-checked against the same real scenario
instead of just against reasoning. See ROADMAP.md Stage 4.

Usage: python3 check_checkpoint.py [MIN-MAX] [--workers N]
  (default: 1-300000, single process; add --workers N to test that path)
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import time


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_and_interrupt(args, after_seconds):
    """Starts args, sends SIGTERM after after_seconds, and waits for exit.

    Deliberately SIGTERM (via Popen.terminate()), not subprocess.run's
    built-in `timeout=` (which calls Popen.kill() -> SIGKILL): SIGTERM is
    what a real interruption looks like (Ctrl+C, `kill`, the `timeout`
    shell command's default, a container orchestrator's stop signal), and
    is exactly what main.py's --workers path installs a handler for so its
    multiprocessing.Pool cleans up its workers instead of orphaning them.
    SIGKILL can't be handled by any userspace code -- testing against it
    would be testing an unsolvable scenario, not this fix.
    """
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(after_seconds)
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=15)
        return "interrupted"
    return "completed"


def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[1:] if rows else []


def main():
    range_arg = "1-300000"
    workers = None
    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        range_arg = args.pop(0)
    if args and args[0] == "--workers":
        workers = args[1]

    workdir = tempfile.mkdtemp(prefix="check_checkpoint_")
    baseline_csv = os.path.join(workdir, "baseline.csv")
    resumed_csv = os.path.join(workdir, "resumed.csv")
    ckpt_dir = os.path.join(workdir, "ckpt")

    base_cmd = ["python3", "main.py", "--range", range_arg, "--no-gui"]
    if workers:
        base_cmd += ["--workers", workers]

    print("[Info] Running uninterrupted baseline over {}{}...".format(
        range_arg, " (--workers {})".format(workers) if workers else ""))
    t0 = time.time()
    run(base_cmd + ["--log", baseline_csv])
    baseline_time = time.time() - t0
    baseline_rows = sorted(tuple(r) for r in read_csv_rows(baseline_csv))
    print("[Info] Baseline: {} bricks in {:.1f}s.".format(len(baseline_rows), baseline_time))

    interrupt_after = max(1, baseline_time * 0.4)
    print("[Info] Running checkpointed search, sending SIGTERM after ~{:.1f}s...".format(interrupt_after))
    status = run_and_interrupt(base_cmd + ["--checkpoint", ckpt_dir, "--log", resumed_csv], interrupt_after)
    if status == "completed":
        print("[Warn] Run completed before the interrupt fired; range may be too small "
              "to exercise resumption meaningfully. Results will still be checked.")
    else:
        print("[Info] Interrupted as expected. Checking for orphaned worker processes...")
        time.sleep(1)  # let anything genuinely still shutting down finish
        leftover = subprocess.run(
            ["pgrep", "-f", "main.py.*{}".format(workdir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if leftover.returncode == 0:
            print("FAIL: worker process(es) still running after the parent was "
                  "SIGTERM'd -- multiprocessing.Pool cleanup didn't happen.")
            shutil.rmtree(workdir, ignore_errors=True)
            return 1
        print("[Info] No orphaned workers. Resuming to completion...")
        run(base_cmd + ["--checkpoint", ckpt_dir, "--log", resumed_csv])

    resumed_rows_list = [tuple(r) for r in read_csv_rows(resumed_csv)]
    resumed_rows = sorted(resumed_rows_list)

    ok = True
    if len(resumed_rows_list) != len(set(resumed_rows_list)):
        dupes = len(resumed_rows_list) - len(set(resumed_rows_list))
        print("FAIL: {} duplicate row(s) in the resumed run's log.".format(dupes))
        ok = False

    if resumed_rows != baseline_rows:
        missing = sorted(set(baseline_rows) - set(resumed_rows))
        extra = sorted(set(resumed_rows) - set(baseline_rows))
        if missing:
            print("FAIL: {} row(s) present in baseline but missing after resume: {}".format(
                len(missing), missing[:5]))
        if extra:
            print("FAIL: {} row(s) in the resumed run not in baseline: {}".format(
                len(extra), extra[:5]))
        ok = False

    if ok:
        print("OK: resumed run matches the uninterrupted baseline exactly "
              "({} bricks, 0 duplicates) over {}{}.".format(
                  len(baseline_rows), range_arg,
                  " (--workers {})".format(workers) if workers else ""))

    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
