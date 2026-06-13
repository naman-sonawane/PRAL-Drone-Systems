# PRAL Drone Systems

Point a drone at a building or location — get marketing-ready aerial media with minimal input.

This repository contains the **PRAL vision docs** and a **v1 frontend demo** that walks through the full user journey against mock data. Drone acquisition (Pipeline 1) is simulated; partners will integrate real flight logic later.

## Quick start

### Prerequisites

- Node.js 18+
- npm

### Run locally

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). You'll be redirected to `/login`.

**Demo login:** enter any email and password — all credentials work.

### Build for production

```bash
npm run build
npm start
```

## Demo flow

| Step | Route | What happens |
|------|-------|--------------|
| 1 | `/login` | Fake auth, session in localStorage |
| 2 | `/` | Draw a circle on satellite map to define AOI |
| 3 | `/processing` | Simulated Pipeline 1 progress (7 stages) |
| 4 | `/clips` | Review & select mock curated clips |
| 5 | `/create` | Pick output style + social destination |
| 6 | `/preview` | Choose from mock rendered previews |
| 7 | `/export` | Fake export progress → download CTA |

## Project structure

```
docs/
  VISION.md          # System vision & pipeline architecture
  VISION_FLOW.md     # Flowchart companion
  PRD.md             # Frontend PRD (this build)

fixtures/
  index.ts           # Typed mock data (Mission, AOI, CuratedFootageSet)

src/
  app/               # Next.js pages (App Router)
  components/        # UI (map selector, cards, loaders)
  lib/
    api/             # Mock API — swap for real backend here
    types.ts         # Shared TypeScript contracts
    auth.ts          # Fake session management
    storage.ts       # Active mission persistence
```

## Architecture notes

PRAL is two decoupled pipelines connected by a **Curated Footage Set**:

1. **Pipeline 1 — Footage Acquisition** (simulated in `/processing`)
2. **Pipeline 2 — Media Processing** (simulated in `/create` → `/preview` → `/export`)

The frontend talks only to `src/lib/api/index.ts`. Replace `MockApiClient` with HTTP calls when the backend is ready — pages and types stay the same.

## Tech stack

- Next.js 15 + TypeScript
- Tailwind CSS v4
- Leaflet (satellite map, circle-to-search AOI)
- Framer Motion (micro-interactions)
- Lucide React (icons)

## Documentation

- [Vision](./docs/VISION.md) — full system design
- [Vision flow](./docs/VISION_FLOW.md) — pipeline diagrams
- [PRD](./docs/PRD.md) — frontend scope & acceptance criteria

## License

Private — PRAL Drone Systems.
