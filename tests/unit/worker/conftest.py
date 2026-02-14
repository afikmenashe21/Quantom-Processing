import sys
from pathlib import Path
from unittest.mock import MagicMock

# Clear any previously cached 'app' and 'shared' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
    if key == "shared" or key.startswith("shared."):
        del sys.modules[key]

_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_services_str = str(_services)
_worker_path = str(_services / "worker")
_keep = {_worker_path, _services_str}
sys.path[:] = [p for p in sys.path if not (p.startswith(_services_str) and p not in _keep)]
if _worker_path not in sys.path:
    sys.path.insert(0, _worker_path)
if _services_str not in sys.path:
    sys.path.insert(0, _services_str)

# Mock qiskit modules if not installed (they're only needed in Docker)
if "qiskit" not in sys.modules:
    _qiskit = MagicMock()
    sys.modules["qiskit"] = _qiskit
    sys.modules["qiskit.qasm3"] = _qiskit.qasm3
    sys.modules["qiskit_aer"] = MagicMock()
