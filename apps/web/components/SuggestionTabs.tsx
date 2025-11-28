'use client';

import { useState } from 'react';
import TradeSuggestionCard from './tradeSuggestionCard';
import { Sparkles, RefreshCw, Activity } from 'lucide-react';

interface SuggestionTabsProps {
  optimizerSuggestions: any[];
  scoutSuggestions: any[];
  journalQueue: any[];
  onRefreshScout: () => void;
  scoutLoading: boolean;
  onRefreshJournal: () => void; // Placeholder for future queue refresh
}

export default function SuggestionTabs({
  optimizerSuggestions,
  scoutSuggestions,
  journalQueue,
  onRefreshScout,
  scoutLoading,
  onRefreshJournal
}: SuggestionTabsProps) {
  const [activeTab, setActiveTab] = useState<'rebalance' | 'scout' | 'journal'>('rebalance');

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden h-full flex flex-col">
      {/* Tabs Header */}
      <div className="flex border-b border-gray-100">
        <button
          onClick={() => setActiveTab('rebalance')}
          className={`flex-1 py-4 text-sm font-medium text-center border-b-2 transition-colors ${
            activeTab === 'rebalance'
              ? 'border-indigo-500 text-indigo-600 bg-indigo-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Activity className="w-4 h-4" />
            Rebalance
            {optimizerSuggestions.length > 0 && (
              <span className="bg-indigo-100 text-indigo-600 py-0.5 px-2 rounded-full text-xs">
                {optimizerSuggestions.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('scout')}
          className={`flex-1 py-4 text-sm font-medium text-center border-b-2 transition-colors ${
            activeTab === 'scout'
              ? 'border-green-500 text-green-600 bg-green-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Sparkles className="w-4 h-4" />
            Scout Picks
            {scoutSuggestions.length > 0 && (
              <span className="bg-green-100 text-green-600 py-0.5 px-2 rounded-full text-xs">
                {scoutSuggestions.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('journal')}
          className={`flex-1 py-4 text-sm font-medium text-center border-b-2 transition-colors ${
            activeTab === 'journal'
              ? 'border-purple-500 text-purple-600 bg-purple-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <span>📖</span>
            Journal Queue
            {journalQueue.length > 0 && (
              <span className="bg-purple-100 text-purple-600 py-0.5 px-2 rounded-full text-xs">
                {journalQueue.length}
              </span>
            )}
          </div>
        </button>
      </div>

      {/* Tab Content */}
      <div className="p-4 flex-1 overflow-y-auto bg-gray-50/50 min-h-[400px]">

        {activeTab === 'rebalance' && (
          <div className="space-y-4">
             {optimizerSuggestions.length === 0 ? (
               <div className="text-center py-10 text-gray-400">
                 <Activity className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No rebalance suggestions.</p>
                 <p className="text-xs mt-1">Run the optimizer to generate trades.</p>
               </div>
             ) : (
               optimizerSuggestions.map((trade, idx) => (
                 // Using TradeSuggestionCard for optimizer trades if they fit the shape,
                 // or a custom row. The optimizer returns simple trade dicts currently.
                 // We might need to adapt them to TradeSuggestionCard props or render differently.
                 // The optimizer trades look like: { symbol, action, value, rationale ... }
                 // TradeSuggestionCard expects: { symbol, strategy_type, entry_price, otc_score ... }
                 // Since they are different, we will stick to the existing list format for Rebalance
                 // BUT wrapped in a card style similar to suggestions for consistency.
                 <div key={idx} className="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
                   <div className="flex justify-between items-start mb-2">
                     <div className="flex items-center gap-2">
                       <span className={`px-2 py-1 rounded text-xs font-bold ${trade.action === 'BUY' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                         {trade.action}
                       </span>
                       <span className="font-bold text-gray-800">{trade.symbol}</span>
                     </div>
                     <span className="text-sm font-semibold text-gray-600">${trade.value?.toLocaleString()}</span>
                   </div>
                   <p className="text-xs text-gray-500 italic">{trade.rationale}</p>
                   {/* If metrics exist (added in step 2) */}
                   {trade.metrics && (
                     <div className="mt-2 flex gap-2 text-xs">
                       {trade.metrics.expected_value && (
                         <span className="text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                           EV: ${trade.metrics.expected_value.toFixed(2)}
                         </span>
                       )}
                       {trade.metrics.probability_of_profit && (
                         <span className="text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
                           Win: {Math.round(trade.metrics.probability_of_profit)}%
                         </span>
                       )}
                     </div>
                   )}
                 </div>
               ))
             )}
          </div>
        )}

        {activeTab === 'scout' && (
          <div className="space-y-4">
            <div className="flex justify-end mb-2">
                <button
                  onClick={onRefreshScout}
                  disabled={scoutLoading}
                  className="text-xs text-green-600 flex items-center gap-1 hover:underline disabled:opacity-50"
                >
                  <RefreshCw className={`w-3 h-3 ${scoutLoading ? 'animate-spin' : ''}`} />
                  Refresh
                </button>
            </div>

            {scoutSuggestions.length === 0 ? (
               <div className="text-center py-10 text-gray-400">
                 <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No scout picks found.</p>
               </div>
            ) : (
               scoutSuggestions.map((opp, idx) => (
                 <TradeSuggestionCard key={idx} suggestion={opp} />
               ))
            )}
          </div>
        )}

        {activeTab === 'journal' && (
          <div className="space-y-4">
            {journalQueue.length === 0 ? (
               <div className="text-center py-10 text-gray-400">
                 <p>Journal queue is empty.</p>
                 <p className="text-xs mt-1">Add trades from Scout or Rebalance to track them.</p>
               </div>
            ) : (
               journalQueue.map((item, idx) => (
                 <TradeSuggestionCard key={idx} suggestion={item} />
               ))
            )}
          </div>
        )}

      </div>
    </div>
  );
}
