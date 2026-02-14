import sys
from pathlib import Path

# Clear any previously cached 'app' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

# Insert API service path at front of sys.path, remove other services
_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_api_path = str(_services / "api")
sys.path[:] = [p for p in sys.path if not (p.startswith(str(_services)) and p != _api_path)]
if _api_path not in sys.path:
    sys.path.insert(0, _api_path)
