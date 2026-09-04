export type StrategyEpisode = {
  strategy: {
    id: string;
    version: string;
    model_version: string | null;
  };
  config_digest: string;
  seed: number;
  result: string;
  metrics: {
    episode_reward: number;
    outcome: string;
    collision: boolean;
    success: boolean;
    timeout: boolean;
    average_speed_mps: number;
    completion_time_s: number;
    lane_change_count: number;
    minimum_ttc_s: number | null;
    comfort_score: number;
    comfort_score_label: string;
  };
  replay?: Record<string, unknown>;
};

export type StrategyComparison = {
  schema_version: "strategy-comparison/v1";
  seed: number;
  config_digest: string;
  episodes: StrategyEpisode[];
  aggregation: unknown | null;
  aggregation_reason: string;
};

export type StrategyComparisonRow = {
  strategyId: string;
  version: string;
  result: string;
  episodeReward: number;
  collision: boolean;
  success: boolean;
  timeout: boolean;
  averageSpeedMps: number;
  completionTimeS: number;
  laneChangeCount: number;
  minimumTtcS: number | null;
  comfortScore: number;
  comfortLabel: "舒适度得分（奖励分量）";
  replay?: Record<string, unknown>;
};

export type StrategyComparisonView = {
  seed: number;
  configDigest: string;
  rows: StrategyComparisonRow[];
  singleEpisodeNotice: string;
};

const STRATEGY_ORDER = [
  "manual",
  "random",
  "qualified_rule",
  "construction_dqn_onnx",
] as const;

const COMFORT_LABEL = "舒适度得分（奖励分量）" as const;

export function buildStrategyComparisonView(
  comparison: StrategyComparison,
): StrategyComparisonView {
  if (comparison.schema_version !== "strategy-comparison/v1") {
    throw new Error("unsupported strategy comparison schema");
  }
  if (comparison.aggregation !== null) {
    throw new Error("single-episode strategy comparison must not contain aggregation");
  }
  if (comparison.episodes.length !== STRATEGY_ORDER.length) {
    throw new Error("strategy comparison must contain exactly four episodes");
  }
  const actualOrder = comparison.episodes.map((episode) => episode.strategy.id);
  if (!actualOrder.every((id, index) => id === STRATEGY_ORDER[index])) {
    throw new Error("strategy comparison contains an unknown or reordered strategy");
  }
  for (const episode of comparison.episodes) {
    if (episode.seed !== comparison.seed || episode.config_digest !== comparison.config_digest) {
      throw new Error("all strategy episodes must use the same config and seed");
    }
    if (episode.metrics.comfort_score_label !== COMFORT_LABEL) {
      throw new Error("comfort score must retain its reward-component label");
    }
  }

  return {
    seed: comparison.seed,
    configDigest: comparison.config_digest,
    rows: comparison.episodes.map((episode) => ({
      strategyId: episode.strategy.id,
      version: episode.strategy.model_version
        ? `${episode.strategy.version} · model ${episode.strategy.model_version}`
        : episode.strategy.version,
      result: episode.metrics.outcome,
      episodeReward: episode.metrics.episode_reward,
      collision: episode.metrics.collision,
      success: episode.metrics.success,
      timeout: episode.metrics.timeout,
      averageSpeedMps: episode.metrics.average_speed_mps,
      completionTimeS: episode.metrics.completion_time_s,
      laneChangeCount: episode.metrics.lane_change_count,
      minimumTtcS: episode.metrics.minimum_ttc_s,
      comfortScore: episode.metrics.comfort_score,
      comfortLabel: COMFORT_LABEL,
      replay: episode.replay,
    })),
    singleEpisodeNotice: comparison.aggregation_reason,
  };
}
