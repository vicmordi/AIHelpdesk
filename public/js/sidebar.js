/**
 * Reusable admin sidebar component. Renders nav and handles active state from hash.
 * @param {HTMLElement} container - Element to render sidebar into
 * @param {Object} options - { currentUser: { email, role }, onLogout: fn }
 */
export function renderSidebar(container, options = {}) {
    const { currentUser = {}, onLogout } = options;
    const role = currentUser.role || "";
    const isSuperAdmin = role === "super_admin" || role === "admin";

    const links = [
        { id: "dashboard", hash: "#dashboard", label: "Dashboard", icon: "🏠" },
        { id: "tickets", hash: "#tickets", label: "View All Tickets", icon: "🎫" },
        { id: "knowledge-base", hash: "#knowledge-base", label: "Knowledge Base", icon: "📚" },
    ];
    if (isSuperAdmin) {
        links.push({ id: "support-admins", hash: "#support-admins", label: "Support Admins", icon: "👥" });
        links.push({ id: "settings", hash: "#settings", label: "Settings", icon: "⚙️" });
    }
    links.push({ id: "logout", hash: "#logout", label: "Logout", icon: "🚪", isLogout: true });

    function getActivePage() {
        const hash = (window.location.hash || "#dashboard").replace("#", "");
        return hash || "dashboard";
    }

    function setActive() {
        const active = getActivePage();
        container.querySelectorAll(".sidebar-link").forEach((el) => {
            const id = el.getAttribute("data-page");
            el.classList.toggle("active", id === active);
        });
        return active;
    }

    const email = currentUser.email || "";
    const initial = email ? email.charAt(0).toUpperCase() : "A";

    container.innerHTML = `
        <div class="sidebar-brand">
            <div class="sidebar-brand-icon">💬</div>
            <span class="sidebar-brand-text">AI Helpdesk</span>
        </div>
        <nav class="sidebar-nav">
            ${links.filter((l) => !l.isLogout).map((l) => `
                <a class="sidebar-link" href="${l.action ? "#" : l.hash}" data-page="${l.id}" data-action="${l.action || ""}" data-nav>
                    <span class="sidebar-link-icon">${l.icon}</span>
                    <span class="sidebar-label">${l.label}</span>
                </a>
            `).join("")}
        </nav>
        <div class="sidebar-footer">
            <div class="sidebar-user">
                <div class="sidebar-user-avatar">${initial}</div>
                <span class="sidebar-user-email">${email}</span>
            </div>
            <a class="sidebar-link" href="#" data-page="logout" data-nav style="margin-top: 8px;">
                <span class="sidebar-link-icon">🚪</span>
                <span class="sidebar-label">Logout</span>
            </a>
        </div>
    `;

    container.querySelectorAll("[data-nav]").forEach((el) => {
        el.addEventListener("click", (e) => {
            const page = el.getAttribute("data-page");
            const action = el.getAttribute("data-action");
            if (page === "logout") {
                e.preventDefault();
                if (typeof onLogout === "function") onLogout();
                return;
            }
            setActive();
        });
    });

    window.addEventListener("hashchange", setActive);
    setActive();
    return { setActive, getActivePage };
}
