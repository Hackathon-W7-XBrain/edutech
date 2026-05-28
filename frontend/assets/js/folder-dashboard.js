import { showToast } from "./api.js";
import { bindAuth } from "./auth.js";
import {
  byId,
  getFolderId,
  loadFolderBundle,
  renderFolderChrome,
  renderFolderDocs,
} from "./folder-common.js";

const folderId = getFolderId();

function renderStats(fileCount) {
  byId("stats-grid").innerHTML = `
    <div class="stat-box"><strong>${fileCount}</strong><span>Files</span></div>
  `;
}

function renderPlaceholder(hostId, message) {
  byId(hostId).innerHTML = `<div class="empty">${message}</div>`;
}

async function loadPage() {
  const bundle = await loadFolderBundle(folderId);
  const docs = bundle.dashboard.docs || bundle.docs || [];

  renderFolderChrome(bundle.folder, "dashboard");
  renderStats(bundle.dashboard.file_count ?? docs.length);
  renderFolderDocs("folder-docs", docs, "No files.");
  renderPlaceholder("topic-progress", "Current DynamoDB data only has folder and file items.");
  renderPlaceholder("quiz-history", "No quiz data yet.");
}

bindAuth({
  onAuthChange: async (userId) => {
    if (!userId) {
      byId("folder-title").textContent = "Sign in required";
      byId("folder-meta").textContent = "Sign in to continue.";
      return;
    }
    try {
      await loadPage();
    } catch (error) {
      showToast(error.message, "error");
    }
  },
});
