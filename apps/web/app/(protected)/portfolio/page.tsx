// apps/web/app/(protected)/portfolio/page.tsx
'use client';

// ... imports
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DataTable } from '@/components/portfolio/data-table'; // Assuming this component exists
import { optionColumns, stockColumns } from '@/components/portfolio/columns'; // Assuming these exist
import { usePortfolio } from '@/hooks/usePortfolio'; // Assuming this hook exists

export default function PortfolioPage() {
  const { positions, isLoading } = usePortfolio();

  // Helper: Aggregate Portfolio Greeks
  const portfolioDelta = positions.reduce((acc, pos) => acc + (pos.greeks?.delta || 0), 0);
  const portfolioTheta = positions.reduce((acc, pos) => acc + (pos.greeks?.theta || 0), 0);

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="space-y-6 p-4">
      {/* 1. Portfolio Health Header */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
           <CardHeader className="pb-2"><CardTitle className="text-sm">Net Portfolio Delta</CardTitle></CardHeader>
           <CardContent>
             <div className="text-2xl font-bold">{portfolioDelta.toFixed(2)}</div>
             <p className="text-xs text-muted-foreground">Market Direction Bias</p>
           </CardContent>
        </Card>
        <Card>
           <CardHeader className="pb-2"><CardTitle className="text-sm">Daily Theta Decay</CardTitle></CardHeader>
           <CardContent>
             <div className="text-2xl font-bold text-green-400">${portfolioTheta.toFixed(2)}</div>
             <p className="text-xs text-muted-foreground">Time value collected/day</p>
           </CardContent>
        </Card>
        {/* ... Liquidity / Cash metrics ... */}
      </div>

      {/* 2. Grouped Holdings Table */}
      <Tabs defaultValue="options" className="w-full">
        <TabsList>
          <TabsTrigger value="options">Active Options</TabsTrigger>
          <TabsTrigger value="shares">Long Term Holds</TabsTrigger>
        </TabsList>

        <TabsContent value="options">
          <DataTable
             columns={optionColumns}
             data={positions.filter(p => p.type === 'option')}
             filterKey="symbol"
          />
        </TabsContent>
        <TabsContent value="shares">
          <DataTable
             columns={stockColumns}
             data={positions.filter(p => p.type === 'equity')}
             filterKey="symbol"
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
