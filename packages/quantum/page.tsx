import PortfolioHoldingsTable from '@/components/portfolio/PortfolioHoldingsTable';
import SyncHoldingsButton from '@/components/portfolio/SyncHoldingsButton';

export default function PortfolioPage() {
  return (
    <div className="p-8 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-white">Portfolio</h1>
          <p className="text-gray-400 mt-1">Real-time holdings and performance</p>
        </div>
        <SyncHoldingsButton />
      </div>

      {/* Summary Cards could go here */}
      
      <div className="mt-8">
        <PortfolioHoldingsTable />
      </div>
    </div>
  );
}