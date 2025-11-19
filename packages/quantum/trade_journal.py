"""
Trade Journal with Auto-Learning
Tracks trades and learns what works
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict


class TradeJournal:
    def __init__(self, journal_file='trade_journal.json'):
        self.journal_file = journal_file
        self.trades = self._load_trades()
    
    def _load_trades(self) -> List[Dict]:
        """Load trades from JSON file"""
        if os.path.exists(self.journal_file):
            with open(self.journal_file, 'r') as f:
                return json.load(f)
        return []
    
    def _save_trades(self):
        """Save trades to JSON file"""
        with open(self.journal_file, 'w') as f:
            json.dump(self.trades, f, indent=2)
    
    def add_trade(
        self,
        symbol: str,
        strategy: str,
        entry_date: str,
        entry_price: float,
        strikes: str,
        dte: int,
        iv_rank: float,
        max_gain: float,
        max_loss: float,
        notes: str = ""
    ) -> Dict:
        """Add a new trade"""
        trade = {
            'id': len(self.trades) + 1,
            'symbol': symbol,
            'strategy': strategy,
            'entry_date': entry_date,
            'entry_price': entry_price,
            'strikes': strikes,
            'dte': dte,
            'iv_rank': iv_rank,
            'max_gain': max_gain,
            'max_loss': max_loss,
            'notes': notes,
            'status': 'open',
            'exit_date': None,
            'exit_price': None,
            'pnl': None,
            'pnl_pct': None
        }
        
        self.trades.append(trade)
        self._save_trades()
        return trade
    
    def close_trade(self, trade_id: int, exit_date: str, exit_price: float) -> Dict:
        """Close a trade and calculate P&L"""
        trade = next((t for t in self.trades if t['id'] == trade_id), None)
        
        if not trade:
            raise ValueError(f"Trade {trade_id} not found")
        
        if trade['status'] == 'closed':
            raise ValueError(f"Trade {trade_id} already closed")
        
        # Calculate P&L
        pnl = exit_price - trade['entry_price']
        pnl_pct = (pnl / abs(trade['entry_price'])) * 100 if trade['entry_price'] != 0 else 0
        
        trade.update({
            'status': 'closed',
            'exit_date': exit_date,
            'exit_price': exit_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })
        
        self._save_trades()
        
        # Auto-learn from this trade
        self._learn_from_trade(trade)
        
        return trade
    
    def _learn_from_trade(self, trade: Dict):
        """Automatically learn patterns from closed trade"""
        patterns = self.analyze_patterns()
        
        # Print what we learned
        print(f"\n📚 Learning from {trade['symbol']} trade:")
        print(f"   P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.1f}%)")
        
        if trade['pnl'] > 0:
            print(f"   ✅ Winner! This setup worked:")
            print(f"      • {trade['strategy']} on {trade['symbol']}")
            print(f"      • IV Rank: {trade['iv_rank']*100:.0f}%")
            print(f"      • DTE: {trade['dte']} days")
        else:
            print(f"   ❌ Loser. Avoid this setup:")
            print(f"      • {trade['strategy']} on {trade['symbol']}")
            print(f"      • When IV Rank = {trade['iv_rank']*100:.0f}%")
    
    def analyze_patterns(self) -> Dict:
        """Analyze all closed trades to find winning patterns"""
        closed_trades = [t for t in self.trades if t['status'] == 'closed']
        
        if not closed_trades:
            return {'message': 'No closed trades yet'}
        
        # Group by strategy
        by_strategy = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0})
        
        for trade in closed_trades:
            strategy = trade['strategy']
            if trade['pnl'] > 0:
                by_strategy[strategy]['wins'] += 1
            else:
                by_strategy[strategy]['losses'] += 1
            by_strategy[strategy]['total_pnl'] += trade['pnl']
        
        # Calculate win rates
        patterns = {}
        for strategy, stats in by_strategy.items():
            total = stats['wins'] + stats['losses']
            win_rate = (stats['wins'] / total * 100) if total > 0 else 0
            
            patterns[strategy] = {
                'win_rate': win_rate,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / total if total > 0 else 0
            }
        
        # Group by IV rank
        high_iv_trades = [t for t in closed_trades if t['iv_rank'] > 0.60]
        low_iv_trades = [t for t in closed_trades if t['iv_rank'] <= 0.60]
        
        high_iv_wins = sum(1 for t in high_iv_trades if t['pnl'] > 0)
        low_iv_wins = sum(1 for t in low_iv_trades if t['pnl'] > 0)
        
        patterns['iv_rank_analysis'] = {
            'high_iv_win_rate': (high_iv_wins / len(high_iv_trades) * 100) if high_iv_trades else 0,
            'low_iv_win_rate': (low_iv_wins / len(low_iv_trades) * 100) if low_iv_trades else 0
        }
        
        return patterns
    
    def generate_rules(self) -> List[str]:
        """Auto-generate trading rules based on patterns"""
        patterns = self.analyze_patterns()
        rules = []
        
        if 'iv_rank_analysis' in patterns:
            high_iv_wr = patterns['iv_rank_analysis']['high_iv_win_rate']
            low_iv_wr = patterns['iv_rank_analysis']['low_iv_win_rate']
            
            if high_iv_wr > low_iv_wr + 10:
                rules.append(f"✅ RULE: Only trade when IV Rank > 60% (Win rate: {high_iv_wr:.0f}% vs {low_iv_wr:.0f}%)")
        
        for strategy, stats in patterns.items():
            if strategy == 'iv_rank_analysis':
                continue
                
            if stats['win_rate'] > 70:
                rules.append(f"✅ RULE: {strategy} is working well ({stats['win_rate']:.0f}% win rate) - keep doing it!")
            elif stats['win_rate'] < 40:
                rules.append(f"❌ RULE: Stop {strategy} ({stats['win_rate']:.0f}% win rate) - it's not working")
        
        return rules
    
    def get_stats(self) -> Dict:
        """Get overall statistics"""
        closed_trades = [t for t in self.trades if t['status'] == 'closed']
        open_trades = [t for t in self.trades if t['status'] == 'open']
        
        if not closed_trades:
            return {
                'total_trades': len(self.trades),
                'open_trades': len(open_trades),
                'closed_trades': 0,
                'win_rate': 0,
                'total_pnl': 0
            }
        
        winners = sum(1 for t in closed_trades if t['pnl'] > 0)
        total_pnl = sum(t['pnl'] for t in closed_trades)
        
        return {
            'total_trades': len(self.trades),
            'open_trades': len(open_trades),
            'closed_trades': len(closed_trades),
            'winners': winners,
            'losers': len(closed_trades) - winners,
            'win_rate': (winners / len(closed_trades) * 100),
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(closed_trades)
        }


if __name__ == '__main__':
    # Demo
    journal = TradeJournal()
    
    # Add some sample trades
    if len(journal.trades) == 0:
        print("Adding sample trades...")
        
        # Trade 1: Winner
        t1 = journal.add_trade(
            symbol='SPY',
            strategy='Credit Put Spread',
            entry_date='2025-11-01',
            entry_price=-1.25,
            strikes='575/570',
            dte=37,
            iv_rank=0.62,
            max_gain=125,
            max_loss=375,
            notes='High IV rank, good setup'
        )
        journal.close_trade(t1['id'], '2025-11-15', 0.50)
        
        # Trade 2: Loser
        t2 = journal.add_trade(
            symbol='QQQ',
            strategy='Credit Put Spread',
            entry_date='2025-11-05',
            entry_price=-1.50,
            strikes='495/490',
            dte=30,
            iv_rank=0.45,
            max_gain=150,
            max_loss=350,
            notes='Low IV, probably shouldnt have taken this'
        )
        journal.close_trade(t2['id'], '2025-11-20', -3.50)
        
        # Trade 3: Winner
        t3 = journal.add_trade(
            symbol='AAPL',
            strategy='Credit Put Spread',
            entry_date='2025-11-10',
            entry_price=-1.30,
            strikes='235/230',
            dte=35,
            iv_rank=0.72,
            max_gain=130,
            max_loss=370,
            notes='Excellent IV rank'
        )
        journal.close_trade(t3['id'], '2025-11-25', 0.40)
    
    # Show stats
    stats = journal.get_stats()
    print("\n" + "="*60)
    print("Trade Journal Statistics")
    print("="*60)
    print(f"Total Trades: {stats['total_trades']}")
    print(f"Closed: {stats['closed_trades']} | Open: {stats['open_trades']}")
    print(f"Winners: {stats['winners']} | Losers: {stats['losers']}")
    print(f"Win Rate: {stats['win_rate']:.1f}%")
    print(f"Total P&L: ${stats['total_pnl']:.2f}")
    print(f"Avg P&L per Trade: ${stats['avg_pnl']:.2f}")
    
    # Show learned rules
    print("\n" + "="*60)
    print("Auto-Generated Rules (Based on Your Trades)")
    print("="*60)
    rules = journal.generate_rules()
    for rule in rules:
        print(rule)
    
    # Show patterns
    print("\n" + "="*60)
    print("Pattern Analysis")
    print("="*60)
    patterns = journal.analyze_patterns()
    for strategy, stats in patterns.items():
        if strategy == 'iv_rank_analysis':
            continue
        print(f"\n{strategy}:")
        print(f"  Win Rate: {stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${stats['total_pnl']:.2f}")
        print(f"  Avg Trade: ${stats['avg_pnl']:.2f}")
