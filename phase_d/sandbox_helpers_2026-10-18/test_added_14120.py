"""Added test (not in Qiskit): reproducer of issue #14867 / H4 (#14120) as a unit test."""
import unittest
from ddt import ddt, data
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import library as lib
from qiskit.transpiler import Target, InstructionProperties

@ddt
class TestNoVF2WithInitialLayout(unittest.TestCase):
    @data(0, 1, 2, 3)
    def test_no_vf2_layout_passes_when_initial_layout_set(self, level):
        target = Target()
        target.add_instruction(lib.CXGate(), {(0, 1): InstructionProperties(error=1e-2),
                                              (1, 2): InstructionProperties(error=1e-5)})
        qc = QuantumCircuit(2); qc.cx(0, 1)
        seen = []
        transpile(qc, target=target, optimization_level=level, initial_layout=[0, 1],
                  callback=lambda pass_, **_: seen.append(pass_.name()))
        self.assertFalse([p for p in seen if p.startswith("VF2")], seen)
