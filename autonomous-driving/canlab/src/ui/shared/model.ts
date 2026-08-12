export interface CanLabAssetMetadata {
  readonly schema_version: string
  readonly asset: { readonly name: string; readonly file: string; readonly version: string; readonly source: string; readonly license: string; readonly sha256: string }
  readonly validation_vectors: { readonly file: string; readonly version: string; readonly sha256: string }
  readonly drive_cycle: {
    readonly file: string
    readonly schema: string
    readonly schema_version: string
    readonly seed: number
    readonly scenario: string
    readonly sha256: string
    readonly phases: readonly string[]
    readonly expected_period_us: Readonly<Record<string, number>>
  }
}
