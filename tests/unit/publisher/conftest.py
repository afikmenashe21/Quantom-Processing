import sys
from pathlib import Path

# Clear any previously cached 'app' modules from other services
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

_services = Path(__file__).resolve().parent.parent.parent.parent / "services"
_pub_path = str(_services / "publisher")
sys.path[:] = [p for p in sys.path if not (p.startswith(str(_services)) and p != _pub_path)]
if _pub_path not in sys.path:
    sys.path.insert(0, _pub_path)
