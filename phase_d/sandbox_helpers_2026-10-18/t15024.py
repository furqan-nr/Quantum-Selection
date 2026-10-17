import qiskit
from qiskit import QuantumCircuit, QuantumRegister, AncillaRegister, transpile
r=[]
for lvl in range(4):
    a = QuantumRegister(2, "a"); b = AncillaRegister(1, "b"); qc = QuantumCircuit(b, a); qc.x(0)
    t = transpile(qc, initial_layout=[0, 1, 2], optimization_level=lvl)
    r.append(t.layout.initial_layout.get_registers() == {a, b})
print(qiskit.__version__, r)
