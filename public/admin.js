/**
 * Admin Dashboard JavaScript
 */
import { auth, apiRequest } from "./firebase-config.js";
import { onAuthStateChanged, signOut } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

let currentUser = null;

// Check authentication
onAuthStateChanged(auth, async (user) => {
    if (!user) {
        window.location.href = 'login.html';
        return;
    }
    
    currentUser = user;
    
    try {
        // Get user info
        const userData = await apiRequest('/auth/me');
        
        // Check if user is admin (employees should not access admin dashboard)
        if (userData.role !== 'admin') {
            alert('Access denied. Administrator privileges required. Your role: ' + (userData.role || 'employee'));
            window.location.href = 'submit-ticket.html';
            return;
        }
        
        // Display user email and avatar
        const userEmail = userData.email;
        document.getElementById('user-email').textContent = userEmail;
        const avatar = document.getElementById('user-avatar');
        avatar.textContent = userEmail.charAt(0).toUpperCase();
        
        // Load initial data
        loadKnowledgeBase();
        loadAllTickets();
        loadEscalatedTickets();
        
        // Setup messages icon click handler
        document.getElementById('messages-icon-btn')?.addEventListener('click', () => {
            openMessagesModal();
        });
        
    } catch (error) {
        console.error('Error loading user data:', error);
        showError('Failed to load user data');
    }
});

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
        // 3) Article "View" button
        const viewBtn = e.target.closest('.view-article-btn');
        if (viewBtn && viewBtn.dataset.articleId) {
            e.preventDefault();
            openArticleViewModal(viewBtn.dataset.articleId);
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
    
    // Ticket modal body: delegation for Update status button (dynamic content)
    document.getElementById('ticket-modal')?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="update-ticket-status"]');
        if (btn && btn.dataset.ticketId) updateTicketStatus(btn.dataset.ticketId);
    });
    
    // Logout handler
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await signOut(auth);
                window.location.href = 'index.html';
            } catch (error) {
                console.error('Logout error:', error);
                showError('Failed to logout');
            }
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
            if (tabName === 'all-tickets') {
                loadAllTickets();
            } else if (tabName === 'escalated-tickets') {
                loadEscalatedTickets();
            }
        });
    });
    
    // Status filter handler
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) {
        statusFilter.addEventListener('change', () => {
            window.currentTicketFilter = statusFilter.value;
            loadAllTickets();
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
        
        // Reload ticket lists to update unread counts and message icon badge
        await loadAllTickets();
        loadEscalatedTickets();
        
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

// Knowledge Base Form Handler
document.getElementById('kb-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const title = document.getElementById('kb-title').value;
    const content = document.getElementById('kb-content').value;
    
    try {
        await apiRequest('/knowledge-base', {
            method: 'POST',
            body: JSON.stringify({ title, content })
        });
        
        showSuccess('Article saved successfully!');
        document.getElementById('kb-form').reset();
        loadKnowledgeBase();
        
    } catch (error) {
        showError(`Failed to save article: ${error.message}`);
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
                    <p style="margin-top: 8px; font-size: 13px;">Create your first article above to help AI resolve tickets.</p>
                </div>
            `;
            return;
        }
        
        articlesList.innerHTML = articles.map(article => `
            <div class="article-card" data-article-id="${article.id}">
                <h3>${escapeHtml(article.title)}</h3>
                <p>${escapeHtml(article.content.length > 200 ? article.content.substring(0, 200) + '...' : article.content)}</p>
                <div class="meta">
                    Created: ${new Date(article.createdAt).toLocaleString()}
                    ${article.updatedAt ? ` | Updated: ${new Date(article.updatedAt).toLocaleString()}` : ''}
                </div>
                <div style="margin-top: 12px; display: flex; gap: 8px;">
                    <button type="button" class="btn btn-primary view-article-btn" data-article-id="${article.id}">View</button>
                    <button type="button" class="btn btn-danger delete-article-btn" data-article-id="${article.id}">Delete</button>
                </div>
            </div>
        `).join('');
        
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
 * Load all tickets (admin view)
 */
async function loadAllTickets() {
    const ticketsList = document.getElementById('all-tickets-list');
    if (!ticketsList) return;
    
    ticketsList.innerHTML = '<div class="loading">Loading tickets...</div>';
    
    try {
        const data = await apiRequest('/tickets');
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
        
        // Apply status filter (from dropdown or stat card)
        const statusFilter = document.getElementById('status-filter')?.value || window.currentTicketFilter || 'all';
        if (statusFilter !== 'all') {
            if (statusFilter === 'resolved') {
                tickets = tickets.filter(t => t.status === 'resolved' || t.status === 'auto_resolved');
            } else if (statusFilter === 'escalated') {
                // Use escalated field, not status
                tickets = tickets.filter(t => t.escalated === true);
            } else {
                tickets = tickets.filter(t => t.status === statusFilter);
            }
        }
        
        // Update list title
        const listTitle = document.getElementById('tickets-list-title');
        if (listTitle) {
            if (statusFilter === 'all') {
                listTitle.textContent = 'All Tickets';
            } else {
                listTitle.textContent = `All Tickets - ${statusFilter.replace('_', ' ').toUpperCase()}`;
            }
        }
        
        // Update count badge
        const allTicketsCount = document.getElementById('all-tickets-count');
        if (allTicketsCount) {
            allTicketsCount.textContent = tickets.length;
            allTicketsCount.style.display = tickets.length > 0 ? 'inline-flex' : 'none';
        }
        
        if (tickets.length === 0) {
            ticketsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📝</div>
                    <p>No tickets found${statusFilter !== 'all' ? ` with status "${statusFilter}"` : ''}.</p>
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
        currentArticleData = { id: null, title: null, content: null, createdAt: null, updatedAt: null };
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
function openArticleViewModal(articleId, title, content, createdAt, updatedAt) {
    if (arguments.length === 1) {
        const article = currentArticles.find(a => a.id === articleId);
        if (!article) {
            console.error('Article not found:', articleId);
            return;
        }
        openArticleViewModal(article.id, article.title, article.content, article.createdAt, article.updatedAt || '');
        return;
    }
    // Store article data for potential editing
    currentArticleData = {
        id: articleId,
        title: title.replace(/\\'/g, "'"),
        content: content.replace(/\\n/g, '\n').replace(/\\'/g, "'"),
        createdAt: createdAt,
        updatedAt: updatedAt
    };
    
    // Set modal title
    document.getElementById('article-modal-title').textContent = 'Knowledge Base Article';
    
    // Populate view mode
    document.getElementById('article-view-title').textContent = currentArticleData.title;
    document.getElementById('article-view-content').textContent = currentArticleData.content;
    
    // Set metadata
    let metaText = `Created: ${new Date(createdAt).toLocaleString()}`;
    if (updatedAt) {
        metaText += ` | Updated: ${new Date(updatedAt).toLocaleString()}`;
    }
    document.getElementById('article-view-meta').textContent = metaText;
    
    // Show view mode, hide edit mode
    document.getElementById('article-view-mode').style.display = 'block';
    document.getElementById('article-edit-mode').style.display = 'none';
    document.getElementById('article-view-buttons').style.display = 'flex';
    document.getElementById('article-edit-buttons').style.display = 'none';
    
    // Open modal (article-modal is the overlay id)
    const modal = document.getElementById('article-modal');
    if (!modal) return console.error('Modal not found: article-modal');
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
    
    // Populate edit form with current data
    document.getElementById('edit-article-id').value = currentArticleData.id;
    document.getElementById('edit-article-title').value = currentArticleData.title;
    document.getElementById('edit-article-content').value = currentArticleData.content;
    
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
    
    // Update metadata
    let metaText = `Created: ${new Date(currentArticleData.createdAt).toLocaleString()}`;
    if (currentArticleData.updatedAt) {
        metaText += ` | Updated: ${new Date(currentArticleData.updatedAt).toLocaleString()}`;
    }
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
    
    if (!title || !content) {
        showError('Title and content are required');
        return;
    }
    
    try {
        await apiRequest(`/knowledge-base/${articleId}`, {
            method: 'PUT',
            body: JSON.stringify({ title, content })
        });
        
        showSuccess('Article updated successfully!');
        
        // Update current article data
        currentArticleData.title = title;
        currentArticleData.content = content;
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
        
        // Reload ticket modal and ticket lists
        await openTicketModal(ticketId);
        loadAllTickets();
        loadEscalatedTickets();
        
    } catch (error) {
        showError(`Failed to update status: ${error.message}`);
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
