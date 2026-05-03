# TraderApp

Real-time stock trading dashboard with a FastAPI backend and React frontend.

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm
- IBKR TWS or IB Gateway running with API enabled (port 7496/7497)
- Alpaca Markets account (free paper trading available)

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml with your Alpaca API keys
```

### Frontend

```bash
cd frontend
npm install
```

## Running

### Backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Runs at **http://localhost:8000**

### Frontend

```bash
cd frontend
npm run dev
```

Runs at **http://localhost:3000**
