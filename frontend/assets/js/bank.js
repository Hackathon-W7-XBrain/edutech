import { api, escapeHtml, showToast } from "./api.js";
import { bindAuth } from "./auth.js";

const state = {
  docs: [],
  folders: [],
  selectedFolderId: "",
  folderModalMode: "create",
  renameFolderId: "",
};

function byId(id) {
  return document.getElementById(id);
}

function openModal(id) {
  byId(id).classList.add("open");
}

function closeModal(id) {
  byId(id).classList.remove("open");
}

function renderBankStats() {
  const assignedDocs = state.docs.filter((doc) => doc.folders?.length).length;
  byId("bank-stats").innerHTML = `
    <div class="metric-pill">
      <strong>${state.docs.length}</strong>
      <span>Bank files</span>
    </div>
    <div class="metric-pill">
      <strong>${state.folders.length}</strong>
      <span>Folders</span>
    </div>
    <div class="metric-pill">
      <strong>${assignedDocs}</strong>
      <span>Attached docs</span>
    </div>
  `;
}

function renderDocs() {
  const host = byId("docs-list");
  if (!state.docs.length) {
    host.innerHTML = '<div class="empty">No files yet.</div>';
    return;
  }

  host.innerHTML = state.docs
    .map((doc) => {
      const folders = doc.folders?.length
        ? `<div class="doc-meta">${doc.folders.map((folder) => `<span class="chip">${escapeHtml(folder)}</span>`).join("")}</div>`
        : '<div class="muted small">Unassigned</div>';
      return `
        <article class="doc-row">
          <div class="doc-row-main">
            <h4>${escapeHtml(doc.filename)}</h4>
            <div class="muted small mono">${escapeHtml(doc.doc_id.slice(0, 8))}</div>
            ${folders}
          </div>
          <div class="doc-actions">
            <button class="btn-secondary" data-doc="${doc.doc_id}" data-action="assign">Add to folder</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderFolders() {
  const host = byId("folders-list");
  if (!state.folders.length) {
    host.innerHTML = '<div class="empty">No folders yet.</div>';
    return;
  }

  host.innerHTML = state.folders
    .map(
      (folder) => `
        <article class="folder-row">
          <div class="folder-row-main">
            <a class="folder-name-link" href="/folder/${folder.folder_id}/workspace">${escapeHtml(folder.name)}</a>
            <div class="muted small">${folder.doc_count} files · ${folder.topics_generated ? "topics ready" : "topics not generated"}</div>
          </div>
          <div class="folder-actions">
            <button class="btn-secondary" data-folder="${folder.folder_id}" data-action="rename">Rename</button>
            <button class="btn-secondary" data-folder="${folder.folder_id}" data-action="add-docs">Add docs</button>
            <a class="btn btn-primary" href="/folder/${folder.folder_id}/workspace">Open</a>
          </div>
        </article>
      `
    )
    .join("");
}

async function loadBank() {
  const [docsResult, foldersResult, health] = await Promise.all([
    api("/api/bank/documents"),
    api("/api/folders"),
    api("/health"),
  ]);
  state.docs = docsResult.docs || [];
  state.folders = foldersResult.folders || [];
  renderBankStats();
  renderDocs();
  renderFolders();
  byId("status-pills").innerHTML = Object.entries(health.backends)
    .map(([key, value]) => `<span class="chip">${escapeHtml(`${key}: ${value}`)}</span>`)
    .join("");
}

async function handleUpload(file) {
  byId("upload-note").textContent = `Uploading ${file.name}...`;
  try {
    const init = await api("/api/bank/documents/upload-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        content_type: file.type || "application/octet-stream",
      }),
    });
    const uploadResp = await fetch(init.upload.url, {
      method: init.upload.method || "PUT",
      headers: init.upload.headers || { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!uploadResp.ok) {
      throw new Error("Upload to storage failed");
    }
    showToast(`Uploaded ${file.name}`, "success");
    byId("upload-note").textContent = `${file.name} uploaded`;
    await loadBank();
  } catch (error) {
    byId("upload-note").textContent = error.message;
    showToast(error.message, "error");
  }
}

function openAssignModal(folderId = "", docId = "") {
  state.selectedFolderId = folderId;
  const folderOptions = state.folders
    .map((folder) => `<option value="${folder.folder_id}" ${folder.folder_id === folderId ? "selected" : ""}>${escapeHtml(folder.name)}</option>`)
    .join("");
  byId("assign-folder-select").innerHTML = `<option value="">Choose folder</option>${folderOptions}`;
  byId("assign-doc-list").innerHTML = state.docs
    .map(
      (doc) => `
        <label class="card row">
          <input type="checkbox" value="${doc.doc_id}" ${doc.doc_id === docId ? "checked" : ""}>
          <span>${escapeHtml(doc.filename)}</span>
        </label>
      `
    )
    .join("");
  openModal("assign-modal");
}

async function submitAssignModal() {
  const folderId = byId("assign-folder-select").value || state.selectedFolderId;
  if (!folderId) {
    showToast("Pick a folder", "error");
    return;
  }
  const checked = [...byId("assign-doc-list").querySelectorAll("input:checked")].map((input) => input.value);
  if (!checked.length) {
    showToast("Pick a file", "error");
    return;
  }
  try {
    await api(`/api/folders/${folderId}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_ids: checked }),
    });
    closeModal("assign-modal");
    showToast("Assigned", "success");
    await loadBank();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openFolderModal(mode, folderId = "") {
  state.folderModalMode = mode;
  state.renameFolderId = folderId;
  const title = byId("folder-modal-title");
  const copy = byId("folder-modal-copy");
  const input = byId("folder-name-input");

  if (mode === "rename") {
    const current = state.folders.find((folder) => folder.folder_id === folderId);
    title.textContent = "Rename folder";
    copy.textContent = "Edit folder name.";
    input.value = current?.name || "";
  } else {
    title.textContent = "Create folder";
    copy.textContent = "Create a new folder.";
    input.value = "";
  }
  openModal("folder-modal");
  input.focus();
}

async function submitFolderModal() {
  const name = byId("folder-name-input").value.trim();
  if (!name) {
    showToast("Enter a name", "error");
    return;
  }
  try {
    if (state.folderModalMode === "rename") {
      await api(`/api/folders/${state.renameFolderId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      showToast("Renamed", "success");
    } else {
      await api("/api/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      showToast("Created", "success");
    }
    closeModal("folder-modal");
    await loadBank();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function bindEvents() {
  const fileInput = byId("upload-input");
  byId("browse-upload").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (event) => {
    const [file] = event.target.files;
    if (file) {
      handleUpload(file);
    }
  });

  const dropzone = byId("dropzone");
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("drag");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag");
    const [file] = event.dataTransfer.files;
    if (file) {
      handleUpload(file);
    }
  });

  byId("create-folder-btn").addEventListener("click", () => openFolderModal("create"));
  byId("open-assign-btn").addEventListener("click", () => openAssignModal());
  byId("folder-modal-close").addEventListener("click", () => closeModal("folder-modal"));
  byId("folder-modal-submit").addEventListener("click", submitFolderModal);
  byId("folder-name-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      submitFolderModal();
    }
  });

  byId("assign-close").addEventListener("click", () => closeModal("assign-modal"));
  byId("assign-submit").addEventListener("click", submitAssignModal);

  byId("docs-list").addEventListener("click", (event) => {
    const target = event.target.closest("button[data-action='assign']");
    if (!target) {
      return;
    }
    openAssignModal("", target.dataset.doc);
  });

  byId("folders-list").addEventListener("click", (event) => {
    const actionNode = event.target.closest("button[data-action]");
    if (!actionNode) {
      return;
    }
    if (actionNode.dataset.action === "rename") {
      openFolderModal("rename", actionNode.dataset.folder);
    }
    if (actionNode.dataset.action === "add-docs") {
      openAssignModal(actionNode.dataset.folder);
    }
  });
}

bindAuth({
  onAuthChange: async (userId) => {
    if (!userId) {
      byId("docs-list").innerHTML = '<div class="empty">Sign in to view your bank.</div>';
      byId("folders-list").innerHTML = '<div class="empty">Sign in to view folders.</div>';
      byId("bank-stats").innerHTML = "";
      return;
    }
    try {
      await loadBank();
    } catch (error) {
      showToast(error.message, "error");
    }
  },
});

bindEvents();
