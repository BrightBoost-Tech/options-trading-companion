'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { AlertTriangle, ClipboardList } from 'lucide-react';

import { Button } from '@/components/ui/button';

interface LocalTradeDraft {
  symbol: string;
  strategy: string;
  expiry: string;
  strikes: string[];
}

const STRATEGY_LABELS: Record<string, string> = {
  long_call_debit_spread: 'Long Call Debit Spread',
  long_put_debit_spread: 'Long Put Debit Spread',
  short_put_credit_spread: 'Short Put Credit Spread',
  short_call_credit_spread: 'Short Call Credit Spread',
  iron_condor: 'Iron Condor',
};

export default function ComposePage() {
  const [symbol, setSymbol] = useState('');
  const [strategy, setStrategy] = useState('');
  const [expiry, setExpiry] = useState('');
  const [strikes, setStrikes] = useState('');
  const [draft, setDraft] = useState<LocalTradeDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const handleCreateDraft = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const normalizedSymbol = symbol.trim().toUpperCase();
    const normalizedStrikes = strikes
      .split(',')
      .map((strike) => strike.trim())
      .filter(Boolean);

    if (!normalizedSymbol || !strategy || !expiry || normalizedStrikes.length === 0) {
      setDraft(null);
      setFormError('Complete every field and provide at least one strike.');
      return;
    }

    setFormError(null);
    setDraft({
      symbol: normalizedSymbol,
      strategy: STRATEGY_LABELS[strategy] ?? strategy,
      expiry,
      strikes: normalizedStrikes,
    });
  };

  const handleReset = () => {
    setSymbol('');
    setStrategy('');
    setExpiry('');
    setStrikes('');
    setDraft(null);
    setFormError(null);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="border-b bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-8 py-4">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Trade Draft</h1>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-900">
              Planning only
            </span>
          </div>
          <Link href="/dashboard" className="text-gray-600 hover:text-gray-900">
            ← Back to Dashboard
          </Link>
        </div>
      </div>

      <main className="mx-auto max-w-4xl space-y-6 p-8">
        <section
          role="status"
          aria-label="Trade draft limitations"
          className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-amber-950"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div className="space-y-2">
              <h2 className="font-semibold">This page does not validate or submit a trade.</h2>
              <p className="text-sm leading-6">
                It does not call the production scanner, market-data providers, IV/OI or earnings
                checks, liquidity gates, risk controls, buying-power checks, lifecycle policy, or the
                broker. The draft stays only in this browser tab and is cleared on refresh.
              </p>
            </div>
          </div>
        </section>

        <section className="rounded-lg bg-white p-6 shadow">
          <div className="mb-5 flex items-start gap-3">
            <ClipboardList className="mt-0.5 h-5 w-5 text-gray-600" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold">Record an idea for review</h2>
              <p className="mt-1 text-sm text-gray-600">
                Use the live dashboard and production suggestion flow for actual eligibility and
                execution decisions.
              </p>
            </div>
          </div>

          <form onSubmit={handleCreateDraft} className="space-y-4">
            <div>
              <label htmlFor="draft-symbol" className="mb-2 block text-sm font-medium">
                Symbol
              </label>
              <input
                id="draft-symbol"
                type="text"
                value={symbol}
                onChange={(event) => setSymbol(event.target.value.toUpperCase())}
                className="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="SPY"
                autoComplete="off"
                required
              />
            </div>

            <div>
              <label htmlFor="draft-strategy" className="mb-2 block text-sm font-medium">
                Strategy
              </label>
              <select
                id="draft-strategy"
                value={strategy}
                onChange={(event) => setStrategy(event.target.value)}
                className="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              >
                <option value="">Select strategy</option>
                <option value="long_call_debit_spread">Long Call Debit Spread</option>
                <option value="long_put_debit_spread">Long Put Debit Spread</option>
                <option value="short_put_credit_spread">Short Put Credit Spread</option>
                <option value="short_call_credit_spread">Short Call Credit Spread</option>
                <option value="iron_condor">Iron Condor</option>
              </select>
            </div>

            <div>
              <label htmlFor="draft-expiry" className="mb-2 block text-sm font-medium">
                Expiry
              </label>
              <input
                id="draft-expiry"
                type="date"
                value={expiry}
                onChange={(event) => setExpiry(event.target.value)}
                className="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>

            <div>
              <label htmlFor="draft-strikes" className="mb-2 block text-sm font-medium">
                Strikes (comma-separated)
              </label>
              <input
                id="draft-strikes"
                type="text"
                value={strikes}
                onChange={(event) => setStrikes(event.target.value)}
                className="w-full rounded-lg border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="480, 475"
                autoComplete="off"
                required
              />
            </div>

            {formError && (
              <p role="alert" className="text-sm font-medium text-red-700">
                {formError}
              </p>
            )}

            <div className="flex flex-col gap-3 sm:flex-row">
              <Button type="submit" className="flex-1 bg-blue-600 hover:bg-blue-700">
                Create local draft
              </Button>
              <Button type="button" variant="outline" onClick={handleReset}>
                Clear
              </Button>
            </div>
          </form>
        </section>

        {draft && (
          <section className="rounded-lg border border-gray-200 bg-white p-6 shadow" aria-live="polite">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Unvalidated local draft</h2>
              <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-gray-700">
                Unvalidated
              </span>
            </div>

            <dl className="grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="font-medium text-gray-500">Symbol</dt>
                <dd className="mt-1 text-gray-900">{draft.symbol}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-500">Strategy</dt>
                <dd className="mt-1 text-gray-900">{draft.strategy}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-500">Expiry</dt>
                <dd className="mt-1 text-gray-900">{draft.expiry}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-500">Strikes</dt>
                <dd className="mt-1 text-gray-900">{draft.strikes.join(', ')}</dd>
              </div>
            </dl>

            <div className="mt-6 rounded-md bg-gray-50 p-4 text-sm leading-6 text-gray-700">
              No accept/reject decision has been made. Review production suggestions on the dashboard;
              only the production workflow can apply current market data, account limits, and safety gates.
            </div>

            <Button asChild variant="outline" className="mt-5">
              <Link href="/dashboard">Return to live dashboard</Link>
            </Button>
          </section>
        )}
      </main>
    </div>
  );
}
