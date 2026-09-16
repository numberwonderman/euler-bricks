#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-check that --prune produces identical results to the unpruned fast
search over a given range. Run this on a representative sample range
before trusting --prune for a large unattended search.

Why this exists: the divisibility conditions --prune relies on (see
PRUNE_MODS and its comment in main.py) were validated empirically against
every Euler brick found in 1-3,000 and 1-20,000, not against a primary
source (WebFetch to Wikipedia/MathWorld/the original paper was blocked by
network policy when this was written). This script lets that validation
be repeated/extended on demand instead of taking it on faith.

Usage: python3 check_prune.py [MIN-MAX]   (default: 1-20000)
"""
import csv
import os
import subprocess
import sys
import tempfile


def run(range_arg, prune):
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        path = tmp.name
    os.unlink(path)  # main.py's log_result() checks os.path.exists() to
                      # decide whether to write the CSV header; leaving the
                      # (empty) tempfile in place tricks it into thinking
                      # there's already a header, and every row after
                      # shifts by one.
    cmd = ["python3", "main.py", "--range", range_arg, "--no-gui", "--log", path]
    if prune:
        cmd.append("--prune")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    os.unlink(path)
    return sorted(tuple(row) for row in rows[1:]) if rows else []


def main():
    range_arg = sys.argv[1] if len(sys.argv) > 1 else "1-20000"
    print("[Info] Running unpruned search over {}...".format(range_arg))
    unpruned = run(range_arg, prune=False)
    print("[Info] Running --prune search over {}...".format(range_arg))
    pruned = run(range_arg, prune=True)

    if unpruned == pruned:
        print("OK: --prune matched the unpruned search over {} ({} bricks).".format(
            range_arg, len(unpruned)))
        return 0

    missing = sorted(set(unpruned) - set(pruned))
    extra = sorted(set(pruned) - set(unpruned))
    print("MISMATCH over {}!".format(range_arg))
    print("  bricks --prune missed ({}): {}".format(len(missing), missing[:5]))
    print("  bricks --prune added  ({}): {}".format(len(extra), extra[:5]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
