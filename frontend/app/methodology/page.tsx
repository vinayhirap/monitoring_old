"use client";

import { Panel, Stat } from "@/components/Panel";

export default function MethodologyPage() {
  return (
    <div className="space-y-4 max-w-5xl">
      <Panel title="Methodology — how decisions are made">
        <p className="text-[12px] text-text-secondary leading-relaxed">
          MarketLens is a <span className="text-accent-amber">gated multi-layer signal aggregator</span>.
          Every recommendation flows through four serial stages, each of which can drop a candidate.
          No layer makes a unilateral call — disagreement between layers actively downgrades the score
          (this is the platform's defining property).
        </p>
      </Panel>

      <Panel title="Stage 1 — Cyclical Pre-Filter">
        <p className="text-[12px] text-text-secondary">
          Computes a single 0–100 esoteric score per symbol from four price-independent inputs:
        </p>
        <table className="w-full text-[12px] tabular mt-2">
          <thead className="text-text-muted text-[10px] uppercase">
            <tr className="border-b border-bg-line">
              <th className="text-left py-1">Component</th>
              <th className="text-right">Weight</th>
              <th className="text-left pl-3">What it measures</th>
            </tr>
          </thead>
          <tbody className="text-text-secondary">
            <Row what="Vedic timing (symbol-nakshatra match)" weight="18%" desc="Moon's nakshatra distance from the symbol's ruling nakshatra (tara). Ruling planet retrograde/direct status." />
            <Row what="Symbol-cycles (numerology)" weight="12%" desc="Pythagorean + Chaldean reduction; symbol-root vs date-root compatibility." />
            <Row what="Gann Square of 9 proximity" weight="35%" desc="Distance from anchor price to nearest Gann level at standard angular harmonics." />
            <Row what="Fibonacci golden-ratio proximity" weight="35%" desc="Auto-detected swing; distance from price to nearest retracement/extension." />
          </tbody>
        </table>
        <p className="text-[11px] text-text-muted mt-2">
          Threshold: <code>esoteric_min</code> (default 55). Symbols below this drop out.
        </p>
      </Panel>

      <Panel title="Stage 2 — Technical Confirmation">
        <p className="text-[12px] text-text-secondary">
          On survivors only, runs the technical engine and computes a combined score:
        </p>
        <table className="w-full text-[12px] tabular mt-2">
          <tbody className="text-text-secondary">
            <Row what="Standard indicators" weight="60%" desc="EMA stack (9/20/50/200), RSI(14), MACD(12/26/9), Bollinger(20,2), ATR(14), ADX(14), VWAP." />
            <Row what="Smart Money Concepts" weight="40%" desc="Pivot structure (HH/HL/LH/LL), BoS, CHoCH, Order Blocks, Fair Value Gaps, premium/discount zone." />
          </tbody>
        </table>
        <p className="text-[11px] text-text-muted mt-2">
          Threshold: <code>technical_min</code> (default 55). Optional <code>require_agreement</code> gate
          drops finalists whose technical direction disagrees with esoteric direction.
        </p>
      </Panel>

      <Panel title="Stage 3 — Strategy Selection">
        <p className="text-[12px] text-text-secondary">
          For each confirmed symbol, picks a playbook from 11 options based on (direction × confidence × IV regime × horizon):
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-2 text-[11px]">
          {[
            "EQUITY_BUY", "EQUITY_SHORT", "FUT_LONG", "FUT_SHORT",
            "OPT_CE_BUY", "OPT_PE_BUY", "OPT_BULL_CALL_SPREAD",
            "OPT_BEAR_PUT_SPREAD", "OPT_IRON_CONDOR", "OPT_LONG_STRADDLE",
            "OPT_SHORT_STRANGLE", "WAIT",
          ].map((s) => (
            <span key={s} className="px-2 py-1 bg-bg-panel border border-bg-line rounded text-text-secondary font-mono">{s}</span>
          ))}
        </div>
        <p className="text-[11px] text-text-muted mt-3">
          Computes entry, ATR-based stoploss, multi-target ladder, position sizing,
          capital allocation %, expected max profit/loss, and option legs.
        </p>
      </Panel>

      <Panel title="Stage 3.5 — Consistency Validator (the unique part)">
        <p className="text-[12px] text-text-secondary">
          After a strategy is selected, the validator re-checks the strategy's <em>direction</em> against
          the <em>individual</em> Stage-1 components (not the aggregate). This catches cases like
          <span className="text-accent-amber"> "OPT_CE_BUY recommended even though per-symbol astrology and
          current hora are bearish"</span> — which the aggregate score would have hidden.
        </p>
        <table className="w-full text-[12px] tabular mt-2">
          <thead className="text-text-muted text-[10px] uppercase">
            <tr className="border-b border-bg-line">
              <th className="text-left py-1">Check</th>
              <th className="text-center">Severity</th>
              <th className="text-left pl-3">Trigger condition</th>
            </tr>
          </thead>
          <tbody className="text-text-secondary">
            <ValRow check="Per-symbol astro" sev="HIGH" cond="Stage-1 astro bias opposite to strategy direction" />
            <ValRow check="Lunar gate" sev="HIGH" cond="Full Moon zone / New Moon zone / Void-of-Course / eclipse window / Riktha tithi" />
            <ValRow check="Current hora" sev="HIGH/MEDIUM" cond="Bearish hora (Saturn weight 0.9 → HIGH, Mars 0.7 → MEDIUM) when strategy is bullish, etc." />
            <ValRow check="Numerology" sev="LOW" cond="Symbol-vs-date compatibility opposite to strategy direction" />
            <ValRow check="Market sentiment" sev="LOW" cond="Overall market climate opposite to strategy direction" />
          </tbody>
        </table>
        <p className="text-[11px] text-text-muted mt-2">
          <span className="text-accent-amber">Mode: strict (default)</span> → 1+ HIGH conflict downgrades the strategy to WAIT.
          Mode: warn → keeps the trade, annotates only. Mode: block → ANY conflict downgrades.
        </p>
      </Panel>

      <Panel title="Stage 4 — Accuracy Attachment">
        <p className="text-[12px] text-text-secondary">
          Runs a fast walk-forward backtest on the last 120 bars of the symbol with the chosen confidence
          threshold. Attaches: <code>hit_rate</code>, <code>profit_factor</code>, <code>expectancy_pct</code>,
          <code>max_drawdown_pct</code>, plus a <code>sample_size_warning</code> when trade count &lt; 8.
        </p>
        <p className="text-[11px] text-text-muted mt-2">
          Note: Stage-4 uses Technical + SMC only (the price-anchored engines).
          Astrology and numerology are real-time inputs — they'd take the same value across all historical
          bars in any single run, which makes them useless for walk-forward validation. This is the
          honest framing — see <a href="/docs/ACCURACY.md" className="text-accent-amber underline">ACCURACY.md</a> for more.
        </p>
      </Panel>

      <Panel title="Final Confidence Blend">
        <p className="text-[12px] text-text-secondary mb-2">For BULLISH direction:</p>
        <pre className="text-[11px] text-accent-amber bg-bg-base/40 p-2 rounded font-mono">
{`final_confidence = 0.30 × esoteric_score
                 + 0.50 × technical_score
                 + 0.20 × historical_hit_rate    (if >=5 backtest trades)
                 + confluence_boost              (max +18 if 6/6 engines aligned)
                 + validator_adjustment          (negative for warnings; -100 for downgrade)`}
        </pre>
        <p className="text-[12px] text-text-secondary mt-2">For BEARISH direction, the first 2 terms invert (100 − score).</p>
      </Panel>

      <Panel title="Quality Grading (4 tiers)">
        <table className="w-full text-[12px] tabular">
          <thead className="text-text-muted text-[10px] uppercase">
            <tr className="border-b border-bg-line">
              <th className="text-left py-1">Tier</th>
              <th className="text-left">Required Conditions</th>
              <th className="text-center">Typical frequency</th>
              <th className="text-center">Honest hit-rate ceiling</th>
            </tr>
          </thead>
          <tbody className="text-text-secondary">
            <QualityRow tier="◆ DIAMOND" color="text-accent-violet" cond="6/6 confluence + lunar PROCEED + 0 HIGH conflicts + hist hit-rate ≥70%" freq="0–3 per scan" rate="70–80%" />
            <QualityRow tier="★ GOLD" color="text-accent-amber" cond="5/6 confluence + lunar PROCEED + 0 HIGH conflicts" freq="2–6 per scan" rate="60–70%" />
            <QualityRow tier="SILVER" color="text-text-secondary" cond="4/6 confluence + lunar PROCEED/CAUTION + 0 HIGH conflicts" freq="5–10 per scan" rate="55–65%" />
            <QualityRow tier="STANDARD" color="text-text-muted" cond="Passed Stages 1–2" freq="10–15 per scan" rate="50–60%" />
          </tbody>
        </table>
      </Panel>

      <Panel title="What this platform does NOT do (the honest limits)">
        <ul className="text-[12px] text-text-secondary list-disc pl-5 space-y-1">
          <li>Predict prices. The scores measure <em>engine agreement</em>, not future price.</li>
          <li>Guarantee any hit-rate. The 70–80% DIAMOND ceiling is what's achievable in backtests on real data with strict filtering — not what the platform has demonstrated to you on real money.</li>
          <li>Replace your own judgement. Every signal needs independent verification (chart inspection, news check, sector context).</li>
          <li>Model slippage, commissions, or impact cost. Net realized performance is lower than gross backtest stats.</li>
          <li>Account for market regime shifts. A 65% hit-rate in trending months can become 40% in chop.</li>
        </ul>
      </Panel>

      <Panel title="Data sources">
        <ul className="text-[12px] text-text-secondary list-disc pl-5 space-y-1">
          <li><b>Planetary positions</b>: Swiss Ephemeris (Moshier algorithm, no external data files needed). Accuracy ~1″ for Moon, ~0.01″ for outer planets.</li>
          <li><b>Sidereal calculations</b>: Lahiri ayanamsa (the official Indian government ayanamsa).</li>
          <li><b>Sunrise/sunset</b>: Computed for the configured lat/lon via Swiss Ephemeris (no fixed clock).</li>
          <li><b>Market candles</b>: Angel One SmartAPI when authenticated, deterministic synthetic OHLCV in paper mode.</li>
          <li><b>Instrument master</b>: Angel One scrip-master JSON (~80k instruments), cached locally, refreshed daily.</li>
        </ul>
      </Panel>

      <p className="text-[10px] text-text-muted text-center py-2">
        Educational and analytical use only. Not SEBI-registered investment advice.
      </p>
    </div>
  );
}

function Row({ what, weight, desc }: { what: string; weight: string; desc: string }) {
  return (
    <tr className="border-b border-bg-line/40">
      <td className="py-1 text-text-primary">{what}</td>
      <td className="text-right text-accent-amber tabular">{weight}</td>
      <td className="pl-3 text-[11px] text-text-muted">{desc}</td>
    </tr>
  );
}

function ValRow({ check, sev, cond }: { check: string; sev: string; cond: string }) {
  return (
    <tr className="border-b border-bg-line/40">
      <td className="py-1 text-text-primary">{check}</td>
      <td className={`text-center text-[10px] font-bold uppercase ${
        sev.includes("HIGH") ? "text-accent-red" : sev.includes("MEDIUM") ? "text-accent-amber" : "text-text-muted"
      }`}>{sev}</td>
      <td className="pl-3 text-[11px] text-text-muted">{cond}</td>
    </tr>
  );
}

function QualityRow({ tier, color, cond, freq, rate }:
                     { tier: string; color: string; cond: string; freq: string; rate: string }) {
  return (
    <tr className="border-b border-bg-line/40">
      <td className={`py-1 font-bold ${color}`}>{tier}</td>
      <td className="text-[11px]">{cond}</td>
      <td className="text-center text-text-secondary">{freq}</td>
      <td className="text-center text-accent-amber tabular">{rate}</td>
    </tr>
  );
}
