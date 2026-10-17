"""Fixed machine-speed calibration workload of the Phase D runner (PREREGISTRATION_PHASE_D.md, Section 6.4).

Run with the venv's interpreter (numpy is pinned identically in every venv). Prints JSON: the median of 5 timed
repetitions (after 1 warm-up) of a fixed mixed workload (pure-Python loop, sorting, a 160x160 matmul chain), in
seconds of perf_counter. The speed factor k of an event is the ratio of the medians over its B-run calls and its
P-run calls (config 'speed_rule'). The workload is frozen; changing it is a deviation.
"""
import json
import random
import statistics
import time


def _work() -> float:
    import numpy as np
    acc = 0
    for i in range(1_500_000):
        acc = (acc * 31 + i) % 1_000_003
    rng = random.Random(12345)
    xs = [rng.random() for _ in range(600_000)]
    xs.sort()
    a = np.random.default_rng(7).standard_normal((160, 160))
    m = a
    for _ in range(200):
        m = (m @ a) / 160.0
    return acc + xs[0] + float(m[0, 0])


def main() -> None:
    _work()
    ts = []
    for _ in range(5):
        t0 = time.perf_counter()
        _work()
        ts.append(time.perf_counter() - t0)
    print(json.dumps({"calibration_median_s": statistics.median(ts), "calibration_runs_s": ts}))


if __name__ == "__main__":
    main()
