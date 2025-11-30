import React, { useState } from 'react';
import TradeSuggestionCard from '../tradeSuggestionCard';
import { Sun } from 'lucide-react';

interface MorningOrdersListProps {
  suggestions: any[];
}

export default function MorningOrdersList({ suggestions }: MorningOrdersListProps) {
  const [loggedIds, setLoggedIds] = useState<Set<string>>(new Set());

  const handleLogged = (id: string) => {
    setLoggedIds(prev => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  const safeSuggestions = Array.isArray(suggestions) ? suggestions : [];
  const displayItems = safeSuggestions.filter(s => !loggedIds.has(s.id));

  if (displayItems.length === 0) {
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
      {displayItems.map((item, idx) => (
        <TradeSuggestionCard key={item.id ?? idx} suggestion={item} onLogged={handleLogged} />
      ))}
    </div>
  );
}
