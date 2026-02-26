/**
 * Submit Ticket Page JavaScript — backend API only, no Firebase client SDK.
 */
import { apiRequest, clearToken, isAuthenticated, formatLocalTime } from "./api.js";
import { getLogoHref, LOGO_ICON_SVG } from "./js/nav-logo.js";

let currentUser = null;

/** Build display label for a message sender (user view: You / Name (Role)) */
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

// Check authentication (token-based)
(async function initAuth() {
    if (!isAuthenticated()) {
        window.location.href = "index.html";
        return;
    }
    try {
        const userData = await apiRequest("/auth/me");
        const adminRoles = ["admin", "super_admin", "support_admin"];
        if (adminRoles.includes(userData.role || "")) {
            window.location.href = "admin.html";
            return;
        }
        currentUser = userData;
        if (userData.must_change_password) {
            window.location.href = "change-password.html";
            return;
        }
        // Logo: employee dashboard (submit-ticket). Admins are redirected above.
        const logoLink = document.getElementById("nav-brand-logo");
        if (logoLink) {
            logoLink.href = "submit-ticket.html";
            const iconEl = logoLink.querySelector(".nav-brand-icon");
            if (iconEl) iconEl.innerHTML = LOGO_ICON_SVG;
        }
        document.getElementById("user-email").textContent = userData.email || "";
        const avatar = document.getElementById("user-avatar");
        if (avatar) avatar.textContent = (userData.email || "U").charAt(0).toUpperCase();
        loadMyTickets();
        document.querySelector('[data-tab="my-tickets"]')?.click();
        document.getElementById("messages-icon-btn")?.addEventListener("click", () => openMessagesModal());
        fetchUnreadCount();
        window._unreadPoll = setInterval(fetchUnreadCount, 10000);
    } catch (err) {
        console.error("Error loading user data:", err);
        showError("Failed to load user data");
        clearToken();
        window.location.href = "index.html";
    }
})();

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
 * Fetch unread message count from API and update header + tab badges.
 */
async function fetchUnreadCount() {
    try {
        const data = await apiRequest("/messages/unread-count");
        const count = data.unread_count ?? data.unread_messages ?? 0;
        const headerBadge = document.getElementById("header-unread-badge");
        const tabBadge = document.getElementById("unread-badge");
        if (headerBadge) {
            headerBadge.textContent = count > 99 ? "99+" : String(count);
            headerBadge.style.display = count > 0 ? "inline-flex" : "none";
            if (count > 0 && (window._lastUnreadCount ?? 0) < count) {
                headerBadge.classList.add("pulse-once");
                setTimeout(() => headerBadge.classList.remove("pulse-once"), 600);
                playNewMessageSound();
            }
            window._lastUnreadCount = count;
        }
        if (tabBadge) {
            tabBadge.textContent = count > 99 ? "99+" : String(count);
            tabBadge.style.display = count > 0 ? "inline-flex" : "none";
        }
    } catch (_) {}
}

/**
 * Close a modal overlay by removing .active. Used by body delegation for .modal-close-btn and overlay backdrop.
 */
function closeModal(overlay) {
    if (!overlay) return;
    overlay.classList.remove('active');
}

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', () => {
    // Responsive nav: hamburger toggle, close on link click or resize to desktop
    const topNav = document.getElementById('top-nav');
    const navToggle = document.getElementById('nav-toggle');
    const navMenu = document.getElementById('nav-menu');
    function closeNavMenu() {
        if (!topNav) return;
        topNav.classList.remove('open');
        if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
    }
    function openNavMenu() {
        if (!topNav) return;
        topNav.classList.add('open');
        if (navToggle) navToggle.setAttribute('aria-expanded', 'true');
    }
    if (navToggle && topNav) {
        navToggle.addEventListener('click', () => {
            const isOpen = topNav.classList.contains('open');
            if (isOpen) closeNavMenu();
            else openNavMenu();
        });
    }
    if (navMenu) {
        navMenu.addEventListener('click', () => closeNavMenu());
    }
    window.addEventListener('resize', () => {
        if (window.innerWidth >= 769) closeNavMenu();
    });
    // Close mobile menu when clicking outside the nav (only on mobile)
    document.body.addEventListener('click', (e) => {
        if (window.innerWidth < 769 && topNav && topNav.classList.contains('open') && !e.target.closest('#top-nav')) {
            closeNavMenu();
        }
    });

    // Body delegation: close modals via .modal-close-btn or clicking overlay
    document.body.addEventListener('click', (e) => {
        if (e.target.closest('.modal-close-btn')) {
            const btn = e.target.closest('.modal-close-btn');
            const overlay = btn.dataset.modal ? document.getElementById(btn.dataset.modal) : btn.closest('.modal-overlay');
            if (overlay) closeModal(overlay);
            return;
        }
        if (e.target.classList.contains('modal-overlay')) {
            closeModal(e.target);
            return;
        }
    });

    // Stat cards: filter by click (no inline onclick)
    document.querySelectorAll('.stat-card[data-filter]').forEach(card => {
        card.addEventListener('click', () => {
            const filter = card.dataset.filter;
            if (filter) filterTicketsByStat(filter);
        });
    });

    // Ticket lists: delegation for ticket card click (open modal)
    document.getElementById('my-tickets-list')?.addEventListener('click', (e) => {
        const card = e.target.closest('.ticket-card[data-ticket-id]');
        if (card) openTicketModal(card.dataset.ticketId);
    });
    document.getElementById('messages-tickets-list')?.addEventListener('click', (e) => {
        const card = e.target.closest('.ticket-card[data-ticket-id]');
        if (card) openTicketFromMessages(card.dataset.ticketId);
    });

    // New ticket button
    document.getElementById('new-ticket-btn')?.addEventListener('click', () => {
        document.querySelector('[data-tab="submit"]')?.click();
    });

    // Logout handler
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            clearToken();
            window.location.href = "index.html";
        });
    }
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;
            
            // Update active tab button
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update active tab content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            const tabContent = document.getElementById(`${tabName}-tab`);
            if (tabContent) {
                tabContent.classList.add('active');
            }
            
            // Load data for active tab
            if (tabName === 'my-tickets') {
                loadMyTickets();
            }
        });
    });
});

// Ticket Form Handler
document.addEventListener('DOMContentLoaded', () => {
    const ticketForm = document.getElementById('ticket-form');
    if (ticketForm) {
        ticketForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const message = document.getElementById('ticket-message').value;
            const submitBtn = document.getElementById('submit-btn');
            const responseDiv = document.getElementById('ticket-response');
            const responseContent = document.getElementById('response-content');
            
            // Hide previous messages
            hideMessages();
            
            // Disable submit button
            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting...';
            
            try {
                const data = await apiRequest('/tickets', {
                    method: 'POST',
                    body: JSON.stringify({ message })
                });
                
                const ticket = data.ticket;
                
                // Show response
                responseDiv.style.display = 'block';
                
                // Success message based on actual ticket status
                if (ticket.status === 'ai_responded') {
                    responseContent.innerHTML = `
                        <div class="alert alert-success">
                            <strong>✅ We found a solution</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">Check the conversation below. Reply YES if it resolved your issue, or NO to escalate to support.</p>
                        </div>
                        <p style="margin-top: 12px; color: var(--text-secondary);">Your ticket is ready. Use the conversation in the window that just opened, or find it under "My Tickets".</p>
                    `;
                    document.getElementById('ticket-form').reset();
                    loadMyTickets();
                    openTicketModal(ticket.id);
                    return;
                }
                
                if (ticket.status === 'escalated') {
                    responseContent.innerHTML = `
                        <div class="alert alert-warning">
                            <strong>⚠️ Ticket Escalated</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">We couldn't find a knowledge base article for this issue. Your ticket has been escalated to our support team.</p>
                        </div>
                        <p style="margin-top: 16px; color: var(--text-secondary);">A support agent will assist you shortly. You can check the status in the "My Tickets" tab.</p>
                    `;
                    document.getElementById('ticket-form').reset();
                    loadMyTickets();
                    openTicketModal(ticket.id);
                    return;
                } else {
                    responseContent.innerHTML = `
                        <div class="alert alert-success">
                            <strong>✅ Ticket Submitted</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">Your ticket has been created. Check "My Tickets" for the conversation.</p>
                        </div>
                    `;
                }
                
                // Reset form
                document.getElementById('ticket-form').reset();
                
                // Reload tickets
                loadMyTickets();
                
            } catch (error) {
                showError(`Failed to submit ticket: ${error.message}`);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Ticket';
            }
        });
    }
});

/**
 * Load user's tickets
 * Make it globally accessible
 */
window.loadMyTickets = async function() {
    const ticketsList = document.getElementById('my-tickets-list');
    ticketsList.innerHTML = '<p class="loading">Loading tickets...</p>';
    
    try {
        const data = await apiRequest('/tickets/my-tickets');
        const tickets = data.tickets || [];
        
        // Calculate unread message counts and statistics
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
                msg.sender !== 'user' && !msg.isRead
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
        
        // Update unread badge in tab
        const unreadBadge = document.getElementById('unread-badge');
        if (unreadBadge) {
            if (totalUnread > 0) {
                unreadBadge.textContent = totalUnread > 99 ? '99+' : totalUnread;
                unreadBadge.style.display = 'inline-flex';
            } else {
                unreadBadge.style.display = 'none';
            }
        }
        
        // Update header unread badge (message icon)
        const headerUnreadBadge = document.getElementById('header-unread-badge');
        if (headerUnreadBadge) {
            if (totalUnread > 0) {
                headerUnreadBadge.textContent = totalUnread > 99 ? '99+' : totalUnread;
                headerUnreadBadge.style.display = 'inline-flex';
            } else {
                headerUnreadBadge.style.display = 'none';
            }
        }
        
        // Always show message icon, even if no unread messages
        const messagesIconBtn = document.getElementById('messages-icon-btn');
        if (messagesIconBtn) {
            messagesIconBtn.style.display = 'block';
        }
        
        // Store tickets for filtering
        window.allTickets = tickets;
        
        // Set default filter to 'all' if not set
        if (!window.currentTicketFilter) {
            window.currentTicketFilter = 'all';
            document.querySelector('.stat-card[data-filter="all"]')?.classList.add('active');
        }
        
        if (tickets.length === 0) {
            ticketsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📝</div>
                    <p>You haven't submitted any tickets yet.</p>
                    <p style="margin-top: 8px; font-size: 13px;">Submit your first ticket to get started!</p>
                </div>
            `;
            return;
        }
        
        // Apply current filter if set
        const currentFilter = window.currentTicketFilter || 'all';
        let filteredTickets = tickets;
        if (currentFilter !== 'all') {
            if (currentFilter === 'resolved') {
                filteredTickets = tickets.filter(t => t.status === 'closed' || t.status === 'resolved' || t.status === 'auto_resolved');
            } else if (currentFilter === 'escalated') {
                // Use escalated field, not status
                filteredTickets = tickets.filter(t => t.escalated === true);
            } else {
                filteredTickets = tickets.filter(t => t.status === currentFilter);
            }
        }
        
        // Update list title
        const listTitle = document.getElementById('tickets-list-title');
        if (listTitle) {
            if (currentFilter === 'all') {
                listTitle.textContent = 'My Tickets';
            } else {
                listTitle.textContent = `My Tickets - ${currentFilter.replace('_', ' ').toUpperCase()}`;
            }
        }
        
        // Sort tickets: unread first, then by creation date (newest first)
        filteredTickets.sort((a, b) => {
            if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
            if (a.unreadCount === 0 && b.unreadCount > 0) return 1;
            return new Date(b.createdAt) - new Date(a.createdAt);
        });
        
        if (filteredTickets.length === 0) {
            ticketsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📝</div>
                    <p>No tickets found${currentFilter !== 'all' ? ` with status "${currentFilter}"` : ''}.</p>
                </div>
            `;
            return;
        }
        
        const statusBadgeClass = (t) => {
            if (t.escalated === true) return 'user-ticket-status-escalated';
            if (t.status === 'closed' || t.status === 'resolved' || t.status === 'auto_resolved') return 'user-ticket-status-closed';
            if (t.status === 'in_progress' || t.status === 'awaiting_confirmation') return 'user-ticket-status-in-progress';
            return 'user-ticket-status-open';
        };
        const statusLabel = (t) => {
            if (t.escalated === true) return 'Escalated';
            return (t.status || 'Open').replace(/_/g, ' ');
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
            <div class="user-tickets-table-wrap">
                <table class="user-tickets-table">
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
                        ${filteredTickets.map(ticket => {
                            const unreadCount = ticket.unreadCount || 0;
                            const title = (ticket.summary || ticket.message || 'No subject').trim();
                            const titleShort = title.length > 50 ? title.substring(0, 50) + '…' : title;
                            const assigned = ticket.assigned_to_name || (ticket.assigned_to ? 'Assigned' : '—');
                            return `
                            <tr class="user-ticket-row" data-ticket-id="${ticket.id}" role="button" tabindex="0">
                                <td>
                                    <span class="user-ticket-title">${escapeHtml(titleShort)}</span>
                                    ${unreadCount > 0 ? `<span class="user-ticket-unread">${unreadCount > 99 ? '99+' : unreadCount}</span>` : ''}
                                </td>
                                <td><span class="user-ticket-badge ${statusBadgeClass(ticket)}">${statusLabel(ticket)}</span></td>
                                <td>${formatLocalTime(ticket.createdAt)}</td>
                                <td>${lastUpdated(ticket)}</td>
                                <td>${escapeHtml(assigned)}</td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
        ticketsList.querySelectorAll('.user-ticket-row').forEach(row => {
            row.addEventListener('click', () => {
                const id = row.dataset.ticketId;
                if (id) window.location.href = `ticket-detail.html?id=${encodeURIComponent(id)}`;
            });
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    row.click();
                }
            });
        });
        
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

function hideMessages() {
    document.getElementById('error-message').style.display = 'none';
    document.getElementById('success-message').style.display = 'none';
}

// Store current ticket data for messaging
/** Navigate to unified ticket detail page (same view for all roles) */
function openTicketModal(ticketId) {
    window.location.href = 'ticket-detail.html?id=' + encodeURIComponent(ticketId);
}

/**
 * Append a message bubble to the ticket conversation thread (for guided flow live updates)
 */
function appendMessageToTicketThread(sender, message, createdAt, senderName, senderRole) {
    const thread = document.getElementById('ticket-conversation-thread');
    if (!thread) return;
    const emptyEl = thread.querySelector('.conversation-empty');
    if (emptyEl) emptyEl.remove();
    const msg = { sender, sender_name: senderName, sender_role: senderRole };
    const senderLabel = getSenderLabel(msg, null, false);
    const time = createdAt ? formatLocalTime(createdAt) : formatLocalTime(new Date().toISOString());
    const bubble = document.createElement('div');
    bubble.className = `message-item ${sender}`;
    bubble.innerHTML = `
        <div class="message-sender">${senderLabel}</div>
        <div class="message-bubble">${escapeHtml(message)}</div>
        <div class="message-time">${time}</div>
    `;
    thread.appendChild(bubble);
    thread.scrollTop = thread.scrollHeight;
}

/**
 * Render option buttons for guided flow (e.g. device choice). Click sends that value as message.
 */
function renderStepOptions(options) {
    const container = document.getElementById('ticket-step-options');
    if (!container) return;
    container.innerHTML = '';
    container.style.display = !options || options.length === 0 ? 'none' : 'flex';
    if (!options || options.length === 0) return;
    options.forEach(opt => {
        const label = opt.label || opt.value || '';
        const value = opt.value || opt.label || label;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline step-option-btn';
        btn.textContent = label;
        btn.dataset.value = value;
        btn.addEventListener('click', () => {
            const input = document.getElementById('ticket-message-text');
            const form = document.getElementById('ticket-message-form');
            if (input) input.value = value;
            if (form) form.requestSubmit();
        });
        container.appendChild(btn);
    });
}

/**
 * Show or hide typing indicator in ticket modal
 */
function setTicketTypingIndicator(show) {
    const el = document.getElementById('ticket-typing-indicator');
    if (el) el.style.display = show ? 'block' : 'none';
    const thread = document.getElementById('ticket-conversation-thread');
    if (thread) thread.scrollTop = thread.scrollHeight;
}

// Ticket message form handler (user)
document.addEventListener('DOMContentLoaded', () => {
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
            
            submitBtn.disabled = true;
            submitBtn.textContent = 'Sending...';
            
            const isGuided = currentUserTicketData && currentUserTicketData.ai_mode === 'guided' && !currentUserTicketData.resolved;
            
            if (isGuided) {
                appendMessageToTicketThread('user', messageText, new Date().toISOString());
                document.getElementById('ticket-message-text').value = '';
                setTicketTypingIndicator(true);
            }
            
            try {
                const data = await apiRequest(`/tickets/${ticketId}/messages`, {
                    method: 'POST',
                    body: JSON.stringify({
                        message: messageText,
                        sender: 'user'
                    })
                });
                
                if (!isGuided) {
                    document.getElementById('ticket-message-text').value = '';
                }
                
                setTicketTypingIndicator(false);
                
                if (isGuided && data.ai_reply) {
                    appendMessageToTicketThread('ai', data.ai_reply.message, data.ai_reply.createdAt);
                    const opts = data.ai_reply.options || [];
                    renderStepOptions(opts);
                    currentUserTicketData = currentUserTicketData || {};
                    currentUserTicketData.messages = (currentUserTicketData.messages || []).concat(
                        { sender: 'user', message: messageText, createdAt: new Date().toISOString() },
                        data.ai_reply
                    );
                    currentUserTicketData.current_step_options = opts;
                    currentUserTicketData.resolved = data.resolved === true || currentUserTicketData.resolved;
                    currentUserTicketData.status = data.resolved ? 'resolved' : (currentUserTicketData.status || 'in_progress');
                    if (data.resolved) {
                        const messageInputArea = document.getElementById('ticket-message-input');
                        if (messageInputArea) messageInputArea.style.display = 'none';
                        const badgeGroup = document.querySelector('#ticket-modal-body .badge-group');
                        if (badgeGroup) {
                            const statusBadge = badgeGroup.querySelector('.badge');
                            if (statusBadge) {
                                statusBadge.textContent = 'RESOLVED';
                                statusBadge.className = 'badge badge-success';
                            }
                        }
                    }
                } else {
                    await openTicketModal(ticketId);
                }
                await loadMyTickets();
                showSuccess('Message sent successfully!');
                
            } catch (error) {
                setTicketTypingIndicator(false);
                showError(`Failed to send message: ${error.message}`);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Send';
            }
        });
    }
});

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
    
    // Update active stat card
    document.querySelectorAll('.stat-card').forEach(card => {
        card.classList.remove('active');
        if (card.dataset.filter === filter) {
            card.classList.add('active');
        }
    });
    
    // Reload tickets with filter applied
    if (window.allTickets) {
        renderFilteredTickets(window.allTickets);
    } else {
        loadMyTickets();
    }
}

/**
 * Render filtered tickets
 */
function renderFilteredTickets(tickets) {
    const ticketsList = document.getElementById('my-tickets-list');
    const currentFilter = window.currentTicketFilter || 'all';
    
    let filteredTickets = tickets;
    if (currentFilter !== 'all') {
        if (currentFilter === 'resolved') {
            filteredTickets = tickets.filter(t => t.status === 'closed' || t.status === 'resolved' || t.status === 'auto_resolved');
        } else if (currentFilter === 'escalated') {
            // Use escalated field, not status
            filteredTickets = tickets.filter(t => t.escalated === true);
        } else {
            filteredTickets = tickets.filter(t => t.status === currentFilter);
        }
    }
    
    // Update list title
    const listTitle = document.getElementById('tickets-list-title');
    if (listTitle) {
        if (currentFilter === 'all') {
            listTitle.textContent = 'My Tickets';
        } else {
            listTitle.textContent = `My Tickets - ${currentFilter.replace('_', ' ').toUpperCase()}`;
        }
    }
    
    // Sort tickets: unread first, then by creation date (newest first)
    filteredTickets.sort((a, b) => {
        if (a.unreadCount > 0 && b.unreadCount === 0) return -1;
        if (a.unreadCount === 0 && b.unreadCount > 0) return 1;
        return new Date(b.createdAt) - new Date(a.createdAt);
    });
    
    if (filteredTickets.length === 0) {
        ticketsList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📝</div>
                <p>No tickets found${currentFilter !== 'all' ? ` with status "${currentFilter}"` : ''}.</p>
            </div>
        `;
        return;
    }
    
    ticketsList.innerHTML = filteredTickets.map(ticket => {
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
                <strong>Your Message:</strong><br>
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
}

/**
 * Open messages modal showing ALL conversations (inbox view)
 * Shows all tickets with messages, sorted by most recent message
 */
async function openMessagesModal() {
    const modal = document.getElementById('messages-modal');
    const messagesList = document.getElementById('messages-tickets-list');
    
    modal.classList.add('active');
    messagesList.innerHTML = '<div class="loading">Loading messages...</div>';
    
    try {
        const data = await apiRequest('/tickets/my-tickets');
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
                    <p style="margin-top: 8px; font-size: 13px;">Start a conversation by submitting a ticket or replying to an existing one.</p>
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
                // Calculate unread count
                ticket.unreadCount = messages.filter(msg => msg.sender !== 'user' && !msg.isRead).length;
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
            const senderLabel = lastMessage ? getSenderLabel(lastMessage, ticket, false) : '';
            
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

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
