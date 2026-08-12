import type { TrajectoryPoint } from "../../../packages/contracts/src/scene.js";

export const NAVIGATION_TEMPLATES = {
  continue: "继续直行",
  "turn-left": "在下一个路口左转",
  "turn-right": "在下一个路口右转",
  "keep-left": "保持左侧行驶",
  "keep-right": "保持右侧行驶",
  custom: "自定义导航指令",
} as const;

export type NavigationTemplate = keyof typeof NAVIGATION_TEMPLATES;

export interface NavigationBranchInput {
  id: string;
  template: NavigationTemplate;
  seed: number;
  instruction?: string;
}

export interface NavigationLabInferenceRequest {
  sceneVersionId: string;
  branchId: string;
  template: NavigationTemplate;
  instruction: string;
  seed: number;
}

export interface NavigationLabInferenceOutput {
  chainOfCausation: string;
  metaAction: string;
  trajectory: readonly TrajectoryPoint[];
}

export type NavigationBranchStatus = "succeeded" | "failed";

export interface NavigationExperimentBranch {
  id: string;
  template: NavigationTemplate;
  instruction: string;
  seed: number;
  status: NavigationBranchStatus;
  output?: NavigationLabInferenceOutput;
  error?: string;
}

export interface NavigationLabExperiment {
  sceneVersionId: string;
  branches: NavigationExperimentBranch[];
}

export type NavigationLabErrorCode = "BRANCH_COUNT" | "DUPLICATE_BRANCH_ID" | "CUSTOM_INSTRUCTION";

export class NavigationLabError extends Error {
  constructor(
    readonly code: NavigationLabErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "NavigationLabError";
  }
}

export type NavigationLabInference = (request: Readonly<NavigationLabInferenceRequest>) => Promise<NavigationLabInferenceOutput>;

function copy<T>(value: T): T {
  return structuredClone(value);
}

function resolveInstruction(branch: NavigationBranchInput): string {
  if (branch.template !== "custom") return NAVIGATION_TEMPLATES[branch.template];
  const instruction = branch.instruction?.trim();
  if (instruction === undefined || instruction.length === 0) {
    throw new NavigationLabError("CUSTOM_INSTRUCTION", "自定义导航分支必须提供非空指令。");
  }
  return instruction;
}

function validateBranches(branches: readonly NavigationBranchInput[]): void {
  if (branches.length < 2 || branches.length > 4) {
    throw new NavigationLabError("BRANCH_COUNT", "一个导航实验必须包含 2 到 4 个分支。");
  }

  const ids = new Set<string>();
  for (const branch of branches) {
    if (ids.has(branch.id)) {
      throw new NavigationLabError("DUPLICATE_BRANCH_ID", "导航实验分支 ID 必须唯一。");
    }
    ids.add(branch.id);
    resolveInstruction(branch);
  }
}

/**
 * Executes navigation variations one at a time so experiments obey the Studio's
 * single-inference concurrency boundary while retaining every branch outcome.
 */
export class NavigationLab {
  constructor(private readonly infer: NavigationLabInference) {}

  async run(sceneVersionId: string, branches: readonly NavigationBranchInput[]): Promise<NavigationLabExperiment> {
    validateBranches(branches);
    const results: NavigationExperimentBranch[] = [];

    for (const branch of branches) {
      const instruction = resolveInstruction(branch);
      const request: NavigationLabInferenceRequest = {
        sceneVersionId,
        branchId: branch.id,
        template: branch.template,
        instruction,
        seed: branch.seed,
      };
      try {
        const output = await this.infer(copy(request));
        results.push({
          id: branch.id,
          template: branch.template,
          instruction,
          seed: branch.seed,
          status: "succeeded",
          output: copy(output),
        });
      } catch (error) {
        results.push({
          id: branch.id,
          template: branch.template,
          instruction,
          seed: branch.seed,
          status: "failed",
          error: error instanceof Error ? error.message : "导航分支推理失败。",
        });
      }
    }

    return { sceneVersionId, branches: results };
  }
}
