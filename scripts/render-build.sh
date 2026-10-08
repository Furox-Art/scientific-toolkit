#!/usr/bin/env bash
set -euo pipefail
# Render build: six stand-alone distributions plus an isolated bundled Axiomize.
python -m pip install --no-cache-dir -e '.[oauth]'
python -m pip install --no-cache-dir axiomize scientific-computing-system scientific-computing-system-2.0 plan-auditor quantum-reasoning-skill eq-layer PyYAML
# The Render runtime already uses a virtual environment. A nested venv cannot
# inherit dependencies from that outer environment. Isolate the bundled module
# tree with --target and use the existing Python interpreter for shared deps.
python -m pip install --no-cache-dir --no-deps --target .reason-pkg axiomize-quantum-skills-2.0
python - <<'PY'
from pathlib import Path
wrapper = Path('.reason-env/bin/axiomize-reason')
wrapper.parent.mkdir(parents=True, exist_ok=True)
wrapper.write_text('''#!/usr/bin/env python
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / ".reason-pkg"))
from axiomize.reasoning.cli import main
raise SystemExit(main())
''', encoding='utf-8')
wrapper.chmod(0o755)
PY
python - <<'PY'
from pathlib import Path
import shutil
for name in ('axiomize','cds','cds2','plan-auditor','quantum-reasoning','eq-layer'):
    assert shutil.which(name), f'Missing CLI: {name}'
assert Path('.reason-env/bin/axiomize-reason').is_file()
print('All seven CLI executables present, pending real CLI smoke tests')
PY
