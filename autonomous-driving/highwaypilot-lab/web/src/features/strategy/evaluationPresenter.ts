export type Rate = {
  value: number;
  numerator: number;
  denominator: number;
  ci95: [number, number];
};

export type EvaluationEpisode = {
  episode_id: string;
  seed: number;
  config_digest: string;
  strategy: { id: string; version: string; model_version: string | null };
  result: string;
  metrics: Record<string, unknown>;
};

export type StrategyEvaluationResult = {
  schema_version: "strategy-evaluation/v1";
  seeds: number[];
  episodes_per_strategy: number;
  strategy_order: string[];
  total_episodes: number;
  episodes: EvaluationEpisode[];
  strategies: Array<{
    strategy: { id: string; version: string; model_version: string | null };
    episode_count: number;
    outcomes: Record<string, number>;
    rates: { success: Rate; collision: Rate; timeout: Rate; offroad: Rate };
    means: {
      episode_reward: number;
      average_speed_mps: number;
      comfort_score: number;
      completion_time_s: number;
    };
  }>;
};

export type StrategyEvaluationJob = {
  evaluation_id: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  progress: { completed: number; total: number };
  result: StrategyEvaluationResult | null;
  error: string | null;
};

const close = (left: number, right: number): boolean => Math.abs(left - right) <= 1e-10;

export function validateStrategyEvaluation(result: StrategyEvaluationResult): StrategyEvaluationResult {
  if (result.schema_version !== "strategy-evaluation/v1") throw new Error("unsupported strategy evaluation schema");
  if (result.seeds.length !== result.episodes_per_strategy || new Set(result.seeds).size !== result.seeds.length) {
    throw new Error("evaluation must contain one distinct Seed per sample");
  }
  if (result.total_episodes !== result.seeds.length * result.strategy_order.length) {
    throw new Error("evaluation total does not match the paired Seed matrix");
  }
  if (result.episodes.length !== result.total_episodes || result.strategies.length !== result.strategy_order.length) {
    throw new Error("evaluation result is incomplete");
  }
  for (const [index, row] of result.strategies.entries()) {
    if (row.strategy.id !== result.strategy_order[index] || row.episode_count !== result.seeds.length) {
      throw new Error("evaluation strategy order or denominator differs");
    }
    for (const rate of Object.values(row.rates)) {
      if (rate.denominator !== row.episode_count || !close(rate.value, rate.numerator / rate.denominator)) {
        throw new Error("evaluation rate is not mechanically derived from its count");
      }
      if (rate.ci95.length !== 2 || rate.ci95[0] < 0 || rate.ci95[1] > 1 || rate.ci95[0] > rate.ci95[1]) {
        throw new Error("evaluation confidence interval is invalid");
      }
    }
    for (const seed of result.seeds) {
      const matches = result.episodes.filter((episode) => episode.seed === seed && episode.strategy.id === row.strategy.id);
      if (matches.length !== 1) throw new Error("each strategy must run exactly once for each Seed");
    }
  }
  return result;
}
