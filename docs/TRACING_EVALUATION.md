# Agent tracing and offline evaluation

The Databricks App uses the saved `olist-agentic-rag-tracing` experiment resource
(`experiment` key, `Can edit`). `app.yaml` maps its ID to
`MLFLOW_EXPERIMENT_ID` and selects the Databricks tracking server with
`MLFLOW_TRACKING_URI=databricks`. No notebook cluster or separate evaluation compute is
required to serve the App.

## Trace behavior

Each `/api/ask` request starts an `olist.ask` parent span. When the model path
runs, child spans mark each Unity Gateway model call, each named governed SQL
tool, and hybrid governance retrieval. Spans record route, generation path,
approved source names, row or hit counts, model name, and retrieval chunk IDs.
They do not record the question, SQL text, prompt, answer, or row contents.
MLflow setup or export failure is logged and cannot replace the existing
governed answer or deterministic fallback. With no experiment ID, tracing is
disabled.

The existing safety bounds remain: only fixed read-only SQL templates run;
the model cannot supply SQL; AI Search passages are contextual; mandatory
numeric evidence and the published-run pointer are enforced. An agent failure
still uses the deterministic SQL answer.

## Offline evaluation

`evals/cases.json` contains four fixed questions and checks for route, required
evidence tools and sources, answer terms, the canonical GMV display, the
1 QUARANTINE + 4 WARN rule-definition breakdown, correct late-delivery scope,
and hybrid governance retrieval. These checks assess saved responses; they do
not call a model or Databricks. They catch selected factual/safety regressions,
but do not prove that an answer is financially audited or fully correct.

Save one JSON object per line in a local file, with the case `id` and its
`/api/ask` JSON `response`. Then run:

```bash
python evals/offline_eval.py responses.jsonl
```

The command exits nonzero when any case fails or is missing. Use the four exact
questions from `evals/cases.json` with dashboard context `operations`,
`overview`, `ALL`, and no date filter. If the model is unavailable and the App
uses deterministic fallback, record that separately; some trace and evidence
fields are specific to the agent path.

## Live validation checkpoint (2026-10-10)

The four cases were checked visually in the running App. This is manual QA,
**not** a run of `offline_eval.py`, because the raw `/api/ask` JSON responses
were not captured:

| Case | Observed result |
| --- | --- |
| Delivered GMV | `BRL 13,220,248.93`; merchandise value, excluding freight, not accounting revenue; governed SQL and AI Search evidence shown. |
| Quality distinctions | 32 distinct quarantined source records (8 in each of four tables); five failed rule definitions, split 1 QUARANTINE + 4 WARN; GMV trust qualified by remaining WARN-level anomalies. |
| RJ versus SP | RJ: 1,495 / 12,350 eligible deliveries = 12.1053%; SP: 1,820 / 40,494 = 4.4945%; historical-data caveat and governed source shown. |
| Freight definition | `sum(freight_value)` where `is_delivered`; freight reported separately from merchandise GMV; metric dictionary and hybrid search evidence shown. |

The saved MLflow experiment displayed a successful trace row, but its detailed
view said **No trace data available**. App logs showed that upload of the trace
artifact to `us-east-2.storage.cloud.databricks.com:443` failed with
`Connection refused`. The trace row therefore does **not** verify the nested
spans. This was an artifact-storage network failure, not an agent answer or
model-endpoint failure. The log already reported `tracking URI: databricks`,
so changing that URI alone is not a supported fix; do not redeploy solely to
test that setting again.

Databricks Free Edition restricts outbound internet and does not provide
custom networking controls. A Unity Catalog-backed experiment is a possible
supported trace-storage path, but it requires a trace-enabled experiment,
MLflow 3.14+, a SQL warehouse, and four trace-table App resources with MODIFY
permissions. Check workspace support and resource cost before changing the
experiment. The empty artifact trace cannot be counted as a successful
end-to-end trace. See [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations),
[Unity Catalog trace storage](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog),
and [App experiment resources](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/mlflow).

## Deploy and verify in the existing Databricks App

1. Confirm GitHub CI for the new commit is green before deployment. In the
   Databricks Git folder linked to **this** repository, switch to `main` and
   pull. Check that the folder shows the new commit; do not pull the Phase 1
   repository or EACC.
2. Open the existing Olist Agentic Operations Control Tower App. Confirm its
   MLflow experiment resource still shows `olist-agentic-rag-tracing`, `Can
   edit`, and key `experiment`. Redeploy the App from the updated Git folder.
   Confirm deployment succeeds and the App starts without dependency errors.
3. In the App, ask: “What is delivered GMV, and can I call it revenue?” Confirm
   `BRL 13,220,248.93`, freight exclusion, and the distinction from accounting
   revenue. Then ask: “Why were source records quarantined, and can I trust
   GMV?” Confirm 32 distinct quarantined source records, five failed rule
   definitions split 1 QUARANTINE + 4 WARN, and a qualified trust answer.
4. Open the saved MLflow experiment, **Traces** tab. The new request should
   show one `olist.ask` trace with nested `gateway.model`,
   `governed_sql.*`, and `governance.retrieval` spans (the retrieval span appears
   for governance questions). If absent, check the App logs for MLflow setup
   or span export errors; do not infer success from a working answer alone.
5. For the full four-case evaluation, capture each `/api/ask` JSON response
   from the browser Network panel or an authenticated API client, label it
   with the corresponding case ID, and run the offline scorer locally. This
   uses the existing App requests and no extra Databricks compute.

The dataset is historical Olist data, not live operations. Dashboard context
is selected manually. Rule failure evaluations can overlap; they are not the
32 distinct quarantined source records.

