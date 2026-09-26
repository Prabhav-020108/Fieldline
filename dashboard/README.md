# FieldLine Dispatch Console (Dashboard)

A multi-tenant dispatch management console and browser-based voice interface for FieldLine, built with [Next.js](https://nextjs.org) (App Router), React 19, and Tailwind CSS.

## Features

- **Company Overview & Multi-Tenancy**: Manage isolated company data (companies, jobs, safety procedures, parts inventory).
- **Voice Dispatch UI (`/companies/[companyId]/call`)**:
  - LiveKit WebRTC client with real-time audio visualizer (`BarVisualizer`) and agent transcription feed.
  - Role-gated call interface requiring authenticated login (dispatcher, supervisor, or technician) with client-minted HMAC call-role tokens.
- **Audit Log Viewer (`/companies/[companyId]/audit`)**:
  - Real-time audit trail of every voice agent action, tool invocation, confidence score, and latency span.
  - Live indicator tracking cloud-synced vs. offline-queued entries.
- **Genuine Connectivity Indicator**:
  - 3-second live health probing to the backend dispatch server.
  - Instant transition animations reflecting cloud-connected vs. offline local operations.

## Getting Started

### 1. Install Dependencies

```bash
npm install
```

### 2. Environment Variables

Create `.env.local` (copied from `.env.example`):

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_LIVEKIT_URL=wss://fieldline-y34tzh74.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
```

### 3. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Linting & Building

```bash
# Lint code
npm run lint

# Production build
npm run build
```
