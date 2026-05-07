// Multi-step build wizard state.
//
// Phase 6.2 + 6.3 — three guarantees from the afina-ai-first reference:
//   1) explicit step-by-step prompting through every required setting,
//   2) free back-navigation that keeps prior input intact; downstream
//      steps flip to "needs_confirmation" when an upstream step changes,
//   3) chat-affordance on every step (handled by Wizard.vue, not here).
//
// State is held in a Nuxt useState() so deep links + refresh-tolerance
// work. The current step index is mirrored to the route query so the
// browser back/forward buttons honor wizard navigation.

import { useRoute, useRouter, useState } from "nuxt/app";
import { computed, watch } from "vue";

import type { BuildVariantRequest, EdaReport, Id } from "@/entities/api";

export type WizardStepStatus = "pending" | "in_progress" | "completed" | "needs_confirmation";

export type WizardStepDef = {
  id: string;
  label: string;
  hint?: string;
};

export type DocumentDraft = {
  title: string;
  text: string;
  language?: string;
};

export type BuildWizardData = {
  corpus_id: Id | null;
  corpus_name: string;
  corpus_description: string;
  language: string;
  documents: DocumentDraft[];
  eda?: EdaReport;
  build_request: BuildVariantRequest;
};

export const BUILD_WIZARD_STEPS: WizardStepDef[] = [
  { id: "corpus", label: "Корпус", hint: "Имя и описание корпуса" },
  { id: "documents", label: "Документы", hint: "Загрузите текст" },
  { id: "eda", label: "EDA", hint: "Рекомендации по корпусу" },
  { id: "pipeline", label: "Пайплайн", hint: "Builder / cleaner / clusterer" },
  { id: "review", label: "Запуск", hint: "Подтверждение и сборка" },
];

const DEFAULT_DATA: BuildWizardData = {
  corpus_id: null,
  corpus_name: "",
  corpus_description: "",
  language: "ru",
  documents: [],
  build_request: {
    name: "v1",
    builder: "ner_extraction",
    cleaner_chain: [],
    clusterer: null,
  },
};

export function useBuildWizard() {
  const route = useRoute();
  const router = useRouter();

  const data = useState<BuildWizardData>("build-wizard:data", () => ({
    ...DEFAULT_DATA,
    documents: [],
    build_request: { ...DEFAULT_DATA.build_request, cleaner_chain: [] },
  }));

  const stepStatuses = useState<WizardStepStatus[]>(
    "build-wizard:status",
    () => BUILD_WIZARD_STEPS.map((_, i) => (i === 0 ? "in_progress" : "pending")),
  );

  const currentIndex = computed<number>({
    get() {
      const idx = Number(route.query.step ?? 0);
      return Math.max(0, Math.min(BUILD_WIZARD_STEPS.length - 1, idx));
    },
    set(v: number) {
      const clamped = Math.max(0, Math.min(BUILD_WIZARD_STEPS.length - 1, v));
      router.push({ query: { ...route.query, step: String(clamped) } });
    },
  });

  const currentStep = computed(() => BUILD_WIZARD_STEPS[currentIndex.value]);

  function goTo(index: number) {
    currentIndex.value = index;
  }

  function next() {
    if (currentIndex.value < BUILD_WIZARD_STEPS.length - 1) {
      markCompleted(currentIndex.value);
      currentIndex.value = currentIndex.value + 1;
    }
  }

  function back() {
    if (currentIndex.value > 0) {
      currentIndex.value = currentIndex.value - 1;
    }
  }

  function markCompleted(index: number) {
    stepStatuses.value = stepStatuses.value.map((s, i) =>
      i === index ? "completed" : s,
    );
  }

  /** When the user revises an earlier step, flip every downstream step
   * to "needs_confirmation" so the wizard can show a yellow chip until
   * the user re-acknowledges them.
   */
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
      documents: [],
      build_request: { ...DEFAULT_DATA.build_request, cleaner_chain: [] },
    };
    stepStatuses.value = BUILD_WIZARD_STEPS.map((_, i) =>
      i === 0 ? "in_progress" : "pending",
    );
    currentIndex.value = 0;
  }

  // When the user navigates step ↔ step, mark the destination as
  // "in_progress" if it was pending. Don't downgrade completed steps.
  watch(currentIndex, (idx) => {
    stepStatuses.value = stepStatuses.value.map((s, i) => {
      if (i === idx && s === "pending") return "in_progress";
      return s;
    });
  });

  return {
    steps: BUILD_WIZARD_STEPS,
    data,
    stepStatuses,
    currentIndex,
    currentStep,
    goTo,
    next,
    back,
    markCompleted,
    invalidateDownstream,
    reset,
  };
}
