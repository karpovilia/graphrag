<script setup lang="ts">
import { getByPath, isArray } from "@krainovsd/js-helpers";
import { VHomeOutlined, VDownloadOutlined, VLinkOutlined, VEditOutlined, VSaveOutlined } from "@krainovsd/vue-icons";
import { VButton, VText } from "@krainovsd/vue-ui";
import { useAsyncData, useRoute, navigateTo } from "nuxt/app";
import { computed, ref, useTemplateRef, onMounted, nextTick } from "vue";
import { createPagePath, themeBehaviorSubject } from "@/entities/tech";
import { watch } from "vue";
import CityGraph from "@/components/organisms/CityGraph/CityGraph.vue";
import type { ICityGraph } from "@/components/organisms/CityGraph/city-graph.types";
import CityInfo, { type ICityLinkInfo, type ICityNodeInfo } from "@/components/organisms/CityInfo/CityInfo.vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { NODE_LIGHT_COLOR } from "@/components/organisms/CityGraph/city-graph.constats";

const route = useRoute();
const { data: info } = await useAsyncData<{ name: string; graph: ICityGraph }>(
  `graph/${route.params.id}`,
  () => $fetch(`/api/graph/${route.params.id}`),
);

const theme = themeBehaviorSubject.useSubscribe();
const selectedNodes = ref<id[]>([]);
const selectedLink = ref<id | null>(null);
const containerRef = useTemplateRef("container");

const searchQuery = ref("");
const searchResultText = ref("");
const searchHistory = ref<{ prompt: string; nodes: string[] }[]>([]);
const searchNodes = ref<string[]>([]);
const isLoading = ref(false);
const isPanelOpen = ref(false);
const isViewingResult = ref(false);
const isSaving = ref(false);
const hasChanges = ref(false);
const nodeSearchQuery = ref("");

function exportGraph() {
  if (!info.value?.graph) return;

  const graphData = info.value.graph;
  const dataStr = JSON.stringify(graphData, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });

  const url = URL.createObjectURL(dataBlob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `graph-${info.value.name || 'export'}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function saveGraph() {
  if (!info.value?.graph) return;

  isSaving.value = true;
  try {
    const route = useRoute();
    const originalId = route.params.id as string;
    
    // Нормализуем связи: заменяем объекты нод на их ID
    const normalizedLinks = info.value.graph.links.map(link => {
      const sourceId = typeof link.source === "object" && "id" in link.source 
        ? link.source.id 
        : link.source;
      const targetId = typeof link.target === "object" && "id" in link.target 
        ? link.target.id 
        : link.target;

      return {
        ...link,
        source: sourceId,
        target: targetId,
      };
    });

    const graphToSave = {
      ...info.value.graph,
      links: normalizedLinks,
    };
    
    const response = await $fetch<{ success: boolean; id: string; name: string; path: string }>(
      `/api/graph/save`,
      {
        method: "POST",
        headers: {
          'Content-Type': 'application/json',
        },
        body: {
          originalId,
          graph: graphToSave,
          name: info.value.name,
        },
      }
    );

    if (response.success) {
      // Сбрасываем флаг изменений после успешного сохранения
      hasChanges.value = false;
      // Перенаправляем на новый сохраненный граф
      await navigateTo(createPagePath.graph(response.id));
    }
  } catch (err) {
    console.error("Error saving graph:", err);
    alert("Error saving graph. Please try again.");
  } finally {
    isSaving.value = false;
  }
}

function mergeNodes() {
  if (!info.value?.graph) return;
  if (selectedNodes.value.length < 2) return;

  const graph = info.value.graph;
  const nodesToMerge = selectedNodes.value
    .map(id => graph.nodes.find(node => node.id === id))
    .filter((node): node is NonNullable<typeof node> => node !== undefined);

  if (nodesToMerge.length < 2) return;

  // Первая нода в selectedNodes - это та, которую выбрали первой
  const firstNode = nodesToMerge[0];
  const otherNodeIds = nodesToMerge.slice(1).map(n => n.id);
  const allNodeIds = nodesToMerge.map(n => n.id);

  // Объединяем все тексты из всех нод, убирая дубликаты по id
  const mergedTexts: Array<{ id: number; text: string }> = [];
  const textIds = new Set<number>();

  for (const node of nodesToMerge) {
    if (node.data?.texts) {
      for (const text of node.data.texts) {
        if (!textIds.has(text.id)) {
          textIds.add(text.id);
          mergedTexts.push(text);
        }
      }
    }
  }

  // Объединяем размеры (берем максимальный)
  const maxSize = Math.max(...nodesToMerge.map(n => n.data?.size ?? 0));

  // Получаем цвет из первой ноды или используем значение по умолчанию
  const nodeColor = firstNode.data?.color ?? NODE_LIGHT_COLOR;

  // Создаем новую ноду на основе первой
  const mergedNode: typeof firstNode = {
    ...firstNode,
    name: firstNode.name,
    data: {
      ...firstNode.data,
      texts: mergedTexts,
      size: maxSize,
      color: nodeColor,
    },
  };

  // Обновляем связи: перенаправляем все связи, которые идут к/от объединяемых нод, на новую ноду
  const updatedLinks = graph.links.map(link => {
    const sourceId = typeof link.source === "object" && "id" in link.source 
      ? link.source.id 
      : link.source;
    const targetId = typeof link.target === "object" && "id" in link.target 
      ? link.target.id 
      : link.target;

    const sourceIsMerged = allNodeIds.includes(sourceId as id);
    const targetIsMerged = allNodeIds.includes(targetId as id);

    // Удаляем связи, которые соединяют объединяемые ноды между собой
    if (sourceIsMerged && targetIsMerged) {
      return null;
    }

    let newSource = link.source;
    let newTarget = link.target;

    // Если source - одна из объединяемых нод, заменяем на объединенную ноду
    if (sourceIsMerged) {
      if (typeof link.source === "object" && "id" in link.source) {
        // Заменяем весь объект на mergedNode, чтобы связь визуально прикреплялась
        newSource = mergedNode;
      } else {
        newSource = firstNode.id;
      }
    }

    // Если target - одна из объединяемых нод, заменяем на объединенную ноду
    if (targetIsMerged) {
      if (typeof link.target === "object" && "id" in link.target) {
        // Заменяем весь объект на mergedNode, чтобы связь визуально прикреплялась
        newTarget = mergedNode;
      } else {
        newTarget = firstNode.id;
      }
    }

    return {
      ...link,
      source: newSource,
      target: newTarget,
    };
  }).filter((link): link is NonNullable<typeof link> => link !== null);

  // Удаляем дубликаты связей (если после объединения появились связи с одинаковыми source и target)
  const uniqueLinks: typeof updatedLinks = [];
  const linkKeys = new Set<string>();

  for (const link of updatedLinks) {
    const sourceId = typeof link.source === "object" && "id" in link.source 
      ? link.source.id 
      : link.source;
    const targetId = typeof link.target === "object" && "id" in link.target 
      ? link.target.id 
      : link.target;
    
    const key = `${sourceId}-${targetId}`;
    if (!linkKeys.has(key)) {
      linkKeys.add(key);
      uniqueLinks.push(link);
    }
  }

  // Удаляем старые ноды (кроме первой, так как она станет новой)
  const updatedNodes = graph.nodes
    .filter(node => !otherNodeIds.includes(node.id))
    .map(node => node.id === firstNode.id ? mergedNode : node);

  // Обновляем граф
  info.value.graph = {
    nodes: updatedNodes,
    links: uniqueLinks,
  };

  // Очищаем выбранные ноды и выбираем новую объединенную ноду
  selectedNodes.value = [firstNode.id];
  
  // Отмечаем, что были изменения
  hasChanges.value = true;
}

function recolorNodes() {
  if (!info.value?.graph) return;
  if (selectedNodes.value.length < 2) return;

  const graph = info.value.graph;
  const nodesToRecolor = selectedNodes.value
    .map(id => graph.nodes.find(node => node.id === id))
    .filter((node): node is NonNullable<typeof node> => node !== undefined);

  if (nodesToRecolor.length < 1) return;

  // Берем цвет из первой выбранной ноды
  const firstNode = nodesToRecolor[0];
  const targetColor = firstNode.data?.color ?? NODE_LIGHT_COLOR;

  // Создаем карту обновленных нод для быстрого доступа
  const updatedNodesMap = new Map<id, typeof graph.nodes[0]>();

  // Обновляем цвет всех выбранных нод
  const updatedNodes = graph.nodes.map(node => {
    if (selectedNodes.value.includes(node.id)) {
      const updatedNode = {
        ...node,
        data: {
          texts: node.data?.texts ?? [],
          size: node.data?.size ?? 0,
          color: targetColor,
        },
      };
      updatedNodesMap.set(node.id, updatedNode);
      return updatedNode;
    }
    updatedNodesMap.set(node.id, node);
    return node;
  });

  // Обновляем связи, чтобы они указывали на обновленные объекты нод
  const updatedLinks = graph.links.map(link => {
    let newSource = link.source;
    let newTarget = link.target;

    // Если source - объект и это одна из перекрашенных нод, заменяем на обновленный объект
    if (typeof link.source === "object" && "id" in link.source && selectedNodes.value.includes(link.source.id)) {
      const updatedNode = updatedNodesMap.get(link.source.id);
      if (updatedNode) {
        newSource = updatedNode;
      }
    }

    // Если target - объект и это одна из перекрашенных нод, заменяем на обновленный объект
    if (typeof link.target === "object" && "id" in link.target && selectedNodes.value.includes(link.target.id)) {
      const updatedNode = updatedNodesMap.get(link.target.id);
      if (updatedNode) {
        newTarget = updatedNode;
      }
    }

    return {
      ...link,
      source: newSource,
      target: newTarget,
    };
  });

  // Обновляем граф - создаем новый объект для реактивности
  if (info.value) {
    info.value.graph = {
      nodes: updatedNodes,
      links: updatedLinks,
    };
  }

  // Сбрасываем выделение после перекрашивания
  selectedNodes.value = [];
  
  // Отмечаем, что были изменения
  hasChanges.value = true;
}

function updateNodeName(nodeId: id, newName: string) {
  if (!info.value?.graph) return;

  const graph = info.value.graph;
  let updatedNode: typeof graph.nodes[0] | null = null;

  const updatedNodes = graph.nodes.map(node => {
    if (node.id === nodeId) {
      updatedNode = {
        ...node,
        name: newName,
      };
      return updatedNode;
    }
    return node;
  });

  if (!updatedNode) return;

  // Обновляем связи, где source или target - это объект с этой нодой
  const updatedLinks = graph.links.map(link => {
    let newSource = link.source;
    let newTarget = link.target;

    if (typeof link.source === "object" && "id" in link.source && link.source.id === nodeId) {
      // Заменяем весь объект на обновленную ноду
      newSource = updatedNode!;
    }
    if (typeof link.target === "object" && "id" in link.target && link.target.id === nodeId) {
      // Заменяем весь объект на обновленную ноду
      newTarget = updatedNode!;
    }

    return {
      ...link,
      source: newSource,
      target: newTarget,
    };
  });

  if (info.value) {
    info.value.graph = {
      nodes: updatedNodes,
      links: updatedLinks,
    };
    // Сбрасываем выделение после обновления
    selectedNodes.value = [];
    
    // Отмечаем, что были изменения
    hasChanges.value = true;
  }
}

function updateNodeText(nodeId: id, textId: number, newText: string) {
  if (!info.value?.graph) return;

  const graph = info.value.graph;
  let updatedNode: typeof graph.nodes[0] | null = null;

  const updatedNodes = graph.nodes.map(node => {
    if (node.id === nodeId && node.data?.texts) {
      updatedNode = {
        ...node,
        data: {
          ...node.data,
          texts: node.data.texts.map(text =>
            text.id === textId ? { ...text, text: newText } : text
          ),
        },
      };
      return updatedNode;
    }
    return node;
  });

  if (!updatedNode) return;

  // Обновляем связи, чтобы они указывали на обновленный объект ноды
  const updatedLinks = graph.links.map(link => {
    let newSource = link.source;
    let newTarget = link.target;

    if (typeof link.source === "object" && "id" in link.source && link.source.id === nodeId) {
      // Заменяем весь объект на обновленную ноду
      newSource = updatedNode!;
    }
    if (typeof link.target === "object" && "id" in link.target && link.target.id === nodeId) {
      // Заменяем весь объект на обновленную ноду
      newTarget = updatedNode!;
    }

    return {
      ...link,
      source: newSource,
      target: newTarget,
    };
  });

  if (info.value) {
    info.value.graph = {
      nodes: updatedNodes,
      links: updatedLinks,
    };
    // Сбрасываем выделение после обновления
    selectedNodes.value = [];
    
    // Отмечаем, что были изменения
    hasChanges.value = true;
  }
}

function updateLinkExplanation(linkId: id, newExplanation: string) {
  if (!info.value?.graph) return;

  const graph = info.value.graph;
  const updatedLinks = graph.links.map(link => {
    if (link.data?.id === linkId) {
      return {
        ...link,
        data: {
          ...link.data,
          explanation: newExplanation,
        },
      };
    }
    return link;
  });

  if (info.value) {
    info.value.graph = {
      ...graph,
      links: updatedLinks,
    };
    // Сбрасываем выделение после обновления
    selectedLink.value = null;
    
    // Отмечаем, что были изменения
    hasChanges.value = true;
  }
}

watch(searchQuery, (newValue) => {
  if (!newValue.trim()) {
    searchResultText.value = "";
    fetchSearchHistory();
  }
});

async function fetchSearchHistory() {
  const route = useRoute();
  const graph = route.params.id as string;

  isLoading.value = true;
  try {
    const response = await $fetch<{ prompt: string; nodes: string[] }[]>(
      `/api/prompt/history`,
      {
        method: "GET",
        query: { graph },
      },
    );
    searchHistory.value = response ?? [];
  } catch (err) {
    console.error("History load error:", err);
    searchHistory.value = [];
  } finally {
    isLoading.value = false;
  }
}

async function doSearch(query: string, nodes: string[] = []) {
  isLoading.value = true;
  searchResultText.value = "";
  isViewingResult.value = true;

  try {
    const route = useRoute();
    const graph = route.params.id as string;
    const response = await $fetch<{ response: string }>(`/api/prompt`, {
      method: "POST",
      headers: {
        'Content-Type': 'application/json',
      },
      body: {
        text: query,
        nodes: nodes,
        graph: graph
      },
    });

    searchResultText.value = response.response;
  } catch (err) {
    console.error("ERROR", err);
    searchResultText.value = "Error";
  } finally {
    isLoading.value = false;
  }
}

function onSearchEnter(event: KeyboardEvent) {
  if (event.key === "Enter" && searchQuery.value.trim()) {
    const nodes = selectedNodeInfo.value.map(n => n.name);
    doSearch(searchQuery.value, nodes);
  }
}

function onHistoryClick(item: { prompt: string; nodes: string[] }) {
  searchQuery.value = item.prompt;
  searchNodes.value = item.nodes;
  selectedNodes.value = [];

  if (item.nodes && item.nodes.length > 0 && info.value?.graph?.nodes) {
    const nodeIdsToSelect: (string | number)[] = [];

    for (const nodeName of item.nodes) {
      const foundNode = info.value.graph.nodes.find(
        node => node.name === nodeName
      );
      if (foundNode) {
        nodeIdsToSelect.push(foundNode.id);
      }
    }

    if (nodeIdsToSelect.length > 0) {
      selectedNodes.value = nodeIdsToSelect;
    }
  }
  doSearch(item.prompt, item.nodes);
}

function togglePanel() {
  isPanelOpen.value = !isPanelOpen.value;
}

function goBackToHistory() {
  isViewingResult.value = false;
  searchResultText.value = "";
  searchQuery.value = "";
  selectedNodes.value = [];
}

onMounted(() => {
  fetchSearchHistory();
});

const selectedNodeInfo = computed<ICityNodeInfo[]>(() => {
  if (!info.value?.graph?.nodes || selectedNodes.value.length === 0) return [];
  const nodes: ICityNodeInfo[] = [];
  for (let node of info.value.graph.nodes) {
    if (selectedNodes.value.includes(node.id)) {
      nodes.push({ id: node.id, name: node.name ?? "No Name", texts: node.data?.texts ?? [] });
    }
  }
  return nodes;
});

const selectedLinkInfo = computed<null | ICityLinkInfo>(() => {
  if (!info.value?.graph?.links || selectedLink.value == undefined) return null;
  for (let link of info.value.graph.links) {
    if (link.data?.id === selectedLink.value) {
      return {
        explanation: link.data?.explanation ?? "",
        name: `${getByPath(link, "source.name")} - ${getByPath(link, "target.name")}`,
        id: link.data.id,
      };
    }
  }
  return null;
});

// Поиск по нодам
function performNodeSearch() {
  if (!nodeSearchQuery.value.trim() || !info.value?.graph?.nodes) {
    selectedNodes.value = [];
    return;
  }
  
  const query = nodeSearchQuery.value.trim().toLowerCase();
  const found = info.value.graph.nodes
    .filter(node => {
      const nodeName = node.name?.toLowerCase() ?? "";
      return nodeName.includes(query);
    })
    .map(node => node.id);
  
  selectedNodes.value = found;
}

function onNodeSearchEnter(event: KeyboardEvent) {
  if (event.key === "Enter") {
    event.preventDefault();
    event.stopPropagation();
    // Устанавливаем выделение сразу
    performNodeSearch();
    // Также устанавливаем в nextTick на случай, если событие клика сбросит выделение
    nextTick(() => {
      if (nodeSearchQuery.value.trim()) {
        performNodeSearch();
      }
    });
  }
}
</script>

<template>
<div ref="container" :class="$style.base">
  <button
    :class="[$style.toggleButton, { [$style.toggleButtonClosed]: !isPanelOpen }]"
    @click="togglePanel"
    :title="'Toogle Panel'"
  >
    <span :class="$style.toggleIcon">{{ isPanelOpen ? '◀' : '▶' }}</span>
  </button>

  <div :class="$style.header">
    <div :class="$style.headerButtons">
      <NuxtLink :to="createPagePath.home">
        <VButton>
          <template #icon>
            <VHomeOutlined />
          </template>
        </VButton>
      </NuxtLink>
      <VButton 
        @click="mergeNodes" 
        title="Merge selected nodes"
        :disabled="selectedNodes.length < 2"
      >
        <template #icon>
          <VLinkOutlined />
        </template>
      </VButton>
      <VButton 
        @click="recolorNodes" 
        title="Recolor selected nodes to first node's color"
        :disabled="selectedNodes.length < 2"
      >
        <template #icon>
          <VEditOutlined />
        </template>
      </VButton>
      <VButton 
        @click="saveGraph" 
        title="Save graph as new copy"
        :disabled="isSaving || !hasChanges"
      >
        <template #icon>
          <VSaveOutlined />
        </template>
      </VButton>
      <VButton @click="exportGraph" title="Export graph">
        <template #icon>
          <VDownloadOutlined />
        </template>
      </VButton>
    </div>
    <VText size="lg">{{ info?.name }}</VText>
    <div :class="$style.headerCenter">
      <input
        type="text"
        v-model="nodeSearchQuery"
        placeholder="Search nodes..."
        :class="$style.nodeSearchInput"
        @keydown="onNodeSearchEnter"
      />
    </div>
    
  </div>

  <div
    v-if="isPanelOpen"
    :class="$style.leftPanel"
  >
    <div :class="$style.searchPanel">
      <input
        type="text"
        v-model="searchQuery"
        placeholder="Enter query..."
        :class="$style.searchInput"
        @keydown="onSearchEnter"
        :disabled="isLoading"
      />

      <div :class="$style.searchResult">
        <template v-if="isLoading">
          <div :class="$style.loaderContainer">
            <div :class="$style.loader"></div>
          </div>
        </template>

        <template v-else-if="searchResultText && isViewingResult">
          <div :class="$style.resultHeader">
            <button :class="$style.backButton" @click="goBackToHistory">
              <span :class="$style.backIcon">←</span>
                Back to history
            </button>
          </div>
          <div :class="$style.resultText" v-html="DOMPurify.sanitize(marked.parse(searchResultText, { async: false }))"></div>
        </template>

        <template v-else>
          <div v-if="searchHistory.length" :class="$style.historySection">
            <div :class="$style.historyTitle">Requests history:</div>
            <div :class="$style.historyContainer">
              <div
                v-for="(item, index) in searchHistory"
                :key="index"
                :class="$style.historyItem"
                @click="onHistoryClick(item)"
              >
                <div :class="$style.historyPrompt">{{ item.prompt }}</div>
                <div v-if="item.nodes.length" :class="$style.historyNodes">
                  Selected nodes: {{ item.nodes.join(', ') }}
                </div>
              </div>
            </div>
          </div>
          <div v-else :class="$style.emptyHistory">History empty</div>
        </template>
      </div>
    </div>
  </div>

  <div :class="[$style.graph, { [$style.graphExpanded]: !isPanelOpen }]">
    <CityGraph
      v-if="info != undefined && isArray(info.graph.links) && isArray(info.graph.nodes)"
      v-model:selected-link="selectedLink"
      v-model:selected-nodes="selectedNodes"
      :theme="theme"
      :graph="info.graph"
    />
    <div v-else :class="$style.empty">
      <VText size="xl" :strong="true">Graph not found</VText>
    </div>
  </div>

  <CityInfo
    v-if="info != undefined"
    :mount-root="containerRef"
    :selected-nodes="selectedNodeInfo"
    :selected-link="selectedLinkInfo"
    @close="
      () => {
        selectedLink = null;
        selectedNodes = [];
      }
    "
    @update-node-name="updateNodeName"
    @update-node-text="updateNodeText"
    @update-link-explanation="updateLinkExplanation"
  />
</div>
</template>

<style lang="scss" module>
.base {
  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  position: relative;
  margin: 0;
  padding: 0;
}

.toggleButton {
  position: absolute;
  left: 380px;
  top: calc(50% + 30px);
  transform: translateY(-50%);
  z-index: 100;
  width: 24px;
  height: 60px;
  background: #1890ff;
  border: none;
  border-radius: 0 6px 6px 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  color: white;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.15);

  &:hover {
    background: #40a9ff;
    width: 28px;
  }
}

.toggleButtonClosed {
  left: 0;
}

.toggleIcon {
  font-size: 14px;
  font-weight: bold;
  transition: transform 0.3s ease;
}

.leftPanel {
  display: flex;
  flex-direction: column;
  width: 380px;
  flex-shrink: 0;
  height: calc(100% - 60px); /* Вычитаем высоту заголовка */
  margin-top: 60px; /* Отступ сверху равен высоте заголовка */
  border-right: 1px solid #e8e8e8;
  background: #fafafa;
  padding: 20px;
  box-sizing: border-box;
}

.graph {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: calc(100% - 60px);
  margin-top: 60px;
  background: white;
  transition: all 0.3s ease;
}

.graphExpanded {
  margin-left: 0;
}

.header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  width: 70%;
  padding: 20px;
  background: white;
  z-index: 50;
  height: 60px; /* Фиксированная высота заголовка */
  box-sizing: border-box;
}

.headerButtons {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.headerCenter {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 0 20px;
}

.nodeSearchInput {
  width: 100%;
  max-width: 400px;
  padding: 8px 16px;
  font-size: 14px;
  box-sizing: border-box;
  border: 2px solid #e8e8e8;
  border-radius: 8px;
  background: white;
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: #1890ff;
    box-shadow: 0 0 0 3px rgba(24, 144, 255, 0.1);
  }

  &::placeholder {
    color: #999;
  }
}

.searchPanel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  flex: 1;
  min-height: 0;
}

.searchInput {
  width: 100%;
  padding: 12px 16px;
  font-size: 15px;
  box-sizing: border-box;
  border: 2px solid #e8e8e8;
  border-radius: 8px;
  background: white;
  transition: all 0.2s ease;
  flex-shrink: 0;

  &:focus {
    outline: none;
    border-color: #1890ff;
    box-shadow: 0 0 0 3px rgba(24, 144, 255, 0.1);
  }

  &:disabled {
    background: #f5f5f5;
    cursor: not-allowed;
  }
}

.empty {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  gap: var(--ksd-padding);
}

.searchResult {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background-color: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  overflow: hidden;
}

/* Стили для заголовка результата с кнопкой "Назад" */
.resultHeader {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
  flex-shrink: 0;
}

.backButton {
  display: flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: none;
  color: #1890ff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    background: #f0f8ff;
    transform: translateX(-2px);
  }
}

.backIcon {
  font-size: 16px;
  font-weight: bold;
}

.resultText {
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 16px;
  line-height: 1.5;
  overflow-y: auto;
  flex: 1;
}

.historySection {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.historyTitle {
  padding: 16px 16px 12px 16px;
  font-size: 14px;
  font-weight: 600;
  color: #666;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
  flex-shrink: 0;
}

.historyContainer {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  min-height: 0;
}

.historyItem {
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  padding: 12px;
  border-radius: 6px;
  background-color: white;
  border: 1px solid #e8e8e8;
  transition: all 0.25s ease;
  margin-bottom: 8px;

  &:hover {
    background-color: #f0f8ff;
    border-color: #1890ff;
    transform: translateX(2px);
    box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
  }

  &:last-child {
    margin-bottom: 0;
  }
}

.historyPrompt {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  line-height: 1.4;
}

.historyNodes {
  font-size: 12px;
  color: #666;
  line-height: 1.3;
  padding-top: 4px;
  border-top: 1px solid #f0f0f0;
}

.loaderContainer {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 200px;
}

.loader {
  width: 28px;
  height: 28px;
  border: 3px solid rgba(0,0,0,0.1);
  border-top-color: var(--ksd-color-primary, #4a90e2);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.emptyHistory {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: #999;
  font-style: italic;
  background: white;
}

/* Кастомный скроллбар */
.historyContainer::-webkit-scrollbar {
  width: 6px;
}

.historyContainer::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.historyContainer::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.historyContainer::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.resultText::-webkit-scrollbar {
  width: 6px;
}

.resultText::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.resultText::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.resultText::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* Анимация для скрытия/показа панели */
.leftPanel {
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.graph {
  transition: margin-left 0.3s ease;
}

.base {
  margin: 0;
  padding: 0;
}
</style>
