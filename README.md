# Fortivex AI — Empowers Academy Autonomous Sales Voice Agent

Production-architected real-time AI sales voice agent built with **LiveKit Agents 1.8**, **Hub-and-Spoke Multi-Agent Orchestration**, **2-Tier OpenAI ↔ Groq Circuit-Breaker Failover**, **Sub-5ms EdTech Hybrid RAG**, **Cal.com API v2 Live Booking**, and a **FastAPI + SQLite CRM Insights Dashboard**.

## System Architecture

```text
[Browser WebRTC / PSTN SIP Trunk (Scale)]
                │
       LiveKit Cloud SFU
                │
   Python Multi-Agent Voice Worker
   ├─ 2-Tier Failover: OpenAI (gpt-4.1-mini / transcribe / tts)
   │                ──▶ Groq LPU (openai/gpt-oss-20b / whisper-turbo / orpheus-tts)
   └─ Hub-and-Spoke Agents (Shared CallState):
       ├─ Main Orchestrator (Intent Router, Sentiment, Wrap-up)
       ├─ Lead Qualifier (EdTech BANT 0-100 Scoring)
       ├─ RAG Course Advisor (Empowers Academy Catalog Grounding)
       └─ Booking & CRM Agent (Cal.com v2 Slots & Confirmed Booking)
                │
   ┌────────────┴────────────┐
   ▼                         ▼
Cal.com v2 API     FastAPI Web Console & CRM (/ & /dashboard)
