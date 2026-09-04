import { describe, expect, it } from "vitest";
import { validateStrategyEvaluation, type StrategyEvaluationResult } from "../../../web/src/features/strategy/evaluationPresenter.ts";


const rate = (numerator: number, denominator = 2) => ({
  value: numerator / denominator,
  numerator,
  denominator,
  ci95: [0, 1] as [number, number],
});

const result = (): StrategyEvaluationResult => ({
  schema_version: "strategy-evaluation/v1",
  seeds: [101, 102],
  episodes_per_strategy: 2,
  strategy_order: ["random", "qualified_rule"],
  total_episodes: 4,
  episodes: [
    [101, "random", "collision"],
    [101, "qualified_rule", "merge_success"],
    [102, "random", "merge_success"],
    [102, "qualified_rule", "merge_success"],
  ].map(([seed, strategy, outcome]) => ({
    episode_id: `${strategy}-${seed}`,
    seed: Number(seed),
    config_digest: String(seed).repeat(64).slice(0, 64),
    strategy: { id: String(strategy), version: "v1", model_version: null },
    result: String(outcome),
    metrics: {},
  })),
  strategies: [
    {
      strategy: { id: "random", version: "v1", model_version: null },
      episode_count: 2,
      outcomes: { merge_success: 1, collision: 1 },
      rates: { success: rate(1), collision: rate(1), timeout: rate(0), offroad: rate(0) },
      means: { episode_reward: 1, average_speed_mps: 20, comfort_score: 0.5, completion_time_s: 10 },
    },
    {
      strategy: { id: "qualified_rule", version: "v1", model_version: null },
      episode_count: 2,
      outcomes: { merge_success: 2, collision: 0 },
      rates: { success: rate(2), collision: rate(0), timeout: rate(0), offroad: rate(0) },
      means: { episode_reward: 2, average_speed_mps: 21, comfort_score: 0.6, completion_time_s: 9 },
    },
  ],
});

describe("strategy evaluation presenter contract", () => {
  it("accepts a complete paired Seed matrix with mechanical rates", () => {
    const value = result();
    expect(validateStrategyEvaluation(value)).toBe(value);
  });

  it("rejects repeated Seeds and fabricated rates", () => {
    const repeated = result();
    repeated.seeds = [101, 101];
    expect(() => validateStrategyEvaluation(repeated)).toThrow(/distinct Seed/);

    const fabricated = result();
    fabricated.strategies[0].rates.collision.value = 0.9;
    expect(() => validateStrategyEvaluation(fabricated)).toThrow(/mechanically derived/);
  });

  it("rejects a missing strategy/Seed cell", () => {
    const incomplete = result();
    incomplete.episodes[3].seed = 101;
    expect(() => validateStrategyEvaluation(incomplete)).toThrow(/exactly once/);
  });
});
