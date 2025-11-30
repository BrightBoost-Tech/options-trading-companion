import React from 'react';
import TradeSuggestionCard from '../tradeSuggestionCard';
import { Sun } from 'lucide-react';

interface MorningOrdersListProps {
  suggestions: any[];
}

export default function MorningOrdersList({ suggestions }: MorningOrdersListProps) {
  const safeSuggestions = Array.isArray(suggestions) ? suggestions : [];

  if (safeSuggestions.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400">
        <Sun className="w-10 h-10 mx-auto mb-3 opacity-20" />
        <p>No morning limit orders found.</p>
        <p className="text-xs mt-1">Check back before market open.</p>
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
