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
│       │   │   ├── journal/   # <-- New
│       │   │   └── compose/   # <-- New
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
        ├── trade_journal.py  # Trade journal logic
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
- **Position Size Calculator**: A `/position-size` endpoint provides trade size suggestions using the Half-Kelly Criterion.

### 5. **Trade Journal & Nested Learning**
- **Database-Backed Journal**: Trades are stored in the database, not a local JSON file, enabling persistent, per-user logging.
- **Guardrails System**: Users can define custom risk rules (e.g., "no earnings plays," "max loss per trade") that are stored in the `rules_guardrails` table.
- **AI-Powered Loss Review**: A system (`loss_reviews` table) to analyze losing trades, identify root causes, and suggest new guardrails, creating a feedback loop for continual learning.
- **Frontend Display**: The dashboard and a dedicated journal page display key statistics and trade history.

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
# -- Required --
POLYGON_API_KEY=your-polygon-key
PLAID_CLIENT_ID=your-plaid-client-id
PLAID_SECRET=your-plaid-sandbox-secret
PLAID_ENV=sandbox # Or 'development', 'production'
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
ENCRYPTION_KEY=your-32-byte-fernet-key # See below for generation command

# -- Optional for AI / Quantum Features --
QCI_API_TOKEN=your-qci-api-token
GEMINI_API_KEY=your-google-gemini-key # For AI-powered loss reviews

# -- Optional for Development --
APP_ENV=development # Enables test users and other dev-only features
```

To generate a valid `ENCRYPTION_KEY`, run the following command from the project root:
```bash
# Activate virtual environment first
source packages/quantum/venv/bin/activate
# Generate key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### 3. Set Up Database (Supabase)

> For full schema, see `supabase/migrations/20240101000000_initial_schema.sql`.

The database schema is designed to support real-time portfolio tracking, trade journaling, and a nested-learning feedback loop.

### Core Tables

**1. `positions`**: The single source of truth for a user's current holdings, synced from their broker via Plaid.
```sql
CREATE TABLE positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  quantity NUMERIC NOT NULL,
  cost_basis NUMERIC NOT NULL,
  current_price NUMERIC,
  currency TEXT,
  source TEXT DEFAULT 'plaid', -- Data source (e.g., plaid, csv)
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, symbol)
);
```

**2. `trades`**: An immutable log of all trading activity, forming the backbone of the journal.
```sql
CREATE TABLE trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  open_ts TIMESTAMPTZ NOT NULL,
  close_ts TIMESTAMPTZ,
  pnl_pct NUMERIC,
  legs_json JSONB NOT NULL, -- Details of the options legs
  thesis_json JSONB,        -- User's rationale for the trade
  market_snapshot_json JSONB -- Market conditions at time of entry
);
```

**3. `rules_guardrails`**: A user-defined set of risk management rules that the system can check against.
```sql
CREATE TABLE rules_guardrails (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rule_key TEXT NOT NULL,      -- e.g., "NO_EARNINGS_HOLDS"
  rule_text TEXT NOT NULL,     -- "Avoid holding positions through earnings reports."
  priority TEXT NOT NULL,      -- 'low', 'medium', 'high'
  enabled BOOLEAN DEFAULT TRUE,
  UNIQUE(user_id, rule_key)
);
```

**4. `loss_reviews`**: The "learning" part of the loop, where AI analyzes losing trades and suggests new guardrails.
```sql
CREATE TABLE loss_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
  root_cause TEXT NOT NULL,            -- e.g., "Held through earnings"
  evidence_json JSONB NOT NULL,        -- Data supporting the cause
  recommended_rule_json JSONB NOT NULL, -- A new rule suggested by the AI
  confidence NUMERIC NOT NULL          -- AI's confidence in the analysis
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
- `GET /plaid/status` - Check if the current user has a connected Plaid account by checking for a valid access token in the `user_settings` table.
- `POST /plaid/create_link_token` - Create a Plaid Link token to initialize the connection flow.
- `POST /plaid/exchange_public_token` - Exchange a public token for a permanent, encrypted access token and save it.
- `POST /plaid/sync_holdings` - Trigger a sync to fetch holdings from the linked Plaid item, upsert them into the `positions` table, and create a new portfolio snapshot.

### Data & Analytics
- `GET /portfolio/snapshot` - Retrieve the latest portfolio snapshot from the `portfolio_snapshots` table. It includes holdings with calculated P&L and risk metrics.
- `GET /holdings/export` - Export user's current holdings from the `positions` table to a CSV file.
- `GET /scout/weekly` - Scan for weekly options trade opportunities.
- `GET /journal/stats` - Get statistics and risk-rule analysis from the `trades` and `rules_guardrails` tables.
- `POST /ev` - Calculate expected value for an options trade.
- `POST /position-size` - Calculate optimal position size using the Half-Kelly Criterion to balance risk and reward.

---

## 🎨 UI Components

### Key Pages

1. **Dashboard** (`/dashboard`)
   - **Layout**: The dashboard is organized with the most critical components—`Positions` and `Portfolio Optimizer`—at the top.
   - **Positions**: Displays current holdings grouped by "Option Plays", "Long Term Holds", and "Cash", fetched from the `/portfolio/snapshot` endpoint.
   - **Portfolio Optimizer**: An interactive panel to run the backend optimizer and view suggested trades based on risk tolerance and market outlook.
   - **Weekly Options Scout**: A card showing top trade ideas from the weekly market scan (`/scout/weekly`).
   - **Trade Journal**: A summary card displaying key stats like win rate and total P&L from the `/journal/stats` endpoint.

2. **Portfolio** (`/portfolio`)
   - **Holdings Table**: A detailed, sortable view of all positions with columns for quantity, cost basis, current price, and total value.
   - **Sync Button**: Manually triggers a Plaid holdings sync via the `/plaid/sync_holdings` endpoint.

3. **Journal** (`/journal`)
   - **Trade History**: A complete log of all trades, filterable by symbol, strategy, and date.
   - **Performance Analytics**: Visualizations of P&L over time, win rate by strategy, and other key metrics.
   - **Guardrail Management**: An interface to view, add, and disable the trading rules that are actively protecting the account.

4. **Settings** (`/settings`)
   - **Broker Connection**: A simple interface for connecting and disconnecting a brokerage account using Plaid Link.
   - **Learning Configuration**: Toggles and settings for the nested learning and AI loss-review features.

---

## 📊 Current Status

### ✅ Completed Features

- [x] **Core Architecture**: FastAPI backend, Next.js 14 frontend, and Supabase for auth/database.
- [x] **Plaid Broker Integration**: Securely link brokerage accounts to sync holdings in real-time.
- [x] **Portfolio Optimization Engine**: Includes both classical and quantum-ready solvers for generating trade recommendations.
- [x] **Market Data & Analytics**: Real-time pricing from Polygon.io, an EV calculator, and a position size tool.
- [x] **Database-Backed Trade Journal**: Log trades to a persistent database for analysis.
- [x] **Nested Learning System**:
    - [x] **Guardrails**: Define custom risk rules to guide trading decisions.
    - [x] **AI Loss Review**: An AI-powered system analyzes losses and suggests new rules to improve over time.
- [x] **Comprehensive UI**: Dashboard, Portfolio, and Journal pages to view data and manage features.

---

## 🚀 Roadmap & What's Next

With a robust foundation for portfolio tracking, optimization, and journaling, the focus now shifts to deepening the analytical capabilities and preparing for a production environment.

### Phase 1: Deepen Analytics & User Experience
- **Advanced Options Analytics**: Integrate and display Greeks (Delta, Gamma, Theta, Vega), IV Rank, and other key options metrics for each position in the portfolio.
- **Historical Performance Tracking**: Develop backend services and frontend charts to track and visualize portfolio value, P&L, and key metrics over time.
- **Enhanced Journal UI**: While the core journal is functional, future enhancements will include rich text editing for trade theses, advanced filtering (e.g., by market conditions at entry), and a dedicated view for visualizing the impact of specific guardrails on performance.

### Phase 2: Production Readiness
- **Plaid Production Approval**: Complete the official Plaid application process to enable connections to live brokerage accounts.
- **Multi-User Scaling & Security**: Implement robust, scalable multi-tenancy, and conduct a thorough security audit of all authentication and data-handling services.
- **End-to-End Testing**: Expand the testing suite to include comprehensive end-to-end tests for all critical user flows, from Plaid connection to trade optimization and journaling.

### Phase 3: Advanced Features & Intelligence
- **Proactive Guardrail Alerts**: Implement a system to proactively alert users when a potential trade or existing position violates one of their defined guardrails.
- **Strategy Backtesting Engine**: Build a service that allows users to backtest their trading strategies and guardrails against historical market data.
- **Smarter Scouting**: Enhance the "Weekly Scout" with more sophisticated models, potentially incorporating user-specific data from their journal and risk profile.

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
