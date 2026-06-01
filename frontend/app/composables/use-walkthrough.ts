// §2.6 guided walkthrough state owner. Headless: GuidedWalkthrough.vue
// renders, this composable drives index / active / persistence.
//
// Steps mirror demo_scenario.md's numbered flow (corpora → graph → layer
// focus → node drawer → suggestions → ask). Each carries a targetTestId
// pointing at a stable testid_contract anchor so the spotlight can
// getBoundingClientRect() the live element.
//
// Auto-start: the GRAPH PAGE decides — it calls start() when
// route.query.walkthrough==='1' OR (first visit && !seen). finish / skip
// / dismiss all persist seen=true so the tour never nags again.

import { computed, ref, type ComputedRef, type Ref } from "vue";

const SEEN_KEY = "gr:walkthrough:seen";

export type WalkStep = {
  id: string;
  titleKey: string;
  bodyKey: string;
  /** data-testid of the element the spotlight should frame. */
  targetTestId?: string;
  route?: string;
};

// Defined once here from demo_scenario.md. targetTestId values are part
// of the testid_contract so the spotlight resolves real DOM anchors.
const STEPS: WalkStep[] = [
  {
    id: "corpora",
    titleKey: "walkthrough.step1Title",
    bodyKey: "walkthrough.step1Body",
    targetTestId: "graph-canvas",
  },
  {
    id: "graph",
    titleKey: "walkthrough.step2Title",
    bodyKey: "walkthrough.step2Body",
    targetTestId: "graph-canvas",
  },
  {
    id: "layer-focus",
    titleKey: "walkthrough.step3Title",
    bodyKey: "walkthrough.step3Body",
    targetTestId: "delta-legend",
  },
  {
    id: "node-drawer",
    titleKey: "walkthrough.step4Title",
    bodyKey: "walkthrough.step4Body",
    targetTestId: "node-drawer",
  },
  {
    id: "suggestions",
    titleKey: "walkthrough.step5Title",
    bodyKey: "walkthrough.step5Body",
    targetTestId: "suggestions-sidebar",
  },
  {
    id: "ask",
    titleKey: "walkthrough.step6Title",
    bodyKey: "walkthrough.step6Body",
    targetTestId: "timeline-toggle",
  },
];

function readSeen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function persistSeen() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* private mode / disabled storage — non-fatal */
  }
}

export type Walkthrough = {
  active: Ref<boolean>;
  index: Ref<number>;
  steps: WalkStep[];
  current: ComputedRef<WalkStep>;
  total: number;
  start: () => void;
  next: () => void;
  back: () => void;
  skip: () => void;
  finish: () => void;
  dismiss: () => void;
  hasSeen: () => boolean;
};

export function useWalkthrough(): Walkthrough {
  const active = ref(false);
  const index = ref(0);
  const steps = STEPS;
  const total = steps.length;

  const current = computed(() => steps[Math.min(index.value, total - 1)]);

  function start() {
    index.value = 0;
    active.value = true;
  }

  function next() {
    if (index.value >= total - 1) {
      finish();
      return;
    }
    index.value = Math.min(index.value + 1, total - 1);
  }

  function back() {
    index.value = Math.max(index.value - 1, 0);
  }

  function close() {
    active.value = false;
    persistSeen();
  }

  // skip / finish / dismiss all close + persist so the tour is one-shot.
  function skip() {
    close();
  }
  function finish() {
    close();
  }
  function dismiss() {
    close();
  }

  return {
    active,
    index,
    steps,
    current,
    total,
    start,
    next,
    back,
    skip,
    finish,
    dismiss,
    hasSeen: readSeen,
  };
}
