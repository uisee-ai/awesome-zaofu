export interface P0EvidenceArtifact {
  path: string
  sha256: string
  byte_count: number
}

/** Preserve durable artifacts while replacing hashes for the files a gate regenerated. */
export const mergeP0EvidenceArtifacts = (
  existing: readonly P0EvidenceArtifact[],
  regenerated: readonly P0EvidenceArtifact[],
): P0EvidenceArtifact[] => {
  const byPath = new Map(existing.map((artifact) => [artifact.path, artifact]))
  for (const artifact of regenerated) byPath.set(artifact.path, artifact)
  return [...byPath.values()]
}
