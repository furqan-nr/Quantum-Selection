# Phase D collection notes (not part of the frozen record)

- Pre-registration pushed: commit 32e53d4 (2026-10-18).
- P timing passes (2.0.1, 2.0.3, 2.1.2, 2.2.1, 2.4.2) and B collect-only (six B releases) run; budget locks D1-D4, D6-D8 written 2026-10-17T20:57:52Z and pushed in commit a3c1148 (2026-10-18T01:22:43Z) before any B timing pass.
- B timing passes 1 and 2 for 2.0.2, 2.1.0, 2.2.0rc1, 2.2.2, 2.5.0 run after that push.
- D5 lock (P = 2.5.0 pass 1, B = 2.5.1) written 2026-10-18T02:04:32Z; must be pushed before the 2.5.1 timing passes.
- Order note: the F checks of D1-D4, D6-D8 (step 12.3(e)) were run before step 12.3(d) (2.5.1 timing passes), while waiting for the D5 lock push. F checks read only those events' completed B passes and touch no lock or 2.5.1 timing; the 2.5.1 venv was prepared (as F of D4/D7) but no 2.5.1 timing pass ran before the D5 lock push.
- All runs used phase_d/runner/run_phase_d.py, invoked one step per sandbox call by a small driver (outputs/phasec/auto_d.py, copied to phase_d/tools/auto_d.py) because sandbox calls are limited to ~170 s.
