'use client';

import { useState } from 'react';
import SuggestionCard from './SuggestionCard';
import { Suggestion } from '@/lib/types';
import { Sparkles, Activity, Sun, Clock, FileText } from 'lucide-react';
import WeeklyReportList from '../suggestions/WeeklyReportList';
import { RefreshCw } from 'lucide-react';

interface SuggestionTabsProps {
  optimizerSuggestions: Suggestion[];
  scoutSuggestions: Suggestion[];
  journalQueue: Suggestion[];
  morningSuggestions: Suggestion[];
  middaySuggestions: Suggestion[];
  weeklyReports: any[];
  onRefreshScout: () => void;
  scoutLoading: boolean;
  onRefreshJournal: () => void;
}

export default function SuggestionTabs({
  optimizerSuggestions,
  scoutSuggestions,
  journalQueue,
  morningSuggestions,
  middaySuggestions,
  weeklyReports,
  onRefreshScout,
  scoutLoading,
  onRefreshJournal
}: SuggestionTabsProps) {
  const [activeTab, setActiveTab] = useState<'morning' | 'midday' | 'rebalance' | 'scout' | 'journal' | 'weekly'>('morning');

  // Placeholder handlers
  const handleStage = (s: Suggestion) => {
      console.log('Staging', s);
      // Logic to toggle staged state or add to a staging queue
  };
  const handleModify = (s: Suggestion) => console.log('Modify', s);
  const handleDismiss = (s: Suggestion, tag: string) => console.log('Dismiss', s, tag);

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden h-full flex flex-col">
      {/* Tabs Header */}
      <div className="flex border-b border-gray-100 overflow-x-auto no-scrollbar">
        <button
          onClick={() => setActiveTab('morning')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
            activeTab === 'morning'
              ? 'border-orange-500 text-orange-600 bg-orange-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Sun className="w-4 h-4" />
            Morning
            {morningSuggestions.length > 0 && (
              <span className="bg-orange-100 text-orange-600 py-0.5 px-2 rounded-full text-xs">
                {morningSuggestions.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('midday')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
            activeTab === 'midday'
              ? 'border-blue-500 text-blue-600 bg-blue-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Clock className="w-4 h-4" />
            Midday
            {middaySuggestions.length > 0 && (
              <span className="bg-blue-100 text-blue-600 py-0.5 px-2 rounded-full text-xs">
                {middaySuggestions.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('rebalance')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
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
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
            activeTab === 'scout'
              ? 'border-green-500 text-green-600 bg-green-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Sparkles className="w-4 h-4" />
            Scout
            {scoutSuggestions.length > 0 && (
              <span className="bg-green-100 text-green-600 py-0.5 px-2 rounded-full text-xs">
                {scoutSuggestions.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('journal')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
            activeTab === 'journal'
              ? 'border-purple-500 text-purple-600 bg-purple-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <span>📖</span>
            Journal
            {journalQueue.length > 0 && (
              <span className="bg-purple-100 text-purple-600 py-0.5 px-2 rounded-full text-xs">
                {journalQueue.length}
              </span>
            )}
          </div>
        </button>

        <button
          onClick={() => setActiveTab('weekly')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap ${
            activeTab === 'weekly'
              ? 'border-slate-500 text-slate-600 bg-slate-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <FileText className="w-4 h-4" />
            Reports
          </div>
        </button>
      </div>

      {/* Tab Content */}
      <div className="p-4 flex-1 overflow-y-auto bg-gray-50/50 min-h-[400px]">

        {activeTab === 'morning' && (
             morningSuggestions.length === 0 ? (
               <div className="text-center py-10 text-gray-400">
                 <p>No morning suggestions.</p>
               </div>
             ) : (
                morningSuggestions.map((s, i) => (
                    <SuggestionCard
                        key={i}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
                ))
             )
        )}

        {activeTab === 'midday' && (
             middaySuggestions.length === 0 ? (
                <div className="text-center py-10 text-gray-400">
                  <p>No midday suggestions.</p>
                </div>
              ) : (
                 middaySuggestions.map((s, i) => (
                     <SuggestionCard
                        key={i}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
                 ))
              )
        )}

        {activeTab === 'weekly' && (
          <WeeklyReportList reports={weeklyReports} />
        )}

        {activeTab === 'rebalance' && (
            optimizerSuggestions.length === 0 ? (
               <div className="text-center py-10 text-gray-400">
                 <Activity className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No rebalance suggestions.</p>
                 <p className="text-xs mt-1">Run the optimizer to generate trades.</p>
               </div>
            ) : (
               optimizerSuggestions.map((s, idx) => (
                    <SuggestionCard
                        key={idx}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
               ))
            )
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
                 <SuggestionCard
                    key={idx}
                    suggestion={opp}
                    onStage={handleStage}
                    onModify={handleModify}
                    onDismiss={handleDismiss}
                />
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
                 <SuggestionCard
                    key={idx}
                    suggestion={item}
                    onStage={handleStage}
                    onModify={handleModify}
                    onDismiss={handleDismiss}
                />
               ))
            )}
          </div>
        )}

      </div>
    </div>
  );
}
