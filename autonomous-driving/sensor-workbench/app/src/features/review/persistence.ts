export type ReviewFaultPoint = "after_prepare" | "after_commit";

export interface RecoveryResult {
  readonly action: "none" | "rolled_forward" | "cleared_committed_journal";
}

export interface ResetResult {
  readonly action: "none" | "discarded" | "cleared_committed_journal";
}

interface WriteAheadJournal {
  readonly schemaVersion: "review-journal.v1";
  readonly base: string | null;
  readonly next: string;
}

export class AtomicWriteConflictError extends Error {
  constructor() {
    super("review state changed before the atomic commit");
    this.name = "AtomicWriteConflictError";
  }
}

export class InterruptedReviewWriteError extends Error {
  constructor(point: ReviewFaultPoint) {
    super(`review write interrupted ${point.replace("_", " ")}`);
    this.name = "InterruptedReviewWriteError";
  }
}

export class ReviewRecoveryRequiredError extends Error {
  constructor() {
    super("review journal requires recovery or reset before another write");
    this.name = "ReviewRecoveryRequiredError";
  }
}

export interface ReviewPersistence {
  readCommitted(): string | null;
  compareAndSwap(expected: string | null, next: string, faultAt?: ReviewFaultPoint): void;
  recover(): RecoveryResult;
  resetPending(): ResetResult;
}

export class MemoryReviewPersistence implements ReviewPersistence {
  private committed: string | null;
  private journal: WriteAheadJournal | null = null;

  constructor(initialState: string | null = null) {
    this.committed = initialState;
  }

  readCommitted(): string | null {
    return this.committed;
  }

  compareAndSwap(expected: string | null, next: string, faultAt?: ReviewFaultPoint): void {
    if (this.journal) throw new ReviewRecoveryRequiredError();
    if (this.committed !== expected) throw new AtomicWriteConflictError();

    this.journal = { schemaVersion: "review-journal.v1", base: expected, next };
    if (faultAt === "after_prepare") throw new InterruptedReviewWriteError(faultAt);

    this.committed = next;
    if (faultAt === "after_commit") throw new InterruptedReviewWriteError(faultAt);
    this.journal = null;
  }

  recover(): RecoveryResult {
    if (!this.journal) return { action: "none" };
    if (this.committed === this.journal.base) {
      this.committed = this.journal.next;
      this.journal = null;
      return { action: "rolled_forward" };
    }
    if (this.committed === this.journal.next) {
      this.journal = null;
      return { action: "cleared_committed_journal" };
    }
    throw new Error("review journal does not match the committed state");
  }

  resetPending(): ResetResult {
    if (!this.journal) return { action: "none" };
    if (this.committed === this.journal.base) {
      this.journal = null;
      return { action: "discarded" };
    }
    if (this.committed === this.journal.next) {
      this.journal = null;
      return { action: "cleared_committed_journal" };
    }
    throw new Error("review journal does not match the committed state");
  }
}

export class LocalStorageReviewPersistence implements ReviewPersistence {
  private readonly stateKey: string;
  private readonly journalKey: string;

  constructor(
    private readonly storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
    workspaceId: string,
  ) {
    if (!workspaceId.trim()) throw new TypeError("workspaceId must not be empty");
    this.stateKey = `sensor-workbench:${workspaceId}:review-state`;
    this.journalKey = `sensor-workbench:${workspaceId}:review-journal`;
  }

  readCommitted(): string | null {
    return this.storage.getItem(this.stateKey);
  }

  compareAndSwap(expected: string | null, next: string, faultAt?: ReviewFaultPoint): void {
    if (this.storage.getItem(this.journalKey) !== null) throw new ReviewRecoveryRequiredError();
    if (this.readCommitted() !== expected) throw new AtomicWriteConflictError();

    const journal: WriteAheadJournal = { schemaVersion: "review-journal.v1", base: expected, next };
    this.storage.setItem(this.journalKey, JSON.stringify(journal));
    if (faultAt === "after_prepare") throw new InterruptedReviewWriteError(faultAt);

    this.storage.setItem(this.stateKey, next);
    if (faultAt === "after_commit") throw new InterruptedReviewWriteError(faultAt);
    this.storage.removeItem(this.journalKey);
  }

  recover(): RecoveryResult {
    const journal = this.readJournal();
    if (!journal) return { action: "none" };
    const committed = this.readCommitted();
    if (committed === journal.base) {
      this.storage.setItem(this.stateKey, journal.next);
      this.storage.removeItem(this.journalKey);
      return { action: "rolled_forward" };
    }
    if (committed === journal.next) {
      this.storage.removeItem(this.journalKey);
      return { action: "cleared_committed_journal" };
    }
    throw new Error("review journal does not match the committed state");
  }

  resetPending(): ResetResult {
    const journal = this.readJournal();
    if (!journal) return { action: "none" };
    const committed = this.readCommitted();
    if (committed === journal.base) {
      this.storage.removeItem(this.journalKey);
      return { action: "discarded" };
    }
    if (committed === journal.next) {
      this.storage.removeItem(this.journalKey);
      return { action: "cleared_committed_journal" };
    }
    throw new Error("review journal does not match the committed state");
  }

  private readJournal(): WriteAheadJournal | null {
    const serialized = this.storage.getItem(this.journalKey);
    if (serialized === null) return null;
    let value: unknown;
    try {
      value = JSON.parse(serialized);
    } catch {
      throw new TypeError("review journal is corrupted JSON");
    }
    if (
      typeof value !== "object" ||
      value === null ||
      (value as Record<string, unknown>).schemaVersion !== "review-journal.v1" ||
      !((value as Record<string, unknown>).base === null || typeof (value as Record<string, unknown>).base === "string") ||
      typeof (value as Record<string, unknown>).next !== "string"
    ) {
      throw new TypeError("review journal is corrupted");
    }
    return value as unknown as WriteAheadJournal;
  }
}
