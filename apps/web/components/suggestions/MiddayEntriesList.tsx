import React from 'react';
import TradeSuggestionCard from '../tradeSuggestionCard';
import { Clock } from 'lucide-react';

interface MiddayEntriesListProps {
  suggestions: any[];
}

export default function MiddayEntriesList({ suggestions }: MiddayEntriesListProps) {
  const safeSuggestions = Array.isArray(suggestions) ? suggestions : [];

  if (safeSuggestions.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400">
        <Clock className="w-10 h-10 mx-auto mb-3 opacity-20" />
        <p>No midday entries found.</p>
        <p className="text-xs mt-1">Scan runs around 12:00 PM EST.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {safeSuggestions.map((item, idx) => (
        <TradeSuggestionCard key={idx} suggestion={item} />
      ))}
    </div>
  );
}
