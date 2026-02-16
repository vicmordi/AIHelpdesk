/**
 * Admin Dashboard JavaScript — backend API only, hash-based pages, sidebar.
 */
import { apiRequest, clearToken, isAuthenticated } from "./api.js";
import { renderSidebar } from "./js/sidebar.js";

let currentUser = null;

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
    } else if (pageId === "dashboard") loadDashboardStats();
    else if (pageId === "support-admins") {
        if (currentUser?.role === "super_admin") loadSupportAdminsPage();
        else document.getElementById("support-admins-list") && (document.getElementById("support-admins-list").innerHTML = "<p class=\"empty-state\">Access denied.</p>");
    } else if (pageId === "settings") {
        if (currentUser?.role === "super_admin") loadSettingsPage();
        else document.getElementById("settings-content") && (document.getElementById("settings-content").innerHTML = "<p class=\"empty-state\">Access denied. Super admin only.</p>");
    }
}

function loadDashboardStats() {
    apiRequest("/tickets").then((data) => {
        const tickets = data.tickets || [];
        const stats = {
            total: tickets.length,
            resolved: tickets.filter((t) => t.status === "resolved" || t.status === "auto_resolved").length,
            escalated: tickets.filter((t) => t.escalated === true).length,
            in_progress: tickets.filter((t) => t.status === "in_progress").length,
        };
        updateStatistics(stats);
    }).catch(() => updateStatistics({ total: 0, resolved: 0, escalated: 0, in_progress: 0 }));
}

async function loadAssignableMembers() {
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

async function loadSupportAdminsPage() {
    const listEl = document.getElementById("support-admins-list");
    if (!listEl) return;
    listEl.innerHTML = "<div class=\"loading\">Loading...</div>";
    try {
        const data = await apiRequest("/admin/users");
        const users = (data.users || []).filter((u) => u.role === "support_admin" || u.role === "super_admin");
        if (users.length === 0) {
            listEl.innerHTML = "<p class=\"empty-state\">No support admins yet. Create one above.</p>";
            return;
        }
        listEl.innerHTML = `
            <table class="data-table">
                <thead><tr><th>Full Name</th><th>Email</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
                <tbody>
                    ${users.map((u) => `
                        <tr>
                            <td>${escapeHtml(u.full_name || u.name || u.email || "")}</td>
                            <td>${escapeHtml(u.email || "")}</td>
                            <td><span class="badge ${u.role === 'super_admin' ? 'badge-warning' : 'badge-info'}">${u.role}</span></td>
                            <td>${u.status === "disabled" ? "<span class=\"badge badge-danger\">Disabled</span>" : "Active"}</td>
                            <td>${u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}</td>
                            <td>
                                ${u.role !== "super_admin" && u.uid !== currentUser?.uid ? `
                                    <button type="button" class="btn btn-small btn-secondary support-admin-reset-pwd" data-uid="${u.uid}">Reset password</button>
                                    ${u.status === "disabled" ? `<button type="button" class="btn btn-small btn-secondary support-admin-enable" data-uid="${u.uid}">Enable</button>` : `<button type="button" class="btn btn-small btn-danger support-admin-disable" data-uid="${u.uid}">Disable</button>`}
                                    <button type="button" class="btn btn-small btn-danger support-admin-delete" data-uid="${u.uid}">Delete</button>
                                ` : "-"}
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
        listEl.querySelectorAll(".support-admin-reset-pwd").forEach((btn) => btn.addEventListener("click", () => resetSupportAdminPassword(btn.dataset.uid)));
        listEl.querySelectorAll(".support-admin-disable").forEach((btn) => btn.addEventListener("click", () => disableSupportAdmin(btn.dataset.uid)));
        listEl.querySelectorAll(".support-admin-enable").forEach((btn) => btn.addEventListener("click", () => enableSupportAdmin(btn.dataset.uid)));
        listEl.querySelectorAll(".support-admin-delete").forEach((btn) => btn.addEventListener("click", () => deleteSupportAdmin(btn.dataset.uid)));
    } catch (e) {
        listEl.innerHTML = `<p class="error-message">${e.message || "Failed to load"}</p>`;
    }
}

async function resetSupportAdminPassword(uid) {
    const newPassword = prompt("Enter new temporary password (min 6 characters):");
    if (!newPassword || newPassword.length < 6) return;
    try {
        await apiRequest("/admin/reset-support-admin-password", { method: "POST", body: JSON.stringify({ uid, new_password: newPassword }) });
        showSuccess("Password reset. User must change on next login.");
        loadSupportAdminsPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function disableSupportAdmin(uid) {
    if (!confirm("Disable this user?")) return;
    try {
        await apiRequest(`/admin/disable-support-admin/${uid}`, { method: "PUT" });
        showSuccess("User disabled.");
        loadSupportAdminsPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function enableSupportAdmin(uid) {
    try {
        await apiRequest(`/admin/enable-support-admin/${uid}`, { method: "PUT" });
        showSuccess("User enabled.");
        loadSupportAdminsPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function deleteSupportAdmin(uid) {
    if (!confirm("Permanently delete this user? This cannot be undone.")) return;
    try {
        await apiRequest(`/admin/support-admin/${uid}`, { method: "DELETE" });
        showSuccess("User deleted.");
        loadSupportAdminsPage();
    } catch (e) { showError(e.message || "Failed"); }
}

async function loadSettingsPage() {
    const content = document.getElementById("settings-content");
    if (!content) return;
    content.innerHTML = "<div class=\"loading\">Loading settings...</div>";
    try {
        let org = null;
        try { org = await apiRequest("/organization"); } catch (_) {}
        let users = [];
        if (org) {
            try {
                const usersData = await apiRequest("/admin/users");
                users = usersData.users || [];
            } catch (_) {}
        }

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
            <div class="card">
                <div class="card-header"><h2>User management</h2></div>
                <div class="card-body">
                    <table class="data-table">
                        <thead><tr><th>Full Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th>Actions</th></tr></thead>
                        <tbody>
                            ${users.map((u) => `
                                <tr>
                                    <td>${escapeHtml(u.full_name || u.name || "")}</td>
                                    <td>${escapeHtml(u.email || "")}</td>
                                    <td><span class="badge badge-info">${u.role}</span></td>
                                    <td>${u.status === "disabled" ? "<span class=\"badge badge-danger\">Disabled</span>" : "Active"}</td>
                                    <td>${u.last_login ? new Date(u.last_login).toLocaleString() : "-"}</td>
                                    <td>
                                        ${u.role !== "super_admin" && u.uid !== currentUser?.uid ? `
                                            ${u.status === "disabled" ? `<button type="button" class="btn btn-small support-admin-enable" data-uid="${u.uid}">Enable</button>` : `<button type="button" class="btn btn-small support-admin-disable" data-uid="${u.uid}">Disable</button>`}
                                        ` : "-"}
                                    </td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
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
        content.querySelectorAll(".support-admin-disable").forEach((btn) => btn.addEventListener("click", () => disableSupportAdmin(btn.dataset.uid)));
        content.querySelectorAll(".support-admin-enable").forEach((btn) => btn.addEventListener("click", () => enableSupportAdmin(btn.dataset.uid)));
    } catch (e) {
        content.innerHTML = `<p class="error-message">${e.message || "Failed to load settings"}</p>`;
    }
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

        const sidebarEl = document.getElementById("admin-sidebar");
        if (sidebarEl) {
            renderSidebar(sidebarEl, {
                currentUser: userData,
                onLogout: () => { clearToken(); window.location.href = "login.html"; },
                onOpenMessages: () => openMessagesModal(),
            });
        }

        const mobileMenu = document.getElementById("admin-mobile-menu");
        const overlay = document.getElementById("admin-overlay");
        if (mobileMenu && sidebarEl) {
            mobileMenu.addEventListener("click", () => sidebarEl.classList.toggle("open"));
            overlay?.addEventListener("click", () => sidebarEl.classList.remove("open"));
        }

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
    
    // Ticket lists: delegation for ticket card click (open modal)
    document.getElementById('all-tickets-list')?.addEventListener('click', (e) => {
        const card = e.target.closest('.ticket-card[data-ticket-id]');
        if (card) openTicketModal(card.dataset.ticketId);
    });
    document.getElementById('escalated-tickets-list')?.addEventListener('click', (e) => {
        const card = e.target.closest('.ticket-card[data-ticket-id]');
        if (card) openTicketModal(card.dataset.ticketId);
    });
    document.getElementById('messages-tickets-list')?.addEventListener('click', (e) => {
        const card = e.target.closest('.ticket-card[data-ticket-id]');
        if (card) openTicketFromMessages(card.dataset.ticketId);
    });
    
    // Ticket modal body: delegation for Update status and Assign (dynamic content)
    document.getElementById('ticket-modal')?.addEventListener('click', (e) => {
        const updateBtn = e.target.closest('[data-action="update-ticket-status"]');
        if (updateBtn && updateBtn.dataset.ticketId) {
            updateTicketStatus(updateBtn.dataset.ticketId);
            return;
        }
        const assignBtn = e.target.closest('[data-action="assign-ticket"]');
        if (assignBtn && assignBtn.dataset.ticketId) {
            assignTicket(assignBtn.dataset.ticketId);
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
    
    // Ticket message form handler (admin)
    const messageForm = document.getElementById('ticket-message-form');
    if (messageForm) {
        messageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const ticketId = document.getElementById('current-ticket-id').value;
            const messageText = document.getElementById('ticket-message-text').value.trim();
            const submitBtn = e.target.querySelector('button[type="submit"]');
            
            if (!messageText) {
                return;
            }
            
            // Disable button
            submitBtn.disabled = true;
            submitBtn.textContent = 'Sending...';
            
            try {
                await apiRequest(`/tickets/${ticketId}/messages`, {
                    method: 'POST',
                    body: JSON.stringify({
                        message: messageText,
                        sender: 'admin'
                    })
                });
                
                // Clear input
                document.getElementById('ticket-message-text').value = '';
                
        // Reload ticket to show new message
        await openTicketModal(ticketId);
        
        await loadAllTickets();
        showSuccess('Message sent successfully!');
                
            } catch (error) {
                showError(`Failed to send message: ${error.message}`);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send';
            }
        });
    }
    
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

// Create support admin (super_admin only)
const createSupportAdminForm = document.getElementById('create-support-admin-form');
if (createSupportAdminForm) {
    createSupportAdminForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const full_name = document.getElementById('support-admin-full-name').value.trim();
        const email = document.getElementById('support-admin-email').value.trim();
        const temporary_password = document.getElementById('support-admin-password').value;
        if (!full_name) {
            showError('Full name is required');
            return;
        }
        try {
            await apiRequest('/admin/create-support-admin', {
                method: 'POST',
                body: JSON.stringify({ full_name, email, temporary_password })
            });
            showSuccess('Support admin created. They must change password on first login.');
            createSupportAdminForm.reset();
        } catch (err) {
            showError(err.message || 'Failed to create support admin');
        }
    });
}

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
            const statusClass = ticket.status === 'auto_resolved' || ticket.status === 'resolved' ? 'badge-success' : 
                               ticket.status === 'in_progress' ? 'badge-info' :
                               ticket.status === 'pending' ? 'badge-neutral' : 'badge-warning';
            
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
                        <span>${new Date(ticket.createdAt).toLocaleString()}</span>
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
    const assignedTo = document.getElementById('assigned-to-filter')?.value || '';
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
            if (ticket.status === 'resolved' || ticket.status === 'auto_resolved') {
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
                tickets = tickets.filter(t => t.status === 'resolved' || t.status === 'auto_resolved');
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
        
        ticketsList.innerHTML = tickets.map(ticket => {
            const unreadCount = ticket.unreadCount || 0;
            const statusClass = ticket.status === 'auto_resolved' || ticket.status === 'resolved' ? 'badge-success' : 
                               ticket.status === 'in_progress' ? 'badge-info' :
                               ticket.status === 'pending' ? 'badge-neutral' : 'badge-warning';
            
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
                    <strong>User:</strong> ${ticket.userId ? ticket.userId.substring(0, 8) + '...' : 'Unknown'}<br>
                    <strong>Message:</strong> ${escapeHtml(ticket.message.length > 150 ? ticket.message.substring(0, 150) + '...' : ticket.message)}
                </div>
                <div class="ticket-meta">
                    <div class="ticket-meta-item">
                        <span>📅</span>
                        <span>${new Date(ticket.createdAt).toLocaleString()}</span>
                    </div>
                </div>
            </div>
        `;
        }).join('');
        
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
            const statusClass = ticket.status === 'auto_resolved' || ticket.status === 'resolved' ? 'badge-success' : 
                               ticket.status === 'in_progress' ? 'badge-info' :
                               ticket.status === 'pending' ? 'badge-neutral' : 'badge-warning';
            
            // Get message preview (last message text)
            const messagePreview = lastMessage ? escapeHtml(lastMessage.message) : '';
            const previewText = messagePreview.length > 100 ? messagePreview.substring(0, 100) + '...' : messagePreview;
            const senderLabel = lastMessage && lastMessage.sender === 'user' ? 'Customer' : 
                               lastMessage && lastMessage.sender === 'admin' ? 'You' : 'AI Assistant';
            
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
                        <span style="font-size: 11px; color: var(--text-tertiary);">${new Date(lastMessage.createdAt).toLocaleString()}</span>
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
                        <span>Created: ${new Date(ticket.createdAt).toLocaleString()}</span>
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
    let metaText = `Created: ${createdAt ? new Date(createdAt).toLocaleString() : '—'}`;
    if (updatedAt) metaText += ` | Updated: ${new Date(updatedAt).toLocaleString()}`;
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
    let metaText = `Created: ${currentArticleData.createdAt ? new Date(currentArticleData.createdAt).toLocaleString() : '—'}`;
    if (currentArticleData.updatedAt) metaText += ` | Updated: ${new Date(currentArticleData.updatedAt).toLocaleString()}`;
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

// Store current ticket data for messaging
let currentTicketData = null;

/**
 * Open ticket detail modal with conversation thread
 */
async function openTicketModal(ticketId) {
    const modal = document.getElementById('ticket-modal');
    const modalBody = document.getElementById('ticket-modal-body');
    const modalTitle = document.getElementById('ticket-modal-title');
    const messageInputArea = document.getElementById('ticket-message-input');
    
    modalTitle.textContent = 'Loading ticket details...';
    modalBody.innerHTML = '<div class="loading">Loading...</div>';
    messageInputArea.style.display = 'none';
    modal.classList.add('active');
    
    try {
        // Get all tickets to find the one we need
        const data = await apiRequest('/tickets');
        const tickets = data.tickets || [];
        const ticket = tickets.find(t => t.id === ticketId);
        
        if (!ticket) {
            modalBody.innerHTML = '<p class="error-message">Ticket not found</p>';
            return;
        }
        
        // Store ticket data for messaging
        currentTicketData = ticket;
        document.getElementById('current-ticket-id').value = ticketId;
        
        modalTitle.textContent = `Ticket #${ticket.id.substring(0, 8)}`;
        
        // Build conversation thread
        const messages = ticket.messages || [];
        
        // If no messages array exists, create one from legacy fields
        let conversationHtml = '';
        if (messages.length === 0) {
            // Legacy: Create messages from original ticket structure
            conversationHtml = `
                <div class="message-item user">
                    <div class="message-sender">Customer</div>
                    <div class="message-bubble">${escapeHtml(ticket.message)}</div>
                    <div class="message-time">${new Date(ticket.createdAt).toLocaleString()}</div>
                </div>
            `;
            if (ticket.aiReply) {
                conversationHtml += `
                    <div class="message-item ai">
                        <div class="message-sender">AI Assistant</div>
                        <div class="message-bubble">${escapeHtml(ticket.aiReply)}</div>
                        <div class="message-time">${new Date(ticket.createdAt).toLocaleString()}</div>
                    </div>
                `;
            }
        } else {
            // Display conversation thread
            conversationHtml = messages.map(msg => {
                const senderLabel = msg.sender === 'user' ? 'Customer' : 
                                   msg.sender === 'admin' ? 'Admin' : 'AI Assistant';
                return `
                    <div class="message-item ${msg.sender}">
                        <div class="message-sender">${senderLabel}</div>
                        <div class="message-bubble">${escapeHtml(msg.message)}</div>
                        <div class="message-time">${new Date(msg.createdAt).toLocaleString()}</div>
                    </div>
                `;
            }).join('');
        }
        
        modalBody.innerHTML = `
            <div class="ticket-detail-section">
                <h3>Status & Category</h3>
                <div class="badge-group">
                    <span class="badge ${ticket.status === 'auto_resolved' || ticket.status === 'resolved' ? 'badge-success' : 
                                   ticket.status === 'in_progress' ? 'badge-info' :
                                   ticket.status === 'pending' ? 'badge-neutral' : 'badge-warning'}">${ticket.status.replace('_', ' ').toUpperCase()}</span>
                    ${ticket.category ? `<span class="badge badge-neutral">${ticket.category}</span>` : ''}
                    ${ticket.confidence !== undefined ? `<span class="badge badge-info">${(ticket.confidence * 100).toFixed(1)}% Confidence</span>` : ''}
                </div>
                <div class="status-controls">
                    <div class="status-select-group">
                        <label for="ticket-status-select">Update Status:</label>
                        <select id="ticket-status-select">
                            <option value="pending" ${ticket.status === 'pending' ? 'selected' : ''}>Pending</option>
                            <option value="in_progress" ${ticket.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
                            <option value="resolved" ${ticket.status === 'resolved' ? 'selected' : ''}>Resolved</option>
                            <option value="escalated" ${ticket.status === 'escalated' ? 'selected' : ''}>Escalated</option>
                            <option value="auto_resolved" ${ticket.status === 'auto_resolved' ? 'selected' : ''}>Auto-Resolved</option>
                        </select>
                        <button type="button" class="btn btn-primary btn-sm" data-action="update-ticket-status" data-ticket-id="${ticketId}">Update</button>
                    </div>
                    ${currentUser?.role === 'super_admin' ? `
                    <div class="assign-controls" style="margin-top: 12px;">
                        <label for="ticket-assign-select">Assign to:</label>
                        <select id="ticket-assign-select">
                            <option value="">Unassigned</option>
                        </select>
                        <button type="button" class="btn btn-primary btn-sm" data-action="assign-ticket" data-ticket-id="${ticketId}">Assign</button>
                    </div>
                    ` : ''}
                </div>
            </div>
            
            ${ticket.summary ? `
            <div class="ticket-detail-section">
                <h3>Summary</h3>
                <p>${escapeHtml(ticket.summary)}</p>
            </div>
            ` : ''}
            
            <div class="ticket-detail-section">
                <h3>Conversation</h3>
                <div class="conversation-thread">
                    ${conversationHtml || '<div class="conversation-empty">No messages yet</div>'}
                </div>
            </div>
            
            ${ticket.knowledge_used && ticket.knowledge_used.length > 0 ? `
            <div class="ticket-detail-section">
                <h3>Knowledge Base Articles Used</h3>
                <p>${ticket.knowledge_used.join(', ')}</p>
            </div>
            ` : ''}
            
            ${ticket.internal_note ? `
            <div class="ticket-detail-section">
                <h3>Internal Note</h3>
                <div class="internal-note">
                    <p>${escapeHtml(ticket.internal_note)}</p>
                </div>
            </div>
            ` : ''}
            
            <div class="ticket-detail-section">
                <h3>Ticket Information</h3>
                <p><strong>User ID:</strong> ${ticket.userId || 'Unknown'}</p>
                <p><strong>Created:</strong> ${new Date(ticket.createdAt).toLocaleString()}</p>
            </div>
        `;
        
        // Show message input for admins
        messageInputArea.style.display = 'block';

        // Populate assign dropdown for super_admin
        const assignSelect = document.getElementById('ticket-assign-select');
        if (assignSelect && currentUser?.role === 'super_admin') {
            try {
                const memData = await apiRequest('/organization/members');
                const members = (memData.members || []).filter((m) => m.role === 'support_admin' || m.role === 'super_admin');
                assignSelect.innerHTML = '<option value="">Unassigned</option>' + members.map((m) => `<option value="${m.uid}" ${ticket.assigned_to === m.uid ? 'selected' : ''}>${escapeHtml(m.email)}</option>`).join('');
            } catch (_) {
                assignSelect.innerHTML = '<option value="">Unassigned</option>';
            }
        }
        
        // Scroll to bottom of conversation
        const conversationThread = modalBody.querySelector('.conversation-thread');
        if (conversationThread) {
            conversationThread.scrollTop = conversationThread.scrollHeight;
        }
        
        // Mark messages as read when viewing (admin sees unread user messages)
        try {
            await apiRequest(`/tickets/${ticketId}/messages/read`, {
                method: 'POST'
            });
            // Reload tickets to update unread counts and message icon badge
            await loadAllTickets();
            loadEscalatedTickets();
        } catch (error) {
            console.error('Error marking messages as read:', error);
        }
        
    } catch (error) {
        modalBody.innerHTML = `<p class="error-message">Error loading ticket: ${error.message}</p>`;
    }
}

/**
 * Update ticket status (Admin only)
 */
async function updateTicketStatus(ticketId) {
    const statusSelect = document.getElementById('ticket-status-select');
    const newStatus = statusSelect.value;
    
    if (!newStatus) {
        showError('Please select a status');
        return;
    }
    
    try {
        await apiRequest(`/tickets/${ticketId}/status`, {
            method: 'PUT',
            body: JSON.stringify({ status: newStatus })
        });
        
        showSuccess('Ticket status updated successfully!');
        
        await openTicketModal(ticketId);
        loadAllTickets();
    } catch (error) {
        showError(`Failed to update status: ${error.message}`);
    }
}

/**
 * Assign ticket to user (super_admin only)
 */
async function assignTicket(ticketId) {
    const assignSelect = document.getElementById('ticket-assign-select');
    if (!assignSelect) return;
    const uid = assignSelect.value || null;
    try {
        await apiRequest(`/tickets/${ticketId}/assign`, {
            method: 'PUT',
            body: JSON.stringify({ assigned_to: uid })
        });
        showSuccess(uid ? 'Ticket assigned.' : 'Ticket unassigned.');
        await openTicketModal(ticketId);
        loadAllTickets();
    } catch (error) {
        showError(error.message || 'Failed to assign');
    }
}

/**
 * Close ticket detail modal
 */
function closeTicketModal() {
    const overlay = document.getElementById('ticket-modal');
    if (overlay) closeModal(overlay);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
