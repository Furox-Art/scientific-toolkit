# Real captured output of examples/analysis_pipeline.py

Generated on this machine by running:

    python examples/analysis_pipeline.py

Environment: Python 3.12.3 (Linux x86_64).
The bundled `axiomize-reason` ran from the isolated package directory
selected by `SCITOOL_REASON_BIN`.

Every line below is genuine captured stdout. No value was computed by the
capture process: each number is what an upstream CLI actually printed.

```text

==============================================================================
Scientific Toolkit MCP gateway -- seven-tool example workflow
==============================================================================
Input data: 10 replicate measurements of one length
Research idea: How does the number of replicate measurements affect the reported uncertainty of a single length measurement?

==============================================================================
Stage 1 -- toolkit_doctor: what is actually installed
==============================================================================
[OK  ] toolkit_doctor

==============================================================================
Stage 2 -- axiomize_intake: clarify the research idea
==============================================================================
[OK  ] axiomize_intake
       upstream program: axiomize, real exit code 0
       | {
       |   "status": "NEEDS_INPUT",
       |   "idea": "How does the number of replicate measurements affect the reported uncertainty of a single length measurement?",
       |   "questions": [
       |     {
       |       "field": "system_boundary",
       |       "question": "What exactly are we modeling, and what is outside the system?"
       |     }
       |   ],
       |   "remaining_questions": 5,
       |   "question_mode": "one_by_one",
       |   "rigor_recommendation": {
       |     "level": "medium",
       |     "reasons": [

==============================================================================
Stage 3 -- cds_stats: pure-Python descriptive statistics
==============================================================================
[OK  ] cds_stats
       upstream program: cds, real exit code 0
       | Descriptive stats
       | +----------+------------+
       | | stat     | value      |
       | +----------+------------+
       | | n        | 10         |
       | | mean     | 12.035     |
       | | median   | 12.035     |
       | | min      | 11.95      |
       | | max      | 12.11      |
       | | p25      | 11.9975    |
       | | p75      | 12.075     |
       | | stdev    | 0.0540062  |
       | | variance | 0.00291667 |
       | +----------+------------+
       parsed from cds output: n=10.0, mean=12.035, stdev=0.0540062

==============================================================================
Stage 4 -- cds2_stats: independent NumPy/SciPy statistics on the same data
==============================================================================
[OK  ] cds2_stats
       upstream program: cds2, real exit code 0
       | n         10
       | mean      12.035
       | std       0.0540062
       | min       11.95
       | q25       11.9975
       | median    12.035
       | q75       12.075
       | max       12.11
       parsed from cds2 output: n=10.0, mean=12.035, std=0.0540062

==============================================================================
Stage 4b -- cross-check the two independent statistics engines
==============================================================================
       cds  mean=12.035  stdev=0.0540062
       cds2 mean=12.035 std=0.0540062
       independent engines agree to reported precision: True

==============================================================================
Stage 5 -- quantum_skill_validate: is the reasoning protocol contract valid?
==============================================================================
[OK  ] quantum_skill_validate
       Contract validity only. This is NOT evidence of improved model performance.
       upstream program: quantum-reasoning, real exit code 0
       | {
       |   "body_lines": 142,
       |   "description": "Maintain multiple genuinely different candidate hypotheses or solution paths, test them against evidence and tools, suppress weak or contradictory paths, revive useful alternatives when new evidence appears, and collapse to the best-supported answer only at the end.",
       |   "description_length": 266,
       |   "name": "quantum-reasoning",
       |   "package_version": "1.1.1",
       |   "problems": [],
       |   "valid": true
       | }
       packaged contract valid: True

==============================================================================
Stage 6 -- axiomize_reason_score: score the conclusion using Stage 4 evidence
==============================================================================
[OK  ] axiomize_reason_score
       evidence and verification are derived from Stage 4's real tool output. Thresholds are uncalibrated reference defaults, not empirical calibrations.
       upstream program: axiomize-reason, real exit code 0
       | {
       |   "branch": "branch-1",
       |   "can_collapse": false,
       |   "reason": "leader score below collapse threshold"
       | }

==============================================================================
Stage 7 -- eq_layer_route: how should this result be reported?
==============================================================================
[OK  ] eq_layer_route
       Conversational control only. This is not factual verification of the result.
       upstream program: eq-layer, real exit code 0
       | {"runtime_mode": "lightweight-local", "intent_backend": "heuristic", "policy": {"name": "mirror_specific", "register": "mirror"}, "affect": {"valence": 0.25, "arousal": 0.25, "escalation_delta": 0.0, "stance": "unknown", "subtext": "statement", "turn_index": 1, "history": [{"valence": 0.0, "arousal": 0.25, "escalation_delta": 0.25, "stance": "unknown", "subtext": "", "turn_index": 0, "history": []}]}, "intent": {"kind": "statement", "canonical_request": "Respond to the user's statement without inventing a request: \"The two independent statistics engines reported mean=12.035 and std=0.0540062 for 10.0 replicates.\".", "response_mode": "contextual", "confidence": 0.5, "explicit": false, "needs_clarification": false, "constraints": [], "evidence": ["no_explicit_request_marker"], "belief": null, "risk_decision": null}, "repair": {"active": false, "kind": "none", "target_turn_index": null, "target_excerpt": "", "correction_excerpt": "", "replacement_excerpt": "", "replacement_explicit": false, "repeated": false, "recent_repair_count": 0, "confidence": 0.0, "evidence_level": "structural", "evidence": ["no_current_user_correction"]}, "interaction_quality": {"current": 1.0, "delta": 0.0, "repeated_failure_count": 0, "unresolved_repair_count": 0, "clarification_count": 0, "evidence_level": "structural", "evidence": ["no_structural_failure_signal"]}, "reference": {"active": false, "form": "none", "resolved": false, "target_turn_index": null, "target_role": "", "target_excerpt": "", "anchor_turn_index": null, "anchor_excerpt": "", "candidate_stack": [], "requires_clarification": false, "confidence": 0.0, "evidence_level": "structural", "evidence": ["no_supported_short_reference"]}, "factored_action": {"task_move": "respond_contextually", "social_move": "mirror_specific", "repair_move": "none", "realization": {"verbosity": "normal", "directness": "normal", "warmth": "normal", "question_budget": 0, "scope_limited": false, "no_guess": false}, "source_policy": "mirror_specific"}, "system_instruction": "Respond using the mirror_specific policy (mirror). Name the concrete thing the user said, not a category of difficulty. Avoid: That sounds really tough.; I understand how you feel..\nUser intent: Respond to the user's statement without inventing a request: \"The two independent statistics engines reported mean=12.035 and std=0.0540062 for 10.0 replicates.\".\nIntent kind: statement; response mode: contextual; confidence: 0.50; constraints: none.\nControl action:\n- task_move: respond_contextually\n- social_move: mirror_specific\n- repair_move: none\n- realization: verbosity=normal, directness=normal, warmth=normal, question_budget=0, scope_limited=false, no_guess=false.\nThe task_move represents the user's goal and must not be replaced by affective/social adaptation. social_move may shape interpersonal delivery only. If repair_move is active and task completion would require guessing, perform the repair first; otherwise preserve task progress. Never exceed question_budget.\nDialogue reference state: active=false, form=none, resolved=false, target_turn=None, target_role=none.\nThis is a structural reference anchor, not proof that a prior goal is semantically unresolved or factually correct.\nRepair state: active=false, kind=none, repeated=false, target_turn=None, replacement_explicit=false.\nA repair signal identifies conversational misalignment only; it does not establish that either side is factually correct.\nInteraction quality: current=1.00, delta=0.00, repeated_failure_count=0, unresolved_repair_count=0, clarification_count=0.\nInteraction quality measures conversation health, not the user's emotion.", "claim_boundary": "Lightweight routing is a portable control pass, not the full learned research pipeline and not proof of emotional intelligence."}
       intent=statement, mode=contextual, task_move=respond_contextually

==============================================================================
Stage 8 -- plan-auditor: independent inspection of this workflow
==============================================================================
[OK  ] plan_auditor_inspect
       Read-only inspection of a real sealed workspace. This does not certify any scientific conclusion.
       upstream program: plan-auditor, real exit code 0
       | {
       |   "task": "Report descriptive statistics for a set of replicate measurements",
       |   "created": "2026-10-08T00:00:00Z",
       |   "steps": [
       |     {
       |       "id": 1,
       |       "title": "Compute statistics from the replicate readings",
       |       "covers": [
       |         "stats-computed"
       |       ],
       |       "verify": [
       |         {
       |           "type": "run",
       |           "cmd": "test -f results/stats.json"

==============================================================================
Workflow summary
==============================================================================
Stages attempted: 8 (gateway metadata, six upstream tools, one audit)
Distinct KNOWN GAPS: 0
  - none: every upstream tool executed and returned its own output

Scope limits for this run:
  * A tool's exit code 0 proves the program ran, not that the science is right.
  * Local stdio dispatch was exercised. Remote HTTP needs a configured bearer token.
  * plan_auditor_audit was NOT run: it can execute project commands and stays local-only.

Machine-readable result for this run:
{
  "measurements": [
    12.04,
    11.97,
    12.11,
    12.02,
    11.95,
    12.08,
    12.06,
    11.99,
    12.03,
    12.1
  ],
  "doctor_installed_commands": [
    "axiomize",
    "cds",
    "cds2",
    "plan-auditor",
    "quantum-reasoning",
    "axiomize-reason",
    "eq-layer"
  ],
  "intake_questions": [
    {
      "field": "system_boundary",
      "question": "What exactly are we modeling, and what is outside the system?"
    }
  ],
  "cds_stats": {
    "n": 10.0,
    "mean": 12.035,
    "median": 12.035,
    "min": 11.95,
    "max": 12.11,
    "p25": 11.9975,
    "p75": 12.075,
    "stdev": 0.0540062,
    "variance": 0.00291667
  },
  "cds2_stats": {
    "n": 10.0,
    "mean": 12.035,
    "std": 0.0540062,
    "min": 11.95,
    "q25": 11.9975,
    "median": 12.035,
    "q75": 12.075,
    "max": 12.11
  },
  "engines_agree": true,
  "protocol_contract_valid": true,
  "reason_score_input": {
    "evidence": 1.0,
    "verification": 1.0
  },
  "routing_decision": {
    "intent_kind": "statement",
    "response_mode": "contextual",
    "task_move": "respond_contextually"
  }
}
```
