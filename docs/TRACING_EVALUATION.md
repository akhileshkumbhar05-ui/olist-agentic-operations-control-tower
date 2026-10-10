# Agent tracing and offline evaluation

The Databricks App uses the saved `olist-agentic-rag-tracing` experiment resource
(`experiment` key, `Can edit`). `app.yaml` maps its ID to
`MLFLOW_EXPERIMENT_ID`. No notebook cluster or separate evaluation compute is
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
