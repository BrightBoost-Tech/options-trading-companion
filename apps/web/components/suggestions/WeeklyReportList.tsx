import React from 'react';
import { FileText, TrendingUp, TrendingDown, Crosshair, Download } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface WeeklyReport {
  id: string;
  report_date: string;
  start_date: string;
  end_date: string;
  total_pnl: number;
  win_rate: number;
  trade_count: number;
  missed_opportunities: any[];
  report_markdown: string;
}

interface WeeklyReportListProps {
  reports: WeeklyReport[];
}

export default function WeeklyReportList({ reports }: WeeklyReportListProps) {
  const [selectedReportId, setSelectedReportId] = React.useState<string | null>(
    reports && reports.length > 0 ? reports[0].id : null
  );

  React.useEffect(() => {
     if (reports && reports.length > 0 && (!selectedReportId || !reports.find(r => r.id === selectedReportId))) {
         setSelectedReportId(reports[0].id);
     }
  }, [reports, selectedReportId]);

  if (!reports || reports.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400">
        <FileText className="w-10 h-10 mx-auto mb-3 opacity-20" />
        <p>No weekly reports available.</p>
        <p className="text-xs mt-1">Reports are generated at the end of each trading week.</p>
      </div>
    );
  }

  const selectedReport = reports.find((r) => r.id === selectedReportId) || reports[0];

  const handleDownload = () => {
    if (!selectedReport) return;
    const blob = new Blob([selectedReport.report_markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `weekly-report-${selectedReport.end_date}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col md:flex-row gap-4 h-[600px]">
      {/* Sidebar List */}
      <div className="w-full md:w-1/3 border-r border-gray-100 pr-2 overflow-y-auto">
        <h3 className="text-xs font-semibold text-gray-500 uppercase mb-3">Report History</h3>
        <div className="space-y-2">
          {reports.map((report) => (
            <button
              key={report.id}
              onClick={() => setSelectedReportId(report.id)}
              className={`w-full text-left p-3 rounded-lg border transition-colors ${
                selectedReportId === report.id
                  ? 'bg-indigo-50 border-indigo-200 shadow-sm'
                  : 'bg-white border-gray-100 hover:bg-gray-50'
              }`}
            >
              <div className="flex justify-between items-center mb-1">
                <span className="font-semibold text-gray-800 text-sm">
                  Week End {new Date(report.end_date || report.report_date).toLocaleDateString()}
                </span>
                {report.total_pnl >= 0 ? (
                  <TrendingUp className="w-3 h-3 text-green-500" />
                ) : (
                  <TrendingDown className="w-3 h-3 text-red-500" />
                )}
              </div>
              <div className="flex gap-2 text-xs text-gray-500">
                <span>{report.trade_count} Trades</span>
                <span>•</span>
                <span>{Math.round(report.win_rate * 100)}% WR</span>
                <span>•</span>
                <span className={report.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                  ${report.total_pnl.toFixed(0)}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="w-full md:w-2/3 pl-2 overflow-y-auto">
        <div className="flex justify-between items-start mb-4 border-b border-gray-100 pb-2">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Weekly Performance Review</h2>
            <p className="text-xs text-gray-500">
              {selectedReport.start_date ? new Date(selectedReport.start_date).toLocaleDateString() : 'Start'} -{' '}
              {new Date(selectedReport.end_date || selectedReport.report_date).toLocaleDateString()}
            </p>
          </div>
          <button
            onClick={handleDownload}
            className="text-xs flex items-center gap-1 text-gray-500 hover:text-gray-800"
          >
            <Download className="w-3 h-3" />
            Download
          </button>
        </div>

        {/* Top Metrics Cards */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-gray-50 p-3 rounded border border-gray-100 text-center">
            <div className="text-xs text-gray-500 uppercase">Net P&L</div>
            <div className={`text-xl font-bold ${selectedReport.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              ${selectedReport.total_pnl.toFixed(2)}
            </div>
          </div>
          <div className="bg-gray-50 p-3 rounded border border-gray-100 text-center">
            <div className="text-xs text-gray-500 uppercase">Win Rate</div>
            <div className="text-xl font-bold text-gray-800">{Math.round(selectedReport.win_rate * 100)}%</div>
          </div>
          <div className="bg-gray-50 p-3 rounded border border-gray-100 text-center">
            <div className="text-xs text-gray-500 uppercase">Trades</div>
            <div className="text-xl font-bold text-gray-800">{selectedReport.trade_count}</div>
          </div>
        </div>

        {/* Missed Opportunities */}
        {selectedReport.missed_opportunities && selectedReport.missed_opportunities.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
              <Crosshair className="w-4 h-4 text-orange-500" />
              Missed Opportunities
            </h3>
            <div className="space-y-2">
              {selectedReport.missed_opportunities.map((opp: any, idx: number) => (
                <div key={idx} className="bg-orange-50 p-2 rounded border border-orange-100 text-xs flex justify-between items-center">
                  <span className="font-semibold text-gray-800">{opp.ticker || opp.symbol}</span>
                  <span className="text-gray-600">{opp.reason || 'High probability setup missed'}</span>
                  <Badge variant="outline" className="text-[10px] bg-white text-orange-600 border-orange-200">
                    Missed
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Markdown Content */}
        <div>
          <h3 className="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
            <FileText className="w-4 h-4 text-indigo-500" />
            Detailed Analysis
          </h3>
          <div className="prose prose-sm max-w-none text-gray-600 bg-white p-4 rounded border border-gray-100 whitespace-pre-wrap font-mono text-xs">
            {selectedReport.report_markdown}
          </div>
        </div>
      </div>
    </div>
  );
}
