'use client';

import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabase';
import { useRouter } from 'next/navigation';
import PlaidLink from '@/components/PlaidLink';

export default function PortfolioPage() {
  const [user, setUser] = useState<any>(null);
  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>('');
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [showPlaidImport, setShowPlaidImport] = useState(false);
  const router = useRouter();

  useEffect(() => {
    loadUser();
  }, []);

  useEffect(() => {
    if (user) {
      loadPortfolios();
    }
  }, [user]);

  useEffect(() => {
    if (selectedPortfolio) {
      loadPositions();
    }
  }, [selectedPortfolio]);

  const loadUser = async () => {
    const { data: { user } } = await supabase.auth.getUser();
    setUser(user);
  };

  const loadPortfolios = async () => {
    const { data } = await supabase
      .from('portfolios')
      .select('*')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false });

    if (data) {
      setPortfolios(data);
      if (data.length > 0 && !selectedPortfolio) {
        setSelectedPortfolio(data[0].id);
      }
    }
  };

  const loadPositions = async () => {
    const { data: stockData } = await supabase
      .from('positions')
      .select('*')
      .eq('portfolio_id', selectedPortfolio);

    const { data: optionData } = await supabase
      .from('option_positions')
      .select('*')
      .eq('portfolio_id', selectedPortfolio);

    setPositions([
      ...(stockData || []).map(p => ({ ...p, type: 'stock' })),
      ...(optionData || []).map(p => ({ ...p, type: 'option' }))
    ]);
  };

  const createPortfolio = async () => {
    const name = prompt('Portfolio name:');
    if (!name) return;

    const { data } = await supabase
      .from('portfolios')
      .insert([{
        user_id: user.id,
        name: name,
        type: 'mixed',
        is_default: portfolios.length === 0
      }])
      .select()
      .single();

    if (data) {
      setPortfolios([...portfolios, data]);
      setSelectedPortfolio(data.id);
      alert('Portfolio created!');
    }
  };

  const handlePlaidSuccess = async (publicToken: string, metadata: any) => {
    setLoading(true);
    
    try {
      const tokenResponse = await fetch('http://localhost:8000/plaid/exchange_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_token: publicToken })
      });
      
      const { access_token } = await tokenResponse.json();
      
      const holdingsResponse = await fetch('http://localhost:8000/plaid/get_holdings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ access_token })
      });
      
      const holdingsData = await holdingsResponse.json();
      await importHoldingsToDatabase(holdingsData);
      
      alert(`Successfully imported ${holdingsData.holdings.length} positions!`);
      setShowPlaidImport(false);
      
    } catch (err) {
      console.error('Import error:', err);
      alert('Failed to import. Check console.');
    } finally {
      setLoading(false);
    }
  };

  const importHoldingsToDatabase = async (holdingsData: any) => {
    if (!selectedPortfolio) return;

    for (const holding of holdingsData.holdings) {
      if (!holding.symbol) continue;

      if (holding.type === 'derivative' && holding.option_contract) {
        const contract = holding.option_contract;
        await supabase.from('option_positions').insert([{
          portfolio_id: selectedPortfolio,
          symbol: holding.symbol,
          option_type: contract.option_type,
          strike: contract.strike_price,
          expiry: contract.expiration_date,
          quantity: holding.quantity,
          premium: holding.institution_price || 0,
          status: 'open'
        }]);
      } else {
        await supabase.from('positions').insert([{
          portfolio_id: selectedPortfolio,
          symbol: holding.symbol,
          quantity: holding.quantity,
          avg_cost: holding.cost_basis ? holding.cost_basis / holding.quantity : holding.institution_price,
          current_price: holding.institution_price,
          position_type: 'stock'
        }]);
      }
    }

    await loadPositions();
  };

  const deletePosition = async (id: string, type: string) => {
    if (!confirm('Delete?')) return;
    const table = type === 'stock' ? 'positions' : 'option_positions';
    await supabase.from(table).delete().eq('id', id);
    await loadPositions();
  };

  const analyzePortfolio = () => {
    const symbols = positions.filter(p => p.type === 'stock').map(p => p.symbol);
    if (symbols.length === 0) {
      alert('Add positions first!');
      return;
    }
    localStorage.setItem('portfolio_symbols', JSON.stringify(symbols));
    router.push('/dashboard');
  };

  if (!user) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto p-8">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold">My Portfolio</h1>
          <div className="flex gap-3">
            <button onClick={createPortfolio} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
              + New Portfolio
            </button>
            <button onClick={() => setShowPlaidImport(!showPlaidImport)} className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
              🔗 Connect Broker
            </button>
            <button onClick={analyzePortfolio} disabled={positions.length === 0} className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400">
              📊 Analyze
            </button>
          </div>
        </div>

        {showPlaidImport && selectedPortfolio && (
          <div className="mb-6 bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg shadow p-6 border-l-4 border-green-500">
            <h3 className="text-lg font-semibold mb-2">Connect Your Brokerage Account</h3>
            <p className="text-sm text-gray-700 mb-4">
              Securely connect Robinhood, TD Ameritrade, Fidelity, Schwab, E*TRADE, or any other broker.
            </p>
            {user && <PlaidLink userId={user.id} onSuccess={handlePlaidSuccess} onExit={() => setShowPlaidImport(false)} />}
            <p className="text-xs text-gray-600 mt-3">🔒 Secured by Plaid</p>
          </div>
        )}

        {portfolios.length > 0 && (
          <div className="mb-6">
            <select value={selectedPortfolio} onChange={(e) => setSelectedPortfolio(e.target.value)} className="px-4 py-2 border rounded-lg">
              {portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        )}

        {selectedPortfolio && (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-6 py-4 border-b">
              <h3 className="text-lg font-semibold">Positions ({positions.length})</h3>
            </div>

            {positions.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                <p className="mb-4">No positions yet!</p>
                <p className="text-sm">Click "Connect Broker" to import automatically</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cost</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {positions.map((pos) => (
                      <tr key={pos.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 font-medium">{pos.symbol}</td>
                        <td className="px-6 py-4">
                          <span className={`px-2 py-1 rounded text-xs ${pos.type === 'stock' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'}`}>
                            {pos.type === 'stock' ? 'Stock' : pos.option_type?.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm">
                          {pos.type === 'option' ? `$${pos.strike} ${pos.expiry}` : '-'}
                        </td>
                        <td className="px-6 py-4">{pos.quantity}</td>
                        <td className="px-6 py-4">${(pos.avg_cost || pos.premium || 0).toFixed(2)}</td>
                        <td className="px-6 py-4">
                          <button onClick={() => deletePosition(pos.id, pos.type)} className="text-red-600 hover:text-red-800 text-sm">
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {portfolios.length === 0 && (
          <div className="text-center py-12 bg-white rounded-lg shadow">
            <p className="text-gray-600 mb-4">No portfolios yet!</p>
            <button onClick={createPortfolio} className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
              Create Your First Portfolio
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
