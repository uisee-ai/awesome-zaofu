import {
  createRunStatusVisualization,
  type RunStatusVisualization,
} from "../../components/studio/index.js";
import type {
  WorkbenchRun,
  WorkbenchRunConfiguration,
} from "../../../../backend/studio/workbench-runs/workbench-run-service.js";

export type WorkbenchResultsClient = {
  submit(configuration: WorkbenchRunConfiguration): Promise<WorkbenchRun> | WorkbenchRun;
  get(runId: string): Promise<WorkbenchRun | null> | WorkbenchRun | null;
};

export type ResultDetailsKey = "chainOfCausation" | "metaAction";

export interface ResultDetailsView {
  value: string | null;
  expanded: boolean;
  copyable: boolean;
}

export interface WorkbenchResultsSnapshot {
  runId: string | null;
  status: RunStatusVisualization | null;
  vqaAnswer: string | null;
  details: Record<ResultDetailsKey, ResultDetailsView>;
}

export interface PresentedWorkbenchResultsSnapshot extends WorkbenchResultsSnapshot {
  runId: string;
  status: RunStatusVisualization;
}

const emptyDetails = (): Record<ResultDetailsKey, ResultDetailsView> => ({
  chainOfCausation: { value: null, expanded: false, copyable: false },
  metaAction: { value: null, expanded: false, copyable: false },
});

/**
 * Renderer-neutral result panel state for a Workbench submission. UI layers can
 * bind `toggleDetails` and `copyDetails` to their native expand/copy controls.
 */
export class WorkbenchResultsPanel {
  private state: WorkbenchResultsSnapshot = {
    runId: null,
    status: null,
    vqaAnswer: null,
    details: emptyDetails(),
  };

  constructor(private readonly client: WorkbenchResultsClient) {}

  snapshot(): WorkbenchResultsSnapshot {
    return structuredClone(this.state);
  }

  async submit(configuration: WorkbenchRunConfiguration): Promise<PresentedWorkbenchResultsSnapshot> {
    return this.present(await this.client.submit(copyConfiguration(configuration)));
  }

  async refresh(runId: string): Promise<PresentedWorkbenchResultsSnapshot | null> {
    const run = await this.client.get(runId);
    return run === null ? null : this.present(run);
  }

  toggleDetails(key: ResultDetailsKey): ResultDetailsView {
    const details = this.state.details[key];
    if (!details.copyable) throw new Error(`${key} is not available until a run succeeds.`);
    details.expanded = !details.expanded;
    return { ...details };
  }

  copyDetails(key: ResultDetailsKey): string {
    const details = this.state.details[key];
    if (!details.copyable || details.value === null) {
      throw new Error(`${key} is not available until a run succeeds.`);
    }
    return details.value;
  }

  private present(run: WorkbenchRun): PresentedWorkbenchResultsSnapshot {
    const priorDetails = this.state.runId === run.id ? this.state.details : emptyDetails();
    const output = run.output;
    const presented: PresentedWorkbenchResultsSnapshot = {
      runId: run.id,
      status: createRunStatusVisualization(run.state),
      vqaAnswer: output?.vqaAnswer ?? null,
      details: {
        chainOfCausation: detail(output?.chainOfCausation, priorDetails.chainOfCausation.expanded),
        metaAction: detail(output?.metaAction, priorDetails.metaAction.expanded),
      },
    };
    this.state = presented;
    return structuredClone(presented);
  }
}

function detail(value: string | undefined, expanded: boolean): ResultDetailsView {
  return { value: value ?? null, expanded: value === undefined ? false : expanded, copyable: value !== undefined };
}

function copyConfiguration(configuration: WorkbenchRunConfiguration): WorkbenchRunConfiguration {
  return { ...configuration, parameters: structuredClone(configuration.parameters) };
}
