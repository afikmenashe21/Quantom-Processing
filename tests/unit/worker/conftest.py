import sys
from pathlib import Path
from unittest.mock import MagicMock

# Clear any previously cached 'app' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_worker_path = str(_services / "worker")
sys.path[:] = [p for p in sys.path if not (p.startswith(str(_services)) and p != _worker_path)]
if _worker_path not in sys.path:
    sys.path.insert(0, _worker_path)

# Mock qiskit modules if not installed (they're only needed in Docker)
if "qiskit" not in sys.modules:
    _qiskit = MagicMock()
    sys.modules["qiskit"] = _qiskit
    sys.modules["qiskit.qasm3"] = _qiskit.qasm3
    sys.modules["qiskit_aer"] = MagicMock()
