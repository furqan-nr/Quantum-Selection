# #15024 — why the gate returned negative, and the exact fix

The fix-boundary run on `sv-15024-fix` vs `sv-15024-bug` reported:

```
baseline  output_equivalent=True  registers=vbits=5 regs=[['alpha',0],['alpha',1],['beta',0],['beta',1],['beta',2]]
candidate output_equivalent=True  registers=vbits=5 regs=[['alpha',0],['alpha',1],['beta',0],['beta',1],['beta',2]]
register_diverges=False  output_oracle_blind=True  => fault_detected=False
```

**The gate worked correctly and saved two Rust builds.** But this is a detector problem, not evidence that
the fault is absent. Two independent sources say so.

## 1. Paper 1 already recorded the discriminating field

`data/mining_validation/label_source_validation.csv`, row `pr = 15024`:

| field | value |
|---|---|
| `fix_location` | TranspileLayout register preservation |
| **`regression_test_asserts_on`** | **`layout.initial_layout.get_registers`** |
| `coded_channel` / `source_confirms` | contract_metadata / contract_metadata (match: yes) |

The detector captured the **register membership of the layout's virtual qubits** — which is derived from the
circuit's own qubits and is therefore identical on both builds no matter what the layout records. The fault
lives in **`initial_layout.get_registers()`**, the register set stored on the `Layout` object, which the
buggy build drops.

## 2. The fix ships its own regression test — mirror it exactly

`bb100f83` ("Preserve registers in output TranspileLayout (#15024)", reproducing issue #15014) touches
`crates/transpiler/src/transpile_layout.rs` (+65) and adds this to
`test/python/transpiler/test_preset_passmanagers.py`:

```python
@data(0, 1, 2, 3)
def test_layout_registers_preserved(self, optimization_level):
    a = QuantumRegister(2, "a")
    b = AncillaRegister(1, "b")          # <-- an ANCILLA register, listed FIRST
    qc = QuantumCircuit(b, a)
    qc.x(0)

    initial_layout = [0, 1, 2]            # <-- explicit initial_layout
    qc_transpiled = transpile(
        qc, initial_layout=initial_layout, optimization_level=optimization_level
    )
    self.assertEqual(qc_transpiled.layout.initial_layout.get_registers(), {a, b})
```

A second test, `test_layout_registers_preserved_with_allocated_ancilla`, uses `AncillaRegister(1,"b")` plus
`QuantumRegister(3,"a")` with entanglement and an explicit
`Target.from_configuration(["u","cx"], coupling_map=CouplingMap.from_line(10))`.

## What to change in `scripts/verify_15024_contract.py`

Four concrete edits — the current trigger differs from the upstream test on every one:

1. **Observable.** Compare `transpiled.layout.initial_layout.get_registers()` between builds — as a
   comparable signature, e.g. a sorted set of `(reg.name, len(reg), type(reg).__name__)`. Drop the
   per-virtual-bit register list as the primary signal (keep it as a secondary field if useful).
2. **Use an `AncillaRegister`.** The current trigger is `alpha[2] + beta[3]`, two plain `QuantumRegister`s.
   The fault is about preserving register structure including **ancillas**; import `AncillaRegister` and
   build `QuantumCircuit(b, a)` with `b` first, matching the test.
3. **Pass an explicit `initial_layout`** (e.g. `[0, 1, 2]`) to `transpile`. The upstream reproduction sets
   it, and the layout path that drops registers is the one exercised by an explicit layout.
4. **Sweep optimization levels 0–3**, as the test does with `@data(0,1,2,3)`, rather than only `--opt 1`.
   Report per level and treat "fires at any level" as detection.

Keep everything else: the acceptance criterion (register signature diverges **while** the output-equivalence
oracle stays blind), the exit codes (0 detected / 2 blind-but-identical / 3 error), and the JSON output shape.

## Then re-run the same gate

```powershell
cd path\to\quantum-selection      # repo root
python scripts\verify_15024_contract.py `
  --baseline-python environment\_builds\sv-15024-fix\venv\Scripts\python.exe `
  --candidate-python environment\_builds\sv-15024-bug\venv\Scripts\python.exe `
  --out results\sv-15024-fixboundary-v2
```

If it fires, the forward builds (`e364cd96` / `ccc2c77b`) are justified. If it still does not fire with the
upstream trigger reproduced faithfully, then stop for real: record #15024 as **not forward-verifiable with
the current oracle family**, keep the forward count at 1 (H4), and proceed under the per-event claim-scope
decision in `FORWARD_COUNT_DECISION.md`. That outcome is publishable — it is the same "generic probes are
blind to this fault class" limitation Paper 1 reported for #14939, now with a second instance.

## General lesson (worth a line in Paper 2)

Targeted triggers must be derived from the fix's own regression test, not invented from the PR title. This is
the third time a plausible-looking generic trigger has been inert (#14939 in Paper 1, and now #15024). The
detection mechanism and the trigger are a matched pair; getting the mechanism right is not sufficient.

---

## RESULT (2026-08-05) — gate PASSED

Re-run with the upstream-faithful trigger (`results/sv-15024-fixboundary-v2/`):

| level | baseline (fixed) `get_registers()` | candidate (buggy) | output oracle |
|---|---|---|---|
| opt0–opt3 (all four) | `[['a',2,'QuantumRegister'], ['b',1,'AncillaRegister']]` | **`[]`** | `output_equiv=True` on **both** |

`register_diverges=True`, `output_oracle_blind=True` → **fault_detected=True** at every optimization level.

The buggy build drops the register set from `initial_layout` **entirely** while the compiled circuit stays
functionally correct. This is a clean output-invisible contract/metadata fault, and the detector is now
proven against a known-positive boundary. The forward builds are justified.

**Root cause of the first negative, for the record:** the original trigger used two plain `QuantumRegister`s
and compared per-virtual-bit register membership — a field derived from the circuit's own qubits, which is
identical on both builds by construction. Deriving the trigger and the observable from the fix's own
regression test changed a null into a four-for-four positive. This is now the third data point for the
"targeted triggers must come from the fix test" lesson (#14939, #15024-v1 negative, #15024-v2 positive).
