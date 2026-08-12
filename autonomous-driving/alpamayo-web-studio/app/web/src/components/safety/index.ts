/**
 * Shared copy for every Studio entry point. Keep this declaration visible at
 * each demo boundary: it limits the product to research and evaluation use.
 */
export const RESEARCH_USE_NOTICE =
  "Alpamayo Web Studio 仅用于研究、实验、评测和演示。模型输出、CoC、Meta Action 和轨迹预测不得直接用于真实车辆控制，不构成安全认证或经过验证的驾驶安全结论，也不能替代完整的感知、规划、控制、冗余和安全保障系统。";

/** Returns the canonical research-and-safety declaration for shared rendering. */
export function createResearchUseNotice(): string {
  return RESEARCH_USE_NOTICE;
}
