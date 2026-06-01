<script setup lang="ts">
  import { computed, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import CorpusStep from "@/components/organisms/Wizard/steps/CorpusStep.vue";
  import DocumentsStep from "@/components/organisms/Wizard/steps/DocumentsStep.vue";
  import EdaStep from "@/components/organisms/Wizard/steps/EdaStep.vue";
  import PipelineStep from "@/components/organisms/Wizard/steps/PipelineStep.vue";
  import ReviewStep from "@/components/organisms/Wizard/steps/ReviewStep.vue";
  import SchemaStep from "@/components/organisms/Wizard/steps/SchemaStep.vue";
  import WizardFrame from "@/components/organisms/Wizard/WizardFrame.vue";
  import { useBuildWizard } from "@/composables/use-build-wizard";

  const { t } = useI18n();
  const wizard = useBuildWizard();
  const reviewRef = ref<InstanceType<typeof ReviewStep> | null>(null);

  const canAdvance = computed(() => {
    const idx = wizard.currentIndex.value;
    const data = wizard.data.value;
    if (idx === 0) return data.corpus_name.trim().length > 0;
    if (idx === 1) return data.documents.some((d) => d.text.trim().length > 0);
    if (idx === 2) return Boolean(data.eda);
    // Schema step is optional — Skip in SchemaStep marks it completed.
    if (idx === 3) return true;
    if (idx === 4) return Boolean(data.build_request.builder);
    return false; // step 5: review uses its own button
  });

  function onAdvance() {
    if (wizard.currentIndex.value === wizard.steps.length - 1) {
      // Review step button is internal; nothing to do here.
      reviewRef.value?.build();
      return;
    }
    wizard.next();
  }
</script>

<template>
  <WizardFrame
    :title="t('wizard.buildPage.title')"
    :steps="wizard.steps"
    :statuses="wizard.stepStatuses.value"
    :current-index="wizard.currentIndex.value"
    :can-advance="canAdvance"
    :advance-label="wizard.currentIndex.value === wizard.steps.length - 1 ? t('wizard.buildPage.advanceFinal') : t('wizard.buildPage.advance')"
    @navigate="(i) => wizard.goTo(i)"
    @back="wizard.back"
    @advance="onAdvance"
  >
    <CorpusStep v-if="wizard.currentIndex.value === 0" />
    <DocumentsStep v-else-if="wizard.currentIndex.value === 1" />
    <EdaStep v-else-if="wizard.currentIndex.value === 2" />
    <SchemaStep v-else-if="wizard.currentIndex.value === 3" />
    <PipelineStep v-else-if="wizard.currentIndex.value === 4" />
    <ReviewStep v-else ref="reviewRef" />
  </WizardFrame>
</template>
