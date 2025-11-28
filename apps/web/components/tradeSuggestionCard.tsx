
import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface TradeSuggestionCardProps {
  trade: {
    symbol: string;
    strategy?: string;
    type?: string;
    score: number;
    badges: string[];
    rationale: string;
  };
}

const TradeSuggestionCard: React.FC<TradeSuggestionCardProps> = ({ trade }) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{trade.symbol} - {trade.strategy || trade.type}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex justify-between items-center mb-4">
          <div className="flex flex-col">
            <span className="text-xs text-gray-500 font-medium uppercase tracking-wider">OTC Score</span>
            <span className="text-2xl font-bold">{trade.score}/100</span>
          </div>
          <div className="flex space-x-2">
            {trade.badges.map((badge) => (
              <Badge key={badge}>{badge}</Badge>
            ))}
          </div>
        </div>
        <p className="text-sm text-gray-500">{trade.rationale}</p>
      </CardContent>
    </Card>
  );
};

export default TradeSuggestionCard;
