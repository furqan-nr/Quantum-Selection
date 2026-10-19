# Running the cost calibration on Kaggle (valid, and cleaner than a busy laptop)

## Why this is legitimate, not a shortcut

The paper's claim is not "these budgets apply to my specific laptop." It is "under a fixed, documented
hardware profile, selection behaves like *this* once the budget binds." So the calibration hardware only
has to be **quiet, stable, and documented** — not any particular machine. Kaggle satisfies all three
better than a laptop with other apps open.

Two facts (verified in the code) make it safe:

1. **`evaluate` consumes the frozen `profiles.json`; it never re-times.** `EvalContext.load` reads
   `data/profile_baseline/profiles.json` into `baseline_costs`, and selection ranks tests on those frozen
   numbers. So only the *calibration* needs consistent hardware; the freeze and B3 are pure arithmetic on
   the frozen costs and can run anywhere (including back on your laptop).
2. **The costhet ground-truth run needs no from-source builds.** It processes the **mutation** cohort in
   process (`baseline = preset PM`, `candidate = mutation operator on the same build`); the historical and
   forward events are skipped. So Kaggle needs only `pip install qiskit==2.4.2` plus the `cart` package —
   no Rust toolchain, no `_builds/`.

Because the budgets are set **from** the measured cost distribution, Kaggle's absolute CPU speed is
irrelevant: whatever the costs come out to, you pick `pr` / `nightly` budgets that bind on that
distribution. A faster or slower CPU just shifts the numbers, not the binding regime.

## The one subtlety: pin threads and document the CPU

`process_time()` sums CPU time across threads, and Qiskit's Rust passes are multi-threaded. For stable,
reproducible costs, **pin to one thread** and record the CPU. Set before importing qiskit:

```python
import os
os.environ["RAYON_NUM_THREADS"] = "1"      # Qiskit Rust parallelism -> single thread
os.environ["OMP_NUM_THREADS"]   = "1"
os.environ["QISKIT_IN_PARALLEL"] = "TRUE"  # discourage Python-level process pools
```

This matches the single-threaded discipline Paper 1 used for the determinism work, and it makes
`process_time` ≈ wall-clock and reproducible. Do the **entire** calibration in one Kaggle session — Kaggle
can assign a different CPU across sessions, so one session keeps the hardware fixed.

## Upload bundle (small — no `_builds/`, no venvs)

Zip just these from the repo root and upload as a Kaggle **Dataset**:

```
src/                       # the cart package
pyproject.toml
data/events/events.csv
data/events/events.json    # ground-truth loads the ledger for the mutation events
configs/                   # budgets.yaml, corpus_costhet.yaml (safe to include)
```

Do **not** upload `environment/_builds/` (huge, and unused here) or `paper/`.

## Notebook cells (CPU accelerator, internet ON for the pip install)

```python
# Cell 1 — pinned, quiet environment
import os
for k, v in {"RAYON_NUM_THREADS":"1","OMP_NUM_THREADS":"1","QISKIT_IN_PARALLEL":"TRUE"}.items():
    os.environ[k] = v
!pip -q install qiskit==2.4.2
import platform, subprocess
print(platform.python_version())
print(subprocess.run(["bash","-lc","grep -m1 'model name' /proc/cpuinfo; nproc"],
                     capture_output=True, text=True).stdout)   # <-- RECORD THIS for the paper
```

```python
# Cell 2 — stage the project (adjust the dataset path to yours)
!cp -r /kaggle/input/<your-dataset-name>/* /kaggle/working/proj/
%cd /kaggle/working/proj
import sys; sys.path.insert(0, "src")
```

```python
# Cell 3 — calibration (fresh raw; 116-unit corpus; >=5-run warmup-discarded median)
!rm -rf data/raw && mkdir -p data/raw data/derived data/profile_baseline data/manifest_static
!PYTHONPATH=src python -m cart.cli manifest --profile costhet
!PYTHONPATH=src python -m cart.cli ground-truth --unit-limit 116 --cost-repeats 5
```

```python
# Cell 4 — surface the deliverables, INCLUDING the raw write-once artifacts this time
# (2026-08-07 addendum: gate 6, label_reproducibility, checks that every label's raw
#  data/raw/<event_id>/<test_id>/result.json exists and matches — the first Kaggle round only
#  downloaded the three derived files below, so data/raw/ (1044 small JSON files, ~3 MB total)
#  was left behind and the gate could not be independently re-verified. Zip it this time.)
import shutil
shutil.make_archive("data_raw_costhet", "zip", "data/raw")
for f in ["data/profile_baseline/profiles.json",
          "data/derived/labels.json",
          "data/manifest_static/manifest_static.json",
          "data_raw_costhet.zip"]:
    print(f, os.path.getsize(f), "bytes")
```

Download all four from the Kaggle output (the three derived files, unchanged, plus the new
`data_raw_costhet.zip`). They go back to the Paper 2 chat unchanged; unzip `data_raw_costhet.zip` into
`data/raw/` in this repo (it should replace/merge with the existing `data/raw/` tree, which currently only
holds the historical-event artifacts, not the costhet mutation-cohort ones).

## What to hand the Paper 2 chat

The four files above, plus the recorded **CPU model + core count + Python version** and the note that
`RAYON_NUM_THREADS=1`. That hardware line belongs in the reproducibility statement — and it is a *stronger*
statement than "measured on the author's laptop," because a referee can reproduce it on the same free
Kaggle tier.

Once `data/raw/` is back, re-run `python3 -c "from cart.gates.validity import run_all_gates; import json;
print(json.dumps(run_all_gates(), indent=2))"` to confirm all six implementation-validity gates pass before
that claim goes into the manuscript (RQ1, §6.2). As of 2026-08-07, 5/6 passed here and
`label_reproducibility` failed only because `data/raw/` was missing — not because any label mismatched.

**RESOLVED 2026-08-08.** The authors re-ran this notebook on Kaggle and obtained `data_raw_costhet.zip`
(1,044 files). Two things were found while wiring it in:

1. Its SHA-256 hashes don't match the `raw_sha256` already recorded in `data/derived/labels.json` — this
   is a **fresh** second calibration run, not a recovery of the first session's files (those were lost
   when the session closed, as expected). The old `data/raw/mut-*` dirs in this repo (stale, pre-B1 pilot
   artifacts, only 416/1044 files, not from the costhet run) were replaced with the fresh 1,044-file set —
   moved to `data/raw_pilot_backup_2026-08-07/` rather than deleted.
2. `gate_label_reproducibility` in `src/cart/gates/validity.py` had a portability bug: `raw_artifact` is
   recorded as an absolute path from the calibration machine (`/kaggle/working/proj/data/raw/...`), which
   cannot resolve on any other machine. Fixed to fall back to resolving by `(event_id, test_id)` identity
   under the `data_dir` being validated — this is what makes a Kaggle-produced `data/raw/` zip actually
   portable to a different checkout, which is the entire point of doing calibration on Kaggle.

With both fixed, **1,040/1,044 labels (99.6%) reproduce exactly** from the raw artifacts. The 4 exceptions
are all instances of the same two mutation types already flagged in §6.4/Table 8 as the selector's weak
point (`insert_redundant_cx_pair`, `insert_redundant_x_pair`), on circuits costing 1-3 ms to transpile —
the mutation cohort's performance-regression flag is a single-pass 20% slowdown threshold with no
bootstrap confirmation, and 20% of ~1-3 ms sits inside ordinary `process_time` jitter even single-threaded.
This is a measurement-noise boundary on the cheapest units in the corpus, not a code defect. §6.2/Table 6
in `build_paper.js` report this precisely (1,040/1,044, not a rounded-up "6/6"). Frozen RQ2/RQ3 numbers
(§6.3-6.6) are unaffected — `labels.json` itself was not touched.

## Before the freeze (unchanged)

Check `profiles.json` for two things the dispersion fields were added to catch: any unit whose
`cost_iqr_s` is a large fraction of its median (unstable — should not sit near a budget edge), and any
unit whose median lands within its own min/max spread of `pr: 120s` or `nightly: 3600s` (knife-edge — move
the budget off it). Then set budgets from the cost distribution, write `version: 1 / frozen: true`, and
only then run `evaluate` + `report_b3`.

## Caveat worth stating once

Kaggle's free CPUs are shared VMs, so even "quiet" they carry mild noise. The ≥5-run warmup-discarded
median plus the single-thread pin handles the normal case, but if any unit's `cost_iqr_s` looks wild,
re-run just that calibration (a second `ground-truth` pass) before trusting it. Stability of the
calibration is the thing that matters, not the machine it ran on.
