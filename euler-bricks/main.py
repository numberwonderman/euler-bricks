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
import math
import multiprocessing
import os
import sys
from functools import lru_cache

LEARNING_MODES = {"l", "learn", "learning"}


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


def search_bricks(a_values, range_end, prune):
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
    """
    for a in a_values:
        partners_a = [(v, diag) for (v, diag) in pythagorean_partners(a) if a < v < range_end]
        if not partners_a:
            continue
        a_diag_for = dict(partners_a)
        for b, d in partners_a:
            required_mod = required_modulus_for_third_edge(a, b) if prune else 1
            for c, f in pythagorean_partners(b):
                if c <= b or c >= range_end:
                    continue
                if required_mod != 1 and c % required_mod != 0:
                    continue
                e = a_diag_for.get(c)
                if e is None:
                    continue
                yield (a, b, c, d, e, f)


def _worker_search(task):
    """Runs in a worker process (Stage 3, --workers): searches one shard of
    `a` values via search_bricks, printing/logging its own finds as it goes
    (prefixed with the worker id) instead of returning everything to the
    main process to report at the end -- that would buffer all output
    until the whole run finishes, losing the live progress a long
    unattended search depends on. Returns (bricks_found, perfect_found) so
    the main process can print a final summary.
    """
    a_start, range_end, prune, stride, worker_id, part_log_path = task
    writer = None
    log_fh = None
    if part_log_path:
        log_fh = open(part_log_path, "w", newline="")
        writer = csv.writer(log_fh)
        writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
    bricks_found = 0
    perfect_found = 0
    try:
        a_values = range(a_start, range_end, stride)
        for a, b, c, d, e, f in search_bricks(a_values, range_end, prune):
            bricks_found += 1
            g_ok, g = EulerBrick.is_perfect_square(a*a + b*b + c*c)
            if g_ok:
                perfect_found += 1
            tag = "[!!!] PERFECT CUBOID FOUND" if g_ok else "[Info] Found 'brick'"
            print("[W{}] {} -- {}:{}:{}  dZY={} dXZ={} dXY={}{}".format(
                worker_id, tag, c, b, a, d, e, f,
                "  g={}".format(g) if g_ok else ""))
            if writer:
                writer.writerow([a, b, c, d, e, f, g if g_ok else "", g_ok])
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
        self.workers = 1

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
            self.workers = args.workers
        else:
            self.mode = input(" -Set mode: manual (default), learning (M/l): ")
            self.root = input(" -Set range (ex: 1-1000 or 1000-1000000 (PRESS ENTER = 1-1000) (STOP = CTRL+z): ")
            if not self.root:
                self.root = "1-1000"
            self.no_gui = False
            self.log_file = None
            self.brute_force = False
            self.prune = False
            self.workers = 1
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
        is_new = not os.path.exists(self.log_file)
        with open(self.log_file, "a", newline="") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
            writer.writerow([a, b, c, d, e, f, g if g is not None else "", perfect])

    def report_brick(self, a, b, c, d, e, f, n):
        g_ok, g = self.is_perfect_square(a*a + b*b + c*c)
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
        """
        minrange, maxrange = self._parse_range(rng)
        self.init = minrange
        self.end = maxrange
        n = 0
        if not self.no_gui and not os.path.exists(self.store_bricks):
            os.mkdir(self.store_bricks)
        for a, b, c, d, e, f in search_bricks(range(max(self.init, 1), self.end), self.end, self.prune):
            n += 1
            self.report_brick(a, b, c, d, e, f, n)

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

        part_paths = [
            "{}.part{}".format(self.log_file, i) if self.log_file else None
            for i in range(workers)
        ]
        tasks = [
            (a_start + i, a_end, self.prune, workers, i, part_paths[i])
            for i in range(workers)
        ]
        print("[Info] Striping a in [{}, {}) round-robin across {} worker process(es)...\n".format(
            a_start, a_end, workers))
        with multiprocessing.Pool(workers) as pool:
            results = pool.map(_worker_search, tasks)

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
    parser.add_argument("--workers", type=int, default=1, metavar="N",
        help="Split the search across N worker processes (each `a` is "
             "independent, so this partitions the range with no overlap). "
             "Requires --no-gui and --range; not combinable with "
             "--brute-force. Default 1 (single process, unchanged).")
    args = parser.parse_args()
    if args.workers > 1:
        if not args.range_:
            parser.error("--workers requires --range (no interactive prompts across processes).")
        if not args.no_gui:
            parser.error("--workers requires --no-gui (matplotlib popups aren't supported across processes).")
        if args.brute_force:
            parser.error("--workers is not combinable with --brute-force.")
    return args


if __name__ == "__main__":
    app = EulerBrick()
    app.run(parse_args())
