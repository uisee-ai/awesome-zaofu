import {
  type AutoLabelAnnotation,
  type AutoLabelFilter,
  type GenerateAutoLabelInput,
  type ReviewInput,
  AutoLabelService,
} from "../../../../backend/studio/labels/auto-label-service.js";

/** UI-facing facade for generating, reviewing, filtering, and exporting labels. */
export class AutoLabelStudioController {
  constructor(private readonly service: AutoLabelService) {}

  generate(input: GenerateAutoLabelInput): AutoLabelAnnotation {
    return this.service.generate(input);
  }

  review(annotationId: string, input: ReviewInput): AutoLabelAnnotation {
    return this.service.review(annotationId, input);
  }

  filter(filter: AutoLabelFilter = {}): AutoLabelAnnotation[] {
    return this.service.list(filter);
  }

  exportJsonl(filter: AutoLabelFilter = {}): string {
    return this.service.exportJsonl(filter);
  }
}
