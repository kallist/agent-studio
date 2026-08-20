import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EvaluationRunPanel,
  EvaluationStudio,
  SuiteList,
  filterEvaluationResults,
  formatEvaluationRate,
} from "@/components/evaluation-studio";
import type {
  AgentDefinition,
  EvaluationCaseResult,
  EvaluationRun,
  EvaluationSuiteSummary,
} from "@/lib/api";
import { api } from "@/lib/api";

const agent: AgentDefinition = {
  id: "00000000-0000-0000-0000-000000000001",
  name: "Calculator Agent",
  instructions: "Use tools.",
  runtime_mode: "mock",
  model: null,
  tools: ["calculator"],
  knowledge_base_ids: [],
  memory_enabled: true,
  created_at: "2026-08-20T00:00:00Z",
};

const suite: EvaluationSuiteSummary = {
  id: "00000000-0000-0000-0000-000000000010",
  name: "Calculator Regression",
  description: "Protect arithmetic",
  agent_id: agent.id,
  revision: 2,
  case_count: 3,
  last_run_id: "00000000-0000-0000-0000-000000000020",
  last_run_status: "completed",
  last_pass_rate: null,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T01:00:00Z",
};

const evaluationRun: EvaluationRun = {
  id: suite.last_run_id!,
  suite_id: suite.id,
  agent_id: agent.id,
  status: "completed",
  suite_revision: 2,
  total_cases: 3,
  completed_cases: 3,
  passed_cases: 1,
  failed_cases: 1,
  error_cases: 1,
  pass_rate: 1 / 3,
  average_duration_ms: null,
  p95_duration_ms: null,
  grader_metrics: {},
  cancel_requested: false,
  error: null,
  created_at: "2026-08-20T00:00:00Z",
  started_at: "2026-08-20T00:00:01Z",
  completed_at: "2026-08-20T00:00:02Z",
};

function result(status: "pass" | "fail" | "error", index: number): EvaluationCaseResult {
  return {
    id: `00000000-0000-0000-0000-00000000003${index}`,
    evaluation_run_id: evaluationRun.id,
    case_id: `00000000-0000-0000-0000-00000000004${index}`,
    run_id: `00000000-0000-0000-0000-00000000005${index}`,
    status,
    case_snapshot: { name: `${status} case`, input: "Calculate 128 * 37 + 456" },
    actual_output: "5192",
    run_status: "completed",
    duration_ms: null,
    graders_passed: status === "pass" ? 1 : 0,
    graders_total: 1,
    error: status === "error" ? "Duration unavailable" : null,
    created_at: "2026-08-20T00:00:00Z",
    completed_at: "2026-08-20T00:00:01Z",
    grader_results: [{
      id: `00000000-0000-0000-0000-00000000006${index}`,
      grader_type: "exact_match",
      required: true,
      outcome: status,
      passed: status === "pass" ? true : status === "fail" ? false : null,
      score: status === "pass" ? 1 : status === "fail" ? 0 : null,
      message: status === "fail" ? "Final output did not match." : "Fixture result.",
      expected: { value: "9999" },
      actual: "5192",
      evidence: [],
    }],
  };
}

afterEach(() => { vi.restoreAllMocks(); });

describe("evaluation helpers and surfaces", () => {
  it("uses N/A for zero-case metrics and renders real suite summaries", () => {
    expect(formatEvaluationRate(null)).toBe("N/A");
    expect(formatEvaluationRate(1)).toBe("100%");
    render(<SuiteList suites={[suite]} agents={[agent]} onOpen={vi.fn()} onOpenRun={vi.fn()} />);
    expect(screen.getByText("Calculator Regression")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
  });

  it("filters PASS, FAIL, and ERROR without changing aggregate math", () => {
    const results = [result("pass", 1), result("fail", 2), result("error", 3)];
    expect(filterEvaluationResults(results, "all")).toHaveLength(3);
    expect(filterEvaluationResults(results, "pass")).toHaveLength(1);
    expect(filterEvaluationResults(results, "fail")[0].status).toBe("fail");
    expect(filterEvaluationResults(results, "error")[0].status).toBe("error");
  });

  it("shows summary N/A values, case detail, grader reason, and trace action", () => {
    const results = [result("pass", 1), result("fail", 2), result("error", 3)];
    const onViewRun = vi.fn();
    render(<EvaluationRunPanel run={evaluationRun} results={results} filteredResults={results} filter="all" selectedResult={results[1]} loading={false} onFilter={vi.fn()} onSelect={vi.fn()} onBack={vi.fn()} onCancel={vi.fn()} onViewRun={onViewRun} />);
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("fail case")).toHaveLength(2);
    expect(screen.getByText("Final output did not match.")).toBeInTheDocument();
    expect(screen.getByText('{"value":"9999"}')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View Run Trace" }));
    expect(onViewRun).toHaveBeenCalledWith(results[1].run_id);
  });

  it("renders zero state and dynamically configures an exact-match grader", async () => {
    vi.spyOn(api, "listEvaluationSuites").mockResolvedValue([]);
    render(<EvaluationStudio agents={[agent]} onViewRun={vi.fn()} />);
    expect(await screen.findByText("No evaluation suites")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Create suite" })[0]);
    expect(screen.getByRole("heading", { name: "Create evaluation suite" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Grader 2 type"), { target: { value: "exact_match" } });
    await waitFor(() => expect(screen.getByLabelText("Expected text")).toBeInTheDocument());
    expect(screen.getByLabelText("Expected text")).toHaveValue("");
  });

  it("recovers from a transient poll failure until terminal results arrive", async () => {
    const runningSuite = { ...suite, last_run_status: "running" as const };
    const running = {
      ...evaluationRun,
      status: "running" as const,
      completed_cases: 0,
      passed_cases: 0,
      failed_cases: 0,
      error_cases: 0,
      pass_rate: null,
      completed_at: null,
    };
    vi.spyOn(api, "listEvaluationSuites").mockResolvedValue([runningSuite]);
    vi.spyOn(api, "getEvaluationRun")
      .mockResolvedValueOnce(running)
      .mockRejectedValueOnce(new Error("Transient refresh failure"))
      .mockResolvedValueOnce(evaluationRun);
    vi.spyOn(api, "listEvaluationResults")
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([result("pass", 1)])
      .mockResolvedValueOnce([result("pass", 1)]);

    render(<EvaluationStudio agents={[agent]} onViewRun={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "RUNNING" }));
    const summary = await screen.findByLabelText("Evaluation summary");
    await waitFor(() => expect(summary).toHaveTextContent("COMPLETED"), { timeout: 2_000 });
    expect(summary).toHaveTextContent("3 / 3");
    expect(screen.getAllByText("pass case")).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.getEvaluationRun).toHaveBeenCalledTimes(3);
  });
});
