# 🤖 AI Helpdesk – Intelligent Knowledge-Driven IT Support Platform

AI Helpdesk is a multi-tenant, AI-powered internal support system designed to reduce IT workload, automate repetitive troubleshooting, and continuously improve organizational knowledge.

This platform combines structured knowledge base automation, smart ticket handling, analytics tracking, and CI/CD deployment pipelines to deliver a production-ready support solution.

---

# 🚀 Overview

AI Helpdesk is built to solve one major problem:

> IT teams spend too much time resolving repetitive, recurring issues.

Instead of repeatedly answering the same tickets, this system:

- Automatically responds to tickets using existing knowledge base articles
- Escalates unresolved issues to support admins
- Learns from resolved tickets
- Suggests new knowledge base articles from recurring ticket patterns
- Reduces repeated IT workload by up to 80%

---

# 🏗 Architecture Overview

Frontend:
- Static HTML, CSS, JavaScript
- Hosted on Firebase Hosting

Backend:
- Python (FastAPI)
- Deployed on Render

Database:
- Firebase Firestore (multi-tenant architecture)

CI/CD:
- GitHub Actions
- Dev preview channel (Firebase)
- Production deployment (main branch)

---

# 🧠 Core Features

---

##Multi-Tenant Organization Model

Each organization is fully isolated.

- Users log in using:
  - Organization Code
  - Email
  - Password

No organization can access another organization’s data.

---

##Role-Based Access Control (RBAC)

### 👑 Super Admin
- Creates organization
- Generates organization code
- Creates Support Admin accounts
- Creates Employee accounts
- Disables / deletes accounts
- Monitors system activity logs
- Runs Knowledge Improvement analysis
- Approves or rejects AI-suggested knowledge articles

### 🛠 Support Admin
- Views assigned tickets
- Chats with users
- Resolves escalated tickets
- Manages ticket workflow

### 👨‍💼 Employee (User)
- Submits tickets
- Chats with AI
- Escalates to support
- Views ticket status (Open / In Progress / Escalated / Closed)

---

##AI-Powered Knowledge Base Engine

The system does NOT rely on generic AI responses.

Instead:

- All answers are generated strictly from the organization’s knowledge base.
- If a ticket matches a KB article:
  - AI sends structured article response
  - User can confirm resolution
  - If unresolved → escalates to support

No external AI hallucinations.
All answers remain organization-scoped.

---

##Automatic Knowledge Improvement System

One of the most powerful features.

### How It Works:

1. Tickets are escalated.
2. Support resolves them.
3. System tracks recurring resolved ticket patterns.
4. If similar tickets ≥ threshold:
   - System clusters them via semantic similarity.
   - Generates a draft knowledge base suggestion.
5. Super Admin reviews and approves/rejects.

Approved articles:
- Automatically added to Knowledge Base.
- Used for future automated responses.

Rejected articles:
- Logged and not regenerated as drafts.
- Marked as “previously rejected” for historical tracking.

This transforms human resolution into reusable automation.

---

##Ticket Lifecycle Management

Ticket statuses:

- Open
- In Progress
- Escalated
- Resolved
- Closed

Workflow:

1. Employee submits ticket.
2. AI checks knowledge base.
3. If article exists → sends full structured solution.
4. User confirms:
   - ✔ Resolved → Ticket closes.
   - ❌ Not resolved → Escalates.
5. Support Admin resolves.
6. Ticket marked closed.

---

##Real-Time Chat System

- User ↔ AI
- User ↔ Support Admin
- Support ↔ User threaded communication
- Message notifications
- Unread count tracking
- Mobile-optimized interface

---

##Organization Activity Monitoring

Super Admin can monitor:

- User login attempts
- Failed login attempts
- Ticket submissions
- Escalations
- Page clicks
- Admin actions
- Suspicious behavior (brute force attempts)

Filterable by:
- Date
- Action type
- User role
- IP address

This provides internal audit-level visibility.

---

##Analytics Dashboard

Includes:

- Pie charts (Resolved / Escalated / In Progress)
- Bar charts (Ticket trends over time)
- Recurring issue metrics (last 30 days)
- Suggested knowledge articles count

---

##CI/CD & Dev Environment

This project uses branch-based deployment strategy.

### 🌿 Dev Branch
- Deploys to Firebase Preview Channel
- Has its own backend environment
- Used for testing new features
- Safe experimentation without affecting production

### 🚀 Main Branch
- Production deployment
- Live Firebase hosting
- Stable backend environment

Deployment Flow:


Work on dev → Test in preview → Merge to main → Auto deploy to production


GitHub Actions handles:
- Firebase hosting deployment
- Environment separation
- Secure secret management

---

# 🔐 Security Features

- Rate limiting (IP + user based)
- Strict input validation
- Environment-based API key management
- Firestore security rules
- Multi-tenant data isolation
- Secure role enforcement
- Activity logging for audit trails

---

# 📱 Mobile Optimization

- Responsive layout
- Toggleable sidebar
- Optimized ticket list view
- Activity logs formatted for small screens
- Compact action buttons for mobile

---

# 💼 Business Impact

This platform helps organizations:

- Reduce IT support workload
- Eliminate repetitive troubleshooting
- Automate common issues
- Build internal knowledge automatically
- Track system usage
- Improve IT response times
- Prevent recurring incidents

Instead of reactive support, organizations move toward proactive automation.

---

# 🛠 Tech Stack

- Python (FastAPI)
- Firebase Firestore
- Firebase Hosting
- GitHub Actions (CI/CD)
- Render (Backend Hosting)
- HTML / CSS / JavaScript
- Semantic clustering for ticket pattern detection

---

# 📌 Future Improvements

- AI confidence scoring
- Advanced anomaly detection
- Slack / Teams integration
- Email-to-ticket ingestion
- Predictive ticket analytics

---

# 👨‍💻 Author

Built as part of advanced academic and independent AI systems engineering exploration.

This project demonstrates how AI, when structured correctly, can reduce operational overhead rather than create noise.

---