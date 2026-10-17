import unittest
from qiskit import QuantumCircuit
from qiskit.circuit import Gate, Parameter
from qiskit.circuit.library import U1Gate, Measure
from qiskit.transpiler import Target
from qiskit.transpiler.passes import Optimize1qGatesDecomposition
class T(unittest.TestCase):
    def test_custom_gate_in_target(self):
        class CustomGate(Gate):
            def __init__(self, lam):
                super().__init__("custom_u1", 1, [lam])
            def __array__(self, dtype=None, _copy=None):
                return U1Gate(*self.params).__array__(dtype=dtype)
        target = Target(num_qubits=2)
        target.add_instruction(CustomGate(Parameter("lam")))
        target.add_instruction(Measure())
        qc = QuantumCircuit(2)
        qc.append(CustomGate(0.5), [0]); qc.append(CustomGate(0.5), [1]); qc.measure_all()
        result = Optimize1qGatesDecomposition(target)(qc)
        expected = QuantumCircuit(2)
        expected.append(CustomGate(0.5), [0]); expected.append(CustomGate(0.5), [1]); expected.measure_all()
        self.assertEqual(result, expected)
