#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-check --perfect-only's pruning against an independent, from-scratch
implementation of the same conditions.

No perfect cuboid is known to exist, so comparing logged output directly
(the way check_prune.py compares --prune's CSV) doesn't work here: the
search only logs a candidate once it's a *verified* perfect cuboid
(exact isqrt check on the space diagonal), which will correctly be empty
on any testable range whether or not the pruning itself is right. What
this checks instead is the pruning in isolation: call search_bricks()
directly with perfect_only=True and compare which (a, b, c) survive
against a second, separately-written function (not perfect_only_requirements
from main.py) that re-derives the same necessary conditions from scratch
and checks every real Euler brick in the range against them. This catches
implementation bugs in the pruning logic even though, without a known
perfect cuboid, it can't validate the underlying divisibility claims
themselves -- see ROADMAP.md's Stage 2 addendum for where those came from.

Usage: python3 check_perfect_only.py [MIN-MAX]   (default: 1-20000)
"""
import sys

import main


def edges_satisfy_perfect_only_conditions(a, b, c):
    """Independent re-derivation (not reusing perfect_only_requirements)
    of the edge-only necessary conditions for a perfect cuboid, from
    Wikipedia's "Euler brick" article, "Perfect cuboid" section:
      - two of the three edges divisible by 3, at least one of those two
        also divisible by 9
      - one edge divisible by 5, one by 7, one by 11, one by 16, one by 19
      - at least one edge odd
    (Skips the conditions involving a face diagonal or the space diagonal
    -- 13/17/29/37 -- since the exact isqrt check on g already covers
    correctness there; see main.py's comment above PERFECT_ONLY_SIMPLE_MODS.)
    """
    edges = (a, b, c)
    div3 = [e for e in edges if e % 3 == 0]
    if len(div3) < 2 or not any(e % 9 == 0 for e in div3):
        return False
    for m in (5, 7, 11, 16, 19):
        if not any(e % m == 0 for e in edges):
            return False
    if not any(e % 2 == 1 for e in edges):
        return False
    return True


def main_check():
    range_arg = sys.argv[1] if len(sys.argv) > 1 else "1-20000"
    lo_str, hi_str = range_arg.split("-")
    a_start, a_end = max(int(lo_str), 1), int(hi_str)
    a_values = range(a_start, a_end)

    print("[Info] Running unfiltered search over {} for ground truth...".format(range_arg))
    all_bricks = [(a, b, c) for a, b, c, d, e, f in main.search_bricks(a_values, a_end, False, False)]
    expected = sorted(t for t in all_bricks if edges_satisfy_perfect_only_conditions(*t))
    print("[Info] {} total Euler bricks found; {} independently satisfy the "
          "perfect-only conditions (not necessarily actual perfect cuboids -- "
          "these are only the necessary, not sufficient, conditions).".format(
              len(all_bricks), len(expected)))

    print("[Info] Running search_bricks(..., perfect_only=True) over {}...".format(range_arg))
    actual = sorted((a, b, c) for a, b, c, d, e, f in main.search_bricks(a_values, a_end, False, True))

    if actual == expected:
        print("OK: --perfect-only's pruning matches the independent check exactly "
              "({} candidates survive out of {} total Euler bricks over {}).".format(
                  len(expected), len(all_bricks), range_arg))
        ok = True
    else:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        print("MISMATCH over {}!".format(range_arg))
        print("  pruning wrongly excluded ({}): {}".format(len(missing), missing[:5]))
        print("  pruning wrongly included ({}): {}".format(len(extra), extra[:5]))
        ok = False

    perfect_found = sum(1 for a, b, c in actual if main.EulerBrick.is_perfect_square(a*a+b*b+c*c)[0])
    print("[Info] Of the {} candidates, {} are verified perfect cuboids "
          "(expected 0 -- none are known to exist).".format(len(actual), perfect_found))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_check())
