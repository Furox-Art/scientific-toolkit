#!/usr/bin/env bash
set -euo pipefail
# Render build: six stand-alone distributions plus an isolated bundled Axiomize.
# Render installs the released distributions from PyPI. GitHub Actions must not:
# every CI fetch of one of these projects counts toward its public download
# statistics, so CI installs the sibling repositories from GitHub source
# instead. The pip cache stays enabled on CI to avoid repeating source builds.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  pip_cache_flag=()
  upstream_specs=(
    "git+https://github.com/Furox-Art/axiomize.git@main"
    "git+https://github.com/Furox-Art/scientific-computing-system.git@main"
    "git+https://github.com/Furox-Art/scientific-computing-system-2.0.git@main"
    "git+https://github.com/Furox-Art/plan-auditor.git@main"
    "git+https://github.com/Furox-Art/quantum-reasoning-skill.git@main"
    "git+https://github.com/Furox-Art/eq-layer.git@main"
    "PyYAML"
  )
  reason_spec="git+https://github.com/Furox-Art/axiomize-quantum-skills-2.0.git@main"
else
  pip_cache_flag=(--no-cache-dir)
  upstream_specs=(axiomize scientific-computing-system scientific-computing-system-2.0 plan-auditor quantum-reasoning-skill eq-layer PyYAML)
  reason_spec=axiomize-quantum-skills-2.0
fi
python -m pip install "${pip_cache_flag[@]}" -e '.[oauth]'
python -m pip install "${pip_cache_flag[@]}" "${upstream_specs[@]}"
# The Render runtime already uses a virtual environment. A nested venv cannot
# inherit dependencies from that outer environment. Isolate the bundled module
# tree with --target and use the existing Python interpreter for shared deps.
python -m pip install "${pip_cache_flag[@]}" --no-deps --target .reason-pkg "${reason_spec}"
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
