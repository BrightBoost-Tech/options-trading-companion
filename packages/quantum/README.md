# Quantum Backend

This package contains the FastAPI backend for the Options Trading Companion.

## Local Development

### Setup

1.  **Install Dependencies:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Environment Variables:**
    - Copy the example environment file:
      ```bash
      cp .env.example .env
      ```
    - Edit the `.env` file with your credentials.

3.  **Plaid Configuration:**
    - Open `packages/quantum/.env`.
    - Set `PLAID_ENV` to `sandbox`, `development`, or `production`.
    - Ensure the `PLAID_CLIENT_ID` and `PLAID_SECRET` match the environment selected. You can find these keys on your [Plaid Dashboard](https://dashboard.plaid.com/team/keys).


### Running the Server

```bash
./run_server.sh
```

The API will be available at `http://127.0.0.1:8000`.
