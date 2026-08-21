export interface SampleStatistics {
  readonly minimum: number;
  readonly maximum: number;
  readonly mean: number;
  readonly median: number;
  readonly p95: number;
}

export function validatePerformanceFixture(fixture: Readonly<Record<string, any>>): true;
export function summarizeSamples(samples: readonly number[]): SampleStatistics;
export function roundMilliseconds(value: number): number;
export function buildPerformanceStatistics(rawSamples: readonly Readonly<Record<string, any>>[]): Readonly<Record<string, any>>;
