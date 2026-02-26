/**
 * Ticket detail page — single unified view for Employee, Support Admin, Super Admin.
 * Loads ticket via GET /tickets/:id. Same layout for all roles; only controls differ.
 */
import { apiRequest, clearToken, isAuthenticated, formatLocalTime } from "./api.js";

let currentUser = null;
let currentTicket = null;

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function getSenderLabel(msg, isAdminView) {
    if (!msg) return "";
    if (msg.sender === "user") return isAdminView ? (msg.sender_name || "Customer") + " (User)" : "You";
    if (msg.sender === "admin") {
        const name = msg.sender_name || "Support";
        const role = msg.sender_role === "super_admin" ? "Super Admin" : msg.sender_role === "support_admin" ? "Support" : "";
        return role ? `${name} (${role})` : name;
    }
    return "AI Assistant";
}

function getTicketId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("id") || "";
}

function isAdmin() {
    return currentUser && ["super_admin", "support_admin", "admin"].includes(currentUser.role || "");
}

async function loadTicket() {
    const id = getTicketId();
    const loading = document.getElementById("ticket-loading");
    const errorEl = document.getElementById("ticket-error");
    const root = document.getElementById("ticket-root");

    if (!id) {
        loading.style.display = "none";
        errorEl.textContent = "No ticket ID provided.";
        errorEl.style.display = "block";
        return;
    }

    try {
        const ticket = await apiRequest(`/tickets/${id}`);
        currentTicket = ticket;
        loading.style.display = "none";
        root.style.display = "block";

        const title = ticket.summary || ticket.message || "Support request";
        const titleShort = title.length > 80 ? title.substring(0, 80) + "…" : title;
        document.getElementById("ticket-detail-title").textContent = titleShort;

        const statusLabel = ticket.escalated === true ? "Escalated" : (ticket.status || "Open").replace(/_/g, " ");
        const statusClass = ticket.escalated === true ? "status-escalated" : ticket.status === "closed" || ticket.status === "resolved" || ticket.status === "auto_resolved" ? "status-closed" : ticket.status === "in_progress" ? "status-in-progress" : "status-open";
        const statusEl = document.getElementById("ticket-detail-status");
        statusEl.textContent = statusLabel;
        statusEl.className = "ticket-detail-badge " + statusClass;

        document.getElementById("ticket-detail-created").textContent = "Created " + formatLocalTime(ticket.createdAt);
        let assignedLabel = "Unassigned";
        if (ticket.assigned_to) {
            if (ticket.assigned_to_name) assignedLabel = "Assigned to " + ticket.assigned_to_name;
            else if (isAdmin()) {
                try {
                    const mem = await apiRequest("/organization/members");
                    const m = (mem.members || []).find((x) => x.uid === ticket.assigned_to);
                    assignedLabel = m ? "Assigned to " + (m.email || m.full_name || "—") : "Assigned";
                } catch (_) {
                    assignedLabel = "Assigned";
                }
            } else assignedLabel = "Assigned";
        }
        document.getElementById("ticket-detail-assigned").textContent = assignedLabel;

        document.getElementById("ticket-detail-description").textContent = ticket.message || "No description.";
        const summarySection = document.getElementById("ticket-detail-summary-section");
        if (ticket.summary) {
            summarySection.style.display = "block";
            document.getElementById("ticket-detail-summary").textContent = ticket.summary;
        } else {
            summarySection.style.display = "none";
        }

        const aiSection = document.getElementById("ticket-detail-ai-section");
        const aiHistory = document.getElementById("ticket-detail-ai-history");
        const aiMessages = (ticket.messages || []).filter((m) => m.sender === "ai");
        if (aiMessages.length > 0) {
            aiSection.style.display = "block";
            aiHistory.innerHTML = aiMessages.map((m) => `
                <div class="ticket-detail-ai-item">
                    <time>${formatLocalTime(m.createdAt || m.created_at)}</time>
                    ${escapeHtml(m.message || "")}
                </div>
            `).join("");
        } else {
            aiSection.style.display = "none";
        }

        const escSection = document.getElementById("ticket-detail-escalation-section");
        if (ticket.escalated === true) {
            escSection.style.display = "block";
            document.getElementById("ticket-detail-escalation").textContent = "This ticket has been escalated to the support team. They will respond as soon as possible.";
        } else {
            escSection.style.display = "none";
        }

        renderChat(ticket);
        setupTabs();
        setupChatForm(ticket);

        const isResolved = ticket.resolved === true || ticket.status === "closed" || ticket.status === "resolved" || ticket.status === "auto_resolved";
        document.getElementById("ticket-chat-input-wrap").style.display = isResolved ? "none" : "block";

        if (isAdmin()) {
            document.getElementById("ticket-detail-admin-controls").style.display = "block";
            const statusSelect = document.getElementById("ticket-status-select");
            statusSelect.value = ticket.status || "open";
            document.getElementById("ticket-status-update-btn").onclick = () => updateStatus(ticket.id);
            if (currentUser.role === "super_admin") {
                document.getElementById("ticket-detail-assign-wrap").style.display = "flex";
                loadAssignMembers(ticket);
                document.getElementById("ticket-assign-btn").onclick = () => assignTicket(ticket.id);
            }
        } else {
            document.getElementById("ticket-detail-admin-controls").style.display = "none";
        }

        try {
            await apiRequest(`/messages/mark-read/${ticket.id}`, { method: "POST" });
        } catch (_) {}
    } catch (err) {
        loading.style.display = "none";
        errorEl.textContent = err.message || err.detail || "Failed to load ticket.";
        errorEl.style.display = "block";
    }
}

async function loadAssignMembers(ticket) {
    const sel = document.getElementById("ticket-assign-select");
    try {
        const data = await apiRequest("/organization/members");
        const members = (data.members || []).filter((m) => m.role === "support_admin" || m.role === "super_admin");
        sel.innerHTML = '<option value="">Unassigned</option>' + members.map((m) => `<option value="${m.uid}" ${ticket.assigned_to === m.uid ? "selected" : ""}>${escapeHtml(m.email || m.full_name || m.uid)}</option>`).join("");
    } catch (_) {
        sel.innerHTML = '<option value="">Unassigned</option>';
    }
}

async function updateStatus(ticketId) {
    const statusSelect = document.getElementById("ticket-status-select");
    const status = statusSelect.value;
    try {
        await apiRequest(`/tickets/${ticketId}/status`, { method: "PUT", body: JSON.stringify({ status }) });
        await loadTicket();
    } catch (err) {
        alert(err.message || "Failed to update status.");
    }
}

async function assignTicket(ticketId) {
    const sel = document.getElementById("ticket-assign-select");
    const uid = sel.value || null;
    try {
        await apiRequest(`/tickets/${ticketId}/assign`, { method: "PUT", body: JSON.stringify({ assigned_to: uid }) });
        await loadTicket();
    } catch (err) {
        alert(err.message || "Failed to assign.");
    }
}

function renderChat(ticket) {
    const thread = document.getElementById("ticket-chat-thread");
    const messages = ticket.messages || [];
    const isAdminView = isAdmin();
    let html = "";
    if (messages.length === 0) {
        const userLabel = isAdminView ? (ticket.created_by_name || "Customer") + " (User)" : "You";
        html = `<div class="ticket-chat-bubble user"><span class="chat-sender">${escapeHtml(userLabel)}</span><div>${escapeHtml(ticket.message || "")}</div><span class="chat-time">${formatLocalTime(ticket.createdAt)}</span></div>`;
        if (ticket.aiReply && ticket.ai_mode !== "guided") {
            html += `<div class="ticket-chat-bubble ai"><span class="chat-sender">AI Assistant</span><div>${escapeHtml(ticket.aiReply)}</div><span class="chat-time">${formatLocalTime(ticket.createdAt)}</span></div>`;
        }
    } else {
        html = messages.map((m) => {
            const senderLabel = getSenderLabel(m, isAdminView);
            const time = formatLocalTime(m.createdAt || m.created_at);
            const cls = m.sender === "user" ? "user" : m.sender === "admin" ? "admin" : "ai";
            return `<div class="ticket-chat-bubble ${cls}"><span class="chat-sender">${escapeHtml(senderLabel)}</span><div>${escapeHtml(m.message || "")}</div><span class="chat-time">${time}</span></div>`;
        }).join("");
    }
    thread.innerHTML = html || "<p style='color: var(--text-tertiary);'>No messages yet.</p>";
    thread.scrollTop = thread.scrollHeight;
}

function appendMessageOptimistic(sender, message, senderLabel) {
    const thread = document.getElementById("ticket-chat-thread");
    const p = thread.querySelector("p");
    if (p) p.remove();
    const cls = sender === "user" ? "user" : sender === "admin" ? "admin" : "ai";
    const time = formatLocalTime(new Date().toISOString());
    const div = document.createElement("div");
    div.className = `ticket-chat-bubble ${cls} ticket-chat-optimistic`;
    div.innerHTML = `<span class="chat-sender">${escapeHtml(senderLabel)}</span><div>${escapeHtml(message)}</div><span class="chat-time">${time}</span>`;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
}

function removeOptimisticMessage() {
    const el = document.getElementById("ticket-chat-thread")?.querySelector(".ticket-chat-optimistic");
    if (el) el.remove();
}

function setupTabs() {
    document.querySelectorAll(".ticket-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll(".ticket-tab").forEach((b) => b.classList.remove("active"));
            document.querySelectorAll(".ticket-tab-panel").forEach((p) => p.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById("ticket-tab-" + tab).classList.add("active");
            if (tab === "chat") {
                const thread = document.getElementById("ticket-chat-thread");
                if (thread) thread.scrollTop = thread.scrollHeight;
            }
        });
    });
}

function setupChatForm(ticket) {
    const form = document.getElementById("ticket-chat-form");
    const input = document.getElementById("ticket-chat-input");
    const adminView = isAdmin();
    const sender = adminView ? "admin" : "user";
    const senderLabel = adminView ? (currentUser?.name || currentUser?.email || "Support") + " (Support)" : "You";

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if ((input.value || "").trim()) form.requestSubmit();
        }
    });
    input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = (input.value || "").trim();
        if (!text) return;
        input.value = "";
        appendMessageOptimistic(sender, text, senderLabel);
        const thread = document.getElementById("ticket-chat-thread");
        thread.scrollTop = thread.scrollHeight;
        input.focus();

        try {
            await apiRequest(`/tickets/${ticket.id}/messages`, {
                method: "POST",
                body: JSON.stringify({ message: text, sender }),
            });
            removeOptimisticMessage();
            const updated = await apiRequest(`/tickets/${ticket.id}`);
            currentTicket = updated;
            renderChat(updated);
        } catch (err) {
            removeOptimisticMessage();
            alert(err.message || "Failed to send message.");
        }
    });
}

(async function init() {
    if (!isAuthenticated()) {
        window.location.href = "index.html";
        return;
    }
    try {
        currentUser = await apiRequest("/auth/me");
        const backLink = document.getElementById("ticket-detail-back");
        if (backLink) {
            backLink.href = ["admin", "super_admin", "support_admin"].includes(currentUser.role || "") ? "admin.html#tickets" : "submit-ticket.html";
            backLink.textContent = (currentUser.role && currentUser.role !== "employee") ? "← Back to Tickets" : "← Back to My Tickets";
        }
        const emailEl = document.getElementById("user-email");
        if (emailEl) emailEl.textContent = currentUser.email || "";
        document.getElementById("logout-btn")?.addEventListener("click", () => {
            clearToken();
            window.location.href = "index.html";
        });
        await loadTicket();
    } catch (err) {
        document.getElementById("ticket-loading").style.display = "none";
        document.getElementById("ticket-error").textContent = err.message || "Failed to load.";
        document.getElementById("ticket-error").style.display = "block";
    }
})();
