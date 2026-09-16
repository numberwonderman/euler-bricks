#!/usr/bin/env python3
# -*- coding: utf-8 -*-"
"""
Euler-Bricks - 2020 - by psy (epsylon@riseup.net)

Extended: exact integer perfect-square checks (no float precision loss),
perfect-cuboid (space-diagonal) detection, CSV result logging, a
non-interactive --range/--no-gui CLI mode for unattended/headless runs,
and (Stage 1 of ROADMAP.md) a divisor-driven search that replaces the
O(n^2)-ish brute-force triple loop.

You should have received a copy of the GNU General Public License along
with Euler-Bricks; if not, write to the Free Software Foundation, Inc., 51
Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""
import argparse
import csv
import json
import math
import multiprocessing
import os
import signal
import sys
from functools import lru_cache

LEARNING_MODES = {"l", "learn", "learning"}
CHECKPOINT_INTERVAL = 1000  # persist progress every this many `a` values processed


class _Interrupted(Exception):
    """Raised by the SIGTERM handler installed in generate_bricks_parallel.

    SIGTERM's default action terminates the process immediately without
    running Python cleanup code -- including multiprocessing.Pool's
    __exit__, which is what calls pool.terminate() on its worker
    processes. Without this, a hard kill (`timeout`, `kill`, a container
    orchestrator's stop signal) leaves the Pool's worker subprocesses
    orphaned and still running (they're daemonic, so they'd normally be
    cleaned up via the parent's atexit handling, but a fatal signal
    bypasses atexit entirely). An orphaned worker can then race a
    subsequent --checkpoint resume, corrupting its output -- caught via
    check_checkpoint.py, not by reasoning about the code. Converting
    SIGTERM into a raised exception lets it unwind through the `with
    multiprocessing.Pool(...)` block normally, so __exit__ still runs.
    """


def _prime_factors(n):
    factors = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] = factors.get(d, 0) + 1
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors[n] = factors.get(n, 0) + 1
    return factors


def _divisors_from_factors(factors):
    divs = [1]
    for p, e in factors.items():
        divs = [d * p**i for d in divs for i in range(e + 1)]
    return divs


# Bounded, not unbounded: found via a real incident (see ROADMAP.md Stage
# 3) where --workers 4 on 1-2,000,000 pushed each worker's RSS past 4.3GB
# with no cap -- 12GB+ total on a 15GB sandbox with no swap -- and had to
# be killed before it plausibly OOM'd the container. Every worker process
# has its own copy of this cache (no cross-process sharing), so
# --workers N multiplies whatever this holds by N.
#
# maxsize is picked from a measured cost, not a guess: caching a=1..1M in
# one process measured ~3.3KB/entry (mostly lru_cache's own bookkeeping,
# not the data itself) -> ~3.3GB for a million entries, matching the
# incident above almost exactly. 200,000 entries caps that at ~550MB per
# process (~2.2GB total at --workers 4), leaving headroom on an ordinary
# machine, not just this sandbox. Stage 2's profiling already found
# factoring isn't the search's bottleneck, so trading some re-factoring
# of evicted values for a hard memory ceiling is cheap.
@lru_cache(maxsize=200_000)
def pythagorean_partners(a):
    """All (b, d) with a^2 + b^2 = d^2 and b > 0.

    Derived from divisor pairs (s, t) of a^2 with s*t = a^2, s < a
    (b = (t-s)/2, d = (t+s)/2), instead of scanning every candidate b.
    Cost is driven by the number of divisors of a^2, not by the search
    range -- this is what makes the search scale past a brute-force
    triple loop. See ROADMAP.md Stage 1.
    """
    if a <= 0:
        return ()
    factors_sq = {p: 2 * e for p, e in _prime_factors(a).items()}
    asq = a * a
    results = []
    for s in _divisors_from_factors(factors_sq):
        if s >= a:
            continue
        t = asq // s
        if (s + t) % 2 != 0:
            continue
        b = (t - s) // 2
        d = (t + s) // 2
        if b > 0:
            results.append((b, d))
    return tuple(sorted(results))


# Stage 2 (ROADMAP.md): necessary conditions on an Euler brick's three edges
# -- at least one edge divisible by 3, one by 4, one by 5, one by 11 --
# reported by multiple secondary sources discussing perfect-cuboid
# constraints (Leech 1977; Lal & Blundon), traced back to the classical
# Euler-brick parametrization. WebFetch to the primary sources (Wikipedia,
# MathWorld, the Roberts 2010 AustMS paper) was blocked by this session's
# network policy, so these were NOT verified against a primary source --
# only empirically, against every real Euler brick this tool found in
# 1-3,000 (39 bricks) and 1-20,000 (320 bricks): zero violations of any of
# the four conditions in either run. That is reassuring but not a proof, so
# this stays opt-in (--prune) rather than folded into the default search,
# and check_prune.py exists to re-validate --prune against the unpruned
# search on any range before trusting it for an unattended run.
PRUNE_MODS = (3, 4, 5, 11)


def required_modulus_for_third_edge(a, b, mods=PRUNE_MODS):
    """Given two edges of a candidate brick, what single modulus must the
    third edge be divisible by, because neither a nor b already covers all
    of `mods`? (If a or b already covers a given modulus, the third edge is
    unconstrained by it.) Returns the product of the still-unsatisfied
    mods -- valid as a single combined check because PRUNE_MODS are
    pairwise coprime -- or 1 if a and b together already satisfy all of
    them (no constraint on the third edge).
    """
    product = 1
    for m in mods:
        if a % m != 0 and b % m != 0:
            product *= m
    return product


# Stage 2 addendum: conditions specific to a PERFECT CUBOID (not general
# Euler bricks), sourced from Wikipedia's "Euler brick" article ("Perfect
# cuboid" section) after the user pasted its text directly into this
# project -- WebFetch to it earlier in this project was blocked by network
# policy, which is why PRUNE_MODS above stayed limited to the weaker,
# empirically-checked subset. These are stated for a PRIMITIVE perfect
# cuboid, but divisibility is multiplicative (if the primitive edge is a
# multiple of m, so is k times it for any k), so they carry over unchanged
# to any perfect cuboid's raw edges -- safe to apply directly here.
#
# Conditions used (edge-only; the ones involving a face diagonal or the
# space diagonal -- divisible by 13/17/29/37 -- are skipped, since they
# can't prune before a full candidate exists, and the search already does
# an exact isqrt check on the space diagonal at that point anyway):
#   - one edge must be odd
#   - one edge must be divisible by 16 (the source's parity condition
#     names a *different* edge divisible only by 4, distinct from the one
#     divisible by 16 -- requiring 16 alone is a safe subset: divisible by
#     16 implies divisible by 4, so this can only be weaker than the true
#     condition, never wrongly reject a valid cuboid)
#   - one edge divisible by 5, one by 7, one by 11, one by 19
#   - TWO edges divisible by 3, and at least one of those two also by 9
#     (stronger than PRUNE_MODS' "one edge by 3" -- this is what can prove
#     a whole (a, b) pair impossible before ever considering a c)
PERFECT_ONLY_SIMPLE_MODS = (5, 7, 11, 16, 19)


def perfect_only_requirements(a, b):
    """Given two edges of a candidate perfect cuboid, what must the third
    edge (c) satisfy -- or is this (a, b) pair already impossible?

    Returns None if no c could complete a valid perfect-cuboid candidate
    with this (a, b) -- skip the pair entirely -- otherwise
    (required_mod, required_odd): the combined modulus (product of
    whichever of PERFECT_ONLY_SIMPLE_MODS, plus 3 or 9 if needed, aren't
    already covered by a or b -- all pairwise coprime, so a single product
    check is valid) c must be divisible by, and whether c must be odd.
    """
    a3, b3 = a % 3 == 0, b % 3 == 0
    a9, b9 = a % 9 == 0, b % 9 == 0
    count3 = a3 + b3
    extra_mod = 1
    if count3 == 0:
        return None  # c alone can't supply "two edges divisible by 3"
    elif count3 == 1:
        if a9 or b9:
            extra_mod = 3
        else:
            extra_mod = 9  # c must cover both "divisible by 3" and "by 9"
    else:  # count3 == 2
        if not (a9 or b9):
            return None  # neither 3-divisible edge is 9-divisible; c can't fix that retroactively

    required_mod = required_modulus_for_third_edge(a, b, mods=PERFECT_ONLY_SIMPLE_MODS)
    if extra_mod != 1 and required_mod % extra_mod != 0:
        required_mod *= extra_mod
    required_odd = (a % 2 == 0) and (b % 2 == 0)
    return required_mod, required_odd


def _bricks_for_a(a, range_end, prune, perfect_only):
    """Yields (a, b, c, d, e, f) Euler-brick tuples for this single a.

    Factored out from search_bricks (below) so Stage 4's checkpointing can
    drive its own `for a in ...` loop and persist progress after each `a`
    completes -- most `a` values yield zero bricks, so checkpointing only
    when a brick is *found* would leave checkpoints stale for long,
    unpredictable stretches. This is the same algorithm as before the
    refactor, just callable one `a` at a time.
    """
    partners_a = [(v, diag) for (v, diag) in pythagorean_partners(a) if a < v < range_end]
    if not partners_a:
        return
    a_diag_for = dict(partners_a)
    for b, d in partners_a:
        required_odd = False
        if perfect_only:
            req = perfect_only_requirements(a, b)
            if req is None:
                continue
            required_mod, required_odd = req
        elif prune:
            required_mod = required_modulus_for_third_edge(a, b)
        else:
            required_mod = 1
        for c, f in pythagorean_partners(b):
            if c <= b or c >= range_end:
                continue
            if required_mod != 1 and c % required_mod != 0:
                continue
            if required_odd and c % 2 == 0:
                continue
            e = a_diag_for.get(c)
            if e is None:
                continue
            yield (a, b, c, d, e, f)


def search_bricks(a_values, range_end, prune, perfect_only=False):
    """Yields (a, b, c, d, e, f) Euler-brick tuples for each a in a_values,
    checked against the shared range_end bound (b, c < range_end).

    Module-level and side-effect-free (no printing/logging/drawing) so it
    is exactly the same code path for the single-process search
    (generate_bricks_fast) and each worker in the multiprocessing search
    (Stage 3, --workers) -- one implementation to trust instead of two
    that could silently diverge. a_values is any iterable (a contiguous
    range for the single-process case; a strided range.range(start, end,
    workers) per worker, so factoring cost -- which grows with a -- is
    spread evenly across workers instead of dumping all the expensive
    large-a work on whichever worker got the last contiguous block).

    perfect_only (Stage 2 addendum) applies the stronger, perfect-cuboid-
    specific conditions above instead of -- not in addition to -- `prune`'s
    general-Euler-brick-safe conditions, including skipping an (a, b) pair
    outright when it's already provably impossible. Still yields ordinary
    (non-perfect) Euler bricks that happen to pass -- most candidates that
    satisfy these necessary conditions still won't have an integer space
    diagonal -- the caller decides whether to report those (see
    report_brick / _worker_search, which check g_ok before printing/
    logging when perfect_only is set).
    """
    for a in a_values:
        yield from _bricks_for_a(a, range_end, prune, perfect_only)


# Stage 4 (ROADMAP.md): checkpoint/resume, so a long unattended search can
# be stopped and picked back up instead of restarting from the beginning
# of the range. A run is modeled as N independent "lanes" over `a` values:
# 1 lane (stride 1) for the single-process search, `workers` lanes (each
# stride `workers`, round-robin per Stage 3) for --workers. Each lane
# tracks the last `a` it fully finished in its own small file, so workers
# never contend writing the same file. `meta.json` records the settings a
# checkpoint was created with; resuming with different settings (a
# different range, prune/perfect_only, or a different worker count, which
# would change what each lane's stride even means) is refused rather than
# silently producing wrong or incomplete results.
def _checkpoint_meta_path(checkpoint_dir):
    return os.path.join(checkpoint_dir, "meta.json")


def _checkpoint_lane_path(checkpoint_dir, lane_id):
    return os.path.join(checkpoint_dir, "lane_{}.txt".format(lane_id))


def checkpoint_settings(a_start, a_end, prune, perfect_only, workers):
    return {
        "a_start": a_start, "a_end": a_end,
        "prune": bool(prune), "perfect_only": bool(perfect_only),
        "workers": workers,
    }


def load_or_init_checkpoint(checkpoint_dir, settings, num_lanes):
    """Returns a list of `num_lanes` resume points: the next `a` each lane
    should process (a_start + lane_id for a fresh lane, or the lane's last
    completed `a` plus its stride if resuming). Creates the checkpoint dir
    and meta.json on first use; on a later run, validates meta.json
    matches `settings` exactly before trusting any lane files found there.
    """
    meta_path = _checkpoint_meta_path(checkpoint_dir)
    stride = settings["workers"]
    a_start = settings["a_start"]
    if os.path.exists(checkpoint_dir):
        if not os.path.exists(meta_path):
            sys.exit("[Error] Checkpoint dir '{}' exists but has no meta.json -- "
                      "refusing to guess whether it's safe to reuse. Remove it or "
                      "pick a different --checkpoint path.".format(checkpoint_dir))
        with open(meta_path) as fh:
            saved = json.load(fh)
        if saved != settings:
            sys.exit("[Error] Checkpoint at '{}' was created with different settings.\n"
                      "  saved:   {}\n  this run: {}\n"
                      "Remove the checkpoint, or match the original --range/--prune/"
                      "--perfect-only/--workers to resume.".format(checkpoint_dir, saved, settings))
        print("[Info] Resuming from checkpoint at '{}'...\n".format(checkpoint_dir))
    else:
        os.makedirs(checkpoint_dir)
        with open(meta_path, "w") as fh:
            json.dump(settings, fh)

    resume_points = []
    for lane_id in range(num_lanes):
        lane_path = _checkpoint_lane_path(checkpoint_dir, lane_id)
        if os.path.exists(lane_path):
            with open(lane_path) as fh:
                last_done = int(fh.read().strip())
            resume_points.append(last_done + stride)
        else:
            resume_points.append(a_start + lane_id)
    return resume_points


def load_logged_keys(log_file):
    """Returns the set of (a, b, c) already present in log_file (empty set
    if it doesn't exist yet). Used to dedupe a checkpointed run's redo
    window: checkpoints save every CHECKPOINT_INTERVAL `a` values, not
    every single one, so an interruption between saves means the next
    resume re-searches (and, without this, would re-log) whatever `a`
    values were already processed-and-logged past the last save point.
    """
    keys = set()
    if not log_file or not os.path.exists(log_file):
        return keys
    with open(log_file, newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if len(row) >= 3:
                keys.add((int(row[0]), int(row[1]), int(row[2])))
    return keys


def save_lane_progress(checkpoint_dir, lane_id, last_a):
    # Write to a temp file then rename: an interruption mid-write (e.g. the
    # process killed at exactly the wrong moment) leaves the old, still-valid
    # checkpoint in place instead of a half-written/corrupt one.
    lane_path = _checkpoint_lane_path(checkpoint_dir, lane_id)
    tmp_path = lane_path + ".tmp"
    with open(tmp_path, "w") as fh:
        fh.write(str(last_a))
    os.replace(tmp_path, lane_path)


def _worker_search(task):
    """Runs in a worker process (Stage 3, --workers): searches one lane of
    `a` values, printing/logging its own finds as it goes (prefixed with
    the worker id) instead of returning everything to the main process to
    report at the end -- that would buffer all output until the whole run
    finishes, losing the live progress a long unattended search depends
    on. Returns (bricks_found, perfect_found) so the main process can
    print a final summary.

    Iterates `a` one at a time (via _bricks_for_a, not search_bricks)
    rather than a single flat generator so it can persist checkpoint
    progress (Stage 4, --checkpoint) after each `a` -- most `a` values
    yield no bricks, so checkpointing only when a brick is found would
    leave the checkpoint stale for long, unpredictable stretches.
    """
    a_start, range_end, prune, perfect_only, stride, worker_id, part_log_path, checkpoint_dir = task
    writer = None
    log_fh = None
    logged_keys = None
    if part_log_path:
        is_new = not os.path.exists(part_log_path)
        if checkpoint_dir and not is_new:
            # Resuming: this lane's part-log may already hold results from
            # past the last checkpoint save (checkpoints save every
            # CHECKPOINT_INTERVAL `a` values, not every one) -- dedupe
            # against them instead of re-logging the same bricks. See
            # ROADMAP.md Stage 4 for how this was caught.
            logged_keys = load_logged_keys(part_log_path)
        log_fh = open(part_log_path, "a", newline="")  # append: a resumed run's
        # earlier (pre-interruption) results for this lane must survive, not be
        # truncated just because this invocation resumes past them.
        writer = csv.writer(log_fh)
        if is_new:
            writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
    bricks_found = 0
    perfect_found = 0
    last_checkpoint_a = a_start - stride
    try:
        for a in range(a_start, range_end, stride):
            for _, b, c, d, e, f in _bricks_for_a(a, range_end, prune, perfect_only):
                g_ok, g = EulerBrick.is_perfect_square(a*a + b*b + c*c)
                if g_ok:
                    perfect_found += 1
                elif perfect_only:
                    continue  # perfect_only: only report/log/count verified perfect cuboids
                if logged_keys is not None:
                    key = (a, b, c)
                    if key in logged_keys:
                        continue
                    logged_keys.add(key)
                bricks_found += 1
                tag = "[!!!] PERFECT CUBOID FOUND" if g_ok else "[Info] Found 'brick'"
                print("[W{}] {} -- {}:{}:{}  dZY={} dXZ={} dXY={}{}".format(
                    worker_id, tag, c, b, a, d, e, f,
                    "  g={}".format(g) if g_ok else ""))
                if writer:
                    writer.writerow([a, b, c, d, e, f, g if g_ok else "", g_ok])
            if checkpoint_dir and (a - last_checkpoint_a) >= CHECKPOINT_INTERVAL * stride:
                # Flush the log BEFORE saving the checkpoint, not after: log_fh
                # stays open (and buffered) for this whole function, unlike
                # log_result's open-write-close-per-row, so without this a hard
                # kill (timeout/SIGTERM skips `finally`) can lose buffered rows
                # for `a` values the checkpoint already claims are done --
                # caught via an actual interrupt-and-resume test, see
                # ROADMAP.md Stage 4.
                if log_fh:
                    log_fh.flush()
                save_lane_progress(checkpoint_dir, worker_id, a)
                last_checkpoint_a = a
        if checkpoint_dir:
            # Loop finished normally (not killed) -- this lane is fully done.
            if log_fh:
                log_fh.flush()
            save_lane_progress(checkpoint_dir, worker_id, range_end - 1)
    finally:
        if log_fh:
            log_fh.close()
    return bricks_found, perfect_found


class EulerBrick(object):
    def __init__(self):
        self.store_bricks = "bricks/"
        self.mode = "manual"
        self.no_gui = False
        self.log_file = None
        self.brute_force = False
        self.prune = False
        self.perfect_only = False
        self.workers = 1
        self.checkpoint_dir = None
        self._logged_keys = None  # set of (a,b,c) already in self.log_file, when resuming a checkpoint

    def banner(self):
        print(75*"=")
        print("  _____      _           ____       _      _         ")
        print(" | ____|   _| | ___ _ __| __ ) _ __(_) ___| | _____  ")
        print(" |  _|| | | | |/ _ \\ '__|  _ \\| '__| |/ __| |/ / __| ")
        print(" | |__| |_| | |  __/ |  | |_) | |  | | (__|   <\\__ \\ ")
        print(" |_____\\__,_|_|\\___|_|  |____/|_|  |_|\\___|_|\\_\\___/ ")
        print("                                                     ")
        print(75*"=","\n")
        print(" Does a 'perfect cuboid' exist?\n")
        print(75*"=","\n")

    def run(self, args=None):
        self.banner()
        if args is not None and args.range_:
            self.mode = args.mode
            self.root = args.range_
            self.no_gui = args.no_gui
            self.log_file = args.log_file
            self.brute_force = args.brute_force
            self.prune = args.prune
            self.perfect_only = args.perfect_only
            self.workers = args.workers
            self.checkpoint_dir = args.checkpoint_dir
        else:
            self.mode = input(" -Set mode: manual (default), learning (M/l): ")
            self.root = input(" -Set range (ex: 1-1000 or 1000-1000000 (PRESS ENTER = 1-1000) (STOP = CTRL+z): ")
            if not self.root:
                self.root = "1-1000"
            self.no_gui = False
            self.log_file = None
            self.brute_force = False
            self.prune = False
            self.perfect_only = False
            self.workers = 1
            self.checkpoint_dir = None
        print("\n[Info] Looking for 'bricks' in the range: "+ str(self.root)+ "\n")
        if self.workers > 1:
            self.generate_bricks_parallel(self.root, self.workers)
        elif self.brute_force:
            self.generate_bricks_bruteforce(self.root)
        else:
            self.generate_bricks_fast(self.root)

    @staticmethod
    def is_perfect_square(n):
        """Exact integer perfect-square test (math.isqrt has no float
        precision loss, unlike math.sqrt(n).is_integer() on large n)."""
        if n < 0:
            return False, 0
        r = math.isqrt(n)
        return (r * r == n), r

    @staticmethod
    def _parse_range(rng):
        srng = rng.split('-')
        try:
            minrange = int(srng[0])
            maxrange = int(srng[1])
        except (ValueError, IndexError):
            print(40*"-"+"\n")
            print("[Error] Numbers on range should be integers (ex: 1-1000). Aborting...\n")
            sys.exit(2)
        if minrange >= maxrange:
            print(40*"-"+"\n")
            print("[Error] Min range should be minor than max range (ex: 1-1000). Aborting...\n")
            sys.exit(2)
        return minrange, maxrange

    def log_result(self, a, b, c, d, e, f, g, perfect):
        if not self.log_file:
            return
        if self._logged_keys is not None:
            # Checkpointed run: the redo window between the last checkpoint
            # save and the actual interruption point gets re-searched on
            # resume (checkpoints are saved periodically, not after every
            # single `a`), which would otherwise re-log the same bricks --
            # see ROADMAP.md Stage 4 for how this was caught.
            key = (a, b, c)
            if key in self._logged_keys:
                return
            self._logged_keys.add(key)
        is_new = not os.path.exists(self.log_file)
        with open(self.log_file, "a", newline="") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
            writer.writerow([a, b, c, d, e, f, g if g is not None else "", perfect])

    def report_brick(self, a, b, c, d, e, f, n):
        g_ok, g = self.is_perfect_square(a*a + b*b + c*c)
        if self.perfect_only and not g_ok:
            return  # perfect_only: only report/log/draw verified perfect cuboids
        print(40*"-"+"\n")
        if g_ok:
            print("[!!!] PERFECT CUBOID FOUND -- space diagonal is also an integer!\n")
        else:
            print("[Info] Found 'brick'!!\n")
        print(" -ID: {} ({})".format(n, str(c)+':'+str(b)+':'+str(a)))
        print(" -Hedges: X={} Y={} Z={}".format(c, b, a))
        print(" -Diagonals: dZY={} dXZ={} dXY={}".format(d, e, f))
        if g_ok:
            print(" -Space diagonal: g={}".format(g))
        self.log_result(a, b, c, d, e, f, g if g_ok else None, g_ok)
        if not self.no_gui:
            self.draw(a, b, c, d, e, f, n, perfect=g_ok)

    def generate_bricks_fast(self, rng):
        """Stage 1: divisor-driven search (see pythagorean_partners above).

        For each `a`, generate every `b` with a^2+b^2 square directly
        (instead of scanning). For each such `b`, generate every `c` with
        b^2+c^2 square the same way, and keep only the `c`s that also
        appear in a's own partner set (so a^2+c^2 is square too) -- an
        Euler brick, with no wasted scanning of non-candidates.

        With self.prune (Stage 2, --prune), also skips candidate `c` values
        that cannot satisfy the empirically-validated-but-not-proven
        necessary divisibility conditions in PRUNE_MODS -- see the comment
        above PRUNE_MODS for exactly what that means and its caveats.

        With self.perfect_only (Stage 2 addendum, --perfect-only), applies
        the stronger perfect-cuboid-specific conditions instead, and
        report_brick suppresses anything that isn't a verified perfect
        cuboid (see PERFECT_ONLY_SIMPLE_MODS and perfect_only_requirements
        above for exactly what's checked and why it's safe to apply).

        With self.checkpoint_dir (Stage 4, --checkpoint), periodically
        persists the highest `a` fully processed so an interrupted run can
        resume instead of restarting from the beginning of the range.
        log_result() already appends rather than truncates, so a resumed
        run's earlier results survive automatically.
        """
        minrange, maxrange = self._parse_range(rng)
        self.init = minrange
        self.end = maxrange
        n = 0
        if not self.no_gui and not os.path.exists(self.store_bricks):
            os.mkdir(self.store_bricks)
        a_start = max(self.init, 1)

        if self.checkpoint_dir:
            settings = checkpoint_settings(a_start, self.end, self.prune, self.perfect_only, workers=1)
            a_resume = load_or_init_checkpoint(self.checkpoint_dir, settings, num_lanes=1)[0]
            if a_resume >= self.end:
                print("[Info] Checkpoint shows this range is already complete; nothing to do.\n")
                return
            if a_resume > a_start:
                print("[Info] Resuming from a={} (of {}-{})\n".format(a_resume, a_start, self.end))
            self._logged_keys = load_logged_keys(self.log_file)
        else:
            a_resume = a_start

        last_checkpoint_a = a_resume - 1
        for a in range(a_resume, self.end):
            for _, b, c, d, e, f in _bricks_for_a(a, self.end, self.prune, self.perfect_only):
                n += 1
                self.report_brick(a, b, c, d, e, f, n)
            if self.checkpoint_dir and (a - last_checkpoint_a) >= CHECKPOINT_INTERVAL:
                save_lane_progress(self.checkpoint_dir, 0, a)
                last_checkpoint_a = a
        if self.checkpoint_dir:
            save_lane_progress(self.checkpoint_dir, 0, self.end - 1)

    def generate_bricks_parallel(self, rng, workers):
        """Stage 3 (ROADMAP.md): partitions the outer `a` loop across
        `workers` processes. Each `a` produces bricks attributed to it
        alone (b, c are always > a), so splitting the outer loop into
        non-overlapping subsets partitions the result set exactly -- no
        duplicate or missed bricks, no coordination needed between workers
        beyond merging their output at the end.

        Workers are assigned a values round-robin (worker i gets
        a_start+i, a_start+i+workers, a_start+i+2*workers, ...) rather than
        contiguous blocks: per-a cost grows with a (bigger numbers take
        longer to factor), so a contiguous "last worker gets the largest
        a's" split leaves that worker running long after the others finish.
        Striping spreads cheap and expensive a's evenly across workers.

        Requires --no-gui: matplotlib popups across multiple processes
        aren't supported, and draw()'s self.mode prompt doesn't apply here.

        With self.checkpoint_dir (Stage 4, --checkpoint), each lane (one
        per worker) persists its own progress, and a resumed run picks up
        each lane where it left off instead of restarting the whole range.
        If every lane is already complete, returns immediately without
        touching self.log_file -- rebuilding it from empty/no part files
        would silently truncate a result set a previous run already
        finished writing.
        """
        minrange, maxrange = self._parse_range(rng)
        self.init = minrange
        self.end = maxrange
        a_start = max(self.init, 1)
        a_end = self.end
        total_a = a_end - a_start
        if total_a <= 0:
            return
        workers = max(1, min(workers, total_a))

        if self.checkpoint_dir:
            settings = checkpoint_settings(a_start, a_end, self.prune, self.perfect_only, workers)
            resume_points = load_or_init_checkpoint(self.checkpoint_dir, settings, num_lanes=workers)
            if all(rp >= a_end for rp in resume_points):
                print("[Info] Checkpoint shows this range is already complete; nothing to do.\n")
                return
        else:
            resume_points = [a_start + i for i in range(workers)]

        part_paths = [
            "{}.part{}".format(self.log_file, i) if self.log_file else None
            for i in range(workers)
        ]
        tasks = [
            (resume_points[i], a_end, self.prune, self.perfect_only, workers, i,
             part_paths[i], self.checkpoint_dir)
            for i in range(workers)
        ]
        print("[Info] Striping a in [{}, {}) round-robin across {} worker process(es)...\n".format(
            a_start, a_end, workers))
        with multiprocessing.Pool(workers) as pool:
            # Installed only now, after Pool(workers) has already forked its
            # workers: they inherit whatever handler was active at fork time,
            # and this one should stay parent-only (a worker receiving SIGTERM
            # from pool.terminate() below should just die immediately, not
            # also try to raise/unwind this same exception in a function it
            # isn't wrapped to catch).
            old_handler = signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(_Interrupted()))
            try:
                results = pool.map(_worker_search, tasks)
            except _Interrupted:
                # Pool.__exit__ still runs after this (terminate()+join() on
                # every worker) as this unwinds through the `with` block --
                # see _Interrupted's docstring. Don't touch self.log_file: the
                # run didn't finish, and each lane's own part-log/checkpoint
                # already has whatever it durably completed, ready for the
                # next --checkpoint resume.
                print("\n[Info] Interrupted -- worker processes terminated cleanly. "
                      "Re-run with the same --checkpoint to resume.\n")
                sys.exit(1)
            finally:
                signal.signal(signal.SIGTERM, old_handler)

        total_bricks = sum(r[0] for r in results)
        total_perfect = sum(r[1] for r in results)
        print("\n"+40*"-")
        print("[Info] Done. {} brick(s) found across {} worker(s) ({} perfect cuboid(s)).".format(
            total_bricks, workers, total_perfect))

        if self.log_file:
            with open(self.log_file, "w", newline="") as out_fh:
                writer = csv.writer(out_fh)
                writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
                for part_path in part_paths:
                    if part_path and os.path.exists(part_path):
                        with open(part_path, newline="") as in_fh:
                            reader = csv.reader(in_fh)
                            next(reader, None)  # skip that shard's own header
                            for row in reader:
                                writer.writerow(row)
                        os.remove(part_path)

    def generate_bricks_bruteforce(self, rng):
        """Original O(n^2)-ish triple-loop search, kept for cross-checking
        generate_bricks_fast's results on small ranges (--brute-force)."""
        minrange, maxrange = self._parse_range(rng)
        self.init = minrange
        self.end = maxrange
        n = 0
        if not self.no_gui and not os.path.exists(self.store_bricks):
            os.mkdir(self.store_bricks)
        for a in range(self.init, self.end):
            asq = a * a
            for b in range(a, self.end):
                bsq = b * b
                d_ok, d = self.is_perfect_square(asq + bsq)
                if not d_ok:
                    continue
                for c in range(b, self.end):
                    csq = c * c
                    e_ok, e = self.is_perfect_square(asq + csq)
                    if not e_ok:
                        continue
                    f_ok, f = self.is_perfect_square(bsq + csq)
                    if not f_ok:
                        continue
                    n += 1
                    self.report_brick(a, b, c, d, e, f, n)

    def draw(self, a, b, c, d, e, f, n, perfect=False):
        import numpy as np
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import matplotlib.pyplot as plt
        plt.rcParams.update({'figure.max_open_warning': 0})

        points = np.array([[c, b, a],
                  [c, -b, -a],
                  [c, b, -a ],
                  [-c, b, -a],
                  [-c, -b, a],
                  [c, -b, a ],
                  [c, b, a  ],
                  [-c, b, a]])
        P = [[2.06498904e-01 , -6.30755443e-07 ,  1.07477548e-03],
            [1.61535574e-06 ,  1.18897198e-01 ,  7.85307721e-06],
            [7.08353661e-02 ,  4.48415767e-06 ,  2.05395893e-01]]
        Z = np.zeros((8,3))
        for i in range(8): Z[i,:] = np.dot(points[i,:],P)
        Z = 1*Z
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        r = [-1,1]
        X, Y = np.meshgrid(r, r)
        ax.scatter3D(Z[:, 0], Z[:, 1], Z[:, 2])
        verts = [[Z[0],Z[1],Z[2],Z[3]],
                [Z[4],Z[5],Z[6],Z[7]],
                [Z[0],Z[1],Z[5],Z[4]],
                [Z[2],Z[3],Z[7],Z[6]],
                [Z[1],Z[2],Z[6],Z[5]],
                [Z[4],Z[7],Z[3],Z[0]]]
        verts2 = [[-Z[0],-Z[1],-Z[2],-Z[3]],
                [-Z[4],-Z[5],-Z[6],-Z[7]],
                [-Z[0],-Z[1],-Z[5],-Z[4]],
                [-Z[2],-Z[3],-Z[7],-Z[6]],
                [-Z[1],-Z[2],-Z[6],-Z[5]],
                [-Z[4],-Z[7],-Z[3],-Z[0]]]
        facecolor = 'gold' if perfect else 'cyan'
        ax.add_collection3d(Poly3DCollection(verts, facecolors=facecolor, linewidths=1, edgecolors='r', alpha=.25))
        ax.add_collection3d(Poly3DCollection(verts2, facecolors=facecolor, linewidths=0, edgecolors='r', alpha=.25))
        ax.set_xlabel("X: {} dXY: {} dXZ: {}".format(int(c),int(f),int(e)))
        ax.set_ylabel("Y: {} dYX: {} dYZ: {}".format(int(b),int(f),int(d)))
        ax.set_zlabel("Z: {} dZX: {} dZY: {}".format(int(a),int(e),int(d)))
        ax.w_xaxis.set_ticklabels("")
        ax.w_yaxis.set_ticklabels("")
        ax.w_zaxis.set_ticklabels("")
        title = "PERFECT CUBOID" if perfect else "Euler's brick"
        header = "[{} {}".format(title, "x:"+str(c)+' y:'+str(b)+' z:'+str(a) + "]\n")
        fig.canvas.set_window_title("Euler's brick ID: {} ".format(n))
        plt.title(header)
        prefix = "PERFECT_CUBOID-" if perfect else ""
        outfile = self.store_bricks+prefix+str(c)+'_'+str(b)+'_'+str(a)+"-euler_brick.png"
        if not os.path.exists(outfile):
            fig.savefig(outfile)
            print("\n[Info] Generated 'brick' image at: "+outfile+"\n")
        else:
            print("\n[Info] You have previously saved this 'brick'...\n")
        if self.mode.strip().lower() not in LEARNING_MODES:
            plt.show()
        ax.clear()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Euler brick / perfect cuboid searcher")
    parser.add_argument("--range", dest="range_", metavar="MIN-MAX",
        help="Search range, e.g. 1-1000. Skips the interactive prompts.")
    parser.add_argument("--mode", choices=["manual", "learning"], default="manual",
        help="manual: pop up each 3D plot (default). learning: skip plot popups.")
    parser.add_argument("--no-gui", action="store_true",
        help="Headless mode: never import matplotlib, just print/log results.")
    parser.add_argument("--log", dest="log_file", metavar="FILE",
        help="Append every found brick (and any perfect cuboid) to FILE as CSV.")
    parser.add_argument("--brute-force", action="store_true",
        help="Use the original O(n^2)-ish triple-loop search instead of the "
             "divisor-driven one. Slower; mainly useful to cross-check "
             "results on small ranges.")
    parser.add_argument("--prune", action="store_true",
        help="Skip candidate edges that cannot satisfy necessary "
             "divisibility conditions (by 3, 4, 5, 11). Empirically "
             "validated (see ROADMAP.md Stage 2 and check_prune.py) but not "
             "confirmed against a primary source -- cross-check with "
             "check_prune.py before trusting it on a large unattended run.")
    parser.add_argument("--perfect-only", action="store_true",
        help="Only report verified perfect cuboids (suppresses ordinary "
             "Euler bricks) and prunes using the stronger, "
             "perfect-cuboid-specific conditions sourced from Wikipedia's "
             "Euler brick article (see ROADMAP.md Stage 2 addendum and "
             "check_perfect_only.py). Supersedes --prune if both are given.")
    parser.add_argument("--workers", type=int, default=1, metavar="N",
        help="Split the search across N worker processes (each `a` is "
             "independent, so this partitions the range with no overlap). "
             "Requires --no-gui and --range; not combinable with "
             "--brute-force. Default 1 (single process, unchanged).")
    parser.add_argument("--checkpoint", dest="checkpoint_dir", metavar="DIR",
        help="Periodically persist search progress to DIR so an "
             "interrupted run can resume instead of restarting the range "
             "from the beginning. Refuses to resume a checkpoint created "
             "with different --range/--prune/--perfect-only/--workers "
             "settings. Requires --range; not combinable with "
             "--brute-force.")
    args = parser.parse_args()
    if args.workers > 1:
        if not args.range_:
            parser.error("--workers requires --range (no interactive prompts across processes).")
        if not args.no_gui:
            parser.error("--workers requires --no-gui (matplotlib popups aren't supported across processes).")
        if args.brute_force:
            parser.error("--workers is not combinable with --brute-force.")
    if args.checkpoint_dir:
        if not args.range_:
            parser.error("--checkpoint requires --range (no interactive prompts across a resumable run).")
        if args.brute_force:
            parser.error("--checkpoint is not combinable with --brute-force.")
    return args


if __name__ == "__main__":
    app = EulerBrick()
    app.run(parse_args())
