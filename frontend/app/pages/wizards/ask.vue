<script setup lang="ts">
  import { computed, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import ModeStep from "@/components/organisms/AskWizard/steps/ModeStep.vue";
  import QueryStep from "@/components/organisms/AskWizard/steps/QueryStep.vue";
  import ResultsStep from "@/components/organisms/AskWizard/steps/ResultsStep.vue";
  import StrategyStep from "@/components/organisms/AskWizard/steps/StrategyStep.vue";
  import VariantsStep from "@/components/organisms/AskWizard/steps/VariantsStep.vue";
  import WizardFrame from "@/components/organisms/Wizard/WizardFrame.vue";
  import { useAskWizard } from "@/composables/use-ask-wizard";

  const { t } = useI18n();
  const wizard = useAskWizard();
  const resultsRef = ref<InstanceType<typeof ResultsStep> | null>(null);

  const canAdvance = computed(() => {
    const idx = wizard.currentIndex.value;
    const data = wizard.data.value;
    if (idx === 0) return Boolean(data.mode);
    if (idx === 1)
      return data.variant_ids.length >= (data.mode === "single" ? 1 : 2);
    if (idx === 2) return Boolean(data.reasoner) && Boolean(data.aggregator);
    if (idx === 3) return data.query.trim().length > 0;
    return false;
  });

  function onAdvance() {
    if (wizard.currentIndex.value === wizard.steps.length - 1) {
      resultsRef.value?.ask();
      return;
    }
    wizard.next();
  }
</script>

<template>
  <WizardFrame
    :title="t('wizard.askPage.title')"
    :steps="wizard.steps"
    :statuses="wizard.stepStatuses.value"
    :current-index="wizard.currentIndex.value"
    :can-advance="canAdvance"
    :advance-label="wizard.currentIndex.value === wizard.steps.length - 1 ? t('wizard.askPage.advanceFinal') : t('wizard.askPage.advance')"
    @navigate="(i) => wizard.goTo(i)"
    @back="wizard.back"
    @advance="onAdvance"
  >
    <ModeStep v-if="wizard.currentIndex.value === 0" />
    <VariantsStep v-else-if="wizard.currentIndex.value === 1" />
    <StrategyStep v-else-if="wizard.currentIndex.value === 2" />
    <QueryStep v-else-if="wizard.currentIndex.value === 3" />
    <ResultsStep v-else ref="resultsRef" />
  </WizardFrame>
</template>
