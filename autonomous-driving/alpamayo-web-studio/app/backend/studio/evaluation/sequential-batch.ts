export interface EvaluationScenario {
  id: string;
}

export interface EvaluationFailure {
  message: string;
}

export type EvaluationBatchItem =
  | { scenarioId: string; status: "succeeded" }
  | { scenarioId: string; status: "failed"; failure: EvaluationFailure };

export interface EvaluationBatchResult {
  items: EvaluationBatchItem[];
}

export type EvaluationExecutor = (scenario: EvaluationScenario) => Promise<void>;

function failureFrom(error: unknown): EvaluationFailure {
  return { message: error instanceof Error ? error.message : String(error) };
}

/** Runs a regression set on one GPU by awaiting each scenario before starting the next. */
export class SequentialEvaluationBatch {
  constructor(private readonly execute: EvaluationExecutor) {}

  async run(scenarios: readonly EvaluationScenario[]): Promise<EvaluationBatchResult> {
    if (scenarios.length < 10) {
      throw new Error("A regression batch requires at least 10 scenarios");
    }

    const items: EvaluationBatchItem[] = [];
    for (const scenario of scenarios) {
      try {
        await this.execute(scenario);
        items.push({ scenarioId: scenario.id, status: "succeeded" });
      } catch (error) {
        items.push({
          scenarioId: scenario.id,
          status: "failed",
          failure: failureFrom(error),
        });
      }
    }

    return { items };
  }
}
