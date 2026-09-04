import { describe, expect, it } from "vitest";

import { buildStrategyComparisonView } from "../../../web/src/features/strategy/comparisonPresenter.ts";


const episode = (id: string, version: string, modelVersion: string | null = null) => ({
  strategy: { id, version, model_version: modelVersion },
  config_digest: "a".repeat(64),
  seed: 19,
  result: "merge_success",
  metrics: {
    episode_reward: 4.25,
    outcome: "merge_success",
    collision: false,
    success: true,
    timeout: false,
    average_speed_mps: 21.5,
    completion_time_s: 8,
    lane_change_count: 1,
    minimum_ttc_s: 3.5,
    comfort_score: 0.75,
    comfort_score_label: "舒适度得分（奖励分量）",
  },
});


describe("strategy comparison presenter", () => {
  it("shows four same-seed episodes with versions and no fabricated rates", () => {
    const view = buildStrategyComparisonView({
      schema_version: "strategy-comparison/v1",
      seed: 19,
      config_digest: "a".repeat(64),
      aggregation: null,
      aggregation_reason: "single episodes do not define rates, rankings or confidence intervals",
      episodes: [
        episode("manual", "manual-policy/v1"),
        episode("random", "random-policy/highwaypilot-rng-v1"),
        episode("qualified_rule", "qualified-rule-policy/v1"),
        episode("construction_dqn_onnx", "onnx-learning-policy/v1", "1.0.0"),
      ],
    });

    expect(view.seed).toBe(19);
    expect(view.rows.map((row) => row.strategyId)).toEqual([
      "manual",
      "random",
      "qualified_rule",
      "construction_dqn_onnx",
    ]);
    expect(view.rows[3].version).toBe("onnx-learning-policy/v1 · model 1.0.0");
    expect(view.rows[0].comfortLabel).toBe("舒适度得分（奖励分量）");
    expect(view.rows[0]).toMatchObject({ collision: false, success: true, timeout: false });
    for (const row of view.rows) {
      expect(Object.keys(row)).not.toContain("successRate");
      expect(Object.keys(row)).not.toContain("collisionRate");
      expect(Object.keys(row)).not.toContain("ranking");
      expect(Object.keys(row)).not.toContain("confidenceInterval");
    }
    expect(view.singleEpisodeNotice).toMatch(/do not define rates/);
  });

  it("fails closed when rows differ in seed/config or contain aggregation", () => {
    const base = {
      schema_version: "strategy-comparison/v1" as const,
      seed: 19,
      config_digest: "a".repeat(64),
      aggregation_reason: "single episode",
      episodes: [
        episode("manual", "manual-policy/v1"),
        episode("random", "random-policy/highwaypilot-rng-v1"),
        episode("qualified_rule", "qualified-rule-policy/v1"),
        episode("construction_dqn_onnx", "onnx-learning-policy/v1", "1.0.0"),
      ],
    };

    expect(() => buildStrategyComparisonView({ ...base, aggregation: { success_rate: 1 } })).toThrow(
      /aggregation/,
    );
    const drifted = structuredClone(base);
    drifted.episodes[2].config_digest = "b".repeat(64);
    expect(() => buildStrategyComparisonView({ ...drifted, aggregation: null })).toThrow(
      /same config/,
    );
  });
});
