# Olist Agentic Operations Control Tower — Live Agent Evaluation

Date: 2026-10-12  
Scope: Historical Olist published run `773b84d219fc40e691f28b6918da5ea0`  
Interface: Databricks App `/api/ask`  
Context: All states, Operations, no date restriction

## Results: four live scenarios manually reviewed

**Manual review: 3 passed, 1 terminology issue.** This is *not* a claim that the offline JSONL evaluator was executed against an archived collection of all four full API responses; those response bodies must be saved to produce a reproducible machine-scored run.

| Case | Route | Mode observed | Result | Observations |
|---|---|---|---|---|
| `gmv_definition` | ANALYTICS | `agentic_tool_calling` | **Issue** | Canonical BRL 13,220,248.93, correct revenue/freight caveats and model-selected semantic retrieval; model incorrectly expanded GMV as “go-to-market value” instead of Gross Merchandise Value |
| `quality_distinctions` | HYBRID | `agentic_tool_calling` | **Pass** | 32 distinct quarantined records (8 orders plus 8 per each of three child datasets); five failed rule definitions: 1 QUARANTINE and 4 WARN; GMV appropriately qualified |
| `delivery_denominator` | ANALYTICS | `agentic_tool_calling` after separate earlier fallback | **Pass** | RJ 1,495/12,350 (12.11%); SP 1,820/40,494 (4.49%); eligible-deliveries denominator; model-selected AI Search; response did not explicitly state the raw-rate difference of ~7.61 percentage points |
| `governance_retrieval` | KNOWLEDGE | `agentic_tool_calling` | **Pass** | Model selected `search_governance_knowledge` and `metric_dictionary`; retrieved `metric:freight` with `sum(freight_value) where is_delivered`, BRL, freight separate from GMV |

### Cross-cutting behavior and caveats

- All amounts and counts are derived from governed Unity Catalog SQL evidence, *not* LLM-generated SQL.
- Model-selected `search_governance_knowledge` was observed on all four cases, but model-selected tool lists differ from executed SQL tools (mandatory publication/evidence guard may execute additional tools).
- One earlier RJ/SP request returned a correct answer under `deterministic_fallback_agent_error`. App Logs showed `RuntimeError: Model returned no grounded final answer`. A bounded evidence-only synthesis retry has since been committed; the later request completed as `agentic_tool_calling`. One successful retry does not establish a reliability rate.
- The freight response included internal pseudo-citations such as `【fetch_governed_evidence rows[5].business_definition】`; the structured source is `workspace.olist_governance.metric_dictionary`. The model also attributed buyer agreement to the freight charge, which is not substantiated by the metric dictionary. A prompt correction has been committed and must be redeployed and tested.
- MLflow trace metadata appears in the experiment, but detailed span export was blocked by refusal connecting from Databricks App to `us-east-2.storage.cloud.databricks.com:443`. Trace completeness remains unverified.
- The historical Olist dataset is not live commerce data; embedded-dashboard context selections are manual. Delivered Item GMV is merchandise value, not recognized accounting revenue. WARN-level anomalies are not independently proven to have zero KPI impact.

## Regression acceptance before VP demo

1. Verify GitHub Actions green for the current `main` commit; pull Git main into the Databricks Git folder and redeploy the App.
2. Re-run `gmv_definition`: the answer must explicitly avoid “go-to-market value”; use Gross Merchandise Value where expanding GMV.
3. Re-run `governance_retrieval`: answer should cite actual Unity Catalog source names/IDs without opaque tool-row citations or unsupported buyer-agreement statements.
4. Save the four complete **Response JSON** bodies from `POST /api/ask` (not headers/cookies) into a local JSONL file, one object per line: `{"id":"gmv_definition","response":{...}}`. Use all four case IDs from `evals/cases.json`.
5. Run `python -m evals.offline_eval <responses.jsonl>`. Report full passing count and attach the JSONL if retained; do not describe manual checks as machine-scored results.
6. Record tested Git SHA, deployed App Git SHA, and remaining limitations in the VP demonstration notes.

## Evaluation contract

- Cases: `evals/cases.json`.
- Scorer: `evals/offline_eval.py`.
- Generation must be `agentic_tool_calling` for a pass, **even if** deterministic fallback returns a numerically correct answer.
- Freight retrieval must be `ai_search_hybrid` **and** `model_selected` with `search_governance_knowledge` in `model_selected_tools`.
- Required source evidence and expected tool execution must match the case contract.

**Scope of claim:** functional end-to-end POC with observed agentic SQL and semantic retrieval, not a production SLO, accounting audit, or complete MLflow observability implementation.
