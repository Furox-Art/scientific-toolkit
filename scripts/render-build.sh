#!/usr/bin/env bash
set -euo pipefail
# Render build: eight stand-alone distributions plus an isolated bundled Axiomize.
# Render installs the released distributions from PyPI. GitHub Actions must not:
# every CI fetch of one of these projects counts toward its public download
# statistics, so CI installs the sibling repositories from GitHub source
# instead. The pip cache stays enabled on CI to avoid repeating source builds.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  pip_cache_flag=()
  # Pinned to immutable commits, one line per sibling repository. The tag is the
  # human-readable identity; the full SHA is what pip actually resolves. Bump a
  # pin only after that tag has been released and its own CI is green.
  upstream_specs=(
    # axiomize v1.14.1 (803eb44b1e7500bfd10760f8813f9dd4e3afe6d0)
    "git+https://github.com/Furox-Art/axiomize.git@803eb44b1e7500bfd10760f8813f9dd4e3afe6d0"
    # scientific-computing-system (SCS) v2.2.12 (dfeda42ebadd1cbef4424ab27564384506618edd)
    "git+https://github.com/Furox-Art/scientific-computing-system.git@dfeda42ebadd1cbef4424ab27564384506618edd"
    # scientific-computing-system-2.0 (SCS2) v5.4.5 (012979f95ff0599af527503c02b4e5434e8af5d1)
    "git+https://github.com/Furox-Art/scientific-computing-system-2.0.git@012979f95ff0599af527503c02b4e5434e8af5d1"
    # plan-auditor v2.6.3 (09e27c9ee7de6a7ec15651e605a7f5b5ea5ab96c)
    "git+https://github.com/Furox-Art/plan-auditor.git@09e27c9ee7de6a7ec15651e605a7f5b5ea5ab96c"
    # quantum-reasoning-skill (QRS) v1.2.0 (a6ee692ca6722aeda55c9912924ae0fb9acc40db)
    "git+https://github.com/Furox-Art/quantum-reasoning-skill.git@a6ee692ca6722aeda55c9912924ae0fb9acc40db"
    # eq-layer v0.2.5 (e31e1882c2fc1ae861683b56ef46aaf31a9ccd6b)
    "git+https://github.com/Furox-Art/eq-layer.git@e31e1882c2fc1ae861683b56ef46aaf31a9ccd6b"
    # literature-evidence-mcp v0.5.1 (b9c90f5e11bf18bba87bb5abfc8e240923424640)
    "git+https://github.com/Furox-Art/literature-evidence-mcp.git@b9c90f5e11bf18bba87bb5abfc8e240923424640"
    # nomosguard v0.7.10 (d0d9de518bd7a7d6155a8eb83054f30eaff3c965)
    "git+https://github.com/Furox-Art/nomosguard.git@d0d9de518bd7a7d6155a8eb83054f30eaff3c965"
    # PyYAML 6.0.3 (the version the full-stack CI run resolves today)
    "PyYAML==6.0.3"
  )
  # axiomize-quantum-skills-2.0 (AQSK2) v1.2.5 (74df0190a77c2b65540aace89b1f9d2c505ec894)
  reason_spec="git+https://github.com/Furox-Art/axiomize-quantum-skills-2.0.git@74df0190a77c2b65540aace89b1f9d2c505ec894"
else
  pip_cache_flag=(--no-cache-dir)
  upstream_specs=(axiomize scientific-computing-system scientific-computing-system-2.0 plan-auditor quantum-reasoning-skill eq-layer literature-evidence-mcp nomosguard "PyYAML==6.0.3")
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
import importlib.util
import shutil
for name in ('axiomize','cds','cds2','plan-auditor','quantum-reasoning','eq-layer',
             'literature-evidence-mcp'):
    assert shutil.which(name), f'Missing CLI: {name}'
assert importlib.util.find_spec('nomosguard.mcp_stdio'), 'Missing module: nomosguard.mcp_stdio'
assert Path('.reason-env/bin/axiomize-reason').is_file()
print('All nine upstream tools present, pending real adapter smoke tests')
PY
