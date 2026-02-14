import sys
from pathlib import Path

# Clear any previously cached 'app' and 'shared' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
    if key == "shared" or key.startswith("shared."):
        del sys.modules[key]

# Insert API service path at front of sys.path, remove other services
_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_services_str = str(_services)
_api_path = str(_services / "api")
_keep = {_api_path, _services_str}
sys.path[:] = [p for p in sys.path if not (p.startswith(_services_str) and p not in _keep)]
if _api_path not in sys.path:
    sys.path.insert(0, _api_path)
if _services_str not in sys.path:
    sys.path.insert(0, _services_str)
