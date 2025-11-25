# Options Trading Companion

A sophisticated portfolio optimization platform that helps retail investors make data-driven options trading decisions using quantum-inspired algorithms, real-time market data, and AI-powered insights.

## 🎯 Project Overview

This application combines modern portfolio theory with advanced options analytics to provide:
- **Portfolio Optimization**: Quantum-inspired algorithms for risk-adjusted returns
- **Real-time Market Data**: Live pricing via Polygon.io API
- **Options Analysis**: Greeks calculations and strategy recommendations
- **Broker Integration**: Secure account connections via Plaid
- **Trade Journal**: AI-powered learning from past trades
- **Weekly Scout**: Automated discovery of high-probability options trades

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
- Mean-variance optimization using `scipy`
- Risk-adjusted portfolio suggestions
- Support for multiple portfolio types (growth, value, dividend, etc.)
- Real-time Sharpe ratio calculations

### 2. **Real-time Market Data**
- Integration with Polygon.io for live stock prices
- Options chain data retrieval
- Historical data analysis
- Support for 10+ ticker symbols

### 3. **Broker Account Integration** ⭐ *Just Completed!*
- Secure connection via Plaid Link
- Read-only access to brokerage accounts
- Automatic position imports
- Support for:
  - Robinhood
  - TD Ameritrade
  - Fidelity
  - Schwab
  - E*TRADE
  - And 12,000+ other institutions

### 4. **Options Analytics**
- Greeks calculations (Delta, Gamma, Theta, Vega)
- Implied volatility analysis
- Strategy recommendations
- Risk/reward profiling

### 5. **Trade Journal with AI Learning**
- Record and track all trades
- AI-powered pattern recognition
- Performance analytics
- Personalized insights based on history

### 6. **Weekly Options Scout**
- Automated scanning for high-probability trades
- Filters based on:
  - Volume
  - Open interest
  - IV rank
  - Technical indicators
- Customizable criteria

### 7. **Compose Trade** 🆕
- AI-powered trade validation
- Strategy gating checks
- Smart alternative suggestions
- Risk validation before submission

---

## 🚀 Getting Started

### Local Startup (Windows)

If you are on Windows, you can start the entire application with one click:

1. Double-click `start_app.bat` in the root folder.
   - This opens two terminal windows (one for the API, one for the frontend).
   - The API runs on http://localhost:8000
   - The Frontend runs on http://localhost:3000

### Prerequisites

- **Node.js** 18+ and pnpm
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
pnpm install

# Install backend dependencies
cd ../../packages/quantum
pip install -r requirements.txt --break-system-packages
```

#### 2. Set Up Environment Variables

**Frontend** (`apps/web/.env.local`):
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_POLYGON_API_KEY=your-polygon-key
```

**Backend** (`packages/quantum/.env`):
```env
POLYGON_API_KEY=your-polygon-key
PLAID_CLIENT_ID=your-plaid-client-id
PLAID_SECRET=your-plaid-sandbox-secret
PLAID_ENV=sandbox
```

#### 3. Set Up Database (Supabase)

> For full schema, see `supabase/migrations/20240101000000_initial_schema.sql`.
> Below is a simplified excerpt of the core tables.

```sql
-- App-level users (Supabase Auth users live in auth.users)
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Positions (per-user holdings)
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
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades (per-user trade history)
CREATE TABLE trades (...);

-- Settings (quantum mode, LLM budget, etc.)
CREATE TABLE settings (...);
```

#### 4. Start the Application

**Terminal 1 - Backend API:**
```bash
cd packages/quantum
python api.py
# Runs on http://localhost:8000
```

**Terminal 2 - Frontend:**
```bash
cd apps/web
pnpm dev
# Runs on http://localhost:3000
```

---

## 📡 API Endpoints

### Portfolio Optimization
- `POST /optimize` - Generate optimized portfolio
- `POST /compare` - Compare multiple strategies
- `POST /portfolio/snapshot` - Get portfolio state
- `GET /holdings/export` - Export holdings to CSV

### Market Data
- `GET /quote/{symbol}` - Real-time quote
- `POST /optimize/real` - Optimization with real market data
- `POST /compare/real` - Strategy comparison with real market data

### Plaid Integration
- `POST /plaid/create_link_token` - Create Plaid Link token
- `POST /plaid/sync_holdings` - Sync account holdings
- `POST /plaid/get_holdings` - Fetch account holdings

### Options Analysis
- `POST /scout/weekly` - Weekly options scout
- `POST /greeks` - Calculate Greeks
- `POST /iv` - Implied volatility analysis

### Trade Journal
- `POST /journal/stats` - Get trading statistics
- `POST /journal/learn` - AI learning from trades

---

## 🔐 Security Features

- **Authentication**: Supabase Auth with JWT tokens
- **Row Level Security**: Database-level access control
- **Encrypted Storage**: Plaid tokens stored encrypted
- **Read-only Broker Access**: No trade execution permissions
- **CORS Protection**: Configured for production domains
- **Environment Variables**: Sensitive data never committed

---

## 🎨 UI Components

### Key Pages

1. **Dashboard** (`/dashboard`)
   - Portfolio overview & Risk metrics
   - Integrated Options Scout
   - Holdings breakdown (Options vs Long Term)
   - Real-time P&L

2. **Compose** (`/compose`)
   - New trade entry
   - AI validation
   - Strategy selector

3. **Portfolio** (`/portfolio`)
   - Position management
   - Optimization suggestions
   - Broker import

4. **Settings** (`/settings`)
   - Broker connection (Plaid)
   - Risk preferences
   - Account management

5. **Trade Journal** (`/journal`)
   - Trade logging
   - Performance tracking
   - AI insights

### Reusable Components

- `PlaidLink.tsx` - Broker connection modal
- Portfolio cards
- Trade forms
- Charts (via Chart.js)

---

## 🧪 Testing

### Test Plaid Integration (Sandbox)

1. Go to Settings → Connect Broker
2. Select "First Platypus Bank" (test institution)
3. Login with:
   - **Username**: `user_good`
   - **Password**: `pass_good`
4. Select any account
5. Success! (fake data will be imported)

### Test API Endpoints
```bash
# Test quote endpoint
curl http://localhost:8000/quote/AAPL

# Test optimization
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"tickers":["AAPL","MSFT","GOOGL"],"risk_tolerance":2.0}'

# Test Plaid
curl -X POST http://localhost:8000/plaid/create_link_token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test123"}'
```

---

## 📊 Current Status

### ✅ Completed Features

- [x] FastAPI backend with CORS
- [x] Next.js 14 frontend (App Router)
- [x] Supabase authentication
- [x] Portfolio optimization engine
- [x] Polygon.io integration
- [x] **Plaid broker integration** ⭐
- [x] Real-time market data
- [x] Options Greeks calculations
- [x] Weekly options scout
- [x] Trade journal with AI learning
- [x] Compose Trade with AI validation
- [x] Responsive UI
- [x] Import real holdings from broker (Plaid)
- [x] Display positions in portfolio (Dashboard Positions table)

### 🚧 In Progress

- [ ] Plaid Production approval (submitted)
- [ ] Advanced charting
- [ ] Options strategy builder
- [ ] Risk metrics dashboard (expanded)

### 📋 Roadmap

1. **Phase 1: Core Functionality** ✅
   - Authentication
   - Portfolio management
   - Market data integration

2. **Phase 2: Broker Integration** ✅
   - Plaid implementation
   - Position imports
   - Account syncing

3. **Phase 3: Advanced Analytics** (Current)
   - Performance tracking / P&L history
   - Advanced risk metrics dashboard
   - Deeper holdings visualizations (charts)

4. **Phase 4: AI Features** (Next)
   - Trade pattern recognition (multi-trade analysis)
   - Predictive modeling
   - Automated recommendations / weekly playbook

5. **Phase 5: Production** (Future)
   - Real broker connections
   - Live trading alerts
   - Mobile app

---

## 🐛 Troubleshooting

### Common Issues

**1. Module not found errors (Next.js)**
```bash
# Clear cache and reinstall
rm -rf .next node_modules
pnpm install
pnpm dev
```

**2. Plaid "INVALID_API_KEYS" error**
```bash
# Check .env file has no quotes or extra spaces
cat packages/quantum/.env

# Verify keys in Plaid dashboard
# https://dashboard.plaid.com/team/keys
```

**3. Database connection errors**
```bash
# Verify Supabase URL and anon key
# Check RLS policies are enabled
# Confirm user is authenticated
```

**4. CORS errors**
```bash
# Ensure API is running on port 8000
# Check frontend is on port 3000
# Restart both servers
```

**5. Python dependency issues**
```bash
# Use --break-system-packages flag
pip install pandas --break-system-packages
```

---

## 🔧 Technology Stack

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Auth**: Supabase Auth
- **State**: React Hooks
- **Charts**: Chart.js / Recharts

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.9+
- **Optimization**: SciPy, NumPy, Pandas
- **Data**: Polygon.io API
- **Broker**: Plaid API

### Infrastructure
- **Database**: Supabase (PostgreSQL)
- **Auth**: Supabase Auth
- **Hosting**: TBD (Vercel + Railway recommended)

---

## 📝 Environment Variables Reference

### Required Variables

**Frontend:**
```env
NEXT_PUBLIC_SUPABASE_URL=          # Supabase project URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=     # Supabase anonymous key
NEXT_PUBLIC_POLYGON_API_KEY=       # Polygon.io API key
```

**Backend:**
```env
POLYGON_API_KEY=                   # Polygon.io API key
PLAID_CLIENT_ID=                   # Plaid client ID
PLAID_SECRET=                      # Plaid secret (sandbox or production)
PLAID_ENV=sandbox                  # 'sandbox' or 'production'
```

### Optional Variables
```env
ANTHROPIC_API_KEY=                 # For AI features (future)
REDIS_URL=                         # For caching (future)
```

---

## 🤝 Contributing

This is currently a personal project. If you'd like to contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull review

---

## 📜 License

MIT License - feel free to use this for your own projects!

---

## 🙏 Acknowledgments

- **Polygon.io** - Real-time market data
- **Plaid** - Secure broker connections
- **Supabase** - Backend infrastructure
- **Anthropic** - AI assistance in development

---

## 📞 Support

For issues or questions:
- Check the troubleshooting section above
- Review API documentation at http://localhost:8000/docs
- Check console logs for detailed errors

---

## 🎯 Quick Start Checklist

- [ ] Clone repository
- [ ] Install dependencies (pnpm + pip)
- [ ] Create Supabase project
- [ ] Get Polygon.io API key
- [ ] Create Plaid account
- [ ] Set up .env files
- [ ] Run database migrations
- [ ] Start backend (`python api.py`)
- [ ] Start frontend (`pnpm dev`)
- [ ] Create account at http://localhost:3000/signup
- [ ] Connect test broker in Settings
- [ ] Test portfolio optimization

---

**Last Updated**: November 14, 2025
**Version**: 1.0.0-beta
**Status**: MVP Complete - Testing Phase

---

## 🚀 What's Next?

Now that Plaid is integrated, the next steps are:

1. **Display Real Holdings** - Show imported positions in portfolio
2. **Sync Button** - Refresh holdings from broker
3. **Production Access** - Get Plaid approved for real accounts
4. **Advanced Analytics** - Greek analysis on imported options
5. **Automated Rebalancing** - Suggestions based on real positions

Ready to build the next feature! 🎉
