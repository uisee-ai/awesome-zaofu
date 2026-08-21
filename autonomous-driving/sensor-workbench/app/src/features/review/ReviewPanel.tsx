import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  toEvidenceReceiptWire,
  toExportEnvelopeWire,
  type EvidenceReceiptV1,
  type ReviewEventTypeV1,
  type ReviewPayloadV1,
  type ReviewSeverityV1,
  type ReviewStatusV1,
  type ReviewTargetV1,
} from "../../contracts";
import { InterruptedReviewWriteError, type ReviewFaultPoint } from "./persistence";
import { type ReviewSnapshot, ReviewStore } from "./store";

export interface ReviewPanelProps {
  readonly store: ReviewStore;
  readonly reviewId: string;
  readonly frameContextId: string;
  readonly target: ReviewTargetV1;
  readonly actorId: string;
  readonly faultAtNextAppend?: ReviewFaultPoint;
  readonly evidenceReceipt?: EvidenceReceiptV1;
  readonly now?: () => string;
  readonly createId?: (kind: "event" | "export") => string;
}

const EMPTY_PAYLOAD: ReviewPayloadV1 = {
  issueCode: null,
  comment: null,
  status: null,
  suggestion: null,
  severity: null,
};

interface OpenLaneLaneSelectionDetail {
  readonly laneRef: string;
}

const OPENLANE_LANE_SELECTION_EVENT = "openlane-lane-selected";

function defaultId(kind: "event" | "export"): string {
  return `${kind}-${globalThis.crypto.randomUUID()}`;
}

export function ReviewPanel({
  store,
  reviewId,
  frameContextId,
  target,
  actorId,
  faultAtNextAppend,
  evidenceReceipt,
  now = () => new Date().toISOString(),
  createId = defaultId,
}: ReviewPanelProps) {
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null);
  const [currentTarget, setCurrentTarget] = useState<ReviewTargetV1>(target);
  const [issueCode, setIssueCode] = useState("");
  const [comment, setComment] = useState("");
  const [status, setStatus] = useState<ReviewStatusV1>("pending");
  const [severity, setSeverity] = useState<ReviewSeverityV1>("medium");
  const [suggestion, setSuggestion] = useState("");
  const [exportText, setExportText] = useState("");
  const [importText, setImportText] = useState("");
  const [importStatus, setImportStatus] = useState("");
  const [recoveryStatus, setRecoveryStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pendingFault = useRef(faultAtNextAppend);

  const refresh = useCallback(async () => setSnapshot(await store.snapshot()), [store]);

  useEffect(() => {
    let active = true;
    void store
      .recover()
      .then(async (result) => {
        const next = await store.snapshot();
        if (!active) return;
        setSnapshot(next);
        if (result.action !== "none") setRecoveryStatus("已恢复完整写入");
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      active = false;
    };
  }, [store]);

  useEffect(() => setCurrentTarget(target), [target]);

  useEffect(() => {
    const updateTargetFromOpenLane = (event: Event) => {
      const detail = (event as CustomEvent<OpenLaneLaneSelectionDetail>).detail;
      if (typeof detail?.laneRef === "string" && detail.laneRef.trim()) {
        setCurrentTarget({ kind: "lane", stableId: detail.laneRef });
      }
    };
    globalThis.addEventListener(OPENLANE_LANE_SELECTION_EVENT, updateTargetFromOpenLane);
    return () => globalThis.removeEventListener(OPENLANE_LANE_SELECTION_EVENT, updateTargetFromOpenLane);
  }, []);

  const currentReview = useMemo(
    () => snapshot?.reviews.find((review) => review.reviewId === reviewId) ?? null,
    [reviewId, snapshot],
  );

  const append = useCallback(
    async (eventType: ReviewEventTypeV1, payload: ReviewPayloadV1) => {
      setBusy(true);
      setError("");
      try {
        const faultAt = pendingFault.current;
        pendingFault.current = undefined;
        const result = await store.append(
          {
            eventId: createId("event"),
            reviewId,
            expectedRevision: currentReview?.revision ?? 0,
            frameContextId,
            target: currentTarget,
            eventType,
            occurredAt: now(),
            actorId,
            payload,
          },
          { faultAt },
        );
        if (result.status === "conflict") {
          setError(`revision 冲突：期望 ${result.expectedRevision}，当前 ${result.actualRevision}`);
        }
      } catch (cause) {
        if (cause instanceof InterruptedReviewWriteError) {
          await store.recover();
          setRecoveryStatus("已恢复完整写入");
        } else {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      } finally {
        await refresh();
        setBusy(false);
      }
    }, [actorId, createId, currentReview?.revision, currentTarget, frameContextId, now, refresh, reviewId, store]);

  const exportDiff = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const envelope = await store.exportDiff({ exportId: createId("export"), createdAt: now(), sinceSequence: 0 });
      setExportText(JSON.stringify(toExportEnvelopeWire(envelope), null, 2));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [createId, now, refresh, store]);

  const importDiff = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      if (!importText.trim()) throw new TypeError("导入差异不能为空");
      const result = await store.importDiff(JSON.parse(importText));
      setImportStatus(`重复 ${result.duplicates}，新增 ${result.imported}`);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [importText, refresh, store]);

  return (
    <section className="swb-review-panel" data-testid="review-panel" aria-label="审核历史">
      <header className="swb-review-header">
        <div>
          <p className="swb-review-eyebrow">ANNOTATION REVIEW</p>
          <h2>审核</h2>
        </div>
        <span className="swb-review-revision" data-testid="review-revision">revision {currentReview?.revision ?? 0}</span>
      </header>

      <section className="swb-review-context" aria-label="当前审核上下文">
        <span>当前目标</span>
        <output data-testid="review-current-target" aria-live="polite" aria-label="当前审核目标">
          {currentTarget.kind}: {currentTarget.stableId}
        </output>
        <span>帧上下文</span>
        <output data-testid="review-current-frame-context" aria-live="polite" aria-label="当前审核帧上下文">
          {frameContextId}
        </output>
      </section>

      <section className="swb-review-card" aria-label="创建审核问题">
        <h3>创建问题</h3>
        <div className="swb-review-grid">
          <label className="swb-review-field swb-review-field-wide">
            <span>问题代码</span>
            <input placeholder="例如：MISALIGNED_BOX" value={issueCode} onChange={(event) => setIssueCode(event.target.value)} />
          </label>
          <label className="swb-review-field">
            <span>严重度</span>
            <select value={severity} onChange={(event) => setSeverity(event.target.value as ReviewSeverityV1)}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </label>
        </div>
        <button
          className="swb-review-primary"
          type="button"
          disabled={busy}
          onClick={() =>
            void append("issue_created", { ...EMPTY_PAYLOAD, issueCode: issueCode.trim(), severity, status: "pending" }).then(() =>
              setIssueCode(""),
            )
          }
        >
          创建问题
        </button>
      </section>

      <section className="swb-review-card" aria-label="处理审核记录">
        <h3>处理记录</h3>
        <label className="swb-review-field">
          <span>评论</span>
          <input placeholder="补充审核依据或处理说明" value={comment} onChange={(event) => setComment(event.target.value)} />
        </label>
        <button type="button" disabled={busy} onClick={() => void append("comment_added", { ...EMPTY_PAYLOAD, comment: comment.trim() }).then(() => setComment(""))}>
          添加评论
        </button>

        <div className="swb-review-grid">
          <label className="swb-review-field">
            <span>状态</span>
            <select value={status} onChange={(event) => setStatus(event.target.value as ReviewStatusV1)}>
              <option value="pending">pending</option>
              <option value="needs_fix">needs_fix</option>
              <option value="accepted">accepted</option>
              <option value="resolved">resolved</option>
              <option value="dismissed">dismissed</option>
            </select>
          </label>
          <button className="swb-review-align-end" type="button" disabled={busy} onClick={() => void append("status_changed", { ...EMPTY_PAYLOAD, status })}>
            更新状态
          </button>
        </div>
        <label className="swb-review-field">
          <span>建议</span>
          <input placeholder="可选的修订建议" value={suggestion} onChange={(event) => setSuggestion(event.target.value)} />
        </label>
        <button type="button" disabled={busy} onClick={() => void append("suggestion_changed", { ...EMPTY_PAYLOAD, suggestion: suggestion.trim() }).then(() => setSuggestion(""))}>
          更新建议
        </button>
      </section>

      <section className="swb-review-history-card">
        <div className="swb-review-history-heading">
          <h3>审核历史</h3>
          <output data-testid="review-summary">{currentReview?.status ?? "未创建"} · {currentReview?.severity ?? "未设置"}</output>
        </div>
        <ol data-testid="review-history" aria-label="审核事件">
          {snapshot?.events
            .filter((event) => event.reviewId === reviewId)
            .map((event) => (
              <li key={event.eventId} data-testid="review-event-target" data-target-kind={event.target.kind} data-target-ref={event.target.stableId}>
                <strong>r{event.revision}</strong>
                <span>{event.payload.comment ?? event.payload.issueCode ?? event.payload.status ?? event.payload.suggestion}</span>
                <small>{event.target.kind}: {event.target.stableId}</small>
              </li>
            ))}
        </ol>
      </section>

      <section className="swb-review-transfer" aria-label="导入与导出差异">
        <h3>导入与导出</h3>
        <button type="button" disabled={busy} onClick={() => void exportDiff()}>导出差异</button>
        <label className="swb-review-field">
          <span>导出 JSON</span>
          <textarea data-testid="review-export-json" readOnly value={exportText} />
        </label>
        <label className="swb-review-field">
          <span>导入差异</span>
          <textarea placeholder="粘贴导出的 JSON 差异" value={importText} onChange={(event) => setImportText(event.target.value)} />
        </label>
        <button type="button" disabled={busy} onClick={() => void importDiff()}>导入差异</button>
        <output data-testid="review-import-status">{importStatus}</output>
      </section>

      <output className="swb-review-recovery" data-testid="review-recovery-status">{recoveryStatus}</output>
      {error ? <p role="alert">{error}</p> : null}
      <script type="application/json" data-testid="review-evidence-receipt">
        {evidenceReceipt ? JSON.stringify(toEvidenceReceiptWire(evidenceReceipt)) : "{}"}
      </script>
    </section>
  );
}
