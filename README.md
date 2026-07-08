---
title: FRRMS - Flood Rescue & Resource Management System
emoji: 🌊
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# FRRMS — Flood Rescue & Resource Management System

An end-to-end disaster response platform for coordinating flood rescue operations across Bangladesh — built for real-world district-level data, not simulated GPS precision.

**Core features:**
- 🚨 Real-time incident, victim, and shelter tracking across districts
- 🧭 **Smart Rescue Routing** — matches missing/at-risk victims to the nearest active rescue unit using real haversine distance between district centroids, prioritized by urgency
- ⚖️ **Volunteer AI Balancing** — redirects pending volunteer requests toward districts with the highest unmet need (live flood risk weighted against current coverage)
- 📦 Resource inventory and shelter capacity management with low-stock alerts
- 🗺️ Public flood risk map for citizens, with role-based dashboards for admins, coordinators, and field personnel

Every AI-assisted suggestion in this system is a **decision-support recommendation** — a human coordinator always reviews and confirms before anything is dispatched. Nothing is auto-executed.

Built with FastAPI, PostgreSQL, and Jinja2.