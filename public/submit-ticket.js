/**
 * Submit Ticket Page JavaScript — backend API only, no Firebase client SDK.
 */
import { apiRequest, clearToken, isAuthenticated } from "./api.js";

let currentUser = null;

// Check authentication (token-based)
(async function initAuth() {
    if (!isAuthenticated()) {
        window.location.href = "login.html";
        return;
    }
    try {
        const userData = await apiRequest("/auth/me");
        if (userData.role === "admin") {
            window.location.href = "admin.html";
            return;
        }
        currentUser = userData;
        document.getElementById("user-email").textContent = userData.email || "";
        const avatar = document.getElementById("user-avatar");
        if (avatar) avatar.textContent = (userData.email || "U").charAt(0).toUpperCase();
        loadMyTickets();
        document.querySelector('[data-tab="my-tickets"]')?.click();
        document.getElementById("messages-icon-btn")?.addEventListener("click", () => openMessagesModal());
    } catch (err) {
        console.error("Error loading user data:", err);
        showError("Failed to load user data");
        clearToken();
        window.location.href = "login.html";
    }
})();

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
            window.location.href = "login.html";
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
                
                if (ticket.ai_mode === 'guided') {
                    responseContent.innerHTML = `
                        <div class="alert alert-success">
                            <strong>✅ Step-by-step help</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">We'll guide you through this. Check the conversation below and reply to continue.</p>
                        </div>
                        <p style="margin-top: 12px; color: var(--text-secondary);">Your ticket is open. Use the conversation in the window that just opened, or find it under "My Tickets".</p>
                    `;
                    document.getElementById('ticket-form').reset();
                    loadMyTickets();
                    openTicketModal(ticket.id);
                    return;
                }
                
                if (ticket.status === 'auto_resolved') {
                    responseContent.innerHTML = `
                        <div class="alert alert-success">
                            <strong>✅ Issue Resolved Automatically</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">
                                Confidence: <strong>${(ticket.confidence * 100).toFixed(1)}%</strong>
                                ${ticket.knowledge_used && ticket.knowledge_used.length > 0 ? 
                                    ` | Based on: ${ticket.knowledge_used.join(', ')}` : ''}
                            </p>
                        </div>
                        <div class="ai-reply">
                            <h4>AI Solution</h4>
                            <p>${escapeHtml(ticket.aiReply || 'No solution provided.')}</p>
                        </div>
                    `;
                } else {
                    responseContent.innerHTML = `
                        <div class="alert alert-warning">
                            <strong>⚠️ Ticket Escalated</strong>
                            <p style="margin-top: 8px; margin-bottom: 0;">Your ticket has been escalated to our support team for review.</p>
                        </div>
                        <div style="margin-top: 16px;">
                            ${ticket.category ? `<p><strong>Category:</strong> <span class="badge badge-neutral">${ticket.category}</span></p>` : ''}
                            ${ticket.summary ? `<p style="margin-top: 8px;"><strong>Summary:</strong> ${escapeHtml(ticket.summary)}</p>` : ''}
                        </div>
                        <p style="margin-top: 16px; color: var(--text-secondary);">Our support team will review your ticket and get back to you soon. You can check the status in the "My Tickets" tab.</p>
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
                filteredTickets = tickets.filter(t => t.status === 'resolved' || t.status === 'auto_resolved');
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
            const statusClass = ticket.status === 'auto_resolved' ? 'badge-success' : 
                               ticket.status === 'resolved' ? 'badge-success' :
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
                    <strong>Your Message:</strong><br>
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

function hideMessages() {
    document.getElementById('error-message').style.display = 'none';
    document.getElementById('success-message').style.display = 'none';
}

// Store current ticket data for messaging
let currentUserTicketData = null;

/**
 * Open ticket detail modal with conversation thread (user view)
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
        // Get user's tickets to find the one we need
        const data = await apiRequest('/tickets/my-tickets');
        const tickets = data.tickets || [];
        const ticket = tickets.find(t => t.id === ticketId);
        
        if (!ticket) {
            modalBody.innerHTML = '<p class="error-message">Ticket not found</p>';
            return;
        }
        
        // Store ticket data for messaging
        currentUserTicketData = ticket;
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
                    <div class="message-sender">You</div>
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
                const senderLabel = msg.sender === 'user' ? 'You' : 
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
        
        const isGuided = ticket.ai_mode === 'guided';
        modalBody.innerHTML = `
            <div class="ticket-detail-section">
                <h3>Status</h3>
                <div class="badge-group">
                    <span class="badge ${ticket.resolved || ticket.status === 'resolved' || ticket.status === 'auto_resolved' ? 'badge-success' : 'badge-warning'}">${(ticket.status || '').replace('_', ' ').toUpperCase()}</span>
                    ${ticket.category ? `<span class="badge badge-neutral">${ticket.category}</span>` : ''}
                    ${!isGuided && ticket.confidence !== undefined ? `<span class="badge badge-info">${(ticket.confidence * 100).toFixed(1)}% Confidence</span>` : ''}
                    ${isGuided ? '<span class="badge badge-info">Step-by-step</span>' : ''}
                </div>
            </div>
            
            ${!isGuided && ticket.summary ? `
            <div class="ticket-detail-section">
                <h3>Summary</h3>
                <p>${escapeHtml(ticket.summary)}</p>
            </div>
            ` : ''}
            
            <div class="ticket-detail-section">
                <h3>Conversation</h3>
                <div class="conversation-thread" id="ticket-conversation-thread">
                    ${conversationHtml || '<div class="conversation-empty">No messages yet</div>'}
                </div>
                <div class="typing-indicator" id="ticket-typing-indicator" style="display: none;" aria-live="polite">
                    <span class="typing-dots"></span> AI is typing...
                </div>
            </div>
            
            ${!isGuided && ticket.knowledge_used && ticket.knowledge_used.length > 0 ? `
            <div class="ticket-detail-section">
                <h3>Based on Knowledge Base</h3>
                <p>${ticket.knowledge_used.join(', ')}</p>
            </div>
            ` : ''}
            
            ${ticket.status === 'needs_escalation' ? `
            <div class="ticket-detail-section">
                <h3>Status Update</h3>
                <div class="alert alert-warning">
                    This ticket has been escalated to our support team. They will review it and get back to you soon.
                </div>
            </div>
            ` : ''}
            
            <div class="ticket-detail-section">
                <h3>Submitted</h3>
                <p>${new Date(ticket.createdAt).toLocaleString()}</p>
            </div>
        `;
        
        // Show message input for users (hide when ticket is resolved)
        const isResolved = ticket.resolved === true || ticket.status === 'resolved' || ticket.status === 'auto_resolved';
        messageInputArea.style.display = isResolved ? 'none' : 'block';
        
        // Scroll to bottom of conversation
        const conversationThread = modalBody.querySelector('#ticket-conversation-thread');
        if (conversationThread) {
            conversationThread.scrollTop = conversationThread.scrollHeight;
        }
        
        // Mark messages as read when viewing
        try {
            await apiRequest(`/tickets/${ticketId}/messages/read`, {
                method: 'POST'
            });
            // Reload tickets to update unread counts and message icon badge
            await loadMyTickets();
        } catch (error) {
            console.error('Error marking messages as read:', error);
        }
        
    } catch (error) {
        modalBody.innerHTML = `<p class="error-message">Error loading ticket: ${error.message}</p>`;
    }
}

/**
 * Close ticket detail modal
 */
function closeTicketModal() {
    const overlay = document.getElementById('ticket-modal');
    if (overlay) closeModal(overlay);
}

/**
 * Append a message bubble to the ticket conversation thread (for guided flow live updates)
 */
function appendMessageToTicketThread(sender, message, createdAt) {
    const thread = document.getElementById('ticket-conversation-thread');
    if (!thread) return;
    const emptyEl = thread.querySelector('.conversation-empty');
    if (emptyEl) emptyEl.remove();
    const senderLabel = sender === 'user' ? 'You' : sender === 'admin' ? 'Admin' : 'AI Assistant';
    const time = createdAt ? new Date(createdAt).toLocaleString() : new Date().toLocaleString();
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
                    currentUserTicketData = currentUserTicketData || {};
                    currentUserTicketData.messages = (currentUserTicketData.messages || []).concat(
                        { sender: 'user', message: messageText, createdAt: new Date().toISOString() },
                        data.ai_reply
                    );
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
            filteredTickets = tickets.filter(t => t.status === 'resolved' || t.status === 'auto_resolved');
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
                <strong>Your Message:</strong><br>
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
            const senderLabel = lastMessage && lastMessage.sender === 'user' ? 'You' : 
                               lastMessage && lastMessage.sender === 'admin' ? 'Admin' : 'AI Assistant';
            
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

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
