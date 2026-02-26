/**
 * Admin Dashboard JavaScript — backend API only, hash-based pages, sidebar.
 */
import { apiRequest, clearToken, isAuthenticated, formatLocalTime } from "./api.js";
import { renderSidebar } from "./js/sidebar.js";

let currentUser = null;

/** Build display label for a message sender (admin view: Customer/Name (Role); user view: You/Name (Role)) */
function getSenderLabel(msg, ticket, isAdminView) {
    if (!msg) return "";
    if (msg.sender === "user") return isAdminView ? (msg.sender_name || ticket?.created_by_name || "Customer") + " (User)" : "You";
    if (msg.sender === "admin") {
        const name = msg.sender_name || "Admin";
        const role = msg.sender_role === "super_admin" ? "Super Admin" : msg.sender_role === "support_admin" ? "Support" : "";
        return role ? `${name} (${role})` : name;
    }
    return "AI Assistant";
}

/**
 * Optional: short subtle sound when new unread message arrives.
 */
function playNewMessageSound() {
    try {
        const C = window.AudioContext || window.webkitAudioContext;
        if (!C) return;
        const ctx = new C();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        osc.type = "sine";
        gain.gain.setValueAtTime(0.1, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.1);
    } catch (_) {}
}

/**
 * Fetch unread message count and update sidebar Messages badge.
 */
async function fetchUnreadCount() {
    try {
        const data = await apiRequest("/messages/unread-count");
        const count = data.unread_count ?? data.unread_messages ?? 0;
        const badge = document.getElementById("sidebar-messages-badge");
        if (badge) {
            badge.textContent = count > 99 ? "99+" : String(count);
            badge.style.display = count > 0 ? "inline-flex" : "none";
            if (count > 0 && (window._adminLastUnreadCount ?? 0) < count) {
                badge.classList.add("pulse-once");
                setTimeout(() => badge.classList.remove("pulse-once"), 600);
                playNewMessageSound();
            }
            window._adminLastUnreadCount = count;
        }
    } catch (_) {}
}

function showPage(pageId) {
    document.querySelectorAll(".admin-page").forEach((el) => {
        el.classList.toggle("active", el.getAttribute("data-page") === pageId);
    });
    if (pageId === "tickets") {
        loadAllTickets();
        loadAssignableMembers();
    } else if (pageId === "knowledge-base") {
        loadKnowledgeBase();
        const addBtn = document.getElementById("kb-add-new-btn");
        if (addBtn) addBtn.style.display = currentUser?.role === "super_admin" ? "inline-flex" : "none";
        if (window.location.hash === "#knowledge-base/add" || window._openAddArticleModal) {
            window._openAddArticleModal = false;
            if (currentUser?.role === "super_admin") openAddArticleModal();
        }
    } else if (pageId === "dashboard") {
        loadDashboardStats();
        if (currentUser?.role === "super_admin") loadKnowledgeAnalytics();
    }
    else if (pageId === "messages") loadMessagesPage();
    else if (pageId === "knowledge-improvement") {
        if (currentUser?.role !== "super_admin") {
            document.getElementById("ki-list-draft") && (document.getElementById("ki-list-draft").innerHTML = "<p class=\"empty-state\">Access denied. Super Admin only.</p>");
            return;
        }
        const subPart = (window.location.hash || "").split("/")[1];
        const suggestionId = (window.location.hash || "").split("/")[2];
        if (subPart === "review" && suggestionId) {
            showSuggestionReviewPage(suggestionId);
        } else {
            loadKnowledgeImprovementPage();
        }
    } else if (pageId === "users") {
        if (currentUser?.role === "super_admin") loadUserManagementPage();
        else document.getElementById("user-mgmt-table-wrap") && (document.getElementById("user-mgmt-table-wrap").innerHTML = "<p class=\"empty-state\">Access denied. Super Admin only.</p>");
    } else if (pageId === "settings") {
        if (currentUser?.role === "super_admin") loadSettingsPage();
        else document.getElementById("settings-content") && (document.getElementById("settings-content").innerHTML = "<p class=\"empty-state\">Access denied. Super admin only.</p>");
    }
}

function loadDashboardStats() {
    const welcomeEl = document.getElementById("dashboard-welcome");
    if (welcomeEl && currentUser) {
        const first = currentUser.first_name || currentUser.name?.split(" ")[0] || currentUser.email?.split("@")[0] || "there";
        const roleLabel = currentUser.role === "super_admin" ? "Super Admin" : currentUser.role === "support_admin" ? "Support Admin" : "User";
        welcomeEl.innerHTML = `Welcome, ${escapeHtml(first)} 👋 <span class="badge badge-neutral" style="margin-left: 8px;">${roleLabel}</span>`;
    }
    apiRequest("/tickets").then((data) => {
        const tickets = data.tickets || [];
        const stats = {
            total: tickets.length,
            resolved: tickets.filter((t) => t.status === "closed" || t.status === "resolved" || t.status === "auto_resolved").length,
            escalated: tickets.filter((t) => t.escalated === true).length,
            in_progress: tickets.filter((t) => t.status === "in_progress").length,
        };
        updateStatistics(stats);
        updateDashboardCharts(tickets);
    }).catch(() => {
        updateStatistics({ total: 0, resolved: 0, escalated: 0, in_progress: 0 });
        updateDashboardCharts([]);
    });
}

async function loadAssignableMembers() {
    const wrap = document.getElementById("assigned-to-filter-wrap");
    if (currentUser?.role !== "super_admin") {
        if (wrap) wrap.style.display = "none";
        return;
    }
    if (wrap) wrap.style.display = "";
    const sel = document.getElementById("assigned-to-filter");
    if (!sel) return;
    try {
        const data = await apiRequest("/organization/members");
        const members = data.members || [];
        const current = sel.value;
        sel.innerHTML = '<option value="">All assignees</option>' + members
            .filter((m) => m.role === "support_admin" || m.role === "super_admin")
            .map((m) => `<option value="${m.uid}">${m.email}</option>`).join("");
        if (current) sel.value = current;
    } catch (_) {
        sel.innerHTML = '<option value="">All assignees</option>';
    }
}

let userMgmtActiveTab = "support_admins";

async function loadUserManagementPage() {
    const wrap = document.getElementById("user-mgmt-table-wrap");
    if (!wrap) return;
    wrap.innerHTML = "<div class=\"loading\">Loading...</div>";
    const tabBtns = document.querySelectorAll("#user-mgmt-tabs .tab-btn");
    tabBtns.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === userMgmtActiveTab);
        btn.onclick = () => {
            userMgmtActiveTab = btn.dataset.tab;
            loadUserManagementPage();
        };
    });
    try {
        const data = await apiRequest("/admin/users");
        const allUsers = data.users || [];
        const supportAdmins = allUsers.filter((u) => u.role === "support_admin" || u.role === "super_admin");
        const employees = allUsers.filter((u) => u.role === "employee");
        const users = userMgmtActiveTab === "support_admins" ? supportAdmins : employees;
        const columns = userMgmtActiveTab === "support_admins"
            ? "<thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>"
            : "<thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>";
        if (users.length === 0) {
            wrap.innerHTML = `<p class="empty-state">No ${userMgmtActiveTab === "support_admins" ? "support admins" : "employees"} yet. Click "+ Add New User" to create one.</p>`;
            return;
        }
        wrap.innerHTML = `
            <table class="data-table">
                ${columns}
                <tbody>
                    ${users.map((u) => `
                        <tr>
                            <td>${escapeHtml(u.full_name || u.name || u.email || "")}</td>
                            <td>${escapeHtml(u.email || "")}</td>
                            <td><span class="badge ${u.role === "super_admin" ? "badge-warning" : u.role === "support_admin" ? "badge-info" : "badge-neutral"}">${u.role.replace("_", " ")}</span></td>
                            <td>${u.status === "disabled" ? "<span class=\"badge badge-danger\">Disabled</span>" : "Active"}</td>
                            <td>
                                ${u.uid !== currentUser?.uid && u.role !== "super_admin" ? `
                                    ${u.role === "support_admin" ? `<button type="button" class="btn btn-small btn-secondary user-reset-pwd" data-uid="${u.uid}">Reset Password</button>` : ""}
                                    ${u.status === "disabled" ? `<button type="button" class="btn btn-small btn-secondary user-enable" data-uid="${u.uid}">Enable</button>` : `<button type="button" class="btn btn-small btn-secondary user-disable" data-uid="${u.uid}">Disable</button>`}
                                    ${u.role === "support_admin" ? `<button type="button" class="btn btn-small btn-danger user-delete" data-uid="${u.uid}">Delete</button>` : ""}
                                ` : "-"}
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
        wrap.querySelectorAll(".user-reset-pwd").forEach((btn) => btn.addEventListener("click", () => resetSupportAdminPassword(btn.dataset.uid)));
        wrap.querySelectorAll(".user-disable").forEach((btn) => btn.addEventListener("click", () => disableSupportAdmin(btn.dataset.uid)));
        wrap.querySelectorAll(".user-enable").forEach((btn) => btn.addEventListener("click", () => enableSupportAdmin(btn.dataset.uid)));
        wrap.querySelectorAll(".user-delete").forEach((btn) => btn.addEventListener("click", () => deleteSupportAdmin(btn.dataset.uid)));
    } catch (e) {
        wrap.innerHTML = `<p class="error-message">${e.message || "Failed to load"}</p>`;
    }
}

function openAddUserModal() {
    document.getElementById("add-user-form").reset();
    document.getElementById("add-user-role").value = "support_admin";
    document.getElementById("add-user-modal").classList.add("active");
}

function closeAddUserModal() {
    document.getElementById("add-user-modal").classList.remove("active");
}

async function resetSupportAdminPassword(uid) {
    const newPassword = prompt("Enter new temporary password (min 6 characters):");
    if (!newPassword || newPassword.length < 6) return;
    try {
        await apiRequest("/admin/reset-support-admin-password", { method: "POST", body: JSON.stringify({ uid, new_password: newPassword }) });
        showSuccess("Password reset. User must change on next login.");
        loadUserManagementPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function disableSupportAdmin(uid) {
    if (!confirm("Disable this user?")) return;
    try {
        await apiRequest(`/admin/disable-support-admin/${uid}`, { method: "PUT" });
        showSuccess("User disabled.");
        loadUserManagementPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function enableSupportAdmin(uid) {
    try {
        await apiRequest(`/admin/enable-support-admin/${uid}`, { method: "PUT" });
        showSuccess("User enabled.");
        loadUserManagementPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function deleteSupportAdmin(uid) {
    if (!confirm("Permanently delete this user? This cannot be undone.")) return;
    try {
        await apiRequest(`/admin/support-admin/${uid}`, { method: "DELETE" });
        showSuccess("User deleted.");
        loadUserManagementPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function loadSettingsPage() {
    const content = document.getElementById("settings-content");
    if (!content) return;
    content.innerHTML = "<div class=\"loading\">Loading settings...</div>";
    try {
        let org = null;
        try { org = await apiRequest("/organization"); } catch (_) {}

        content.innerHTML = `
            <div class="card">
                <div class="card-header"><h2>Organization</h2></div>
                <div class="card-body">
                    ${org ? `
                        <p><strong>Name:</strong> ${escapeHtml(org.name || "")}</p>
                        <p><strong>Code:</strong> ${escapeHtml(org.organization_code || "")}</p>
                        <p><strong>Created:</strong> ${org.created_at ? new Date(org.created_at).toLocaleDateString() : "-"}</p>
                        <p><strong>Total members:</strong> ${org.total_members ?? "-"}</p>
                        <p><strong>Total tickets:</strong> ${org.total_tickets ?? "-"}</p>
                        <form id="update-org-form" class="form-inline" style="margin-top: 16px;">
                            <input type="text" id="settings-org-name" placeholder="Organization name" value="${escapeHtml(org.name || "")}">
                            <input type="text" id="settings-org-code" placeholder="Organization code" value="${escapeHtml(org.organization_code || "")}">
                            <button type="submit" class="btn btn-primary">Update</button>
                        </form>
                    ` : `
                        <p>No organization linked. Create one to manage your team.</p>
                        <form id="create-org-legacy-form" class="form-inline">
                            <input type="text" id="legacy-org-name" placeholder="Organization name" required>
                            <input type="text" id="legacy-org-code" placeholder="Organization code" required>
                            <button type="submit" class="btn btn-primary">Create organization</button>
                        </form>
                    `}
                </div>
            </div>
            <div class="card">
                <div class="card-header"><h2>Security</h2></div>
                <div class="card-body">
                    <form id="change-password-form">
                        <div class="form-group">
                            <label>Change your password</label>
                            <input type="password" id="current-password" placeholder="Current password" required>
                            <input type="password" id="new-password" placeholder="New password" required minlength="6">
                            <button type="submit" class="btn btn-primary">Update password</button>
                        </div>
                    </form>
                </div>
            </div>
        `;

        const updateOrgForm = content.querySelector("#update-org-form");
        if (updateOrgForm) updateOrgForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const name = content.querySelector("#settings-org-name")?.value?.trim();
            const code = content.querySelector("#settings-org-code")?.value?.trim();
            try {
                await apiRequest("/organization", { method: "PUT", body: JSON.stringify({ name: name || undefined, organization_code: code || undefined }) });
                showSuccess("Organization updated.");
                loadSettingsPage();
            } catch (err) { showError(err.message || "Failed"); }
        });
        const createOrgForm = content.querySelector("#create-org-legacy-form");
        if (createOrgForm) createOrgForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const name = content.querySelector("#legacy-org-name")?.value?.trim();
            const code = content.querySelector("#legacy-org-code")?.value?.trim();
            try {
                await apiRequest("/auth/create-org-for-legacy", { method: "POST", body: JSON.stringify({ organization_name: name, organization_code: code }) });
                showSuccess("Organization created.");
                loadSettingsPage();
            } catch (err) { showError(err.message || "Failed"); }
        });
        const changePwdForm = content.querySelector("#change-password-form");
        if (changePwdForm) changePwdForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const current = content.querySelector("#current-password")?.value;
            const newPwd = content.querySelector("#new-password")?.value;
            try {
                await apiRequest("/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: newPwd }) });
                showSuccess("Password updated.");
                changePwdForm.reset();
            } catch (err) { showError(err.message || "Failed"); }
        });
    } catch (e) {
        content.innerHTML = `<p class="error-message">${e.message || "Failed to load settings"}</p>`;
    }
}

// ─── Knowledge Improvement (Super Admin only) ─────────────────────────────────
async function loadKnowledgeAnalytics() {
    if (currentUser?.role !== "super_admin") return;
    try {
        const data = await apiRequest("/admin/knowledge-improvement/analytics");
        const widgetWrap = document.getElementById("dashboard-knowledge-widgets");
        if (widgetWrap) {
            widgetWrap.style.display = "";
            const recurringEl = document.getElementById("dashboard-recurring-issues");
            const suggestedEl = document.getElementById("dashboard-suggested-articles");
            if (recurringEl) recurringEl.textContent = String(data.recurring_issues_this_month ?? "—");
            if (suggestedEl) suggestedEl.textContent = String(data.suggested_articles_pending ?? "—");
        }
        const badge = document.getElementById("sidebar-ki-badge");
        if (badge) {
            const count = Number(data.suggested_articles_pending) || 0;
            badge.textContent = count > 99 ? "99+" : String(count);
            badge.style.display = count > 0 ? "inline-flex" : "none";
        }
    } catch (_) {
        const widgetWrap = document.getElementById("dashboard-knowledge-widgets");
        if (widgetWrap) widgetWrap.style.display = "none";
    }
}

async function loadKnowledgeImprovementPage() {
    const listView = document.getElementById("ki-list-view");
    const reviewView = document.getElementById("ki-review-view");
    if (listView) listView.style.display = "";
    if (reviewView) reviewView.style.display = "none";
    const runBtn = document.getElementById("ki-run-analysis-btn");
    const listDraft = document.getElementById("ki-list-draft");
    const listRejected = document.getElementById("ki-list-rejected");
    const listCovered = document.getElementById("ki-list-covered");
    const listApproved = document.getElementById("ki-list-approved");
    if (!listDraft) return;
    [listDraft, listRejected, listCovered, listApproved].forEach((el) => { if (el) el.innerHTML = "<div class=\"loading\">Loading...</div>"; });
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = "Running…"; }
    try {
        const [draftRes, rejectedRes, approvedRes, analyticsData] = await Promise.all([
            apiRequest("/admin/knowledge-improvement/suggestions?status=draft"),
            apiRequest("/admin/knowledge-improvement/suggestions?status=rejected"),
            apiRequest("/admin/knowledge-improvement/suggestions?status=approved"),
            apiRequest("/admin/knowledge-improvement/analytics").catch(() => ({})),
        ]);
        const drafts = draftRes.suggestions || [];
        const rejected = rejectedRes.suggestions || [];
        const approved = approvedRes.suggestions || [];
        const lastRunNew = analyticsData.last_run_new_drafts || [];
        const lastRunRejected = analyticsData.last_run_previously_rejected || [];
        const lastRunExisting = analyticsData.last_run_already_existing || [];
        const lastRunApproved = analyticsData.last_run_already_approved || [];

        const lastRun = analyticsData.last_analysis_run;
        const recurringDetected = analyticsData.recurring_issues_detected ?? 0;
        const lastEl = document.getElementById("ki-last-analysis");
        const recurEl = document.getElementById("ki-recurring-detected");
        if (lastEl) lastEl.textContent = lastRun ? formatLocalTime(lastRun) : "—";
        if (recurEl) recurEl.textContent = String(recurringDetected);

        function renderCard(s, showViewBtn = true, label = "View & Review") {
            const conf = s.confidence_score != null ? s.confidence_score : "—";
            const statusBadge = (s.status || "");
            const badgeClass = statusBadge === "draft" ? "badge-warning" : statusBadge === "approved" ? "badge-success" : "badge-neutral";
            return `
            <div class="kb-article-card" data-suggestion-id="${escapeHtml(s.id)}">
                <div class="kb-article-title">${escapeHtml(s.title || "Untitled")}</div>
                <div class="kb-article-meta" style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
                    <span class="badge badge-info">${s.ticket_count || 0} tickets</span>
                    ${conf !== "—" ? `<span class="badge badge-neutral">${conf}% confidence</span>` : ""}
                    ${statusBadge ? `<span class="badge ${badgeClass}">${statusBadge}</span>` : ""}
                    ${s.category ? `<span style="font-size: 12px; color: var(--text-tertiary);">${escapeHtml(s.category)}</span>` : ""}
                    ${s.created_at ? `<span style="font-size: 12px; color: var(--text-tertiary);">${formatLocalTime(s.created_at)}</span>` : ""}
                </div>
                <div class="kb-article-preview" style="margin-top: 8px; font-size: 13px; max-height: 60px; overflow: hidden; text-overflow: ellipsis;">
                    ${escapeHtml((s.content || "").slice(0, 150))}${(s.content || "").length > 150 ? "…" : ""}
                </div>
                ${showViewBtn ? `<div style="margin-top: 12px;"><button type="button" class="btn btn-small btn-primary view-suggestion-btn" data-id="${escapeHtml(s.id)}">${label}</button></div>` : ""}
            </div>`;
        }

        if (listDraft) {
            document.getElementById("ki-badge-draft").textContent = String(drafts.length);
            listDraft.innerHTML = drafts.length === 0
                ? "<p class=\"empty-state\">No draft suggestions. Run Analysis to generate from resolved tickets.</p>"
                : drafts.map((s) => renderCard(s, true, "View & Review")).join("");
        }
        if (listRejected) {
            document.getElementById("ki-badge-rejected").textContent = String(rejected.length);
            listRejected.innerHTML = rejected.length === 0
                ? "<p class=\"empty-state\">No rejected suggestions.</p>"
                : rejected.map((s) => renderCard(s, true, "View")).join("");
        }
        if (listCovered) {
            document.getElementById("ki-badge-covered").textContent = String(lastRunExisting.length);
            listCovered.innerHTML = lastRunExisting.length === 0
                ? "<p class=\"empty-state\">None from last run. Run Analysis to see topics already covered by KB.</p>"
                : lastRunExisting.map((item) => `
                <div class="kb-article-card">
                    <div class="kb-article-title">${escapeHtml(item.title || item.normalized_topic || "Topic")}</div>
                    <div class="kb-article-meta" style="margin-top: 8px;"><span class="badge badge-info">${item.ticket_count || 0} tickets</span></div>
                    <div style="margin-top: 8px;"><a href="#knowledge-base" data-kb-id="${escapeHtml(item.linked_kb_id || "")}">View existing article</a></div>
                </div>`).join("");
        }
        if (listApproved) {
            document.getElementById("ki-badge-approved").textContent = String(approved.length);
            listApproved.innerHTML = approved.length === 0
                ? "<p class=\"empty-state\">No approved suggestions yet.</p>"
                : approved.map((s) => renderCard(s, true, "View")).join("");
        }

        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = "Run Analysis";
            runBtn.onclick = runKnowledgeAnalysis;
        }
        listDraft.querySelectorAll(".view-suggestion-btn").forEach((btn) => {
            btn.addEventListener("click", () => { window.location.hash = `#knowledge-improvement/review/${btn.dataset.id}`; showPage("knowledge-improvement"); });
        });
        listRejected.querySelectorAll(".view-suggestion-btn").forEach((btn) => {
            btn.addEventListener("click", () => { window.location.hash = `#knowledge-improvement/review/${btn.dataset.id}`; showPage("knowledge-improvement"); });
        });
        listApproved.querySelectorAll(".view-suggestion-btn").forEach((btn) => {
            btn.addEventListener("click", () => { window.location.hash = `#knowledge-improvement/review/${btn.dataset.id}`; showPage("knowledge-improvement"); });
        });
    } catch (e) {
        if (listDraft) listDraft.innerHTML = `<p class="error-message">${e.message || "Failed to load"}</p>`;
        if (runBtn) { runBtn.disabled = false; runBtn.textContent = "Run Analysis"; runBtn.onclick = runKnowledgeAnalysis; }
    }
}

async function showSuggestionReviewPage(suggestionId) {
    const listView = document.getElementById("ki-list-view");
    const reviewView = document.getElementById("ki-review-view");
    const loadingEl = document.getElementById("ki-review-loading");
    const contentEl = document.getElementById("ki-review-content");
    const errorEl = document.getElementById("ki-review-error");
    if (listView) listView.style.display = "none";
    if (reviewView) reviewView.style.display = "";
    if (loadingEl) { loadingEl.style.display = ""; loadingEl.textContent = "Loading suggestion..."; }
    if (contentEl) contentEl.style.display = "none";
    if (errorEl) errorEl.style.display = "none";
    try {
        const s = await apiRequest(`/admin/knowledge-improvement/suggestions/${suggestionId}`);
        if (loadingEl) loadingEl.style.display = "none";
        if (contentEl) contentEl.style.display = "";
        document.getElementById("ki-review-title").textContent = s.title || "Untitled";
        const statusBadge = document.getElementById("ki-review-status-badge");
        if (statusBadge) {
            statusBadge.textContent = s.status || "draft";
            statusBadge.className = "badge " + ((s.status || "") === "draft" ? "badge-warning" : (s.status || "") === "approved" ? "badge-success" : "badge-neutral");
        }
        document.getElementById("ki-review-category").textContent = s.category || "—";
        document.getElementById("ki-review-ticket-count").textContent = s.ticket_count || s.related_tickets?.length || 0;
        document.getElementById("ki-review-confidence").textContent = s.confidence_score != null ? s.confidence_score : "—";
        const decisionWrap = document.getElementById("ki-review-decision-reason-wrap");
        const decisionEl = document.getElementById("ki-review-decision-reason");
        const linkedWrap = document.getElementById("ki-review-linked-kb-wrap");
        const linkedLink = document.getElementById("ki-review-linked-kb-link");
        if (decisionWrap && decisionEl) {
            if ((s.status || "") === "rejected" && s.decision_reason) {
                decisionWrap.style.display = "";
                decisionEl.textContent = s.decision_reason;
            } else {
                decisionWrap.style.display = "none";
            }
        }
        if (linkedWrap && linkedLink) {
            const kbId = s.linked_kb_id || s.published_article_id;
            if ((s.status || "") === "approved" && kbId) {
                linkedWrap.style.display = "";
                linkedLink.href = "#knowledge-base";
                linkedLink.textContent = "View published article";
                linkedLink.onclick = (e) => { e.preventDefault(); window.location.hash = "#knowledge-base"; showPage("knowledge-base"); };
            } else {
                linkedWrap.style.display = "none";
            }
        }
        document.getElementById("ki-review-content-body").textContent = s.content || "";
        document.getElementById("ki-edit-title").value = s.title || "";
        document.getElementById("ki-edit-category").value = s.category || "";
        document.getElementById("ki-edit-content").value = s.content || "";
        const tickets = s.related_tickets || [];
        const ticketsList = document.getElementById("ki-review-tickets-list");
        if (ticketsList) {
            if (tickets.length === 0) {
                ticketsList.innerHTML = "<p class=\"empty-state\">No related ticket details available.</p>";
            } else {
                ticketsList.innerHTML = tickets.map((t) => `
                    <div class="ticket-card" style="margin-bottom: 16px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius);">
                        <div style="font-weight: 600;">Ticket ${escapeHtml(t.ticket_id || "")}</div>
                        <div style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">${t.created_at ? formatLocalTime(t.created_at) : ""} · ${escapeHtml(t.status || "")}</div>
                        <div style="margin-top: 8px;"><strong>Title:</strong> ${escapeHtml((t.title || "").slice(0, 200))}</div>
                        <div style="margin-top: 4px; font-size: 13px;"><strong>Description:</strong> ${escapeHtml((t.description || "").slice(0, 500))}${(t.description || "").length > 500 ? "…" : ""}</div>
                        ${t.resolution ? `<div style="margin-top: 8px; font-size: 13px; padding: 8px; background: var(--bg-secondary); border-radius: var(--radius);"><strong>Resolution:</strong><br>${escapeHtml((t.resolution || "").slice(0, 1000))}${(t.resolution || "").length > 1000 ? "…" : ""}</div>` : ""}
                    </div>
                `).join("");
            }
        }
        const isDraft = (s.status || "") === "draft";
        document.getElementById("ki-approve-btn").style.display = isDraft ? "" : "none";
        document.getElementById("ki-reject-btn").style.display = isDraft ? "" : "none";
        document.getElementById("ki-edit-draft-btn").style.display = isDraft ? "" : "none";
        document.getElementById("ki-edit-actions").style.display = "none";
        document.getElementById("ki-review-view-mode").style.display = "";
        document.getElementById("ki-review-edit-mode").style.display = "none";
        document.getElementById("ki-approve-btn").onclick = () => approveKnowledgeSuggestion(s.id);
        document.getElementById("ki-reject-btn").onclick = () => rejectKnowledgeSuggestion(s.id);
        document.getElementById("ki-edit-draft-btn").onclick = () => {
            document.getElementById("ki-review-view-mode").style.display = "none";
            document.getElementById("ki-review-edit-mode").style.display = "";
            document.getElementById("ki-approve-btn").style.display = "none";
            document.getElementById("ki-reject-btn").style.display = "none";
            document.getElementById("ki-edit-draft-btn").style.display = "none";
            document.getElementById("ki-edit-actions").style.display = "";
        };
        document.getElementById("ki-cancel-edit-btn").onclick = () => {
            document.getElementById("ki-review-view-mode").style.display = "";
            document.getElementById("ki-review-edit-mode").style.display = "none";
            document.getElementById("ki-approve-btn").style.display = "";
            document.getElementById("ki-reject-btn").style.display = "";
            document.getElementById("ki-edit-draft-btn").style.display = "";
            document.getElementById("ki-edit-actions").style.display = "none";
        };
        document.getElementById("ki-save-draft-btn").onclick = () => saveDraftSuggestion(s.id);
    } catch (e) {
        if (loadingEl) loadingEl.style.display = "none";
        if (errorEl) {
            errorEl.textContent = e.message || "Failed to load suggestion";
            errorEl.style.display = "";
        }
    }
}

async function saveDraftSuggestion(id) {
    const title = document.getElementById("ki-edit-title")?.value?.trim();
    const category = document.getElementById("ki-edit-category")?.value?.trim() || undefined;
    const content = document.getElementById("ki-edit-content")?.value ?? "";
    if (!title) { showError("Title is required"); return; }
    try {
        await apiRequest(`/admin/knowledge-improvement/suggestions/${id}`, {
            method: "PUT",
            body: JSON.stringify({ title, category, content }),
        });
        showSuccess("Draft saved.");
        document.getElementById("ki-review-content-body").textContent = content;
        document.getElementById("ki-review-view-mode").style.display = "";
        document.getElementById("ki-review-edit-mode").style.display = "none";
        document.getElementById("ki-approve-btn").style.display = "";
        document.getElementById("ki-reject-btn").style.display = "";
        document.getElementById("ki-edit-draft-btn").style.display = "";
        document.getElementById("ki-edit-actions").style.display = "none";
        document.getElementById("ki-review-title").textContent = title;
    } catch (e) { showError(e.message || "Save failed"); }
}

async function runKnowledgeAnalysis() {
    const runBtn = document.getElementById("ki-run-analysis-btn");
    if (runBtn) runBtn.disabled = true;
    try {
        const data = await apiRequest("/admin/knowledge-improvement/run", { method: "POST" });
        showSuccess(data.message || "Analysis complete.");
        loadKnowledgeImprovementPage();
        if (currentUser?.role === "super_admin") loadKnowledgeAnalytics();
    } catch (e) {
        showError(e.message || "Analysis failed.");
    } finally {
        if (runBtn) runBtn.disabled = false;
    }
}

async function approveKnowledgeSuggestion(id) {
    try {
        const data = await apiRequest(`/admin/knowledge-improvement/suggestions/${id}/approve`, { method: "POST" });
        showSuccess(data.message || "Article published.");
        window.location.hash = "#knowledge-improvement";
        loadKnowledgeImprovementPage();
        if (currentUser?.role === "super_admin") loadKnowledgeAnalytics();
    } catch (e) { showError(e.message || "Approve failed"); }
}

async function rejectKnowledgeSuggestion(id) {
    if (!confirm("Reject this suggestion? It will not be published.")) return;
    const reason = prompt("Optional: Reason for rejection (stored for decision-aware dedup):");
    const body = reason && reason.trim() ? { decision_reason: reason.trim() } : {};
    try {
        await apiRequest(`/admin/knowledge-improvement/suggestions/${id}/reject`, { method: "POST", body: JSON.stringify(body) });
        showSuccess("Suggestion rejected.");
        window.location.hash = "#knowledge-improvement";
        loadKnowledgeImprovementPage();
        if (currentUser?.role === "super_admin") loadKnowledgeAnalytics();
    } catch (e) { showError(e.message || "Reject failed"); }
}

// Check authentication and init sidebar + routing
(async function initAuth() {
    if (!isAuthenticated()) {
        window.location.href = "login.html";
        return;
    }
    try {
        const userData = await apiRequest("/auth/me");
        const adminRoles = ["admin", "super_admin", "support_admin"];
        if (!adminRoles.includes(userData.role || "")) {
            alert("Access denied. Administrator privileges required.");
            window.location.href = "submit-ticket.html";
            return;
        }
        currentUser = userData;
        if (userData.must_change_password) {
            window.location.href = "change-password.html";
            return;
        }

        fetchUnreadCount();
        window._adminUnreadPoll = setInterval(() => {
            fetchUnreadCount();
            if (userData.role === "super_admin") loadKnowledgeAnalytics();
        }, 10000);

        const sidebarEl = document.getElementById("admin-sidebar");
        if (sidebarEl) {
            renderSidebar(sidebarEl, {
                currentUser: userData,
                onLogout: () => { clearToken(); window.location.href = "login.html"; },
                onOpenMessages: () => openMessagesModal(),
            });
        }
        if (userData.role === "super_admin") loadKnowledgeAnalytics();

        const mobileMenu = document.getElementById("admin-mobile-menu");
        const overlay = document.getElementById("admin-overlay");
        const adminApp = document.getElementById("admin-app");
        function closeSidebar() {
            sidebarEl?.classList.remove("sidebar-open");
            adminApp?.classList.remove("sidebar-open");
            overlay?.classList.remove("visible");
            overlay?.setAttribute("aria-hidden", "true");
            document.body.classList.remove("sidebar-open");
        }
        function openSidebar() {
            sidebarEl?.classList.add("sidebar-open");
            adminApp?.classList.add("sidebar-open");
            overlay?.classList.add("visible");
            overlay?.setAttribute("aria-hidden", "false");
            document.body.classList.add("sidebar-open");
        }
        function toggleSidebar() {
            if (sidebarEl?.classList.contains("sidebar-open")) closeSidebar();
            else openSidebar();
        }
        if (mobileMenu && sidebarEl) {
            mobileMenu.addEventListener("click", () => {
                toggleSidebar();
                const open = sidebarEl.classList.contains("sidebar-open");
                mobileMenu.setAttribute("aria-expanded", String(open));
            });
            overlay?.addEventListener("click", closeSidebar);
            closeSidebar();
        }
        sidebarEl?.addEventListener("click", (e) => {
            if (e.target.closest(".sidebar-link") && window.innerWidth < 992) closeSidebar();
        });
        window.addEventListener("hashchange", closeSidebar);

        const hash = (window.location.hash || "#dashboard").replace("#", "") || "dashboard";
        const pagePart = hash.split("/")[0];
        const subPart = hash.split("/")[1];
        if (pagePart === "knowledge-base" && subPart === "add") {
            window.location.hash = "knowledge-base";
            showPage("knowledge-base");
            if (currentUser?.role === "super_admin") setTimeout(openAddArticleModal, 100);
        } else {
            showPage(pagePart);
        }
        window.addEventListener("hashchange", () => {
            const h = (window.location.hash || "#dashboard").replace("#", "") || "dashboard";
            const p = h.split("/")[0];
            const sub = h.split("/")[1];
            if (p === "knowledge-base" && sub === "add") {
                history.replaceState(null, "", "#knowledge-base");
                showPage("knowledge-base");
                if (currentUser?.role === "super_admin") setTimeout(openAddArticleModal, 100);
                return;
            }
            showPage(p);
        });

        loadKnowledgeBase();
    } catch (err) {
        console.error("Error loading user data:", err);
        showError("Failed to load user data");
        clearToken();
        window.location.href = "login.html";
    }
})();

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', () => {
    // Dashboard stat cards: navigate to tickets with filter
    document.querySelectorAll('.stat-card[data-filter]').forEach(card => {
        card.addEventListener('click', () => {
            const filter = card.dataset.filter;
            window.location.hash = 'tickets';
            window.currentTicketFilter = filter;
            const statusFilter = document.getElementById('status-filter');
            if (statusFilter) statusFilter.value = filter;
            showPage('tickets');
        });
    });
    // Tickets page filters
    const statusGroupFilter = document.getElementById('status-group-filter');
    const assignedToFilter = document.getElementById('assigned-to-filter');
    const ticketsSearch = document.getElementById('tickets-search');
    [statusGroupFilter, assignedToFilter, ticketsSearch].forEach(el => {
        if (el) el.addEventListener('change', () => loadAllTickets());
    });
    if (ticketsSearch) ticketsSearch.addEventListener('input', () => { clearTimeout(window._searchTickets); window._searchTickets = setTimeout(loadAllTickets, 300); });
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) statusFilter.addEventListener('change', () => loadAllTickets());

    // Single body delegation: modal close, overlay click, and article View/Delete (no inline handlers)
    document.body.addEventListener('click', (e) => {
        // 1) Modal close: X button or footer "Close" with .modal-close-btn
        if (e.target.closest('.modal-close-btn')) {
            const btn = e.target.closest('.modal-close-btn');
            const overlay = (btn.dataset.modal && document.getElementById(btn.dataset.modal))
                ? document.getElementById(btn.dataset.modal)
                : btn.closest('.modal-overlay');
            if (overlay) closeModal(overlay);
            e.preventDefault();
            return;
        }
        // 2) Click on overlay backdrop (the dark overlay div)
        if (e.target.classList.contains('modal-overlay')) {
            closeModal(e.target);
            return;
        }
        // 3) Article "View" or "Edit" button
        const viewBtn = e.target.closest('.view-article-btn');
        if (viewBtn && viewBtn.dataset.articleId) {
            e.preventDefault();
            openArticleViewModal(viewBtn.dataset.articleId);
            return;
        }
        const editBtn = e.target.closest('.edit-article-btn');
        if (editBtn && editBtn.dataset.articleId) {
            e.preventDefault();
            openArticleViewModal(editBtn.dataset.articleId);
            return;
        }
        // 4) Article "Delete" button
        const delBtn = e.target.closest('.delete-article-btn');
        if (delBtn && delBtn.dataset.articleId) {
            e.preventDefault();
            deleteArticle(delBtn.dataset.articleId);
            return;
        }
        // 5) Article card (clicking card body, not a button)
        const card = e.target.closest('.article-card');
        if (card && card.dataset.articleId && !e.target.closest('button')) {
            openArticleViewModal(card.dataset.articleId);
            return;
        }
    });

    // Stat cards: filter tickets by click (no inline onclick)
    document.querySelectorAll('.stat-card[data-filter]').forEach(card => {
        card.addEventListener('click', () => {
            const filter = card.dataset.filter;
            if (filter) filterTicketsByStat(filter);
        });
    });
    
    // Article modal: Edit / Cancel / Save (not close — close uses body delegation)
    document.getElementById('article-edit-btn')?.addEventListener('click', switchToEditMode);
    document.getElementById('article-cancel-edit-btn')?.addEventListener('click', cancelEditMode);
    document.getElementById('article-save-edit-btn')?.addEventListener('click', saveArticleEdit);
    
    // Ticket lists: click anywhere on row navigates to ticket detail page (same as employee)
    document.getElementById('all-tickets-list')?.addEventListener('click', (e) => {
        const row = e.target.closest('tr[data-ticket-id], .ticket-card[data-ticket-id], .ticket-list-row[data-ticket-id]');
        if (row && row.dataset.ticketId) {
            e.preventDefault();
            e.stopPropagation();
            window.location.href = 'ticket-detail.html?id=' + encodeURIComponent(row.dataset.ticketId);
        }
    });
    document.getElementById('escalated-tickets-list')?.addEventListener('click', (e) => {
        const row = e.target.closest('tr[data-ticket-id], .ticket-card[data-ticket-id]');
        if (row && row.dataset.ticketId) {
            e.preventDefault();
            e.stopPropagation();
            window.location.href = 'ticket-detail.html?id=' + encodeURIComponent(row.dataset.ticketId);
        }
    });
    document.getElementById('messages-tickets-list')?.addEventListener('click', (e) => {
        const row = e.target.closest('tr[data-ticket-id], .ticket-card[data-ticket-id]');
        if (row && row.dataset.ticketId) {
            e.preventDefault();
            e.stopPropagation();
            closeMessagesModal();
            window.location.href = 'ticket-detail.html?id=' + encodeURIComponent(row.dataset.ticketId);
        }
    });
    
    // Logout handler
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            clearToken();
            window.location.href = "login.html";
        });
    }
    
    // Ticket chat is on unified ticket-detail.html (no modal form here)
    // Modal "click outside" is handled by body delegation (e.target.classList.contains('modal-overlay'))
});

// Add Article modal: open, close, save (Super Admin only)
function openAddArticleModal() {
    const modal = document.getElementById('add-article-modal');
    if (!modal) return;
    document.getElementById('add-article-title').value = '';
    document.getElementById('add-article-category').value = '';
    document.getElementById('add-article-content').value = '';
    modal.classList.add('active');
}

function closeAddArticleModal() {
    const modal = document.getElementById('add-article-modal');
    if (modal) modal.classList.remove('active');
}

document.getElementById('add-article-save-btn')?.addEventListener('click', async () => {
    const title = document.getElementById('add-article-title')?.value?.trim();
    const category = document.getElementById('add-article-category')?.value?.trim();
    const content = document.getElementById('add-article-content')?.value?.trim();
    if (!title || !content) {
        showError('Title and content are required');
        return;
    }
    try {
        await apiRequest('/knowledge-base', {
            method: 'POST',
            body: JSON.stringify({ title, content, category: category || undefined })
        });
        showSuccess('Article saved successfully!');
        closeAddArticleModal();
        loadKnowledgeBase();
    } catch (error) {
        showError(error.message || 'Failed to save article');
    }
});

document.getElementById('kb-add-new-btn')?.addEventListener('click', openAddArticleModal);

// User Management: Add New User button and modal submit (super_admin only)
document.getElementById('user-mgmt-add-btn')?.addEventListener('click', openAddUserModal);
document.getElementById('add-user-save-btn')?.addEventListener('click', async () => {
    const fullName = document.getElementById('add-user-full-name')?.value?.trim();
    const email = document.getElementById('add-user-email')?.value?.trim();
    const password = document.getElementById('add-user-password')?.value;
    const role = document.getElementById('add-user-role')?.value;
    if (!fullName || !email || !password || password.length < 6) {
        showError('Full name, email, and password (min 6 characters) are required.');
        return;
    }
    const btn = document.getElementById('add-user-save-btn');
    if (btn) btn.disabled = true;
    try {
        if (role === 'support_admin') {
            await apiRequest('/admin/create-support-admin', {
                method: 'POST',
                body: JSON.stringify({ full_name: fullName, email, temporary_password: password })
            });
            showSuccess('Support admin created. They must change password on first login.');
        } else {
            await apiRequest('/admin/create-employee', {
                method: 'POST',
                body: JSON.stringify({ full_name: fullName, email, temporary_password: password })
            });
            showSuccess('Employee created.');
        }
        closeAddUserModal();
        loadUserManagementPage();
    } catch (err) {
        showError(err.message || 'Failed to create user');
    } finally {
        if (btn) btn.disabled = false;
    }
});

// Store loaded articles for event delegation (View/Delete by data-article-id)
let currentArticles = [];

/**
 * Load knowledge base articles
 */
async function loadKnowledgeBase() {
    const articlesList = document.getElementById('articles-list');
    articlesList.innerHTML = '<p class="loading">Loading articles...</p>';
    
    try {
        const data = await apiRequest('/knowledge-base');
        const articles = data.articles || [];
        currentArticles = articles;
        
        // Update count badge
        const kbCount = document.getElementById('kb-count');
        if (kbCount) {
            kbCount.textContent = articles.length;
            kbCount.style.display = articles.length > 0 ? 'inline-flex' : 'none';
        }
        
        if (articles.length === 0) {
            articlesList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📚</div>
                    <p>No knowledge base articles yet.</p>
                    <p style="margin-top: 8px; font-size: 13px;">${currentUser?.role === 'super_admin' ? 'Click "+ Add New Article" to create one.' : ''}</p>
                </div>
            `;
            return;
        }

        const isSuperAdmin = currentUser?.role === 'super_admin';
        articlesList.innerHTML = articles.map(article => {
            const category = article.category ? `<span class="kb-card-category">${escapeHtml(article.category)}</span>` : '';
            const author = article.created_by_name ? escapeHtml(article.created_by_name) : '—';
            const created = article.createdAt ? new Date(article.createdAt).toLocaleDateString() : '—';
            const preview = (article.content || '').length > 200 ? article.content.substring(0, 200) + '...' : (article.content || '');
            const actions = isSuperAdmin
                ? `<button type="button" class="btn btn-primary view-article-btn" data-article-id="${article.id}">View</button>
                   <button type="button" class="btn btn-secondary edit-article-btn" data-article-id="${article.id}">Edit</button>
                   <button type="button" class="btn btn-danger delete-article-btn" data-article-id="${article.id}">Delete</button>`
                : `<button type="button" class="btn btn-primary view-article-btn" data-article-id="${article.id}">View</button>`;
            return `
            <div class="article-card kb-article-card" data-article-id="${article.id}">
                <div class="kb-card-header">
                    <h3 class="kb-card-title">${escapeHtml(article.title)}</h3>
                    ${category}
                </div>
                <p class="kb-card-preview">${escapeHtml(preview)}</p>
                <div class="kb-card-meta">
                    <span>Created: ${created}</span>
                    <span>Author: ${author}</span>
                </div>
                <div class="kb-card-actions">${actions}</div>
            </div>
            `;
        }).join('');
        
    } catch (error) {
        articlesList.innerHTML = `<p class="error-message">Error loading articles: ${error.message}</p>`;
    }
}

/**
 * Delete knowledge base article
 */
async function deleteArticle(articleId) {
    if (!confirm('Are you sure you want to delete this article?')) {
        return;
    }
    
    try {
        await apiRequest(`/knowledge-base/${articleId}`, {
            method: 'DELETE'
        });
        
        showSuccess('Article deleted successfully!');
        loadKnowledgeBase();
        
    } catch (error) {
        showError(`Failed to delete article: ${error.message}`);
    }
}

/**
 * Load escalated tickets
 */
async function loadEscalatedTickets() {
    const ticketsList = document.getElementById('escalated-tickets-list');
    if (!ticketsList) return;
    ticketsList.innerHTML = '<p class="loading">Loading tickets...</p>';
    
    try {
        const data = await apiRequest('/tickets/escalated');
        let tickets = data.tickets || [];
        
        // Calculate unread counts (admin sees unread user messages)
        let totalUnread = 0;
        tickets.forEach(ticket => {
            const messages = ticket.messages || [];
            const unreadCount = messages.filter(msg => 
                msg.sender === 'user' && !msg.isRead
            ).length;
            ticket.unreadCount = unreadCount;
            totalUnread += unreadCount;
        });
        
        // Update unread badge
        const unreadBadge = document.getElementById('escalated-unread');
        if (unreadBadge) {
            if (totalUnread > 0) {
                unreadBadge.textContent = totalUnread > 99 ? '99+' : totalUnread;
                unreadBadge.style.display = 'inline-flex';
            } else {
                unreadBadge.style.display = 'none';
            }
        }
        
        // Update header unread badge (aggregate from all tickets)
        // Note: This is a simplified version - ideally we'd aggregate from all tickets
        // For now, we'll update it when all tickets are loaded
        
        // Update count badges
        const escalatedCount = document.getElementById('escalated-count');
        const escalatedBadge = document.getElementById('escalated-badge');
        if (escalatedCount) {
            escalatedCount.textContent = tickets.length;
            escalatedCount.style.display = tickets.length > 0 ? 'inline-flex' : 'none';
        }
        if (escalatedBadge) {
            escalatedBadge.textContent = `${tickets.length} Pending`;
            escalatedBadge.style.display = tickets.length > 0 ? 'inline-flex' : 'none';
        }
        
        if (tickets.length === 0) {
            ticketsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">✅</div>
                    <p>No escalated tickets.</p>
                    <p style="margin-top: 8px; font-size: 13px;">All tickets have been resolved automatically!</p>
                </div>
            `;
            return;
        }
        
        // Sort tickets: unread first, then by creation date (newest first)
        tickets.sort((a, b) => {
            if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
            if (a.unreadCount === 0 && b.unreadCount > 0) return 1;
            return new Date(b.createdAt) - new Date(a.createdAt);
        });
        
        ticketsList.innerHTML = tickets.map(ticket => {
            const unreadCount = ticket.unreadCount || 0;
            const statusClass = ticket.status === 'closed' || ticket.status === 'resolved' || ticket.status === 'auto_resolved' ? 'badge-success' : 
                               ticket.status === 'ai_responded' || ticket.status === 'in_progress' || ticket.status === 'awaiting_confirmation' ? 'badge-info' :
                               ticket.status === 'escalated' ? 'badge-warning' : 'badge-neutral';
            
            return `
            <div class="ticket-card status-${ticket.status}" data-ticket-id="${ticket.id}">
                <div class="ticket-header">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div class="ticket-id">Ticket #${ticket.id.substring(0, 8)}</div>
                            ${unreadCount > 0 ? `<span class="notification-badge">${unreadCount > 99 ? '99+' : unreadCount}</span>` : ''}
                        </div>
                        <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
                            <span class="badge ${statusClass}">${ticket.status.replace('_', ' ').toUpperCase()}</span>
                            ${ticket.category ? `<span class="badge badge-neutral">${ticket.category}</span>` : ''}
                        </div>
                    </div>
                </div>
                ${ticket.summary ? `<div class="ticket-summary">${escapeHtml(ticket.summary)}</div>` : ''}
                <div class="ticket-message">
                    <strong>Customer Message:</strong><br>
                    ${escapeHtml(ticket.message.length > 150 ? ticket.message.substring(0, 150) + '...' : ticket.message)}
                </div>
                <div class="ticket-meta">
                    <div class="ticket-meta-item">
                        <span>📅</span>
                        <span>${formatLocalTime(ticket.createdAt)}</span>
                    </div>
                </div>
            </div>
        `;
        }).join('');
        
    } catch (error) {
        ticketsList.innerHTML = `<p class="error-message">Error loading tickets: ${error.message}</p>`;
    }
}

/**
 * Utility functions
 */
function showError(message) {
    const errorDiv = document.getElementById('error-message');
    errorDiv.textContent = message;
    errorDiv.style.display = 'flex';
    setTimeout(() => {
        errorDiv.style.display = 'none';
    }, 5000);
}

function showSuccess(message) {
    const successDiv = document.getElementById('success-message');
    successDiv.textContent = message;
    successDiv.style.display = 'flex';
    setTimeout(() => {
        successDiv.style.display = 'none';
    }, 3000);
}

/**
 * Load all tickets (admin view). Uses status_group, assigned_to, search and status filter.
 */
async function loadAllTickets() {
    const ticketsList = document.getElementById('all-tickets-list');
    if (!ticketsList) return;

    const statusGroup = document.getElementById('status-group-filter')?.value || '';
    const assignedTo = (currentUser?.role === 'super_admin' ? document.getElementById('assigned-to-filter')?.value : null) || '';
    const search = document.getElementById('tickets-search')?.value?.trim() || '';
    const statusFilter = document.getElementById('status-filter')?.value || 'all';
    const params = new URLSearchParams();
    if (statusGroup) params.set('status_group', statusGroup);
    if (assignedTo) params.set('assigned_to', assignedTo);
    if (search) params.set('search', search);
    const qs = params.toString();
    const url = '/tickets' + (qs ? '?' + qs : '');

    ticketsList.innerHTML = '<div class="loading">Loading tickets...</div>';

    try {
        const data = await apiRequest(url);
        let tickets = data.tickets || [];
        
        // Calculate unread counts (admin sees unread user messages) and statistics
        let totalUnread = 0;
        let stats = {
            total: tickets.length,
            resolved: 0,
            escalated: 0,
            in_progress: 0
        };
        
        tickets.forEach(ticket => {
            const messages = ticket.messages || [];
            const unreadCount = messages.filter(msg => 
                msg.sender === 'user' && !msg.isRead
            ).length;
            ticket.unreadCount = unreadCount;
            totalUnread += unreadCount;
            
            // Count by status and escalation
            // Escalation is independent of status - a ticket can be both escalated and in_progress
            if (ticket.status === 'closed' || ticket.status === 'resolved' || ticket.status === 'auto_resolved') {
                stats.resolved++;
            }
            // Count escalated tickets (using escalated field, not status)
            if (ticket.escalated === true) {
                stats.escalated++;
            }
            // Count in-progress tickets
            if (ticket.status === 'in_progress') {
                stats.in_progress++;
            }
        });
        
        // Update statistics cards
        updateStatistics(stats);
        
        // Update unread badge
        const unreadBadge = document.getElementById('all-tickets-unread');
        if (unreadBadge) {
            if (totalUnread > 0) {
                unreadBadge.textContent = totalUnread > 99 ? '99+' : totalUnread;
                unreadBadge.style.display = 'inline-flex';
            } else {
                unreadBadge.style.display = 'none';
            }
        }
        
        // Store tickets for filtering
        window.allTickets = tickets;
        
        // Set default filter to 'all' if not set
        if (!window.currentTicketFilter) {
            window.currentTicketFilter = 'all';
            document.querySelector('.stat-card[data-filter="all"]')?.classList.add('active');
        }
        
        // Apply status filter (from dropdown)
        const statusFilterVal = document.getElementById('status-filter')?.value || window.currentTicketFilter || 'all';
        if (statusFilterVal !== 'all') {
            if (statusFilterVal === 'resolved') {
                tickets = tickets.filter(t => t.status === 'closed' || t.status === 'resolved' || t.status === 'auto_resolved');
            } else if (statusFilterVal === 'escalated') {
                tickets = tickets.filter(t => t.escalated === true);
            } else {
                tickets = tickets.filter(t => t.status === statusFilterVal);
            }
        }

        const listTitle = document.getElementById('tickets-list-title');
        if (listTitle) listTitle.textContent = statusFilterVal === 'all' ? 'All Tickets' : `All Tickets - ${statusFilterVal.replace('_', ' ').toUpperCase()}`;

        if (tickets.length === 0) {
            ticketsList.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📝</div><p>No tickets found.</p></div>`;
            return;
        }
        
        // Sort tickets: unread first, then by creation date (newest first)
        tickets.sort((a, b) => {
            if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
            if (a.unreadCount === 0 && b.unreadCount > 0) return 1;
            return new Date(b.createdAt) - new Date(a.createdAt);
        });
        
        const statusBadgeClass = (t) => {
            if (t.escalated === true) return "admin-ticket-status-escalated";
            if (t.status === "closed" || t.status === "resolved" || t.status === "auto_resolved") return "admin-ticket-status-closed";
            if (t.status === "in_progress" || t.status === "awaiting_confirmation") return "admin-ticket-status-in-progress";
            return "admin-ticket-status-open";
        };
        const statusLabel = (t) => {
            if (t.escalated === true) return "Escalated";
            return (t.status || "Open").replace(/_/g, " ");
        };
        const lastUpdated = (t) => {
            const msgs = t.messages || [];
            if (msgs.length > 0) {
                const last = msgs[msgs.length - 1];
                const ts = last.createdAt || last.created_at;
                if (ts) return formatLocalTime(ts);
            }
            return t.updatedAt ? formatLocalTime(t.updatedAt) : formatLocalTime(t.createdAt);
        };
        ticketsList.innerHTML = `
            <div class="admin-tickets-table-wrap">
                <table class="admin-tickets-table">
                    <thead>
                        <tr>
                            <th>Ticket Title</th>
                            <th>Status</th>
                            <th>Created</th>
                            <th>Last Updated</th>
                            <th>Assigned Admin</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${tickets.map(ticket => {
                            const unreadCount = ticket.unreadCount || 0;
                            const title = (ticket.summary || ticket.message || "No subject").trim();
                            const titleShort = title.length > 60 ? title.substring(0, 60) + "…" : title;
                            const assignedName = ticket.assigned_to_name || (ticket.assigned_to ? "Assigned" : "—");
                            return `
                            <tr class="ticket-list-row ticket-card admin-ticket-row" data-ticket-id="${ticket.id}" role="button" tabindex="0">
                                <td>
                                    <a href="ticket-detail.html?id=${encodeURIComponent(ticket.id)}" class="admin-ticket-link">${escapeHtml(titleShort)}</a>
                                    ${unreadCount > 0 ? `<span class="ticket-row-unread">${unreadCount > 99 ? "99+" : unreadCount}</span>` : ""}
                                </td>
                                <td><span class="admin-ticket-badge ${statusBadgeClass(ticket)}">${statusLabel(ticket)}</span></td>
                                <td>${formatLocalTime(ticket.createdAt)}</td>
                                <td>${lastUpdated(ticket)}</td>
                                <td>${escapeHtml(assignedName)}</td>
                            </tr>`;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        `;
        
    } catch (error) {
        ticketsList.innerHTML = `<p class="error-message">Error loading tickets: ${error.message}</p>`;
    }
}

// Status filter handler (moved inside DOMContentLoaded in the wrapper above)

/**
 * Update statistics cards
 */
function updateStatistics(stats) {
    const statTotal = document.getElementById('stat-total');
    if (statTotal) {
        statTotal.setAttribute('data-value', stats.total);
        statTotal.textContent = stats.total;
    }
    const statResolved = document.getElementById('stat-resolved');
    if (statResolved) {
        statResolved.setAttribute('data-value', stats.resolved);
        statResolved.textContent = stats.resolved;
    }
    const statEscalated = document.getElementById('stat-escalated');
    if (statEscalated) {
        statEscalated.setAttribute('data-value', stats.escalated);
        statEscalated.textContent = stats.escalated;
    }
    const statInProgress = document.getElementById('stat-in-progress');
    if (statInProgress) {
        statInProgress.setAttribute('data-value', stats.in_progress);
        statInProgress.textContent = stats.in_progress;
    }
}

let dashboardPieChart = null;
let dashboardBarChart = null;

function updateDashboardCharts(tickets) {
    const ChartLib = typeof window !== "undefined" && window.Chart;
    if (!ChartLib) return;

    const resolved = tickets.filter((t) => t.status === "closed" || t.status === "resolved" || t.status === "auto_resolved").length;
    const inProgress = tickets.filter((t) => t.status === "in_progress").length;
    const escalated = tickets.filter((t) => t.escalated === true).length;
    const open = tickets.filter((t) => {
        const s = (t.status || "").toLowerCase();
        const isResolved = s === "closed" || s === "resolved" || s === "auto_resolved";
        const isInProgress = s === "in_progress";
        return !isResolved && !isInProgress && !t.escalated;
    }).length;

    const pieCtx = document.getElementById("dashboard-pie-chart");
    if (pieCtx) {
        if (dashboardPieChart) {
            dashboardPieChart.destroy();
            dashboardPieChart = null;
        }
        dashboardPieChart = new ChartLib(pieCtx, {
            type: "doughnut",
            data: {
                labels: ["Resolved", "In Progress", "Escalated", "Open"],
                datasets: [{
                    data: [resolved, inProgress, escalated, open],
                    backgroundColor: ["#5a8f6a", "#c4956a", "#a65d5d", "#b87333"],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { color: "#c4c7cc" },
                    },
                },
            },
        });
    }

    const barCtx = document.getElementById("dashboard-bar-chart");
    if (barCtx) {
        const now = new Date();
        const days = [];
        const counts = [];
        for (let i = 6; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            d.setHours(0, 0, 0, 0);
            days.push(d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }));
            const dayStart = d.getTime();
            const dayEnd = dayStart + 24 * 60 * 60 * 1000;
            const count = tickets.filter((t) => {
                const created = t.created_at || t.createdAt || t.created;
                if (!created) return false;
                const ts = typeof created === "number" ? created : new Date(created).getTime();
                return ts >= dayStart && ts < dayEnd;
            }).length;
            counts.push(count);
        }
        if (dashboardBarChart) {
            dashboardBarChart.destroy();
            dashboardBarChart = null;
        }
        dashboardBarChart = new ChartLib(barCtx, {
            type: "bar",
            data: {
                labels: days,
                datasets: [{
                    label: "Tickets",
                    data: counts,
                    backgroundColor: "rgba(184, 115, 51, 0.8)",
                    borderColor: "rgb(184, 115, 51)",
                    borderWidth: 1,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, color: "#8b8f98" },
                        grid: { color: "rgba(255,255,255,0.06)" },
                    },
                    x: {
                        ticks: { color: "#8b8f98" },
                        grid: { color: "rgba(255,255,255,0.06)" },
                    },
                },
                plugins: {
                    legend: { display: false },
                },
            },
        });
    }
}

/**
 * Filter tickets by clicking statistics card
 */
function filterTicketsByStat(filter) {
    window.currentTicketFilter = filter;
    
    // Update status filter dropdown
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) {
        statusFilter.value = filter;
    }
    
    // Update active stat card
    document.querySelectorAll('.stat-card').forEach(card => {
        card.classList.remove('active');
        if (card.dataset.filter === filter) {
            card.classList.add('active');
        }
    });
    
    // Reload tickets with filter applied
    // Check which tab is active and reload accordingly
    const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
    if (activeTab === 'all-tickets') {
        loadAllTickets();
    } else if (activeTab === 'escalated-tickets') {
        loadEscalatedTickets();
    } else {
        loadAllTickets();
    }
}

/**
 * Load Messages page (3 tabs: In Progress, Escalated, Closed)
 * Support Admin: only assigned tickets. Super Admin: all tickets.
 */
let messagesPageActiveTab = 'in_progress';
async function loadMessagesPage() {
    const listEl = document.getElementById('messages-page-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="loading">Loading...</div>';
    const tabBtns = document.querySelectorAll('#messages-tabs .tab-btn');
    tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === messagesPageActiveTab);
        btn.onclick = () => {
            messagesPageActiveTab = btn.dataset.tab;
            loadMessagesPage();
        };
    });
    try {
        const data = await apiRequest('/tickets');
        let tickets = data.tickets || [];
        if (messagesPageActiveTab === 'in_progress') {
            tickets = tickets.filter(t => t.status === 'in_progress');
        } else if (messagesPageActiveTab === 'escalated') {
            tickets = tickets.filter(t => t.status === 'escalated' || t.escalated === true);
        } else if (messagesPageActiveTab === 'closed') {
            tickets = tickets.filter(t => ['closed', 'resolved', 'auto_resolved'].includes(t.status));
        }
        tickets.forEach(ticket => {
            const messages = ticket.messages || [];
            ticket.lastMessage = messages[messages.length - 1];
            ticket.lastMessageTime = ticket.lastMessage ? new Date(ticket.lastMessage.createdAt).getTime() : 0;
            ticket.unreadCount = messages.filter(m => m.sender === 'user' && !m.isRead).length;
        });
        tickets.sort((a, b) => (b.lastMessageTime || 0) - (a.lastMessageTime || 0));
        const statusClass = (t) => t.status === 'closed' || t.status === 'resolved' || t.status === 'auto_resolved' ? 'badge-success' :
            t.status === 'in_progress' || t.status === 'ai_responded' || t.status === 'awaiting_confirmation' ? 'badge-info' :
            t.status === 'escalated' ? 'badge-warning' : 'badge-neutral';
        if (tickets.length === 0) {
            listEl.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div><p>No tickets in this category.</p></div>`;
            return;
        }
        listEl.innerHTML = tickets.map(ticket => {
            const lastMessage = ticket.lastMessage;
            const senderLabel = lastMessage ? getSenderLabel(lastMessage, ticket, true) : '';
            const preview = lastMessage ? (escapeHtml(lastMessage.message).substring(0, 100) + (lastMessage.message.length > 100 ? '...' : '')) : '';
            return `
            <div class="ticket-card status-${ticket.status}" data-ticket-id="${ticket.id}" style="cursor: pointer;">
                <div class="ticket-header">
                    <div class="ticket-id">Ticket #${ticket.id.substring(0, 8)}</div>
                    ${(ticket.unreadCount || 0) > 0 ? `<span class="notification-badge">${ticket.unreadCount > 99 ? '99+' : ticket.unreadCount}</span>` : ''}
                    <span class="badge ${statusClass(ticket)}">${(ticket.status || '').replace('_', ' ').toUpperCase()}</span>
                </div>
                ${ticket.summary ? `<div class="ticket-summary">${escapeHtml(ticket.summary)}</div>` : ''}
                ${lastMessage ? `<div style="font-size: 13px; color: var(--text-secondary); margin-top: 8px;">${senderLabel}: ${preview}</div>` : ''}
            </div>`;
        }).join('');
        listEl.querySelectorAll('.ticket-card[data-ticket-id]').forEach(card => {
            card.addEventListener('click', () => openTicketModal(card.dataset.ticketId));
        });
    } catch (err) {
        listEl.innerHTML = `<p class="error-message">Error: ${err.message}</p>`;
    }
}

/**
 * Open messages modal showing ALL conversations (inbox view) - Admin
 * Shows all tickets with messages, sorted by most recent message
 */
async function openMessagesModal() {
    const modal = document.getElementById('messages-modal');
    const messagesList = document.getElementById('messages-tickets-list');
    
    modal.classList.add('active');
    messagesList.innerHTML = '<div class="loading">Loading messages...</div>';
    
    try {
        const data = await apiRequest('/tickets');
        const tickets = data.tickets || [];
        
        // Filter tickets that have messages (conversations)
        const ticketsWithMessages = tickets.filter(ticket => {
            const messages = ticket.messages || [];
            return messages.length > 0;
        });
        
        if (ticketsWithMessages.length === 0) {
            messagesList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <p>No conversations yet.</p>
                    <p style="margin-top: 8px; font-size: 13px;">Conversations will appear here when users submit tickets or reply.</p>
                </div>
            `;
            return;
        }
        
        // Sort by most recent message (newest first)
        ticketsWithMessages.forEach(ticket => {
            const messages = ticket.messages || [];
            if (messages.length > 0) {
                // Get the last message timestamp
                const lastMessage = messages[messages.length - 1];
                ticket.lastMessageTime = new Date(lastMessage.createdAt).getTime();
                ticket.lastMessage = lastMessage;
                // Calculate unread count (admin sees unread user messages)
                ticket.unreadCount = messages.filter(msg => msg.sender === 'user' && !msg.isRead).length;
            }
        });
        
        ticketsWithMessages.sort((a, b) => {
            // First sort by unread (unread first)
            if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
            if (a.unreadCount === 0 && b.unreadCount > 0) return 1;
            // Then by most recent message
            return (b.lastMessageTime || 0) - (a.lastMessageTime || 0);
        });
        
        messagesList.innerHTML = ticketsWithMessages.map(ticket => {
            const messages = ticket.messages || [];
            const unreadCount = ticket.unreadCount || 0;
            const lastMessage = ticket.lastMessage || messages[messages.length - 1];
            const statusClass = ticket.status === 'closed' || ticket.status === 'resolved' || ticket.status === 'auto_resolved' ? 'badge-success' : 
                               ticket.status === 'ai_responded' || ticket.status === 'in_progress' || ticket.status === 'awaiting_confirmation' ? 'badge-info' :
                               ticket.status === 'escalated' ? 'badge-warning' : 'badge-neutral';
            
            // Get message preview (last message text)
            const messagePreview = lastMessage ? escapeHtml(lastMessage.message) : '';
            const previewText = messagePreview.length > 100 ? messagePreview.substring(0, 100) + '...' : messagePreview;
            const senderLabel = lastMessage ? getSenderLabel(lastMessage, ticket, true) : '';
            
            return `
            <div class="ticket-card status-${ticket.status}" data-ticket-id="${ticket.id}">
                <div class="ticket-header">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div class="ticket-id">Ticket #${ticket.id.substring(0, 8)}</div>
                            ${unreadCount > 0 ? `<span class="notification-badge">${unreadCount > 99 ? '99+' : unreadCount}</span>` : ''}
                        </div>
                        <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
                            <span class="badge ${statusClass}">${ticket.status.replace('_', ' ').toUpperCase()}</span>
                        </div>
                    </div>
                </div>
                ${ticket.summary ? `<div class="ticket-summary">${escapeHtml(ticket.summary)}</div>` : ''}
                <div class="ticket-message" style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-color);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <strong style="font-size: 12px; color: var(--text-secondary);">${senderLabel}</strong>
                        <span style="font-size: 11px; color: var(--text-tertiary);">${formatLocalTime(lastMessage.createdAt)}</span>
                    </div>
                    <div style="color: var(--text-primary); font-size: 14px;">${previewText}</div>
                </div>
                <div class="ticket-meta">
                    <div class="ticket-meta-item">
                        <span>👤</span>
                        <span>${ticket.userId || 'Unknown'}</span>
                    </div>
                    <div class="ticket-meta-item">
                        <span>📅</span>
                        <span>Created: ${formatLocalTime(ticket.createdAt)}</span>
                    </div>
                </div>
            </div>
        `;
        }).join('');
        
    } catch (error) {
        messagesList.innerHTML = `<p class="error-message">Error loading messages: ${error.message}</p>`;
    }
}

/**
 * Open ticket from messages modal
 */
function openTicketFromMessages(ticketId) {
    closeMessagesModal();
    openTicketModal(ticketId);
}

/**
 * Close messages modal
 */
function closeMessagesModal() {
    const overlay = document.getElementById('messages-modal');
    if (overlay) closeModal(overlay);
}

// Article modal state
let currentArticleData = {
    id: null,
    title: null,
    content: null,
    category: null,
    created_by_name: null,
    createdAt: null,
    updatedAt: null
};

/**
 * Close any modal overlay. Use for .modal-close-btn and overlay-backdrop clicks.
 * Resets article modal state when closing article-modal.
 */
function closeModal(overlay) {
    if (!overlay) return;
    overlay.classList.remove('active');
    if (overlay.id === 'article-modal') {
        document.getElementById('edit-article-form')?.reset();
        currentArticleData = { id: null, title: null, content: null, category: null, created_by_name: null, createdAt: null, updatedAt: null };
        const viewMode = document.getElementById('article-view-mode');
        const editMode = document.getElementById('article-edit-mode');
        const viewBtns = document.getElementById('article-view-buttons');
        const editBtns = document.getElementById('article-edit-buttons');
        if (viewMode) viewMode.style.display = 'block';
        if (editMode) editMode.style.display = 'none';
        if (viewBtns) viewBtns.style.display = 'flex';
        if (editBtns) editBtns.style.display = 'none';
    }
}

/**
 * Open article view modal. Call with (articleId) to look up from currentArticles, or (id, title, content, createdAt, updatedAt).
 */
function openArticleViewModal(articleId, title, content, createdAt, updatedAt, category, createdByName) {
    if (arguments.length === 1) {
        const article = currentArticles.find(a => a.id === articleId);
        if (!article) {
            console.error('Article not found:', articleId);
            return;
        }
        openArticleViewModal(article.id, article.title, article.content, article.createdAt, article.updatedAt || '', article.category, article.created_by_name);
        return;
    }
    currentArticleData = {
        id: articleId,
        title: (title || '').replace(/\\'/g, "'"),
        content: (content || '').replace(/\\n/g, '\n').replace(/\\'/g, "'"),
        category: category || null,
        created_by_name: createdByName || null,
        createdAt: createdAt,
        updatedAt: updatedAt
    };

    document.getElementById('article-modal-title').textContent = 'Knowledge Base Article';
    document.getElementById('article-view-title').textContent = currentArticleData.title;
    document.getElementById('article-view-content').textContent = currentArticleData.content;
    const catEl = document.getElementById('article-view-category');
    const catGroup = document.getElementById('article-view-category-group');
    if (catEl && catGroup) {
        catEl.textContent = currentArticleData.category || '—';
        catGroup.style.display = currentArticleData.category ? 'block' : 'none';
    }
    let metaText = `Created: ${createdAt ? formatLocalTime(createdAt) : '—'}`;
    if (updatedAt) metaText += ` | Updated: ${formatLocalTime(updatedAt)}`;
    if (currentArticleData.created_by_name) metaText += ` | Author: ${currentArticleData.created_by_name}`;
    document.getElementById('article-view-meta').textContent = metaText;

    const viewBtns = document.getElementById('article-view-buttons');
    const editBtn = document.getElementById('article-edit-btn');
    if (editBtn) editBtn.style.display = currentUser?.role === 'super_admin' ? 'inline-flex' : 'none';
    document.getElementById('article-view-mode').style.display = 'block';
    document.getElementById('article-edit-mode').style.display = 'none';
    if (viewBtns) viewBtns.style.display = 'flex';
    document.getElementById('article-edit-buttons').style.display = 'none';

    const modal = document.getElementById('article-modal');
    if (!modal) return;
    modal.classList.add('active');
}

/**
 * Switch from view mode to edit mode
 */
function switchToEditMode() {
    if (!currentArticleData.id) {
        showError('No article data available');
        return;
    }
    
    document.getElementById('edit-article-id').value = currentArticleData.id;
    document.getElementById('edit-article-title').value = currentArticleData.title;
    document.getElementById('edit-article-content').value = currentArticleData.content;
    const editCat = document.getElementById('edit-article-category');
    if (editCat) editCat.value = currentArticleData.category || '';
    
    // Update modal title
    document.getElementById('article-modal-title').textContent = 'Edit Knowledge Base Article';
    
    // Hide view mode, show edit mode
    document.getElementById('article-view-mode').style.display = 'none';
    document.getElementById('article-edit-mode').style.display = 'block';
    document.getElementById('article-view-buttons').style.display = 'none';
    document.getElementById('article-edit-buttons').style.display = 'flex';
}

/**
 * Cancel edit mode and return to view mode
 */
function cancelEditMode() {
    if (!currentArticleData.id) {
        closeArticleModal();
        return;
    }
    
    // Reset form (but keep current data in memory)
    document.getElementById('edit-article-form').reset();
    
    // Update modal title back to view mode
    document.getElementById('article-modal-title').textContent = 'Knowledge Base Article';
    
    // Refresh view mode with current data (may have been updated)
    document.getElementById('article-view-title').textContent = currentArticleData.title;
    document.getElementById('article-view-content').textContent = currentArticleData.content;
    const catEl = document.getElementById('article-view-category');
    const catGroup = document.getElementById('article-view-category-group');
    if (catEl && catGroup) {
        catEl.textContent = currentArticleData.category || '—';
        catGroup.style.display = currentArticleData.category ? 'block' : 'none';
    }
    let metaText = `Created: ${currentArticleData.createdAt ? formatLocalTime(currentArticleData.createdAt) : '—'}`;
    if (currentArticleData.updatedAt) metaText += ` | Updated: ${formatLocalTime(currentArticleData.updatedAt)}`;
    if (currentArticleData.created_by_name) metaText += ` | Author: ${currentArticleData.created_by_name}`;
    document.getElementById('article-view-meta').textContent = metaText;
    
    // Show view mode, hide edit mode
    document.getElementById('article-view-mode').style.display = 'block';
    document.getElementById('article-edit-mode').style.display = 'none';
    document.getElementById('article-view-buttons').style.display = 'flex';
    document.getElementById('article-edit-buttons').style.display = 'none';
}

/**
 * Close article modal (calls closeModal for consistency)
 */
function closeArticleModal() {
    const overlay = document.getElementById('article-modal');
    if (overlay) closeModal(overlay);
}

/**
 * Save article edit
 */
async function saveArticleEdit() {
    const articleId = document.getElementById('edit-article-id').value;
    const title = document.getElementById('edit-article-title').value;
    const content = document.getElementById('edit-article-content').value;
    const category = document.getElementById('edit-article-category')?.value?.trim() || undefined;
    if (!title || !content) {
        showError('Title and content are required');
        return;
    }
    try {
        await apiRequest(`/knowledge-base/${articleId}`, {
            method: 'PUT',
            body: JSON.stringify({ title, content, category })
        });
        showSuccess('Article updated successfully!');
        currentArticleData.title = title;
        currentArticleData.content = content;
        currentArticleData.category = category || null;
        currentArticleData.updatedAt = new Date().toISOString();
        
        // Return to view mode with updated data
        cancelEditMode();
        
        // Refresh the article list
        loadKnowledgeBase();
        
    } catch (error) {
        showError(`Failed to update article: ${error.message}`);
    }
}

/** Navigate to unified ticket detail page (same view for all roles) */
function openTicketModal(ticketId) {
    window.location.href = 'ticket-detail.html?id=' + encodeURIComponent(ticketId);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/** Status dot class for compact ticket list: resolved=green, in_progress=yellow, escalated=red, open=blue */
function getTicketStatusDot(ticket) {
    if (ticket.status === "closed" || ticket.status === "resolved" || ticket.status === "auto_resolved") return "dot-resolved";
    if (ticket.escalated === true) return "dot-escalated";
    if (ticket.status === "in_progress") return "dot-in-progress";
    return "dot-open";
}

function timeAgoStr(isoOrTimestamp) {
    const date = typeof isoOrTimestamp === "number" ? new Date(isoOrTimestamp) : new Date(isoOrTimestamp);
    const sec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (sec < 60) return "just now";
    if (sec < 3600) return Math.floor(sec / 60) + "m ago";
    if (sec < 86400) return Math.floor(sec / 3600) + "h ago";
    if (sec < 604800) return Math.floor(sec / 86400) + "d ago";
    return date.toLocaleDateString();
}
