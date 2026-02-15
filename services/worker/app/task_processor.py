import logging
import time

from qiskit.qasm3 import loads
from qiskit_aer import AerSimulator

logger = logging.getLogger(__name__)


def execute_qasm3(qasm3_str: str, shots: int) -> dict[str, int]:
    """Parse QASM3 string, simulate with AerSimulator, return counts.

    This is a pure function (no global state) so it can be safely pickled
    and executed in a ProcessPoolExecutor child process.
    """
    circuit = loads(qasm3_str)
    logger.debug("qasm3_parsed num_qubits=%s", circuit.num_qubits)

    simulator = AerSimulator()
    start = time.time()
    result = simulator.run(circuit, shots=shots).result()
    elapsed_ms = (time.time() - start) * 1000
    counts = result.get_counts(circuit)
    logger.info("qasm3_executed shots=%s elapsed_ms=%.0f", shots, elapsed_ms)

    # Ensure counts values are plain ints (not numpy)
    return {str(k): int(v) for k, v in counts.items()}
