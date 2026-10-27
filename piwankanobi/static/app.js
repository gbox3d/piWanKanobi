"use strict";

const byId = (id) => document.getElementById(id);
const promptInput = byId("prompt");
const messagesElement = byId("messages");
const fileInput = byId("image-input");
const maxImageBytes = 8 * 1024 * 1024;
let messages = [];
let attachedImage = null;
let pending = false;
let imageLoading = false;
let serverState = "loading";
let requestId = 0;
let dragDepth = 0;

function showError(message = "") {
  byId("error-message").textContent = message;
  byId("error-message").hidden = !message;
}

function showNotice(message = "") {
  byId("notice").textContent = message;
  byId("notice").hidden = !message;
}

function updateControls() {
  byId("send-button").disabled = pending || imageLoading || serverState !== "ready" || !promptInput.value.trim();
  for (const id of ["attach-button", "remove-image", "reset-button", "sample-button"]) {
    byId(id).disabled = pending || imageLoading;
  }
  promptInput.readOnly = pending;
  byId("chat-form").setAttribute("aria-busy", String(pending || imageLoading));
}

function resizePrompt() {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 160)}px`;
}

function setStatus(state, message) {
  serverState = state;
  byId("status").dataset.state = state;
  byId("status-text").textContent = message;
  updateControls();
}

async function checkHealth() {
  try {
    const response = await fetch("./api/health", { cache: "no-store", signal: AbortSignal.timeout(10000) });
    const health = await response.json();
    const state = health.state || health.status;
    if (health.model) byId("model-name").textContent = health.model;
    if (state === "ready" || state === "ok") {
      setStatus("ready", "대화할 준비가 됐어요");
    } else if (state === "busy") {
      setStatus("busy", pending ? "이미지를 살펴보는 중" : "다른 답변을 준비하는 중");
    } else if (state === "loading" || state === "starting") {
      setStatus("loading", "모델을 준비하는 중이에요");
    } else {
      setStatus("error", "모델 연결을 확인하고 있어요");
    }
  } catch {
    setStatus("error", "서버에 다시 연결하는 중");
  }
  window.setTimeout(checkHealth, serverState === "ready" ? 10000 : 2000);
}

function clearConversation() {
  messages = [];
  messagesElement.replaceChildren();
  byId("welcome").hidden = false;
  showError();
  showNotice();
}

function setImage(image) {
  if (messages.length) {
    clearConversation();
    showNotice("이미지가 바뀌어 새 대화를 시작했어요.");
  }
  attachedImage = image;
  byId("attachment").hidden = !image;
  if (image) {
    byId("attachment-image").src = image.data;
    byId("attachment-name").textContent = image.name;
  } else {
    byId("attachment-image").removeAttribute("src");
    byId("attachment-name").textContent = "";
  }
  fileInput.value = "";
  updateControls();
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("이미지를 읽지 못했어요. 다시 선택해 주세요."));
    reader.readAsDataURL(file);
  });
}

async function prepareImage(file) {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    throw new Error("PNG, JPG, WebP 이미지를 선택해 주세요.");
  }
  if (file.size > maxImageBytes) throw new Error("이미지는 최대 8 MB까지 넣을 수 있어요.");
  let data = await readFile(file);
  const decoded = new Image();
  await new Promise((resolve, reject) => {
    decoded.onload = resolve;
    decoded.onerror = () => reject(new Error("이미지 파일을 열 수 없어요. 다른 이미지를 선택해 주세요."));
    decoded.src = data;
  });
  const longestSide = Math.max(decoded.naturalWidth, decoded.naturalHeight);
  if (longestSide > 1600) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(decoded.naturalWidth * 1600 / longestSide));
    canvas.height = Math.max(1, Math.round(decoded.naturalHeight * 1600 / longestSide));
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(decoded, 0, 0, canvas.width, canvas.height);
    data = canvas.toDataURL("image/jpeg", .88);
  }
  return { name: file.name || "붙여넣은 이미지", data };
}

async function attachFile(file) {
  if (!file || pending || imageLoading) return;
  imageLoading = true;
  updateControls();
  showError();
  showNotice();
  try {
    setImage(await prepareImage(file));
    promptInput.focus();
  } catch (error) {
    showError(error.message);
  } finally {
    imageLoading = false;
    updateControls();
  }
}

function appendMessage(role, content, options = {}) {
  const row = document.createElement("article");
  row.className = `message ${role}`;
  if (role === "assistant") {
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.textContent = "π";
    avatar.setAttribute("aria-hidden", "true");
    row.append(avatar);
  }
  const body = document.createElement("div");
  body.className = "message-body";
  if (role === "assistant") {
    const label = document.createElement("p");
    label.className = "message-label";
    label.textContent = "PiWanKanobi";
    body.append(label);
  }
  if (options.image) {
    const image = document.createElement("img");
    image.src = options.image;
    image.alt = "질문에 첨부한 이미지";
    image.className = "message-image";
    body.append(image);
  }
  const text = document.createElement("p");
  text.className = "message-text";
  text.textContent = content;
  body.append(text);
  if (options.typing) {
    text.className = "typing";
    for (let i = 0; i < 3; i++) text.append(document.createElement("i"));
    const label = document.createElement("span");
    label.className = "typing-label";
    label.textContent = "생각하고 있어요";
    text.append(label);
  }
  if (typeof options.seconds === "number") {
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = `${options.seconds.toFixed(1)}초`;
    body.append(meta);
  }
  row.append(body);
  messagesElement.append(row);
  return row;
}

function scrollToLatest() {
  window.requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }));
}

async function sendMessage(event) {
  event.preventDefault();
  const content = promptInput.value.trim();
  if (pending || imageLoading || serverState !== "ready" || !content) return;
  pending = true;
  updateControls();
  showError();
  showNotice();
  byId("welcome").hidden = true;
  const userRow = appendMessage("user", content, { image: messages.length ? null : attachedImage?.data });
  const typingRow = appendMessage("assistant", "", { typing: true });
  scrollToLatest();
  const conversation = [...messages, { role: "user", content }];
  const params = { messages: conversation, max_tokens: 128 };
  if (attachedImage) params.image = attachedImage.data;
  try {
    const response = await fetch("./rpc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++requestId, method: "vlm.chat", params }),
      signal: AbortSignal.timeout(180000),
    });
    const reply = await response.json();
    if (reply.error) throw new Error(reply.error.message || "답변을 만들지 못했어요. 다시 시도해 주세요.");
    if (!response.ok || typeof reply.result?.message?.content !== "string") {
      throw new Error("서버 응답을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
    typingRow.remove();
    messages = [...conversation, { role: "assistant", content: reply.result.message.content }];
    appendMessage("assistant", reply.result.message.content, { seconds: reply.result.elapsed_seconds });
    promptInput.value = "";
    resizePrompt();
    if (reply.result.model) byId("model-name").textContent = reply.result.model;
    setStatus("ready", "대화할 준비가 됐어요");
  } catch (error) {
    typingRow.remove();
    userRow.remove();
    byId("welcome").hidden = messages.length > 0;
    showError(error.name === "TimeoutError" ? "답변이 오래 걸리고 있어요. 잠시 후 다시 보내 주세요." : error.message);
  } finally {
    pending = false;
    updateControls();
    promptInput.focus();
    scrollToLatest();
  }
}

byId("chat-form").addEventListener("submit", sendMessage);
promptInput.addEventListener("input", () => { resizePrompt(); updateControls(); });
promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    byId("chat-form").requestSubmit();
  }
});
byId("attach-button").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => attachFile(fileInput.files[0]));
byId("remove-image").addEventListener("click", () => { setImage(null); promptInput.focus(); });
byId("reset-button").addEventListener("click", () => {
  clearConversation();
  setImage(null);
  promptInput.value = "";
  resizePrompt();
  updateControls();
  promptInput.focus();
});
byId("sample-button").addEventListener("click", async () => {
  if (pending || imageLoading) return;
  imageLoading = true;
  updateControls();
  showError();
  try {
    const response = await fetch("./samples/apple.png");
    if (!response.ok) throw new Error("예제 이미지를 불러오지 못했어요.");
    const file = new File([await response.blob()], "사과 예제.png", { type: "image/png" });
    setImage(await prepareImage(file));
    promptInput.value = "이 그림에는 어떤 과일이 있나요? 색깔도 알려주세요.";
    resizePrompt();
    promptInput.focus();
  } catch (error) {
    showError(error.message);
  } finally {
    imageLoading = false;
    updateControls();
  }
});
for (const button of document.querySelectorAll("[data-prompt]")) {
  button.addEventListener("click", () => {
    if (pending) return;
    promptInput.value = button.dataset.prompt;
    resizePrompt();
    updateControls();
    promptInput.focus();
  });
}
document.addEventListener("paste", (event) => {
  const image = Array.from(event.clipboardData?.files || []).find((file) => file.type.startsWith("image/"));
  if (image) { event.preventDefault(); attachFile(image); }
});
document.addEventListener("dragenter", (event) => {
  if (!Array.from(event.dataTransfer?.types || []).includes("Files")) return;
  event.preventDefault();
  dragDepth++;
  if (!pending && !imageLoading) byId("drop-overlay").hidden = false;
});
document.addEventListener("dragover", (event) => {
  if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault();
});
document.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) byId("drop-overlay").hidden = true;
});
document.addEventListener("drop", (event) => {
  if (!event.dataTransfer?.files.length) return;
  event.preventDefault();
  dragDepth = 0;
  byId("drop-overlay").hidden = true;
  attachFile(event.dataTransfer.files[0]);
});
checkHealth();
