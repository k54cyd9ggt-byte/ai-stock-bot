"""Research-only daily close-to-close paper trading. Never submits live orders."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parent
FEATURES = ['r1', 'r5', 'r20', 'vol20', 'ma10', 'ma50', 'range']


def features(df):
    close = df['Close'].astype(float)
    out = pd.DataFrame(index=df.index)
    out['r1'] = close.pct_change()
    out['r5'] = close.pct_change(5)
    out['r20'] = close.pct_change(20)
    out['vol20'] = out['r1'].rolling(20).std()
    out['ma10'] = close / close.rolling(10).mean() - 1
    out['ma50'] = close / close.rolling(50).mean() - 1
    out['range'] = (df['High'] - df['Low']) / close
    out['next_return'] = close.shift(-1) / close - 1
    return out.replace([np.inf, -np.inf], np.nan)


def load(symbol, years):
    raw = yf.download(symbol, period=f'{years}y', auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise ValueError(f'No data for {symbol}')
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw[['Close', 'High', 'Low']].dropna()
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize() if raw.index.tz is None else pd.to_datetime(raw.index).tz_convert(None).normalize()
    return raw


def predict_at(frame, idx, min_train):
    # At close idx, labels up to idx-1 are already observable.
    history = frame.iloc[:idx].dropna(subset=FEATURES + ['next_return'])
    current = frame.iloc[idx]
    if len(history) < min_train or current[FEATURES].isna().any():
        return 0.0
    y = (history['next_return'] > 0).astype(int)
    if y.nunique() < 2:
        return float(y.iloc[-1])
    model = RandomForestClassifier(n_estimators=80, max_depth=5, min_samples_leaf=8,
                                   random_state=42, n_jobs=1)
    model.fit(history[FEATURES], y)
    probs = model.predict_proba(pd.DataFrame([current[FEATURES].values], columns=FEATURES))
    return float(probs[0, list(model.classes_).index(1)])


def target_weights(probs, cfg):
    chosen = sorted(((s, v) for s, v in probs.items() if v >= cfg['min_probability']),
                    key=lambda x: x[1], reverse=True)
    weights = {}
    remaining = cfg['max_total_exposure']
    for symbol, _ in chosen:
        w = min(cfg['max_position_weight'], remaining)
        if w <= 0:
            break
        weights[symbol] = w
        remaining -= w
    return weights


def backtest(data, cfg):
    # Calendar-aligned prices: use only dates shared by all symbols to avoid
    # forward-filling across different exchange holidays.
    common = sorted(set.intersection(*(set(d.index) for d in data.values())))
    frames = {s: features(d.loc[common]) for s, d in data.items()}
    cash = cfg['initial_cash_jpy']; peak = cash
    rows = []; halted = False; old_weights = {}
    start = max(cfg['training_days'] + 55, 310)
    for idx in range(start, len(common)-1):
        day = str(common[idx].date())
        probs = {s: predict_at(f, idx, cfg['training_days']) for s, f in frames.items()}
        weights = {} if halted else target_weights(probs, cfg)
        turnover = sum(abs(weights.get(s, 0)-old_weights.get(s, 0)) for s in data)
        fee = turnover * cfg['fee_bps'] / 10000
        next_return = sum(weights.get(s, 0) * float(f.iloc[idx]['next_return'])
                          for s, f in frames.items())
        daily = next_return - fee
        cash *= max(0, 1 + daily)
        peak = max(peak, cash)
        dd = 1 - cash / peak
        if dd >= cfg['max_drawdown'] or daily <= -cfg['max_daily_loss']:
            halted = True
        rows.append({'date': day, 'equity_jpy': round(cash, 2),
                     'daily_return': round(daily, 7), 'drawdown': round(dd, 5),
                     'halted': halted, 'weights': json.dumps(weights)})
        old_weights = weights
    return pd.DataFrame(rows)


def paper(data, cfg, state_path):
    # Accounting uses last close-to-close returns of PREVIOUS positions.
    # New decisions are recorded for the NEXT close-to-close period.
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'equity_jpy': cfg['initial_cash_jpy'], 'peak_jpy': cfg['initial_cash_jpy'],
        'weights': {}, 'last_close': {}, 'last_dates': {}, 'halted': False, 'history': []}
    latest_dates = {s: str(d.index[-1].date()) for s, d in data.items()}
    if state.get('last_dates') == latest_dates:
        print('No new market closes; state unchanged')
        return
    old_weights = state.get('weights', {})
    pnl = 0.0
    for s, w in old_weights.items():
        if s in state.get('last_close', {}) and s in data:
            old = state['last_close'][s]
            if old > 0:
                pnl += w * (float(data[s]['Close'].iloc[-1]) / old - 1)
    equity = state['equity_jpy'] * max(0, 1+pnl)
    peak = max(state.get('peak_jpy', equity), equity)
    drawdown = 1-equity/peak
    halted = bool(state.get('halted')) or drawdown >= cfg['max_drawdown'] or pnl <= -cfg['max_daily_loss']
    probs = {}
    for s, d in data.items():
        f = features(d)
        probs[s] = predict_at(f, len(f)-1, cfg['training_days'])
    weights = {} if halted else target_weights(probs, cfg)
    turnover = sum(abs(weights.get(s,0)-old_weights.get(s,0)) for s in data)
    fee = equity * turnover * cfg['fee_bps']/10000
    equity -= fee
    record = {'time_utc': datetime.now(timezone.utc).isoformat(),
              'market_dates': latest_dates, 'equity_jpy': round(equity,2),
              'drawdown': round(1-equity/peak,5), 'probabilities': probs,
              'target_weights': weights, 'halted': halted}
    state.update({'equity_jpy': equity, 'peak_jpy': peak, 'weights': weights,
                  'last_close': {s:float(d['Close'].iloc[-1]) for s,d in data.items()},
                  'last_dates': latest_dates, 'halted': halted,
                  'history': (state.get('history',[])+[record])[-500:]})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(json.dumps(record, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['backtest', 'paper'])
    parser.add_argument('--config', default=str(ROOT/'config.json'))
    parser.add_argument('--state', default=str(ROOT/'state/paper.json'))
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    if cfg['max_total_exposure'] > 1 or cfg['max_position_weight'] > 1:
        raise ValueError('Exposure must be <= 1')
    data = {}
    for s in cfg['symbols']:
        try:
            data[s] = load(s, cfg['lookback_years'])
        except Exception as exc:
            print(f'ERROR downloading {s}: {exc}')
            raise SystemExit(1)
    if args.mode == 'backtest':
        result = backtest(data, cfg)
        if result.empty:
            raise SystemExit('Not enough shared trading dates for backtest')
        (ROOT/'output').mkdir(exist_ok=True)
        result.to_csv(ROOT/'output/backtest.csv', index=False)
        total = result['equity_jpy'].iloc[-1]/cfg['initial_cash_jpy']-1
        print(f'Final equity: {result["equity_jpy"].iloc[-1]:,.0f} JPY | Return: {total:.2%} | Max drawdown: {result["drawdown"].max():.2%}')
    else:
        paper(data, cfg, Path(args.state))


if __name__ == '__main__':
    main()
