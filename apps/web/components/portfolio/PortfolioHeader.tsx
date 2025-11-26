import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, TrendingUp, Clock } from "lucide-react";

interface PortfolioMetrics {
  totalDelta: number;
  totalTheta: number;
  netLiquidity: number;
  buyingPower: number;
}

export function PortfolioHeader({ metrics }: { metrics: PortfolioMetrics }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Net Liquidity</CardTitle>
          <TrendingUp className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">${metrics.netLiquidity.toLocaleString()}</div>
          <p className="text-xs text-muted-foreground">Total Account Value</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Portfolio Delta</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          {/* Color code Delta: Green for positive (Bullish), Red for negative (Bearish) */}
          <div className={`text-2xl font-bold ${metrics.totalDelta >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {metrics.totalDelta.toFixed(2)}
          </div>
          <p className="text-xs text-muted-foreground">Directional Exposure</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Daily Theta</CardTitle>
          <Clock className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-green-500">
            +${metrics.totalTheta.toFixed(2)}
          </div>
          <p className="text-xs text-muted-foreground">Time Decay Collected / Day</p>
        </CardContent>
      </Card>

       <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Buying Power</CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">${metrics.buyingPower.toLocaleString()}</div>
          <p className="text-xs text-muted-foreground">Available for deployment</p>
        </CardContent>
      </Card>
    </div>
  );
}