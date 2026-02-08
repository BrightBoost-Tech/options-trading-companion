'use client';

import { useState } from 'react';
import TradeSuggestionCard from './tradeSuggestionCard';
import OptimizerSuggestionCard from './suggestions/OptimizerSuggestionCard';
import MorningOrdersList from './suggestions/MorningOrdersList';
import MiddayEntriesList from './suggestions/MiddayEntriesList';
import WeeklyReportList from './suggestions/WeeklyReportList';
import { Sparkles, RefreshCw, Activity, Sun, Clock, FileText, BookOpen } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface SuggestionTabsProps {
  optimizerSuggestions: any[];
  scoutSuggestions: any[];
  journalQueue: any[];
  morningSuggestions: any[];
  middaySuggestions: any[];
  weeklyReports: any[];
  onRefreshScout: () => void;
  scoutLoading: boolean;
  onRefreshJournal: () => void;
}

// Helper for safe numeric formatting (replicated locally for the Rebalance tab logic)
const safeFixed = (value: number | null | undefined, digits = 2) =>
  typeof value === "number" ? value.toFixed(digits) : "--";

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

  return (
    <div className="bg-card rounded-lg shadow overflow-hidden h-full flex flex-col">
      {/* Tabs Header */}
      <div className="flex border-b border-gray-100 overflow-x-auto no-scrollbar" role="tablist">
        <button
          id="tab-morning"
          role="tab"
          aria-selected={activeTab === 'morning'}
          aria-controls="panel-morning"
          type="button"
          onClick={() => setActiveTab('morning')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-orange-500 ${
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
          id="tab-midday"
          role="tab"
          aria-selected={activeTab === 'midday'}
          aria-controls="panel-midday"
          type="button"
          onClick={() => setActiveTab('midday')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 ${
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
          id="tab-rebalance"
          role="tab"
          aria-selected={activeTab === 'rebalance'}
          aria-controls="panel-rebalance"
          type="button"
          onClick={() => setActiveTab('rebalance')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-indigo-500 ${
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
          id="tab-scout"
          role="tab"
          aria-selected={activeTab === 'scout'}
          aria-controls="panel-scout"
          type="button"
          onClick={() => setActiveTab('scout')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-green-500 ${
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
          id="tab-journal"
          role="tab"
          aria-selected={activeTab === 'journal'}
          aria-controls="panel-journal"
          type="button"
          onClick={() => setActiveTab('journal')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-purple-500 ${
            activeTab === 'journal'
              ? 'border-purple-500 text-purple-600 bg-purple-50/50'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <BookOpen className="w-4 h-4" />
            Journal
            {journalQueue.length > 0 && (
              <span className="bg-purple-100 text-purple-600 py-0.5 px-2 rounded-full text-xs">
                {journalQueue.length}
              </span>
            )}
          </div>
        </button>

        <button
          id="tab-weekly"
          role="tab"
          aria-selected={activeTab === 'weekly'}
          aria-controls="panel-weekly"
          type="button"
          onClick={() => setActiveTab('weekly')}
          className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-500 ${
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
      <div className="p-4 flex-1 overflow-y-auto bg-muted/50 min-h-[400px]">

        {activeTab === 'morning' && (
          <div role="tabpanel" id="panel-morning" aria-labelledby="tab-morning">
            <MorningOrdersList suggestions={morningSuggestions} />
          </div>
        )}

        {activeTab === 'midday' && (
          <div role="tabpanel" id="panel-midday" aria-labelledby="tab-midday">
            <MiddayEntriesList suggestions={middaySuggestions} />
          </div>
        )}

        {activeTab === 'weekly' && (
          <div role="tabpanel" id="panel-weekly" aria-labelledby="tab-weekly">
            <WeeklyReportList reports={weeklyReports} />
          </div>
        )}

        {activeTab === 'rebalance' && (
          <div role="tabpanel" id="panel-rebalance" aria-labelledby="tab-rebalance" className="space-y-4">
             {optimizerSuggestions.length === 0 ? (
               <EmptyState
                 icon={Activity}
                 title="No rebalance suggestions"
                 description="Run the optimizer to generate trades."
               />
             ) : (
               optimizerSuggestions.map((trade, idx) => (
                 <OptimizerSuggestionCard key={idx} trade={trade} />
               ))
             )}
          </div>
        )}

        {activeTab === 'scout' && (
          <div role="tabpanel" id="panel-scout" aria-labelledby="tab-scout" className="space-y-4">
            <div className="flex justify-end mb-2">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={onRefreshScout}
                        disabled={scoutLoading}
                        className="h-6 text-xs text-green-600 gap-1 hover:text-green-700 hover:bg-green-50"
                      >
                        <RefreshCw className={`w-3 h-3 ${scoutLoading ? 'animate-spin' : ''}`} />
                        Refresh
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Refresh market scan for new opportunities</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
            </div>

            {scoutSuggestions.length === 0 ? (
               <EmptyState
                 icon={Sparkles}
                 title="No scout picks found"
                 description="Market scan returned no results."
               />
            ) : (
               scoutSuggestions.map((opp, idx) => (
                 <TradeSuggestionCard key={idx} suggestion={opp} />
               ))
            )}
          </div>
        )}

        {activeTab === 'journal' && (
          <div role="tabpanel" id="panel-journal" aria-labelledby="tab-journal" className="space-y-4">
            {journalQueue.length === 0 ? (
               <EmptyState
                 icon={BookOpen}
                 title="Journal queue is empty"
                 description="Add trades from Scout or Rebalance to track them."
               />
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
