// apps/web/components/scout/TradeCard.tsx
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function TradeCard({ trade }) {
  const isBlocked = trade.status === 'blocked';

  return (
    <Card className={`w-full ${isBlocked ? 'opacity-60 grayscale' : 'border-green-500/50'}`}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg font-bold">
          {trade.symbol} <span className="text-sm font-normal text-muted-foreground">{trade.strategy}</span>
        </CardTitle>
        {/* The Alpha Score Badge */}
        {!isBlocked && (
          <Badge variant="outline" className="bg-green-950 text-green-400 border-green-800">
            Score: {trade.alpha_score}
          </Badge>
        )}
      </CardHeader>

      <CardContent>
        <div className="grid grid-cols-2 gap-4 text-sm mb-4">
          <div>
            <p className="text-muted-foreground">Strike / Exp</p>
            <p className="font-mono">{trade.strikes} @ {trade.expiration}</p>
          </div>
          <div>
            <p className="text-muted-foreground">IV Rank</p>
            <p className={`font-mono ${trade.iv_rank > 50 ? 'text-yellow-400' : 'text-foreground'}`}>
              {trade.iv_rank}%
            </p>
          </div>
        </div>

        {/* Detailed Greeks Grid */}
        <div className="grid grid-cols-4 gap-2 text-xs bg-secondary/30 p-2 rounded-md mb-3">
          <div className="text-center">
            <span className="block text-muted-foreground">Δ Delta</span>
            {trade.greeks.delta}
          </div>
          <div className="text-center">
            <span className="block text-muted-foreground">Θ Theta</span>
            <span className="text-green-400">{trade.greeks.theta}</span>
          </div>
          <div className="text-center">
            <span className="block text-muted-foreground">POP%</span>
            {(trade.prob_profit * 100).toFixed(0)}%
          </div>
          <div className="text-center">
            <span className="block text-muted-foreground">EV</span>
            ${trade.expected_value}
          </div>
        </div>

        {isBlocked ? (
          <div className="text-red-400 text-sm font-semibold flex items-center gap-2">
            🚫 Guardrail: {trade.rejection_reason}
          </div>
        ) : (
          <button className="w-full bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-4 py-2 rounded text-sm">
            Analyze & Stage
          </button>
        )}
      </CardContent>
    </Card>
  )
}
