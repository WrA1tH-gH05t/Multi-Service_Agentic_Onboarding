# Multi-Service Agentic Onboarding — Project Demo

This folder contains the interactive, standalone front-end walkthrough and simulation platform for the **Multi-Service Agentic Onboarding System (Moro Hub — Task 1)**.

---

## 🚀 Quick Start

Open either file directly in any modern web browser (Google Chrome, Microsoft Edge, Safari, Firefox) without any web server or package installation required:

- **`index.html`** or **`moro_hub_walkthrough.html`**
- Double-click from your file explorer or open via `file://`.

---

## 🌟 Key Features

### 1. Autonomous Walkthrough Mode
- **Scroll & Auto-Play Tour**: 10 sequential chapters illustrating end-to-end architecture (FastAPI &rarr; StorageService &rarr; MinIO Object Store &rarr; PostgreSQL Database &rarr; Vision Model).
- **Speech Synthesis AI Narration**: Multi-accent narrator support (🇬🇧 British UK, 🇺🇸 American US, 🇦🇺 Australian AU, 🇮🇳 Indian English).
- **Live Topology Stage**: Interactive node highlights showing packets, latency, encryption states, and real-time data flows.
- **Qwen 2.5-VL 7B Vision Extraction**: Demonstrating state-of-the-art multimodal vision-language document parsing with ~6.0 GB VRAM footprint and 92.9% DocVQA benchmark accuracy.

### 2. Interactive 5-Level Quest Game
- **Level 1 — Customer Authentication**: Configurable applicant credentials (passport name, email, national ID) with real-time speech synchronization and locked tenant namespace partitioning (`ae-tenant-9842`).
- **Level 2 — Service Discovery**: Multi-tier onboarding selection (Basic Registration, Family Sponsorship, Investor Visa, etc.).
- **Level 3 — Document Upload & Scan**: Simulated byte streaming, cryptographic hash computation (SHA-256), and multimodal OCR extraction.
- **Level 4 — Verification & Confirmation**: Rule validation checks and consensus matching.
- **Level 5 — Sealed Application / Protected Rollback**: Cryptographic audit seal with zero data loss guarantee.

### 3. Chaos Injection Lab
Simulate enterprise failure modes to demonstrate pipeline resilience and atomic rollbacks:
- ✂️ **Sever Socket at 70%**: Simulates premature TCP disconnect during document transmission; triggers automatic object cleanup in MinIO.
- 📏 **File Size > 50 MB (78.4 MB)**: Demonstrates HTTP 413 Payload Too Large pre-flight guardrails.
- 🪲 **Inject '../../' Traversal**: Path traversal sanitization preventing illegal directory escapes.
- ⛔ **MinIO Cluster Offline (503)**: Storage cluster circuit breaker and cooldown handling.
- **Explosion & Alert Visuals**: Full-screen shockwave, spark particles, and incident diagnostic reporting.

---

## 📦 Zero External Dependencies
- Completely self-contained single HTML file.
- Embedded SVG icons, CSS glassmorphism, responsive layout, and Web Audio API synthesizer.
