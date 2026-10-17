import numpy as np, qiskit
from qiskit import QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit.library import CU1Gate
qr = QuantumRegister(2); qc = QuantumCircuit(qr); qc.append(CU1Gate(np.pi), [qr[0], qr[1]])
try:
    transpile(qc, None, coupling_map=[[1, 1], [1, 0]], basis_gates=["u1","u2","u3","id","cx"], optimization_level=3)
    print(qiskit.__version__, "OK")
except BaseException as e:
    print(qiskit.__version__, "EXC", type(e).__name__, str(e)[:80])
