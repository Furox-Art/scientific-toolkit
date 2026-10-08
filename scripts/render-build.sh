#!/usr/bin/env bash
set -euo pipefail
# Render build: six stand-alone distributions plus an isolated bundled Axiomize.
python -m pip install --no-cache-dir -e '.[oauth]'
python -m pip install --no-cache-dir axiomize scientific-computing-system scientific-computing-system-2.0 plan-auditor quantum-reasoning-skill eq-layer PyYAML
python -m venv --system-site-packages .reason-env
.reason-env/bin/python -m pip install --no-cache-dir --no-deps axiomize-quantum-skills-2.0
python - <<'PY'
from pathlib import Path
import shutil
for name in ('axiomize','cds','cds2','plan-auditor','quantum-reasoning','eq-layer'):
    assert shutil.which(name), f'Missing CLI: {name}'
assert Path('.reason-env/bin/axiomize-reason').is_file()
print('All seven CLI executables present, pending real CLI smoke tests')
PY
