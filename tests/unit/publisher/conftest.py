import sys
from pathlib import Path

# Clear any previously cached 'app' and 'shared' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
    if key == "shared" or key.startswith("shared."):
        del sys.modules[key]

_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_services_str = str(_services)
_pub_path = str(_services / "publisher")
_keep = {_pub_path, _services_str}
sys.path[:] = [p for p in sys.path if not (p.startswith(_services_str) and p not in _keep)]
if _pub_path not in sys.path:
    sys.path.insert(0, _pub_path)
if _services_str not in sys.path:
    sys.path.insert(0, _services_str)
