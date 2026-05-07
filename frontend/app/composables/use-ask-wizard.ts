// Reasoning wizard state — sibling of use-build-wizard, same three
// guarantees (step-by-step / back-nav / chat-affordance), wraps a
// MoE/single reason run.

import { useRoute, useRouter, useState } from "nuxt/app";
import { computed, watch } from "vue";

import type { ExpertResult, Id, MoEResult, ReasonMode } from "@/entities/api";
import type { WizardStepDef, WizardStepStatus } from "@/composables/use-build-wizard";

export type AskWizardData = {
  mode: ReasonMode;
  variant_ids: Id[];
  reasoner: string;
  aggregator: string;
  query: string;
  reasoner_params: Record<string, unknown>;
  aggregator_params: Record<string, unknown>;
};

export const ASK_WIZARD_STEPS: WizardStepDef[] = [
  { id: "mode", label: "Режим", hint: "Single или MoE" },
  { id: "variants", label: "Варианты", hint: "Какие графы спрашиваем" },
  { id: "strategy", label: "Стратегия", hint: "Reasoner и aggregator" },
  { id: "query", label: "Вопрос" },
  { id: "results", label: "Ответ" },
];

const DEFAULT_DATA: AskWizardData = {
  mode: "single",
  variant_ids: [],
  reasoner: "keyword_search",
  aggregator: "evidence_union",
  query: "",
  reasoner_params: {},
  aggregator_params: {},
};

export type StreamingState = {
  running: boolean;
  experts: ExpertResult[];
  answer: MoEResult | null;
  error: string | null;
};

export function useAskWizard() {
  const route = useRoute();
  const router = useRouter();

  const data = useState<AskWizardData>("ask-wizard:data", () => ({
    ...DEFAULT_DATA,
    variant_ids: [],
    reasoner_params: {},
    aggregator_params: {},
  }));
  const stepStatuses = useState<WizardStepStatus[]>(
    "ask-wizard:status",
    () => ASK_WIZARD_STEPS.map((_, i) => (i === 0 ? "in_progress" : "pending")),
  );
  const streaming = useState<StreamingState>("ask-wizard:stream", () => ({
    running: false,
    experts: [],
    answer: null,
    error: null,
  }));

  const currentIndex = computed<number>({
    get() {
      const idx = Number(route.query.step ?? 0);
      return Math.max(0, Math.min(ASK_WIZARD_STEPS.length - 1, idx));
    },
    set(v: number) {
      const clamped = Math.max(0, Math.min(ASK_WIZARD_STEPS.length - 1, v));
      router.push({ query: { ...route.query, step: String(clamped) } });
    },
  });

  const currentStep = computed(() => ASK_WIZARD_STEPS[currentIndex.value]);

  function goTo(index: number) {
    currentIndex.value = index;
  }

  function next() {
    if (currentIndex.value < ASK_WIZARD_STEPS.length - 1) {
      stepStatuses.value = stepStatuses.value.map((s, i) =>
        i === currentIndex.value ? "completed" : s,
      );
      currentIndex.value = currentIndex.value + 1;
    }
  }

  function back() {
    if (currentIndex.value > 0) currentIndex.value = currentIndex.value - 1;
  }

  function invalidateDownstream(fromIndex: number) {
    stepStatuses.value = stepStatuses.value.map((s, i) => {
      if (i <= fromIndex) return s;
      if (s === "completed") return "needs_confirmation";
      return s;
    });
  }

  function reset() {
    data.value = {
      ...DEFAULT_DATA,
      variant_ids: [],
      reasoner_params: {},
      aggregator_params: {},
    };
    stepStatuses.value = ASK_WIZARD_STEPS.map((_, i) =>
      i === 0 ? "in_progress" : "pending",
    );
    streaming.value = { running: false, experts: [], answer: null, error: null };
    currentIndex.value = 0;
  }

  watch(currentIndex, (idx) => {
    stepStatuses.value = stepStatuses.value.map((s, i) => {
      if (i === idx && s === "pending") return "in_progress";
      return s;
    });
  });

  return {
    steps: ASK_WIZARD_STEPS,
    data,
    stepStatuses,
    streaming,
    currentIndex,
    currentStep,
    goTo,
    next,
    back,
    invalidateDownstream,
    reset,
  };
}
