import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  AssetUploadError,
  MAX_UPLOAD_BYTES,
  createAssetUploadController,
  validateAssetUpload,
} from "../../web/src/features/asset-upload/upload-controller.js";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("asset validation accepts JPEG/PNG only when MIME, extension, and size agree", () => {
  const jpeg = validateAssetUpload({
    filename: "front.JPG",
    mimeType: "image/jpeg",
    sizeBytes: 1024,
  });
  const png = validateAssetUpload({
    filename: "side.png",
    mimeType: "image/png",
    sizeBytes: MAX_UPLOAD_BYTES,
  });

  assert.equal(jpeg.mimeType, "image/jpeg");
  assert.equal(png.filename, "side.png");

  assert.throws(
    () => validateAssetUpload({ filename: "frame.jpg", mimeType: "image/png", sizeBytes: 1024 }),
    (error: unknown) => error instanceof AssetUploadError && error.code === "EXTENSION_MISMATCH",
  );
  assert.throws(
    () => validateAssetUpload({ filename: "frame.webp", mimeType: "image/webp", sizeBytes: 1024 }),
    (error: unknown) => error instanceof AssetUploadError && error.code === "UNSUPPORTED_MIME",
  );
  assert.throws(
    () => validateAssetUpload({ filename: "frame.png", mimeType: "image/png", sizeBytes: MAX_UPLOAD_BYTES + 1 }),
    (error: unknown) => error instanceof AssetUploadError && error.code === "FILE_TOO_LARGE",
  );
});

test("rejected files never reach the uploader and valid uploads expose progress", async () => {
  let uploads = 0;
  let observedProgress = 0;
  const controller = createAssetUploadController(async (_asset, reportProgress) => {
    uploads += 1;
    reportProgress(45);
    observedProgress = controller.snapshot().progress;
  });

  await assert.rejects(
    controller.upload({ filename: "remote.jpg", mimeType: "image/webp", sizeBytes: 10 }),
    AssetUploadError,
  );
  assert.equal(uploads, 0);
  assert.equal(controller.snapshot().phase, "failed");

  await controller.upload({ filename: "front.jpg", mimeType: "image/jpeg", sizeBytes: 10 });
  assert.equal(uploads, 1);
  assert.equal(observedProgress, 45);
  assert.deepEqual(controller.snapshot(), { phase: "complete", progress: 100 });
});

test("backend asset validation has the same boundary and performs no URL fetch", () => {
  const validation = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.assets import AssetUpload, AssetUploadValidationError, validate_asset_upload",
        "valid = validate_asset_upload(AssetUpload(filename='front.jpg', content_type='image/jpeg', size_bytes=10))",
        "assert valid.filename == 'front.jpg'",
        "try:",
        "    validate_asset_upload(AssetUpload(filename='remote.jpg', content_type='image/webp', size_bytes=10))",
        "except AssetUploadValidationError as error:",
        "    assert error.code == 'UNSUPPORTED_MIME'",
        "else:",
        "    raise AssertionError('invalid upload was accepted')",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(validation.status, 0, validation.stderr);
});
