'use client';

import { useState } from 'react';

export default function ComposePage() {
  const [symbol, setSymbol] = useState('');
  const [strategy, setStrategy] = useState('');
  const [expiry, setExpiry] = useState('');
  const [strikes, setStrikes] = useState('');
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<any>(null);

  const handleValidate = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidating(true);
    
    // Simulate AI validation
    setTimeout(() => {
      const mockResult = {
        decision: Math.random() > 0.3 ? 'accept' : 'revise',
        reasons: [
          'IV rank is 52%, within optimal range',
          'Liquidity sufficient (OI > 1000)',
          'No earnings within 7 days',
        ],
        alternative: Math.random() > 0.5 ? {
          expiry: '2025-02-21',
          strikes: [475, 470],
          reasoning: 'Moving to next expiry for better theta decay'
        } : null,
      };
      
      setResult(mockResult);
      setValidating(false);
    }, 1500);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold">Compose Trade</h1>
          <a href="/dashboard" className="text-gray-600 hover:text-gray-900">
            ← Back to Dashboard
          </a>
        </div>
      </div>

      <div className="max-w-4xl mx-auto p-8 space-y-6">
        <p className="text-gray-600">
          Enter your trade idea and get AI-powered validation with strict gating checks.
        </p>

        <form onSubmit={handleValidate} className="bg-white rounded-lg shadow p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Symbol</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="SPY"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Strategy</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            >
              <option value="">Select strategy</option>
              <option value="credit_put_spread">Credit Put Spread</option>
              <option value="iron_condor">Iron Condor</option>
              <option value="covered_call">Covered Call</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Expiry (YYYY-MM-DD)</label>
            <input
              type="date"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Strikes (comma-separated)
            </label>
            <input
              type="text"
              value={strikes}
              onChange={(e) => setStrikes(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="480, 475"
              required
            />
          </div>

          <button
            type="submit"
            disabled={validating}
            className="w-full py-2 px-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:bg-gray-400"
          >
            {validating ? 'Validating with AI...' : 'Validate Trade'}
          </button>
        </form>

        {result && (
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-4">Validation Result</h3>
            
            <div className="space-y-4">
              <div>
                <span className="font-medium">Decision: </span>
                <span className={`px-3 py-1 rounded text-sm font-medium ${
                  result.decision === 'accept'
                    ? 'bg-green-100 text-green-800'
                    : result.decision === 'revise'
                    ? 'bg-yellow-100 text-yellow-800'
                    : 'bg-red-100 text-red-800'
                }`}>
                  {result.decision.toUpperCase()}
                </span>
              </div>

              {result.reasons && (
                <div>
                  <p className="font-medium mb-2">Analysis:</p>
                  <ul className="list-disc list-inside space-y-1">
                    {result.reasons.map((reason: string, i: number) => (
                      <li key={i} className="text-gray-700 text-sm">{reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              {result.alternative && (
                <div className="bg-blue-50 p-4 rounded">
                  <p className="font-medium mb-2">Suggested Alternative:</p>
                  <div className="space-y-1 text-sm">
                    <p><strong>Expiry:</strong> {result.alternative.expiry}</p>
                    <p><strong>Strikes:</strong> {result.alternative.strikes.join(', ')}</p>
                    <p className="text-gray-700 mt-2">{result.alternative.reasoning}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
