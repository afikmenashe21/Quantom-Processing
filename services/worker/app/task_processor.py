import logging

from qiskit.qasm3 import loads
from qiskit_aer import AerSimulator

from app.config import settings

logger = logging.getLogger(__name__)


def execute_qasm3(qasm3_str: str) -> dict[str, int]:
    """Parse QASM3 string, simulate with AerSimulator, return counts."""
    circuit = loads(qasm3_str)
    simulator = AerSimulator()
    result = simulator.run(circuit, shots=settings.shots).result()
    counts = result.get_counts(circuit)
    # Ensure counts values are plain ints (not numpy)
    return {str(k): int(v) for k, v in counts.items()}
