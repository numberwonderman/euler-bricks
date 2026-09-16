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

## Stage 1 — Algorithmic rewrite (the important one)

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

## Stage 2 — Known number-theoretic filters

Published results on Euler bricks / perfect cuboids give necessary
divisibility and parity conditions on `a, b, c` (e.g. one edge must be
divisible by 4, one by 3, one by 5, plus additional modular constraints).
Checking these first lets us reject candidate `a` values cheaply, before
paying the cost of factoring `a²` and generating divisor pairs in Stage 1.
Needs a literature check to get the exact conditions right before encoding
them (get this wrong and we silently skip real solutions).

## Stage 3 — Implementation speed

- Move the hot inner loop out of plain Python: a compiled extension
  (Cython, or Rust via PyO3) for the divisor-pair generation and
  intersection, or at minimum vectorize with numpy.
- `multiprocessing` sharding across ranges of `a` — each `a` is fully
  independent, so this parallelizes with no coordination overhead beyond
  merging result logs.

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
