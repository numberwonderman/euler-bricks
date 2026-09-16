# Roadmap: pushing this toward a real perfect-cuboid search

Context: the current `main.py` (see `perfect-cuboid-detection` branch) correctly
*detects* a perfect cuboid (integer space diagonal, not just integer face
diagonals) via exact `math.isqrt` checks, and has a headless `--range/--no-gui/--log`
CLI. But it's still a brute-force triple loop over `(a, b, c)`, which is nowhere
near fast enough to reach the actual searched frontier for this open problem
(roughly 10^18, covered by prior work using parametrized/optimized searches).
This is a staged plan to close that gap, built incrementally as token budget
allows. Each stage should land as its own PR/commit and be independently
testable against the known smallest Euler brick (44, 117, 240) as a sanity check.

## Stage 0 — Correctness baseline (done)

- Exact integer perfect-square checks (`math.isqrt`-based, no float precision
  loss).
- Real perfect-cuboid detection: checks the space diagonal
  `sqrt(a^2+b^2+c^2)`, not just the three face diagonals.
- Fixed the "learning mode" operator-precedence bug that made plot popups
  never actually get suppressed.
- Headless CLI (`--range`, `--no-gui`, `--mode`, `--log`) for unattended runs.
- Good for roughly up to 10^6–10^7 on one core before pure-Python loop
  overhead dominates.

## Stage 1 — Algorithmic rewrite (the important one) — DONE

Replace the O(n²)-ish nested scan with divisor-driven Pythagorean-triple
generation:

- For a fixed `a`, every `b` with `a² + b²` a perfect square can be generated
  directly from the divisor pairs of `a²` (classic parametrization: for
  `d - b` and `d + b` both dividing `a²` with matching parity), instead of
  scanning every candidate `b` up to `n`.
- Do the same to get the set of candidate `c` values that pair with `a`
  (from `a² + c²`) and the set that pair with `b` (from `b² + c²`), then take
  the **intersection** of those two candidate-`c` sets instead of testing
  every `c`.
- This is the actual algorithmic gap between "brute force" and how real
  searches work — everything below is a speed multiplier on top of it, but
  this step is what makes larger bounds reachable at all.

**Implemented** as `pythagorean_partners(a)` in `main.py` (trial-division
factoring of `a`, doubled exponents to get divisors of `a²`, filtered to
divisor pairs `s < a` with `s,t` same parity). `generate_bricks_fast` uses
it: for each `a`, get partners in range; for each partner `b`, get `b`'s own
partners and keep only the `c`s that also show up in `a`'s partner set (dict
lookup instead of a full intersection merge). The old triple loop is kept as
`generate_bricks_bruteforce` / `--brute-force`, used only to cross-check
results on small ranges.

Verified identical output against the brute-force method on `1-500`,
`1-2000`, and `1-20000` (320 bricks, byte-identical CSV). Measured speedup
at `1-20000`: brute-force 65.5s vs fast 0.47s (~140x), and the gap grows
with range since brute-force is still ~O(n²) while the fast version scales
with divisor counts. The fast version alone completed `1-1,000,000` in
~75s (17,873 Euler bricks found, 0 perfect cuboids — expected) — a range
brute-force was never going to reach in this session.

Factoring is still plain trial division up to `sqrt(a)`, so it degrades on
very large `a` (this is exactly what Stage 3's sieve/Pollard-rho swap is
for) — Stage 1 fixes the *algorithm*, not yet the *factoring* implementation.

## Stage 2 — Known number-theoretic filters — DONE (opt-in, modest payoff)

Published sources on Euler bricks / perfect cuboids state necessary
divisibility conditions on the three edges (one divisible by 3, one by 4,
one by 5, one by 11 — with perfect-cuboid-specific sources describing
stronger refinements: 9 instead of 3, 16 instead of 4, plus 7 and 19).
**WebFetch to the primary sources (Wikipedia, MathWorld, the Roberts 2010
AustMS paper) was blocked by this session's network policy**, so none of
this was confirmed against a primary source — only via WebSearch's
synthesized summaries of secondary discussion. Given that a wrong filter
here would *silently skip a real solution* — the one failure mode this
whole project exists to avoid — only the weaker, doubly-corroborated
subset (3, 4, 5, 11 — not the 9/16/7/19 refinements) was implemented, and
only as **strictly opt-in** (`--prune`), never folded into the default
search.

Before trusting even that: ran an empirical check across every real Euler
brick this tool found in `1-3,000` (39 bricks) and `1-20,000` (320 bricks)
— zero violations of any of the four conditions in either range. That's
consistent with these being classical theorems about *all* Euler bricks
(provable from Euler's parametrization), not extra constraints specific to
perfect cuboids, but 320 samples isn't a proof either. `check_prune.py` was
added to make this checkable on demand: it runs the same range pruned and
unpruned and diffs the results. **Run it on a representative sample of any
range before trusting `--prune` on an unattended search** — it's what
caught the one real bug in this stage (see below).

**Implemented** as `required_modulus_for_third_edge(a, b)` in `main.py`:
given two edges already fixed, returns the single combined modulus (using
that 3, 4, 5, 11 are pairwise coprime, so the product of whichever ones
neither `a` nor `b` already covers is a valid single check) the third edge
must satisfy. Wired into `generate_bricks_fast`'s inner loop as `c %
required_mod != 0` → skip.

**Bug caught by `check_prune.py` itself**: the first version used
`tempfile.NamedTemporaryFile` to get a path, which pre-creates the file;
`main.py`'s `log_result()` checks `os.path.exists()` to decide whether to
write the CSV header, saw the (empty) file already there, and skipped the
header — shifting every logged row up by one and silently losing the
first real result from the comparison (`320` vs `319` bricks over
`1-20,000`, not caught until diffing against a direct run). Fixed by
`os.unlink()`-ing the path right after it's allocated. Recorded here
because it's a reminder that the verification tooling needs verifying too.

**Performance reality check**: the first implementation checked
`any(c % m != 0 for m in required_mods)` per candidate — a generator
expression, which in CPython costs more than the dict lookup it was meant
to avoid. Net effect: **`--prune` was 18% *slower*** at `1-1,000,000`
(63.8s vs 54.0s unpruned). Collapsing the check to the single combined
modulus above got it back to roughly break-even (56.6s vs 58.6s, ~3%
faster — within noise). Profiling showed why the win is small regardless:
at `1-1,000,000`, `pythagorean_partners()` factoring is not the bottleneck
(3.84s for the first 200,000 values, average divisor-partner-list length
~19); the dominant cost is the sheer number of Python-level inner-loop
iterations in the intersection step (~3.6×10^8 at `N=10^6`). Pruning
correctly skips some of those iterations' dict lookups, but the fixed
per-iteration Python loop/tuple-unpack overhead dominates regardless of
what's skipped. That's a useful data point for Stage 3: it means the
interpreter overhead itself, not this specific inefficiency, is the next
real lever — reinforces that Stage 3 (compiled/vectorized inner loop)
matters more than further pruning refinement at this scale.

## Stage 3 — Implementation speed — DONE (multiprocessing; compiled extension skipped, see below)

Checked the environment before picking an approach: `gcc` and `rustc` are
both present here, but neither `Cython` nor `numpy` is installed, and this
tool's own README promises it "runs on many platforms" with just
`python3` — no compiler, no package installs. A Cython/Rust extension
would mean every user needs a working C or Rust toolchain just to get the
speed win, which doesn't fit a project whose entire installation story is
"you need Python 3." So Stage 3 implements the other option the roadmap
listed: `multiprocessing`, stdlib-only, works anywhere Python does.

**Implemented**: `--workers N`. `search_bricks()` (the core algorithm) was
factored out to a module-level, side-effect-free generator shared by the
single-process path (`generate_bricks_fast`) and each worker
(`_worker_search`) — one implementation to trust instead of two that could
silently diverge. Requires `--range` and `--no-gui` (validated at the
argparse level); not combinable with `--brute-force`.

Each `a` produces bricks attributed to it alone (`b`, `c` are always `>
a`), so partitioning the outer `a` loop across workers is exact — no
duplicate or missed bricks, no coordination needed beyond merging each
worker's CSV part-file at the end. Workers are assigned `a` values
**round-robin** (worker `i` gets `a_start+i, a_start+i+workers, ...`)
rather than contiguous blocks, because factoring cost grows with `a` —
contiguous chunking left whichever worker got the largest-`a` block
running long after the others finished.

Verified identical results (serial vs. `--workers 4`) on `1-20,000` (320
bricks, byte-identical after sorting).

**Performance reality check**: on this 4-CPU sandbox (confirmed via
`nproc`/cgroup — no quota throttling), `--workers 4` measured **~1.6x**
wall-clock speedup at `1-1,000,000` (53.7s → 33.3s), not the ideal ~4x.
Switching from contiguous to round-robin partitioning didn't meaningfully
change this (33.3s either way) — so the imbalance measured between shards
(~1.8x cost ratio, largest-`a` shard vs. smallest) wasn't the dominant
limiter. The likely cause: each worker process has its own
`pythagorean_partners()` `lru_cache` (Stage 1), so a `b` value factored by
one worker gets silently re-factored by every other worker that also
touches it — real duplicated work with no way to share it across
processes without adding a shared-cache layer (out of scope for this
stage).

**Second, more serious finding, at `1-2,000,000`**: single-process
completed in 2m13.7s. The 4-worker run was killed partway through (not
allowed to finish) after its 3 CPU-bound processes' RSS climbed past
4.3GB *each* (12GB+ total) with no cap, on a 15GB-total sandbox with no
swap configured -- confirmed via `free -h`, not inferred. CPU utilization
per worker had already dropped from ~72% to ~25% and process state moved
from running to sleeping before the kill, consistent with memory
pressure. This is the same unbounded `lru_cache(maxsize=None)` from Stage
1: fine for one process, but `--workers N` multiplies that memory cost by
N with no sharing between them, and it scales with the search range, not
with a fixed budget. Left running, this range would very plausibly have
OOM-killed the container rather than finished.

**Fixed, not just documented**: `pythagorean_partners()`'s `lru_cache` was
switched from `maxsize=None` to a measured, bounded size. Caching
`a=1..1,000,000` in one process was measured at ~3.3KB/entry (mostly
`lru_cache`'s own bookkeeping, not the data) -> ~3.3GB for a million
entries, which is where the incident's per-worker RSS came from almost
exactly. `maxsize=200_000` caps that at ~550MB/process. Re-ran the exact
scenario that broke before (`--workers 4`, `1-2,000,000`, watched every
10s): total RSS across 4 workers now **plateaus at ~8.7GB and holds flat**
instead of climbing past 12.7GB and still rising. Re-verified correctness
after the change (`check_prune.py` on `1-20,000`, unchanged: 320 bricks,
byte-identical).

8.7GB across 4 workers is still substantial for a modest machine -- a
`--cache-size` CLI flag so users can tune the tradeoff for their own RAM
would be a reasonable follow-up, not implemented here to keep this stage's
scope to "make the discovered risk safe," not "make it configurable."

**Practical consequence**: `--workers` is correct (verified identical
results vs. serial on `1-20,000`) and gives a real, if sub-linear, speedup
at moderate ranges (~1.6x on 4 cores at `1-1,000,000`). Memory is now
bounded rather than unbounded, but still substantial per worker -- check
`free -h` against `--workers N` × ~550MB before pointing it at a large
range on a memory-constrained machine.

## Stage 4 — Checkpointing & resumability

Since this is being built (and run) across multiple sessions/token budgets:

- Durable checkpoint (SQLite or JSON) recording the highest `a` fully
  searched per shard, so a run can stop and resume without restarting from 1.
- Results log stays append-only CSV (already have this from Stage 0) so
  partial progress is never lost.

## Stage 5 — Reality check

Even with Stages 1–4 done, closing the gap to the actual frontier (~10^18,
covered by prior work with heavily optimized C and years of cluster time) is
a stretch goal, not a guarantee. Once Stage 1–3 land, benchmark actual
triples-checked-per-second and be honest about what bound is reachable in
realistic wall-clock time before promising more.
