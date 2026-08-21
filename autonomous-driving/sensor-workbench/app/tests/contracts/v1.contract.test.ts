import { describe, expect, it } from "vitest";

import {
  ADAPTER_CONTRACT_VERSION,
  EVIDENCE_RECEIPT_VERSION,
  EXPORT_ENVELOPE_VERSION,
  FRAME_CONTEXT_VERSION,
  REVIEW_EVENT_VERSION,
  WORKSPACE_CONTRACT_VERSION,
  parseAdapterDescriptorWire,
  parseEvidenceReceiptWire,
  parseExportEnvelopeWire,
  parseFrameContextWire,
  parseReviewEventWire,
  parseWorkspaceWire,
  toAdapterDescriptorWire,
  toEvidenceReceiptWire,
  toExportEnvelopeWire,
  toFrameContextWire,
  toReviewEventWire,
  toWorkspaceWire,
} from "../../src/contracts";
import {
  adapterDescriptorCamelGolden,
  adapterDescriptorWireGolden,
  evidenceReceiptCamelGolden,
  evidenceReceiptWireGolden,
  exportEnvelopeCamelGolden,
  exportEnvelopeWireGolden,
  frameContextCamelGolden,
  frameContextWireGolden,
  reviewEventCamelGolden,
  reviewEventWireGolden,
  workspaceCamelGolden,
  workspaceWireGolden,
} from "./fixtures/v1.golden";

describe("immutable v1 contract versions", () => {
  it("exports every canonical version literal", () => {
    expect({
      adapter: ADAPTER_CONTRACT_VERSION,
      evidence: EVIDENCE_RECEIPT_VERSION,
      export: EXPORT_ENVELOPE_VERSION,
      frame: FRAME_CONTEXT_VERSION,
      review: REVIEW_EVENT_VERSION,
      workspace: WORKSPACE_CONTRACT_VERSION,
    }).toEqual({
      adapter: "adapter.v1",
      evidence: "evidence-receipt.v1",
      export: "export-envelope.v1",
      frame: "frame-context.v1",
      review: "review-event.v1",
      workspace: "workspace.v1",
    });
  });
});

describe.each([
  ["adapter", adapterDescriptorCamelGolden, adapterDescriptorWireGolden, toAdapterDescriptorWire, parseAdapterDescriptorWire],
  ["frame context", frameContextCamelGolden, frameContextWireGolden, toFrameContextWire, parseFrameContextWire],
  ["workspace", workspaceCamelGolden, workspaceWireGolden, toWorkspaceWire, parseWorkspaceWire],
  ["review event", reviewEventCamelGolden, reviewEventWireGolden, toReviewEventWire, parseReviewEventWire],
  ["export envelope", exportEnvelopeCamelGolden, exportEnvelopeWireGolden, toExportEnvelopeWire, parseExportEnvelopeWire],
  ["evidence receipt", evidenceReceiptCamelGolden, evidenceReceiptWireGolden, toEvidenceReceiptWire, parseEvidenceReceiptWire],
] as const)("%s wire parity", (_name, camelGolden, wireGolden, serialize, parse) => {
  it("serializes every camelCase field to the exact snake_case golden object", () => {
    expect(serialize(camelGolden as never)).toEqual(wireGolden);
  });

  it("parses every snake_case field and ignores unknown forward-compatible fields", () => {
    expect(parse({ ...wireGolden, future_v2_field: "ignored-by-v1" } as never)).toEqual(camelGolden);
  });
});

describe("fail-closed v1 readers", () => {
  it("rejects a frame without the complete sensor offset list", () => {
    const { sensor_frames: _sensorFrames, ...incomplete } = frameContextWireGolden;
    expect(() => parseFrameContextWire(incomplete)).toThrow(/sensor_frames/);
  });

  it("rejects evidence that could claim passed with a non-zero exit", () => {
    expect(() => parseEvidenceReceiptWire({ ...evidenceReceiptWireGolden, exit_code: 1 })).toThrow(/exit_code/);
  });

  it("rejects exports that contain media or absolute paths", () => {
    expect(() => parseExportEnvelopeWire({ ...exportEnvelopeWireGolden, media_included: true })).toThrow(/media_included/);
    expect(() => parseExportEnvelopeWire({ ...exportEnvelopeWireGolden, absolute_paths_included: true })).toThrow(
      /absolute_paths_included/,
    );
  });
});
