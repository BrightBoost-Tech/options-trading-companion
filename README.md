# Options Trading Companion

A sophisticated portfolio optimization platform that helps retail investors make data-driven options trading decisions using quantum-inspired algorithms, real-time market data, and AI-powered insights.

## 🎯 Project Overview

This application combines modern portfolio theory with advanced options analytics to provide:
- **Portfolio Optimization**: Quantum-inspired algorithms for risk-adjusted returns.
- **Real-time Market Data**: Live pricing via Polygon.io API.
- **Broker Integration**: Secure account connections via Plaid.
- **Trade Journal**: Foundational support for trade logging and analysis.
- **Weekly Scout**: Automated discovery of high-probability options trades.

---

## 🏗️ Architecture
```
options-trading-companion/
├── apps/
│   └── web/                    # Next.js 14 frontend
│       ├── app/
│       │   ├── (protected)/   # Authenticated routes
│       │   │   ├── dashboard/
│       │   │   ├── portfolio/
│       │   │   ├── settings/
│       │   │   ├── journal/
│       │   │   └── compose/
│       │   ├── login/
│       │   └── signup/
│       ├── components/
│       │   └── PlaidLink.tsx  # Broker connection component
│       └── lib/
│           └── supabase.ts    # Supabase client
│
└── packages/
    └── quantum/               # Python backend API
        ├── api.py            # FastAPI server
        ├── optimizer.py      # Portfolio optimization engine
        ├── plaid_service.py  # Plaid integration
        ├── polygon_client.py # Market data client
        └── .env             # Environment variables
```

---

## ✨ Features Implemented

### 1. **Portfolio Optimization Engine**
- **Surrogate Classical Solver**: Mean-variance-skew optimization for robust performance.
- **Quantum-Ready**: Optional integration with QCI Dirac-3 via `QciDiracAdapter` for advanced, skew-aware optimization (requires `QCI_API_TOKEN`).
- **Dynamic Constraints**: Automatically adjusts position limits for small portfolios to ensure mathematical solvability.
- **Diagnostic Endpoints**: Includes local and remote tests to verify the optimizer's logic.

### 2. **Real-time Market Data**
- **Polygon.io Integration**: Live stock and options pricing.
- **Mock Data Fallback**: Provides deterministic mock data for development and testing when API keys are not configured, ensuring stability.

### 3. **Broker Account Integration (Plaid)**
- **Secure Connection**: Uses Plaid Link for read-only access to brokerage accounts.
- **Automated Position Syncing**: Imports and normalizes holdings from linked accounts into the `positions` table.
- **Encrypted Storage**: Plaid access tokens are encrypted using Fernet before being stored.

### 4. **Options Analytics & Scouting**
- **Weekly Options Scout**: Scans the market for high-probability trade opportunities based on predefined criteria.
- **Expected Value (EV) Calculator**: An endpoint (`/ev`) calculates the expected value and max loss for various options strategies.

### 5. **Trade Journal (Foundational)**
- **Backend Service**: Includes a `TradeJournal` class to load, analyze, and generate statistics from a local JSON file.
- **Frontend Display**: The dashboard shows basic journal stats like win rate and total P&L.

---

## 🚀 Getting Started

### Local Startup (Windows)

If you are on Windows, you can start the entire application with one click:

1. Double-click `start_app.bat` in the root folder.
   - This opens two terminal windows (one for the API, one for the frontend).
   - The API runs on http://127.0.0.1:8000
   - The Frontend runs on http://localhost:3000

### Prerequisites

- **Node.js** 18+ and npm/pnpm
- **Python** 3.9+
- **Supabase** account (free tier works)
- **Polygon.io** API key (free tier: 5 calls/min)
- **Plaid** account (sandbox is free)

### Installation

#### 1. Clone and Install Dependencies
```bash
# Clone repository
git clone <your-repo-url>
cd options-trading-companion

# Install frontend dependencies
cd apps/web
npm install

# Install backend dependencies
cd ../../packages/quantum
pip install -r requirements.txt
```

#### 2. Set Up Environment Variables

**Frontend** (`apps/web/.env.local`):
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

**Backend** (`packages/quantum/.env`):
```env
POLYGON_API_KEY=your-polygon-key
PLAID_CLIENT_ID=your-plaid-client-id
PLAID_SECRET=your-plaid-sandbox-secret
PLAID_ENV=sandbox
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
ENCRYPTION_KEY=your-32-byte-fernet-key
# Optional for quantum optimization
QCI_API_TOKEN=your-qci-api-token
# Optional for development
APP_ENV=development
```

#### 3. Set Up Database (Supabase)

> For full schema, see `supabase/migrations/20240101000000_initial_schema.sql`.
> The core table for holdings is `positions`.

```sql
-- Positions (per-user holdings)
-- This table is the single source of truth for user holdings.
CREATE TABLE positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  qty NUMERIC NOT NULL,
  avg_price NUMERIC NOT NULL,
  greek_delta NUMERIC,
  greek_theta NUMERIC,
  greek_vega NUMERIC,
  iv_rank NUMERIC,
  updated_at TIMESTAMTz DEFAULT NOW()
);
```

#### 4. Start the Application

**Terminal 1 - Backend API:**
```bash
# From root directory
./packages/quantum/run_server.sh
# Runs on http://127.0.0.1:8000
```

**Terminal 2 - Frontend:**
```bash
cd apps/web
npm run dev
# Runs on http://localhost:3000
```

---

## 📡 API Endpoints

### Portfolio Optimization
- `POST /optimize/portfolio` - Generate an optimized portfolio based on current holdings, returning target weights and suggested trades.
- `GET /optimize/diagnostics/phase1` - Local test to verify the skew-aware optimizer logic.
- `POST /optimize/diagnostics/phase2/qci_uplink` - Live test to verify connection to QCI quantum hardware (requires `QCI_API_TOKEN`).

### Plaid Integration
- `GET /plaid/status` - Check if the current user has a connected Plaid account.
- `POST /plaid/create_link_token` - Create a Plaid Link token to initialize the connection flow.
- `POST /plaid/exchange_token` - Exchange a public token for a permanent access token and save it.
- `POST /plaid/sync_holdings` - Trigger a sync to fetch holdings from the linked Plaid item.

### Data & Analytics
- `GET /portfolio/snapshot` - Retrieve the latest cached portfolio snapshot, including holdings and risk metrics.
- `GET /holdings/export` - Export user's current holdings to a CSV file.
- `GET /scout/weekly` - Scan for weekly options trade opportunities.
- `GET /journal/stats` - Get statistics from the trade journal.
- `POST /ev` - Calculate expected value and position size for an options trade.

---

## 🎨 UI Components

### Key Pages

1. **Dashboard** (`/dashboard`)
   - **Positions**: Displays current holdings grouped by "Option Plays", "Long Term Holds", and "Cash", fetched from the latest portfolio snapshot.
   - **Portfolio Optimizer**: An interactive panel to run the backend optimizer and view suggested trades.
   - **Weekly Options Scout**: A card showing top trade ideas from the weekly scan.
   - **Trade Journal**: A card displaying key stats like win rate and P&L.

2. **Portfolio** (`/portfolio`)
   - **Holdings Table**: A detailed view of all positions with columns for quantity, cost basis, current price, and total value.
   - **Sync Button**: Manually triggers a Plaid holdings sync.

3. **Settings** (`/settings`)
   - **Broker Connection**: A simple interface for connecting and disconnecting a brokerage account using Plaid Link.

---

## 📊 Current Status

### ✅ Completed Features

- [x] FastAPI backend with CORS and rate limiting.
- [x] Next.js 14 frontend with protected routes.
- [x] Supabase authentication and database.
- [x] **Plaid broker integration** for syncing holdings.
- [x] **Portfolio optimization engine** with classical and quantum-ready solvers.
- [x] **Weekly options scout** for trade ideas.
- [x] Mock data fallbacks for stable development.
- [x] Display of positions in Dashboard and Portfolio pages.

### 🚧 In Progress / Planned

- [ ] **Advanced Options Analytics**: Display Greeks, IV rank, and other metrics per position.
- [ ] **Trade Journal Enhancements**: Move from a local JSON file to a database-backed system with a dedicated UI.
- [ ] **Historical Performance**: Track portfolio value and P&L over time with charts.
- [ ] **Plaid Production Approval**: Complete the process to use Plaid with real brokerage accounts.

---

## 🔧 Technology Stack

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Auth**: Supabase Auth

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.9+
- **Optimization**: NumPy, Pandas, SciPy
- **Data**: Polygon.io API
- **Broker**: Plaid API

### Infrastructure
- **Database**: Supabase (PostgreSQL)
- **Auth**: Supabase Auth

---

## 📝 Environment Variables Reference

### Required Variables

**Frontend (`apps/web/.env.local`):**
```env
NEXT_PUBLIC_SUPABASE_URL=          # Supabase project URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=     # Supabase anonymous key
```

**Backend (`packages/quantum/.env`):**
```env
POLYGON_API_KEY=                   # Polygon.io API key for market data
PLAID_CLIENT_ID=                   # Plaid client ID
PLAID_SECRET=                      # Plaid secret (for sandbox or production)
PLAID_ENV=sandbox                  # Plaid environment ('sandbox', 'development', or 'production')
SUPABASE_SERVICE_ROLE_KEY=         # Supabase service role key for backend access
ENCRYPTION_KEY=                    # 32-byte Fernet key for encrypting Plaid tokens
```

### Optional Variables

**Backend (`packages/quantum/.env`):**
```env
QCI_API_TOKEN=                     # API token for QCI quantum computer access
APP_ENV=development                # Set to 'development' to enable test mode features
```

---

**Last Updated**: November 25, 2024
**Version**: 2.0.0
