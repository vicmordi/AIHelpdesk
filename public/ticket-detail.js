/**
 * Ticket detail page — full-width view with Details and Chat tabs.
 * For employees only; loads ticket from /tickets/my-tickets by ?id=.
 */
import { apiRequest, clearToken, isAuthenticated } from "./api.js";

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function getSenderLabel(msg, ticket) {
    if (!msg) return "";
    if (msg.sender === "user") return "You";
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

let currentTicket = null;

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
        const data = await apiRequest("/tickets/my-tickets");
        const tickets = data.tickets || [];
        const ticket = tickets.find((t) => t.id === id);
        if (!ticket) {
            loading.style.display = "none";
            errorEl.textContent = "Ticket not found or you don't have access.";
            errorEl.style.display = "block";
            return;
        }

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

        document.getElementById("ticket-detail-created").textContent = "Created " + new Date(ticket.createdAt).toLocaleString();
        document.getElementById("ticket-detail-assigned").textContent = ticket.assigned_to_name ? "Assigned to " + ticket.assigned_to_name : "Unassigned";

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
                    <time>${new Date(m.createdAt || m.created_at).toLocaleString()}</time>
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

        try {
            await apiRequest(`/messages/mark-read/${ticket.id}`, { method: "POST" });
        } catch (_) {}
    } catch (err) {
        loading.style.display = "none";
        errorEl.textContent = err.message || "Failed to load ticket.";
        errorEl.style.display = "block";
    }
}

function renderChat(ticket) {
    const thread = document.getElementById("ticket-chat-thread");
    const messages = ticket.messages || [];
    let html = "";
    if (messages.length === 0) {
        html = `<div class="ticket-chat-bubble user"><span class="chat-sender">You</span><div>${escapeHtml(ticket.message || "")}</div><span class="chat-time">${new Date(ticket.createdAt).toLocaleString()}</span></div>`;
        if (ticket.aiReply && ticket.ai_mode !== "guided") {
            html += `<div class="ticket-chat-bubble ai"><span class="chat-sender">AI Assistant</span><div>${escapeHtml(ticket.aiReply)}</div><span class="chat-time">${new Date(ticket.createdAt).toLocaleString()}</span></div>`;
        }
    } else {
        html = messages.map((m) => {
            const senderLabel = getSenderLabel(m, ticket);
            const time = new Date(m.createdAt || m.created_at).toLocaleString();
            const cls = m.sender === "user" ? "user" : m.sender === "admin" ? "admin" : "ai";
            return `<div class="ticket-chat-bubble ${cls}"><span class="chat-sender">${escapeHtml(senderLabel)}</span><div>${escapeHtml(m.message || "")}</div><span class="chat-time">${time}</span></div>`;
        }).join("");
    }
    thread.innerHTML = html || "<p style='color: var(--text-tertiary);'>No messages yet.</p>";
    thread.scrollTop = thread.scrollHeight;
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
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = (input.value || "").trim();
        if (!text) return;
        try {
            await apiRequest(`/tickets/${ticket.id}/messages`, {
                method: "POST",
                body: JSON.stringify({ message: text, sender: "user" }),
            });
            input.value = "";
            const data = await apiRequest("/tickets/my-tickets");
            const updated = (data.tickets || []).find((t) => t.id === ticket.id);
            if (updated) {
                currentTicket = updated;
                renderChat(updated);
            }
        } catch (err) {
            alert(err.message || "Failed to send message.");
        }
    });
}

(async function init() {
    if (!isAuthenticated()) {
        window.location.href = "login.html";
        return;
    }
    try {
        const userData = await apiRequest("/auth/me");
        if (["admin", "super_admin", "support_admin"].includes(userData.role || "")) {
            window.location.href = "admin.html";
            return;
        }
        const emailEl = document.getElementById("user-email");
        if (emailEl) emailEl.textContent = userData.email || "";
        document.getElementById("logout-btn")?.addEventListener("click", () => {
            clearToken();
            window.location.href = "login.html";
        });
        await loadTicket();
    } catch (err) {
        document.getElementById("ticket-loading").style.display = "none";
        document.getElementById("ticket-error").textContent = err.message || "Failed to load.";
        document.getElementById("ticket-error").style.display = "block";
    }
})();
