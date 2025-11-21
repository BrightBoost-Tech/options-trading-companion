# Data Providers Overview

This document outlines the integration of data providers for portfolio holdings.

## Primary Source: Plaid

*   **Module**: `packages/quantum/plaid_service.py`
*   **Client**: `plaid.ApiClient`
*   **Environment Variables**:
    *   `PLAID_ENV` (sandbox, development, production)
    *   `PLAID_CLIENT_ID`
    *   `PLAID_SECRET`
*   **Flow**:
    1.  Frontend gets Link Token from `/plaid/create_link_token`.
    2.  User authenticates via Plaid Link.
    3.  Frontend sends Public Token to `/plaid/exchange_public_token`.
    4.  Backend exchanges Public Token for Access Token and stores it.
    5.  Holdings are synced via `/plaid/sync_holdings`, which calls `plaid_service.fetch_and_normalize_holdings`.
*   **Data Model**: `Holding` (in `packages/quantum/models.py`) with `source="plaid"`.

## Secondary Source: SnapTrade (In Progress)

SnapTrade is being added as a fallback/alternative, primarily for brokerages like Robinhood.

*   **Goal**: Provide a seamless fallback when Plaid fails or for specific brokerages.
*   **Planned Module**: `packages/quantum/snaptrade_client.py`
*   **Environment Variables** (Planned):
    *   `SNAPTRADE_CLIENT_ID`
    *   `SNAPTRADE_CONSUMER_KEY`
    *   `SNAPTRADE_ENV`
    *   `SNAPTRADE_BASE_URL` (optional)

## CSV Import

*   **Endpoint**: `/holdings/upload_csv`
*   **Format**: Supports Robinhood CSV exports.
*   **Data Model**: `Holding` with `source="robinhood-csv"`.
