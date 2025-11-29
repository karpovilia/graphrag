<script setup lang="ts">
import { ref } from "vue";
import { useAsyncData } from "nuxt/app";
import type { ICityGraphImportMap } from "@/entities/cities";
import { createPagePath } from "@/entities/tech";

const toast = ref({
  show: false,
  message: '',
  type: 'success'
});

function showToast(type: string, message: string) {
  toast.value = { show: true, message, type };
  setTimeout(() => {
    toast.value.show = false;
  }, 3000);
}

const availableModels = [
  { label: "Deepseek", value: "deepseek" },
  { label: "Deepseek R1", value: "deepseek-r1" },
  { label: "GPT 5.1", value: "gpt5.1" },
  { label: "GPT 5", value: "gpt5" },
  { label: "GPT 4", value: "gpt4" },
  { label: "GPT 4o", value: "gpt4o" },
  { label: "YandexGPT 5 Pro", value: "yandexgpt5-pro" },
  { label: "YandexGPT 5 Lite", value: "yandexgpt5-lite" },
  { label: "YandexGPT 4 Pro", value: "yandexgpt4-pro" },
  { label: "YandexGPT 4 Lite", value: "yandexgpt4-lite" },
  { label: "Qwen2.5", value: "qwen2.5"},
  { label: "RuQwen", value: "ruqwen"}
];

const availableLanguages = [
  { label: "Russian", value: "ru" },
  { label: "English", value: "en" },
];

const availableAlgorithms = [
  { label: "Leiden", value: "leiden" },
  { label: "Leiden-BFS", value: "leiden-bfs" },
  { label: "Leiden-Threshold", value: "leiden-threshold" },
  { label: "Bayan", value: "bayan" },
];

const { data: imports } = await useAsyncData<ICityGraphImportMap[]>("import-map", () =>
  $fetch("/api/import-map")
);

const isLoading = ref(false);
const isModalOpen = ref(false);
const uploadStage = ref(''); // Текущий этап загрузки

const token = ref("");
const modelName = ref("");
const selectedModelLabel = ref("");
const algorithmName = ref("");
const selectedAlgorithmLabel = ref("");
const language = ref("ru");
const selectedLanguageLabel = ref("Russian");
const files = ref<File[]>([]);
const fileErrors = ref<Record<number, string>>({});
const dropdownOpen = ref(false);
const algorithmDropdownOpen = ref(false);
const languageDropdownOpen = ref(false);

const MAX_FILE_SIZE = 300 * 1024; // 300 KB
const MAX_FILES = 100;

function isTokenValid(value: string) {
  return value.trim().length >= 6;
}

function isModelNameValid(value: string) {
  return value.trim().length > 0;
}

function openModal() {
  isModalOpen.value = true;
}

function closeModal() {
  isModalOpen.value = false;
  token.value = "";
  modelName.value = "";
  selectedModelLabel.value = "";
  algorithmName.value = "";
  selectedAlgorithmLabel.value = "";
  language.value = "ru";
  selectedLanguageLabel.value = "Russian";
  files.value = [];
  fileErrors.value = {};
  dropdownOpen.value = false;
  algorithmDropdownOpen.value = false;
  languageDropdownOpen.value = false;
  uploadStage.value = ''; // Сброс этапа при закрытии модалки
}

function selectModel(model: { label: string; value: string }) {
  modelName.value = model.value;
  selectedModelLabel.value = model.label;
  dropdownOpen.value = false;
}

function selectAlgorithm(algorithm: { label: string; value: string }) {
  algorithmName.value = algorithm.value;
  selectedAlgorithmLabel.value = algorithm.label;
  algorithmDropdownOpen.value = false;
}

function selectLanguage(lang: { label: string; value: string }) {
  language.value = lang.value;
  selectedLanguageLabel.value = lang.label;
  languageDropdownOpen.value = false;
}

async function validateFile(file: File): Promise<string | null> {
  // Проверка расширения
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (extension !== 'txt' && extension !== 'md') {
    return `File "${file.name}" must be .txt or .md`;
  }

  // Проверка размера
  if (file.size > MAX_FILE_SIZE) {
    return `File "${file.name}" exceeds ${MAX_FILE_SIZE / 1024}KB limit`;
  }

  // Проверка кодировки UTF-8
  try {
    const arrayBuffer = await file.arrayBuffer();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    decoder.decode(arrayBuffer);
  } catch (e) {
    return `File "${file.name}" is not valid UTF-8`;
  }

  return null;
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files && target.files.length > 0) {
    const newFiles = Array.from(target.files);
    
    // Проверка общего количества файлов
    if (files.value.length + newFiles.length > MAX_FILES) {
      showToast('error', `Maximum ${MAX_FILES} files allowed`);
      target.value = '';
      return;
    }

    // Валидация каждого файла
    const validFiles: File[] = [];
    const errors: Record<number, string> = { ...fileErrors.value };
    let startIndex = files.value.length;

    for (let i = 0; i < newFiles.length; i++) {
      const file = newFiles[i];
      const error = await validateFile(file);
      
      if (error) {
        errors[startIndex + i] = error;
        showToast('error', error);
      } else {
        validFiles.push(file);
      }
    }

    files.value = [...files.value, ...validFiles];
    fileErrors.value = errors;

    target.value = '';
  }
}

function removeFile(index: number) {
  files.value.splice(index, 1);
  // Удаляем ошибку для этого файла
  const newErrors: Record<number, string> = {};
  Object.keys(fileErrors.value).forEach(key => {
    const keyNum = parseInt(key);
    if (keyNum < index) {
      newErrors[keyNum] = fileErrors.value[keyNum];
    } else if (keyNum > index) {
      newErrors[keyNum - 1] = fileErrors.value[keyNum];
    }
  });
  fileErrors.value = newErrors;
}

function clearAllFiles() {
  files.value = [];
  fileErrors.value = {};
}

async function importGraph() {
  if (files.value.length === 0) {
    showToast('error', "Please select at least one file");
    return;
  }
  if (!isTokenValid(token.value)) {
    showToast('error', "Invalid token: must be at least 6 characters");
    return;
  }
  if (!isModelNameValid(modelName.value)) {
    showToast('error', "Please select a model");
    return;
  }
  if (!algorithmName.value) {
    showToast('error', "Please select a community detection algorithm");
    return;
  }

  // Проверка на ошибки в файлах
  if (Object.keys(fileErrors.value).length > 0) {
    showToast('error', "Please fix file errors before uploading");
    return;
  }

  isLoading.value = true;

  try {
    // Этап 1: Загрузка файлов
    uploadStage.value = 'uploading';
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Читаем содержимое файлов
    const fileContents: Array<{ name: string; content: string }> = [];
    for (const file of files.value) {
      const content = await file.text();
      fileContents.push({ name: file.name, content });
    }

    // Этап 2: Подготовка данных
    uploadStage.value = 'preparing';
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Отправка на бекенд
    const formData = new FormData();
    formData.append('token', token.value);
    formData.append('model', modelName.value);
    formData.append('algorithm', algorithmName.value);
    formData.append('language', language.value);
    
    // Добавляем файлы
    for (const file of files.value) {
      formData.append('files', file);
    }
    
    const response = await $fetch<{ success: boolean; message?: string }>(
      `/api/import`,
      {
        method: "POST",
        body: formData,
      }
    );

    if (response.success) {
      // Этап 3: Обработка данных
      uploadStage.value = 'processing';
      await new Promise(resolve => setTimeout(resolve, 2000));

      // Этап 4: Построение графа
      uploadStage.value = 'building';
      await new Promise(resolve => setTimeout(resolve, 2000));

      // Завершение
      showToast('error', 'Invalid token');
      // showToast('success', `Successfully uploaded and processed ${files.value.length} file${files.value.length > 1 ? 's' : ''}!`);
      closeModal();
    } else {
      throw new Error(response.message || "Upload failed");
    }
  } catch (e: any) {
    console.error("Error uploading graphs:", e);
    showToast('error', e.message || "Error uploading graphs");
  } finally {
    isLoading.value = false;
    uploadStage.value = '';
  }
}

// Функция для получения текста текущего этапа
function getStageText() {
  switch (uploadStage.value) {
    case 'uploading':
      return `Uploading ${files.value.length} file${files.value.length !== 1 ? 's' : ''}..`;
    case 'preparing':
      return 'Prepare data....';
    case 'processing':
      return 'Processing data...';
    case 'building':
      return 'Building graph....';
    default:
      return `Uploading ${files.value.length} file${files.value.length !== 1 ? 's' : ''}...`;
  }
}
</script>

<template>
  <div :class="$style.base">
    <div :class="$style.header">
      <h2 :class="$style.title">Available Datasets:</h2>
      <div :class="$style.importWrapper">
        <button :class="$style.uploadButton" @click="openModal">
          <span :class="$style.uploadIcon">📤</span>
          Upload Data
        </button>
      </div>
    </div>

    <div :class="$style.list">
      <template v-if="imports && imports.length">
        <NuxtLink
          v-for="item in imports"
          :key="item.id"
          :to="createPagePath.graph(item.id)"
          no-prefetch
          :class="$style.item"
        >
          <span :class="$style.itemContent">{{ item.name }}</span>
        </NuxtLink>
      </template>
    </div>

    <!-- Modal -->
    <div v-if="isModalOpen" :class="$style.modalOverlay" @click="closeModal">
      <div :class="$style.modalContent" @click.stop>
        <div :class="$style.modalHeader">
          <h3 :class="$style.modalTitle">Upload Data</h3>
          <button :class="$style.closeButton" @click="closeModal">×</button>
        </div>

        <div :class="$style.form">
          <div :class="$style.formGroup">
            <label :class="$style.label">Token</label>
            <input
              v-model="token"
              :class="$style.input"
              placeholder="Enter your token"
              type="text"
            />
            <div :class="$style.hint">Must be at least 6 characters</div>
          </div>

          <div :class="$style.formGroup">
            <label :class="$style.label">Language</label>
            <div :class="$style.selectWrapper">
              <div
                :class="[$style.select, { [$style.selectOpen]: languageDropdownOpen }]"
                @click="languageDropdownOpen = !languageDropdownOpen"
              >
                <span :class="[$style.selectText, { [$style.placeholder]: !selectedLanguageLabel }]">
                  {{ selectedLanguageLabel || "Select language" }}
                </span>
                <span :class="$style.selectArrow">▼</span>
              </div>
              <div v-if="languageDropdownOpen" :class="$style.dropdown">
                <div
                  v-for="lang in availableLanguages"
                  :key="lang.value"
                  :class="[$style.option, { [$style.optionSelected]: language === lang.value }]"
                  @click="selectLanguage(lang)"
                >
                  {{ lang.label }}
                </div>
              </div>
            </div>
          </div>

          <div :class="$style.formGroup">
            <label :class="$style.label">Model Name</label>
            <div :class="$style.selectWrapper">
              <div
                :class="[$style.select, { [$style.selectOpen]: dropdownOpen }]"
                @click="dropdownOpen = !dropdownOpen"
              >
                <span :class="[$style.selectText, { [$style.placeholder]: !selectedModelLabel }]">
                  {{ selectedModelLabel || "Select model" }}
                </span>
                <span :class="$style.selectArrow">▼</span>
              </div>
              <div v-if="dropdownOpen" :class="$style.dropdown">
                <div
                  v-for="model in availableModels"
                  :key="model.value"
                  :class="[$style.option, { [$style.optionSelected]: modelName === model.value }]"
                  @click="selectModel(model)"
                >
                  {{ model.label }}
                </div>
              </div>
            </div>
          </div>

          <div :class="$style.formGroup">
            <label :class="$style.label">Community Detection Algorithm</label>
            <div :class="$style.selectWrapper">
              <div
                :class="[$style.select, { [$style.selectOpen]: algorithmDropdownOpen }]"
                @click="algorithmDropdownOpen = !algorithmDropdownOpen"
              >
                <span :class="[$style.selectText, { [$style.placeholder]: !selectedAlgorithmLabel }]">
                  {{ selectedAlgorithmLabel || "Select algorithm" }}
                </span>
                <span :class="$style.selectArrow">▼</span>
              </div>
              <div v-if="algorithmDropdownOpen" :class="$style.dropdown">
                <div
                  v-for="algorithm in availableAlgorithms"
                  :key="algorithm.value"
                  :class="[$style.option, { [$style.optionSelected]: algorithmName === algorithm.value }]"
                  @click="selectAlgorithm(algorithm)"
                >
                  {{ algorithm.label }}
                </div>
              </div>
            </div>
            <div :class="$style.hint">Select community detection algorithms</div>
          </div>

          <div :class="$style.formGroup">
            <label :class="$style.label">Files</label>
            <div :class="$style.fileUpload">
              <input
                type="file"
                id="file-input"
                :class="$style.fileInput"
                @change="handleFileUpload"
                accept=".txt,.md"
                multiple
              />
              <label for="file-input" :class="$style.fileLabel">
                <span :class="$style.fileIcon">📎</span>
                Choose Files
              </label>
              <div :class="$style.fileHint">
                Select .txt or .md files (UTF-8, max {{ MAX_FILE_SIZE / 1024 }}KB each, max {{ MAX_FILES }} files)
              </div>
            </div>

            <!-- Список выбранных файлов -->
            <div v-if="files.length > 0" :class="$style.fileList">
              <div :class="$style.fileListHeader">
                <span :class="$style.fileListTitle">
                  Selected files ({{ files.length }})
                </span>
                <button
                  v-if="files.length > 1"
                  :class="$style.clearAllButton"
                  @click="clearAllFiles"
                >
                  Clear all
                </button>
              </div>
              <div :class="$style.fileItems">
                <div
                  v-for="(file, index) in files"
                  :key="index"
                  :class="[$style.fileItem, { [$style.fileItemError]: fileErrors[index] }]"
                >
                  <div :class="$style.fileInfo">
                    <span :class="$style.fileName">{{ file.name }}</span>
                    <span :class="$style.fileSize">({{ (file.size / 1024).toFixed(2) }} KB)</span>
                    <div v-if="fileErrors[index]" :class="$style.fileError">
                      {{ fileErrors[index] }}
                    </div>
                  </div>
                  <button
                    :class="$style.removeFileButton"
                    @click="removeFile(index)"
                    title="Remove file"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div :class="$style.modalActions">
          <button :class="[$style.button, $style.buttonSecondary]" @click="closeModal">
            Cancel
          </button>
          <button
            :class="[$style.button, $style.buttonPrimary]"
            @click="importGraph"
            :disabled="isLoading || files.length === 0 || Object.keys(fileErrors).length > 0"
          >
            <span v-if="isLoading" :class="$style.spinnerSmall"></span>
            {{ isLoading ? 'Importing...' : `Import ${files.length} File${files.length !== 1 ? 's' : ''}` }}
          </button>
        </div>
      </div>
    </div>

    <!-- Loading Overlay -->
    <div v-if="isLoading" :class="$style.overlay">
      <div :class="$style.loadingContent">
        <div :class="$style.spinner"></div>
        <div :class="$style.loadingText">{{ getStageText() }}</div>
      </div>
    </div>

    <!-- Toast -->
    <div
      v-if="toast.show"
      :class="[
        $style.toast,
        $style[`toast--${toast.type}`]
      ]"
    >
      <div :class="$style.toastIcon">
        <span v-if="toast.type === 'success'">✓</span>
        <span v-else-if="toast.type === 'error'">✕</span>
        <span v-else-if="toast.type === 'warning'">⚠</span>
        <span v-else>ℹ</span>
      </div>
      <div :class="$style.toastContent">
        <div :class="$style.toastMessage">{{ toast.message }}</div>
      </div>
      <button :class="$style.toastClose" @click="toast.show = false">
        <span>×</span>
      </button>
    </div>
  </div>
</template>

<style lang="scss" module>
.base {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  height: 100%;
  padding: var(--ksd-padding-lg);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 0;
}

.title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #333;
}

.uploadButton {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #1890ff;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: #40a9ff;
    transform: translateY(-1px);
  }

  &:active {
    transform: translateY(0);
  }
}

.uploadIcon {
  font-size: 16px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item {
  padding: 12px 16px;
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    background: #f0f0f0;
    border-color: #d9d9d9;
  }

  a {
    text-decoration: none;
    color: #1890ff;
    font-weight: 500;

    &:hover {
      color: #40a9ff;
    }
  }
}

/* Modal Styles */
.modalOverlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.modalContent {
  background: white;
  border-radius: 12px;
  width: 520px;
  max-width: 90vw;
  max-height: 90vh;
  overflow: hidden;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  animation: modalAppear 0.2s ease-out;
}

@keyframes modalAppear {
  from {
    opacity: 0;
    transform: scale(0.9) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modalHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 24px 0;
  margin-bottom: 24px;
}

.modalTitle {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #333;
}

.closeButton {
  background: none;
  border: none;
  font-size: 24px;
  color: #999;
  cursor: pointer;
  padding: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;

  &:hover {
    background: #f5f5f5;
    color: #666;
  }
}

.form {
  padding: 0 24px;
}

.formGroup {
  margin-bottom: 24px;
}

.label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: #333;
  font-size: 14px;
}

.input {
  width: 100%;
  padding: 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 14px;
  transition: all 0.2s ease;

  &:focus {
    outline: none;
    border-color: #1890ff;
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
  }

  &::placeholder {
    color: #999;
  }
}

.hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.selectWrapper {
  position: relative;
}

.select {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: white;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: #40a9ff;
  }
}

.selectOpen {
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
}

.selectText {
  color: #333;
}

.placeholder {
  color: #999;
}

.selectArrow {
  color: #666;
  transition: transform 0.2s ease;
}

.selectOpen .selectArrow {
  transform: rotate(180deg);
}

.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  margin-top: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 10;
  max-height: 200px;
  overflow-y: auto;
}

.option {
  padding: 12px;
  cursor: pointer;
  transition: background-color 0.2s ease;
  border-bottom: 1px solid #f0f0f0;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: #f5f5f5;
  }
}

.optionSelected {
  background: #e6f7ff;
  color: #1890ff;
  font-weight: 500;
}

.fileUpload {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fileInput {
  display: none;
}

.fileLabel {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fafafa;
  border: 1px dashed #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  width: fit-content;

  &:hover {
    border-color: #1890ff;
    background: #f0f8ff;
  }
}

.fileIcon {
  font-size: 14px;
}

.fileHint {
  font-size: 12px;
  color: #666;
}

/* Стили для списка файлов */
.fileList {
  margin-top: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  overflow: hidden;
}

.fileListHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fafafa;
  border-bottom: 1px solid #e8e8e8;
}

.fileListTitle {
  font-size: 12px;
  font-weight: 500;
  color: #666;
}

.clearAllButton {
  background: none;
  border: none;
  color: #ff4d4f;
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;

  &:hover {
    background: #fff2f0;
  }
}

.fileItems {
  max-height: 200px;
  overflow-y: auto;
}

.fileItem {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: #fafafa;
  }
}

.fileItemError {
  background: #fff2f0;
  border-left: 3px solid #ff4d4f;
}

.fileInfo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.fileName {
  font-size: 13px;
  color: #333;
  word-break: break-all;
}

.fileSize {
  font-size: 11px;
  color: #999;
}

.fileError {
  font-size: 11px;
  color: #ff4d4f;
  margin-top: 2px;
}

.removeFileButton {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 16px;
  line-height: 1;
  flex-shrink: 0;

  &:hover {
    background: #fff2f0;
    color: #ff4d4f;
  }
}

.modalActions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 24px;
  border-top: 1px solid #f0f0f0;
  margin-top: 8px;
}

.button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.buttonPrimary {
  background: #1890ff;
  color: white;

  &:hover:not(:disabled) {
    background: #40a9ff;
  }
}

.buttonSecondary {
  background: #f5f5f5;
  color: #666;

  &:hover {
    background: #e8e8e8;
  }
}

/* Loading Styles */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
}

.loadingContent {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.loadingText {
  font-size: 16px;
  color: #333;
  font-weight: 500;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid #e8e8e8;
  border-top: 4px solid #1890ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.spinnerSmall {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top: 2px solid currentColor;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.toast {
  position: fixed;
  top: 5%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-radius: 12px;
  box-shadow:
    0 20px 40px rgba(0, 0, 0, 0.15),
    0 0 0 1px rgba(255, 255, 255, 0.1);
  z-index: 2000;
  animation: toastAppear 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  backdrop-filter: blur(10px);
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.2);
  min-width: 320px;
  max-width: 480px;
}

@keyframes toastAppear {
  0% {
    opacity: 0;
    transform: translate(-50%, -50%) scale(0.8) translateY(10px);
  }
  100% {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1) translateY(0);
  }
}

.toastIcon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  flex-shrink: 0;
  font-weight: bold;
  font-size: 14px;
}

.toastContent {
  flex: 1;
}

.toastMessage {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  color: #333;
}

.toastClose {
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  transition: all 0.2s ease;
  font-size: 18px;

  &:hover {
    background: rgba(0, 0, 0, 0.05);
    color: #666;
  }
}

/* Стили для разных типов уведомлений */
.toast--success {
  .toastIcon {
    background: #f6ffed;
    color: #52c41a;
    border: 1px solid #b7eb8f;
  }
  border-left: 4px solid #52c41a;
}

.toast--error {
  .toastIcon {
    background: #fff2f0;
    color: #ff4d4f;
    border: 1px solid #ffccc7;
  }
  border-left: 4px solid #ff4d4f;
}

.toast--warning {
  .toastIcon {
    background: #fffbe6;
    color: #faad14;
    border: 1px solid #ffe58f;
  }
  border-left: 4px solid #faad14;
}

.toast--info {
  .toastIcon {
    background: #e6f7ff;
    color: #1890ff;
    border: 1px solid #91d5ff;
  }
  border-left: 4px solid #1890ff;
}

/* Анимация исчезновения */
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -50%) scale(0.9) translateY(-10px);
}
</style>
