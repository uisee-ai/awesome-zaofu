export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export type AcceptedImageMimeType = "image/jpeg" | "image/png";

export interface AssetUploadCandidate {
  filename: string;
  mimeType: string;
  sizeBytes: number;
}

export interface AcceptedAssetUpload {
  filename: string;
  mimeType: AcceptedImageMimeType;
  sizeBytes: number;
}

export type AssetUploadErrorCode =
  | "UNSUPPORTED_MIME"
  | "EXTENSION_MISMATCH"
  | "FILE_TOO_LARGE"
  | "EMPTY_FILE";

export class AssetUploadError extends Error {
  constructor(
    readonly code: AssetUploadErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "AssetUploadError";
  }
}

const extensionsByMimeType: Record<AcceptedImageMimeType, readonly string[]> = {
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
};

export function validateAssetUpload(candidate: AssetUploadCandidate): AcceptedAssetUpload {
  if (candidate.mimeType !== "image/jpeg" && candidate.mimeType !== "image/png") {
    throw new AssetUploadError("UNSUPPORTED_MIME", "只支持 JPEG 或 PNG 图片。");
  }
  if (!Number.isFinite(candidate.sizeBytes) || candidate.sizeBytes <= 0) {
    throw new AssetUploadError("EMPTY_FILE", "上传文件不能为空。");
  }
  if (candidate.sizeBytes > MAX_UPLOAD_BYTES) {
    throw new AssetUploadError("FILE_TOO_LARGE", "图片不能超过 10 MiB。");
  }

  const extensionMatches = extensionsByMimeType[candidate.mimeType].some((extension) =>
    candidate.filename.toLowerCase().endsWith(extension),
  );
  if (!extensionMatches) {
    throw new AssetUploadError("EXTENSION_MISMATCH", "图片扩展名必须与 MIME 类型一致。");
  }

  return {
    filename: candidate.filename,
    mimeType: candidate.mimeType,
    sizeBytes: candidate.sizeBytes,
  };
}

export type AssetUploadState =
  | { phase: "idle"; progress: 0 }
  | { phase: "uploading"; progress: number }
  | { phase: "complete"; progress: 100 }
  | { phase: "failed"; progress: 0; error: AssetUploadError };

export type AssetUploader = (
  asset: AcceptedAssetUpload,
  reportProgress: (percentage: number) => void,
) => Promise<void>;

export class AssetUploadController {
  private state: AssetUploadState = { phase: "idle", progress: 0 };

  constructor(private readonly uploader: AssetUploader) {}

  snapshot(): AssetUploadState {
    return this.state;
  }

  async upload(candidate: AssetUploadCandidate): Promise<void> {
    let asset: AcceptedAssetUpload;
    try {
      asset = validateAssetUpload(candidate);
    } catch (error) {
      const uploadError = error instanceof AssetUploadError
        ? error
        : new AssetUploadError("UNSUPPORTED_MIME", "无法验证上传文件。");
      this.state = { phase: "failed", progress: 0, error: uploadError };
      throw uploadError;
    }

    this.state = { phase: "uploading", progress: 0 };
    await this.uploader(asset, (percentage) => {
      const boundedProgress = Math.max(0, Math.min(100, Math.round(percentage)));
      this.state = { phase: "uploading", progress: boundedProgress };
    });
    this.state = { phase: "complete", progress: 100 };
  }
}

export function createAssetUploadController(uploader: AssetUploader): AssetUploadController {
  return new AssetUploadController(uploader);
}
