"""Explicit catalog: original repositories remain independent and unchanged."""

REPOSITORIES = (
    {
        "name": "axiomize",
        "role": "Model specification, simulation, falsification, and numerical verification",
        "interface": "axiomize CLI (also has its own MCP server)",
        "tools": ["axiomize_intake", "axiomize_model"],
    },
    {
        "name": "scientific-computing-system",
        "role": "Pure-Python computational science and statistics",
        "interface": "cds CLI",
        "tools": ["cds_stats"],
    },
    {
        "name": "scientific-computing-system-2.0",
        "role": "NumPy/SciPy-backed scientific computing",
        "interface": "cds2 CLI",
        "tools": ["cds2_stats"],
    },
    {
        "name": "plan-auditor",
        "role": "Independent agent plan verification and completion gating",
        "interface": "plan-auditor CLI; audit execution requires explicit local opt-in",
        "tools": ["plan_auditor_inspect", "plan_auditor_audit"],
    },
    {
        "name": "quantum-reasoning-skill",
        "role": "Model-agnostic reasoning protocol; package contract verification",
        "interface": "quantum-reasoning CLI (inspector, not an LLM)",
        "tools": ["quantum_skill_validate"],
    },
    {
        "name": "axiomize-quantum-skills-2.0",
        "role": "Bundled Axiomize plus quantum-inspired branching; no duplicate Axiomize MCP registration",
        "interface": "axiomize-reason CLI",
        "tools": ["axiomize_reason_score"],
    },
    {
        "name": "eq-layer",
        "role": "Intent, affect, and conversational control selection; not scientific validation",
        "interface": "eq-layer CLI, local heuristic/learned routing",
        "tools": ["eq_layer_route"],
    },
)


def catalog() -> list[dict]:
    return [dict(item, url=f"https://github.com/Furox-Art/{item['name']}") for item in REPOSITORIES]
