# Agent Studio v1 demo

This script demonstrates one Agent across execution, tools, RAG, Memory, observability, and Evaluation. It uses deterministic Mock plus PostgreSQL/pgvector and requires no provider key.

## Prerequisite and startup

1. Start Docker Desktop or Docker Engine.
2. From the repository root, run `docker compose up --build -d` (Windows users may run `.\scripts\docker-up.ps1`).
3. Open `http://127.0.0.1:3000` and confirm the sidebar says **Connected**.

If startup fails, run `docker compose ps` and `docker compose logs --tail 100 api web db`. Do not continue if API health is unavailable.

## Two-minute version

Use prepared demo records if they already exist:

1. Open **Playground**, select **Demo Lifecycle Agent**, and run `Calculate 128 * 37 + 456`.
2. Point out `5192`, Tool Call, Tool Result, and Mock usage shown as N/A.
3. Open **Run detail**, show the ordered timeline and the Tools filter.
4. Open **Evaluations**, open **v1 Demo Evaluation**, and show PASS plus its linked Run Trace.
5. Finish on **Dashboard** and explain that metrics project persisted normal Runs, not evaluation traffic.

## Full 5–8 minute version

### 1. Create and ingest the knowledge base

1. Open **Agent Builder**.
2. In **Knowledge / RAG**, enter `Agent Studio Demo KB` and description `Safe v1 lifecycle demo facts`, then choose **Create**.
3. Choose [agent-studio-demo-knowledge.md](demo/agent-studio-demo-knowledge.md) and select **Upload & ingest**.
4. Wait until the document state is `completed`.
5. In **Test retrieval**, enter `What is the recovery codename and preferred persistence environment?` and choose **Semantic + keyword search**.

Expected: the first ranked source names `Glacier-5192`, PostgreSQL 17, and pgvector. Explain that only completed ingestion generations are retrievable.

### 2. Create the Agent

1. In **Identity & behavior**, name the Agent `Demo Lifecycle Agent`.
2. Use the prompt `Use Calculator for arithmetic and attached knowledge for grounded answers.`
3. Keep **Mock** selected. It is deterministic and requires no key.
4. Keep **Calculator** and **Durable Memory** enabled.
5. Select **Agent Studio Demo KB** under Knowledge, then choose **Save agent**.

Expected: the app opens **Playground** and clearly labels the runtime as deterministic Mock.

### 3. Calculator and trace

1. Enter `Calculate 128 * 37 + 456` and choose **Run agent**.
2. Confirm the final answer is `5192`.
3. Point out **Tool selected**, **Tool call**, **Tool result**, and **Final answer**.

Expected: one successful Calculator call. Usage is N/A because Mock does not issue a model request.

### 4. RAG and Memory across Runs

1. Run `Remember that my preferred demo environment is PostgreSQL.`
2. Confirm **Memory written** appears and the remembered fact appears in the Memory panel.
3. Run `What demo environment do I prefer, and what recovery codename does the handbook use?`
4. Confirm **Memory retrieved** appears. Expand the knowledge citation and show the upload source.

Expected: the second Run retrieves the Agent-scoped fact and executes `knowledge_search` against the completed demo document. Explain that both sources are untrusted context and do not grant permissions.

### 5. Observability

1. Choose **Run detail**.
2. Show status, duration, steps, tool calls, usage/N/A, terminal reason, and the ordered execution timeline.
3. Use **Knowledge / RAG**, **Memory**, and **Tools** filters, then return to **All**.

Expected: Run plus ordered RunEvent data remains available after refresh.

### 6. Evaluation

1. Open **Evaluations** and choose **Create suite**.
2. Set suite name to `v1 Demo Evaluation` and select **Demo Lifecycle Agent**.
3. Set case name to `Calculator canonical result` and input to `Calculate 128 * 37 + 456`.
4. Set expected text to `5192` and tool name to `calculator`.
5. Save, choose **Run evaluation**, and wait for completion.
6. Show PASS, then choose **View Run Trace**.

Expected: 100% pass rate and a linked real evaluation Run. Explain that FAIL means a grader mismatch while ERROR means execution/grading infrastructure failed.

### 7. Dashboard close

Open **Dashboard**. Show persisted normal Runs, success rate, average duration, and recent trace links. Evaluation traffic is intentionally excluded from normal dashboard metrics.

## Fallbacks

- Ingestion not completed: refresh the selected collection; do not claim RAG success from a queued/processing job.
- No citation: confirm the Agent is bound to **Agent Studio Demo KB** and the document is `completed`.
- Provider error: recreate/select an Agent in **Mock** mode; do not add a key during the default demo.
- Evaluation not finished: wait for its status refresh; a pending/running state is not PASS.
- API offline or DB unavailable: stop the demo and restore health; the UI must not be described as connected.

## Cleanup

`docker compose down` preserves demo data. Delete individual demo Memories or suites in the UI if desired. To remove the entire isolated Docker project, use `.\scripts\docker-down.ps1 -PurgeData` and enter its exact confirmation; this removes all data for that Compose project, not only demo records.

## Verified v1 screenshots

- [Dashboard](assets/dashboard.png)
- [Calculator Tool Call](assets/playground-tool-call.png)
- [RAG citation](assets/rag-citation.png)
- [Run Detail trace](assets/run-trace.png)
- [Evaluation PASS](assets/evaluation.png)

These files are produced by `pnpm --dir apps/web screenshots:v1` against a running local stack. The script uses only public APIs and safe deterministic demo data, then checks desktop/mobile overflow and browser console errors.
