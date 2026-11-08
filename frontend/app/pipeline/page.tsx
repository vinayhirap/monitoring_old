"use client";

import { useState } from "react";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt, signalColor, biasColor } from "@/lib/format";
import { ArrowDown, Sparkles, BarChart3, Target, FlaskConical, Gem } from "lucide-react";
import { FadeInCard, AnimatedNumber, PulseBadge, GlowCard } from "@/components/animated";
import clsx from "clsx";

export default function PipelinePage() {
  const [horizon, setHorizon] = useState("SWING");
  const [esotericMin, setEsotericMin] = useState(55);
  const [technicalMin, setTechnicalMin] = useState(55);
  const [maxFinalists, setMaxFinalists] = useState(15);
  const [attachAccuracy, setAttachAccuracy] = useState(true);
  const [requireAgreement, setRequireAgreement] = useState(true);
  const [consistencyMode, setConsistencyMode] = useState<"strict" | "warn" | "block">("strict");
  const [quick, setQuick] = useState(true);
  const [diamondOnly, setDiamondOnly] = useState(false);
  const [minHitRate, setMinHitRate] = useState(0);
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr(""); setData(null);
    try {
      const qs = new URLSearchParams({
        horizon, capital: "100000",
        esoteric_min: String(esotericMin),
        technical_min: String(technicalMin),
        require_agreement: String(requireAgreement),
        max_finalists: String(maxFinalists),
        attach_accuracy: String(attachAccuracy),
        consistency_mode: consistencyMode,
        quick: String(quick),
        diamond_only: String(diamondOnly),
        min_backtest_hit_rate: String(minHitRate),
      });
      const res = await fetcher<any>(`/api/pipeline/run?${qs.toString()}`);
      setData(res);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Gated Pipeline — Esoteric ▸ Technical ▸ Strategy ▸ Accuracy"
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setDiamondOnly(!diamondOnly)}
              className={clsx("px-2 py-1.5 rounded text-[11px] border flex items-center gap-1",
                diamondOnly
                  ? "border-accent-violet bg-accent-violet/15 text-accent-violet font-bold"
                  : "border-bg-line text-text-secondary"
              )}
              title="DIAMOND mode: only finalists with 6/6 confluence + lunar PROCEED + 0 HIGH conflicts + ≥70% historical hit-rate. Typically 0-3 picks per run."
            >
              <Gem className="w-3 h-3" /> {diamondOnly ? "DIAMOND ONLY" : "DIAMOND OFF"}
            </button>
            <input
              type="number"
              value={minHitRate}
              onChange={(e) => setMinHitRate(parseInt(e.target.value) || 0)}
              placeholder="min hit %"
              className="w-20 bg-bg-base border border-bg-line rounded px-2 py-1 text-[11px] tabular"
              title="Drop finalists below this historical hit-rate (0=off)"
            />
            <button
              onClick={() => setQuick(!quick)}
              className={`px-2 py-1.5 rounded text-[11px] border ${quick
                ? "border-accent-green text-accent-green" : "border-accent-amber text-accent-amber"}`}
              title="Quick = top-50 (~30s). Full = ~180 (~120s)."
            >
              {quick ? "QUICK (50)" : "FULL (~180)"}
            </button>
            <button onClick={run} disabled={busy}
              className="px-4 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold disabled:opacity-50">
              {busy ? "Running pipeline…" : "Run Pipeline"}
            </button>
          </div>
        }
      >
        <div className="grid grid-cols-2 md:grid-cols-7 gap-3 text-[11px]">
          <Field label="Horizon">
            <select value={horizon} onChange={(e) => setHorizon(e.target.value)}
              className="w-full bg-bg-base border border-bg-line rounded px-2 py-1 font-mono">
              <option>INTRADAY</option><option>SWING</option><option>POSITIONAL</option>
            </select>
          </Field>
          <Field label="Esoteric ≥">
            <input type="number" value={esotericMin} onChange={(e) => setEsotericMin(parseInt(e.target.value) || 50)}
              className="w-full bg-bg-base border border-bg-line rounded px-2 py-1 tabular" />
          </Field>
          <Field label="Technical ≥">
            <input type="number" value={technicalMin} onChange={(e) => setTechnicalMin(parseInt(e.target.value) || 50)}
              className="w-full bg-bg-base border border-bg-line rounded px-2 py-1 tabular" />
          </Field>
          <Field label="Max finalists">
            <input type="number" value={maxFinalists} onChange={(e) => setMaxFinalists(parseInt(e.target.value) || 5)}
              className="w-full bg-bg-base border border-bg-line rounded px-2 py-1 tabular" />
          </Field>
          <Field label="Require agreement">
            <button onClick={() => setRequireAgreement(!requireAgreement)}
              className={clsx("w-full px-2 py-1 rounded border",
                requireAgreement ? "border-accent-green text-accent-green" : "border-bg-line text-text-secondary")}>
              {requireAgreement ? "YES" : "NO"}
            </button>
          </Field>
          <Field label="Attach accuracy">
            <button onClick={() => setAttachAccuracy(!attachAccuracy)}
              className={clsx("w-full px-2 py-1 rounded border",
                attachAccuracy ? "border-accent-green text-accent-green" : "border-bg-line text-text-secondary")}>
              {attachAccuracy ? "YES" : "NO"}
            </button>
          </Field>
          <Field label="Consistency mode">
            <select value={consistencyMode} onChange={(e) => setConsistencyMode(e.target.value as any)}
              className="w-full bg-bg-base border border-bg-line rounded px-2 py-1 font-mono">
              <option value="strict">STRICT</option>
              <option value="warn">WARN</option>
              <option value="block">BLOCK</option>
            </select>
          </Field>
        </div>
        <div className="text-[10px] text-text-muted mt-3 space-y-1">
          <div>
            Sequential 4-stage filter across 180+ NSE F&O symbols. Stage 1 (cyclical pre-filter: Vedic timing,
            symbol-cycles, Gann, Fibonacci) acts as a gate; survivors proceed to Stage 2 (technical + SMC);
            finalists get strategy selection, consistency validation, and mini-backtest accuracy.
          </div>
          <div>
            <span className="text-accent-amber font-semibold">Consistency mode</span> controls direction-conflict policy:
            <span className="text-accent-red"> strict</span> downgrades to WAIT on HIGH conflict (default),
            <span className="text-accent-amber"> warn</span> annotates only,
            <span className="text-accent-red"> block</span> downgrades on any conflict. See{" "}
            <a href="/methodology" className="text-accent-amber underline">methodology</a>.
          </div>
        </div>
        {err && <div className="text-accent-red text-[11px] mt-2">{err}</div>}
      </Panel>

      {data && <FunnelStrip data={data} />}
      {data && <LunarStrip data={data} />}
      {data && <HoraStrip data={data} />}
      {data && <Finalists data={data} />}
      {data && <RejectedDetails data={data} />}

      <div className="text-[10px] text-text-muted text-center py-2">
        Educational use only. Cyclical timing layers are confluence enhancements, not standalone trade rationale.
        See <a href="/methodology" className="text-accent-amber underline">methodology</a> for the pipeline breakdown.
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-text-muted mb-1">{label}</div>
      {children}
    </div>
  );
}

function FunnelStrip({ data }: { data: any }) {
  const steps = [
    { icon: Sparkles, label: "Universe scanned",      value: data.universe_size,  color: "text-text-secondary" },
    { icon: Sparkles, label: "Stage 1 — Cyclical ✓",  value: data.stage1_passed,  color: "text-accent-violet" },
    { icon: BarChart3,label: "Stage 2 — Technical ✓", value: data.stage2_passed,  color: "text-accent-blue" },
    { icon: Target,   label: "Finalists",             value: data.finalists.length, color: "text-accent-amber" },
  ];
  return (
    <Panel title="Funnel">
      <div className="flex items-center justify-between gap-2">
        {steps.map((s, i) => (
          <div key={i} className="flex-1 flex items-center gap-2">
            <div className="flex-1 text-center border border-bg-line rounded p-3 bg-bg-panel">
              <s.icon className={clsx("w-4 h-4 mx-auto mb-1", s.color)} />
              <div className={clsx("text-2xl font-bold tabular", s.color)}>{s.value}</div>
              <div className="text-[10px] text-text-muted uppercase mt-1">{s.label}</div>
            </div>
            {i < steps.length - 1 && <ArrowDown className="w-4 h-4 text-text-muted rotate-[-90deg]" />}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Finalists({ data }: { data: any }) {
  if (!data.finalists?.length) {
    return (
      <Panel title="Finalists">
        <div className="text-text-muted text-xs">
          {data.params?.diamond_only
            ? "No DIAMOND-tier setups today. The universe simply doesn't have a 6/6 unanimous, lunar-PROCEED, ≥70%-hit-rate pick right now. This is normal — Diamond signals are rare. Try again later or disable DIAMOND mode."
            : "No symbols survived both gates. Lower thresholds or disable \"require agreement\" to widen the funnel."}
        </div>
      </Panel>
    );
  }
  const diamondCount = data.finalists.filter((f: any) => f.quality_grade === "DIAMOND").length;
  return (
    <Panel title={`${data.finalists.length} Finalist${data.finalists.length > 1 ? "s" : ""} · ${diamondCount} DIAMOND-tier — ranked by confluence`}>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {data.finalists.map((f: any, i: number) => (
          <FadeInCard key={f.symbol} delay={i * 0.05}>
            <FinalistCard f={f} />
          </FadeInCard>
        ))}
      </div>
    </Panel>
  );
}

function FinalistCard({ f }: { f: any }) {
  const eso = f.esoteric, tec = f.technical, strat = f.strategy, acc = f.accuracy;
  const validation = f.validation;
  const wasDowngraded = validation?.adjusted_strategy === "WAIT" && validation?.original_strategy !== "WAIT";
  const grade = f.quality_grade || "STANDARD";
  const isDiamond = grade === "DIAMOND";
  const isGold = grade === "GOLD";
  const cardBorder = isDiamond ? "border-accent-violet/60"
                     : isGold ? "border-accent-amber/50"
                     : wasDowngraded ? "border-accent-red/50"
                     : validation?.severity_counts?.MEDIUM > 0 ? "border-accent-amber/50"
                     : "border-bg-line";
  const cardInner = (
    <div className={`border ${cardBorder} rounded bg-panel-grad`}>
      <div className="px-3 py-2 border-b border-bg-line flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-text-primary font-semibold text-base">{f.symbol}</span>
          <span className="text-[9px] text-text-muted">{f.sector}</span>
          {isDiamond && (
            <PulseBadge color="violet" className="bg-accent-violet/25 text-accent-violet border border-accent-violet/60">
              ◆ DIAMOND
            </PulseBadge>
          )}
          {isGold && (
            <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-accent-amber/20 text-accent-amber border border-accent-amber/40 font-bold">
              ★ GOLD
            </span>
          )}
          {grade === "SILVER" && (
            <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-text-secondary/20 text-text-secondary border border-bg-line font-bold">
              SILVER
            </span>
          )}
          {wasDowngraded && (
            <PulseBadge color="red" className="bg-accent-red/20 text-accent-red border border-accent-red/40">
              Downgraded
            </PulseBadge>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-[10px] px-2 py-0.5 rounded border border-bg-line ${biasColor(eso.direction)}`}>
            {eso.direction}
          </span>
          <span className={`font-bold text-sm tracking-wider ${signalColor(f.final_signal)} flex items-center gap-1`}>
            {f.final_signal}
            <AnimatedNumber value={f.final_confidence} decimals={1} className="tabular" />
          </span>
        </div>
      </div>

      {/* Stage scores */}
      <div className="px-3 py-2 grid grid-cols-3 gap-2 text-[11px] border-b border-bg-line">
        <div>
          <div className="text-[9px] uppercase text-text-muted">Stage 1 — Esoteric</div>
          <div className="text-accent-violet tabular font-semibold">{fmt.num(eso.score, 1)}</div>
          <div className="text-[9px] text-text-muted">
            {eso.components.astrology.nakshatra} • {eso.components.gann.bias}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-text-muted">Stage 2 — Technical</div>
          <div className="text-accent-blue tabular font-semibold">{fmt.num(tec.score, 1)}</div>
          <div className="text-[9px] text-text-muted">{tec.smc_structure}</div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-text-muted">Stage 4 — Accuracy</div>
          <div className="text-accent-amber tabular font-semibold">
            {acc.hit_rate !== undefined ? `${fmt.num(acc.hit_rate, 1)}%` : "—"}
          </div>
          <div className="text-[9px] text-text-muted">
            {acc.trades ? `${acc.trades} trades · PF ${fmt.num(acc.profit_factor, 2)}` : "no backtest"}
            {acc.sample_size_warning && <span className="text-accent-red"> · small sample</span>}
          </div>
        </div>
      </div>

      {/* Strategy block */}
      <div className="px-3 py-2 border-b border-bg-line">
        <div className="flex items-center justify-between">
          <span className="text-accent-amber font-semibold text-[12px]">{strat.strategy}</span>
          <span className="text-[10px] text-text-muted">{strat.horizon}</span>
        </div>
        <div className="text-[10px] text-text-secondary mt-1">{strat.rationale}</div>
        <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] tabular">
          <div><div className="text-text-muted uppercase text-[9px]">Entry</div><div>{fmt.inr(strat.entry)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">SL</div><div className="text-accent-red">{fmt.inr(strat.stoploss)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">T1</div><div className="text-accent-green">{fmt.inr(strat.targets?.[0])}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">RR</div><div>{fmt.num(strat.risk_reward, 2)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Qty</div><div>{strat.suggested_qty}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Capital %</div><div>{fmt.num(strat.capital_allocation_pct, 2)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Max profit</div><div className="text-accent-green">{fmt.inr(strat.expected_max_profit_inr)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Max loss</div><div className="text-accent-red">{fmt.inr(strat.expected_max_loss_inr)}</div></div>
        </div>
        {strat.instrument_legs?.length > 0 && (
          <div className="mt-2 text-[10px] text-text-secondary">
            <span className="text-text-muted">Legs:</span>{" "}
            {strat.instrument_legs.map((l: any, i: number) =>
              <span key={i} className={l.action === "BUY" ? "text-accent-green" : "text-accent-red"}>
                {l.action} {l.type}@{l.strike}{i < strat.instrument_legs.length - 1 ? ", " : ""}
              </span>)}
          </div>
        )}
      </div>

      {/* Consistency check */}
      {validation && (
        <div className={clsx(
          "px-3 py-2 border-b border-bg-line",
          wasDowngraded ? "bg-accent-red/5"
          : validation.severity_counts.MEDIUM > 0 ? "bg-accent-amber/5"
          : "bg-accent-green/5"
        )}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase text-text-muted tracking-wider">
              Consistency check (astro + hora vs {validation.original_strategy})
            </span>
            <span className={clsx("text-[10px] uppercase font-bold",
              validation.final_action === "PROCEED" ? "text-accent-green"
              : validation.final_action === "WARN" ? "text-accent-amber"
              : "text-accent-red")}>
              {validation.final_action.replace(/_/g, " ")}
            </span>
          </div>
          <div className="text-[10px] text-text-secondary">{validation.summary}</div>

          {validation.conflicts?.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {validation.conflicts.map((c: any, i: number) => (
                <li key={i} className="text-[10px] flex items-start gap-1">
                  <span className={clsx("uppercase font-bold shrink-0 w-12",
                    c.severity === "HIGH" ? "text-accent-red"
                    : c.severity === "MEDIUM" ? "text-accent-amber"
                    : "text-text-muted")}>
                    [{c.severity[0]}]
                  </span>
                  <span className="text-text-muted shrink-0 w-16">{c.component}:</span>
                  <span className="text-text-secondary">{c.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Confluence + Holding plan */}
      {(f.confluence || f.holding_plan) && (
        <div className="px-3 py-2 border-b border-bg-line grid grid-cols-2 gap-3 text-[10px]">
          {f.confluence && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] uppercase text-text-muted tracking-wider">Confluence</span>
                <span className={clsx(
                  "text-[9px] uppercase font-bold px-1.5 py-0.5 rounded",
                  f.confluence.grade === "UNANIMOUS" ? "bg-accent-green/20 text-accent-green"
                  : f.confluence.grade === "VERY_STRONG" ? "bg-accent-green/15 text-accent-green"
                  : f.confluence.grade === "STRONG" ? "bg-accent-blue/15 text-accent-blue"
                  : f.confluence.grade === "MODERATE" ? "bg-accent-amber/15 text-accent-amber"
                  : "bg-accent-red/15 text-accent-red"
                )}>
                  {f.confluence.grade.replace("_", " ")}
                </span>
              </div>
              <div className="text-text-primary tabular text-sm font-semibold">
                {f.confluence.aligned_count}/{f.confluence.total_count}
                <span className="text-text-muted text-[10px] ml-1">aligned</span>
                <span className="text-accent-amber ml-2">{f.confluence.boost > 0 ? "+" : ""}{f.confluence.boost.toFixed(1)} boost</span>
              </div>
              <div className="text-text-secondary text-[10px] mt-1">
                <span className="text-accent-green">{f.confluence.aligned_engines.join(", ") || "—"}</span>
                {f.confluence.contrarian_engines.length > 0 && (
                  <> · <span className="text-accent-red">contra: {f.confluence.contrarian_engines.join(", ")}</span></>
                )}
              </div>
            </div>
          )}
          {f.holding_plan && (
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider mb-1">Holding Plan</div>
              <div className="text-text-primary text-[11px]">
                <span className="text-accent-amber">{f.holding_plan.optimal_entry_window.when.replace(/_/g, " ")}</span>
                {f.holding_plan.optimal_entry_window.wait_minutes > 0 && (
                  <span className="text-text-muted ml-1">
                    ({f.holding_plan.optimal_entry_window.wait_minutes}m)
                  </span>
                )}
              </div>
              <div className="text-text-secondary text-[10px] tabular">
                T1 in <span className="text-accent-green">{f.holding_plan.estimated_days_to_t1}d</span> ·
                T{f.holding_plan.partial_book_schedule?.length || 1} in <span className="text-accent-green">{f.holding_plan.estimated_days_to_t_final}d</span>
              </div>
              <div className="text-text-muted text-[10px]">
                Exit by <span className="text-accent-red">{f.holding_plan.exit_by_date}</span>
              </div>
              <div className="mt-1 text-[9px] text-text-muted">
                {f.holding_plan.partial_book_schedule?.map((s: any, i: number) => (
                  <span key={i}>
                    {i > 0 && " · "}
                    <span className="text-accent-amber">{s.book_pct}%</span> @ {s.at_target} ({s.est_date})
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {f.holding_plan?.notes?.length > 0 && (
        <div className="px-3 py-1.5 border-b border-bg-line text-[10px] text-accent-amber">
          {f.holding_plan.notes.map((n: string, i: number) => <div key={i}>⚠ {n}</div>)}
        </div>
      )}

      {/* Reasoning */}
      <div className="px-3 py-2 text-[10px] text-text-secondary space-y-0.5">
        <div><span className="text-text-muted uppercase">Esoteric:</span> {f.composite_reasons.esoteric}</div>
        <div><span className="text-text-muted uppercase">Technical:</span> {f.composite_reasons.technical}</div>
        <div className="text-accent-amber"><span className="text-text-muted uppercase">Accuracy:</span> {f.composite_reasons.accuracy}</div>
        {f.confluence?.summary && (
          <div className="text-text-secondary"><span className="text-text-muted uppercase">Confluence:</span> {f.confluence.summary}</div>
        )}
        {f.composite_reasons.consistency && (
          <div className="text-text-secondary"><span className="text-text-muted uppercase">Consistency:</span> {f.composite_reasons.consistency}</div>
        )}
      </div>
    </div>
  );

  // DIAMOND finalists get a halo pulse; GOLD gets a subtle amber glow.
  if (isDiamond) return <GlowCard intensity="high" color="violet">{cardInner}</GlowCard>;
  if (isGold)    return <GlowCard intensity="medium" color="amber">{cardInner}</GlowCard>;
  return cardInner;
}

function LunarStrip({ data }: { data: any }) {
  const lunar = data.params?.lunar;
  if (!lunar) return null;
  const gateColor =
    lunar.gate === "AVOID"   ? "bg-accent-red/15 border-accent-red text-accent-red"
    : lunar.gate === "WAIT"  ? "bg-accent-red/10 border-accent-red/50 text-accent-red"
    : lunar.gate === "CAUTION" ? "bg-accent-amber/10 border-accent-amber/50 text-accent-amber"
    : "bg-accent-green/10 border-accent-green/50 text-accent-green";
  return (
    <div className={clsx("border rounded px-3 py-2", gateColor)}>
      <div className="flex items-center gap-4 flex-wrap">
        <span className="font-bold uppercase tracking-wider">
          Lunar Gate: {lunar.gate}
        </span>
        <span className="text-[11px]">
          {lunar.phase_name} · {lunar.paksha} paksha · tithi {((lunar.tithi_num - 1) % 15) + 1} ({lunar.tithi_name})
        </span>
        <span className="text-[11px]">
          Moon in <span className="font-semibold">{lunar.moon_nakshatra}</span> ({lunar.moon_sign})
        </span>
        {lunar.is_full_moon && <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-accent-red/30">FULL MOON ZONE</span>}
        {lunar.is_new_moon && <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-accent-red/30">NEW MOON ZONE</span>}
        {lunar.is_void_of_course && <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-accent-red/40">VOID-OF-COURSE</span>}
        {lunar.eclipse_zone && <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-accent-red/40">ECLIPSE WINDOW</span>}
        <span className="ml-auto text-[11px] tabular">strength {lunar.strength_score}/100</span>
      </div>
      {lunar.rules_triggered?.length > 0 && (
        <ul className="mt-2 text-[10px] space-y-0.5">
          {lunar.rules_triggered.slice(0, 5).map((r: any, i: number) => (
            <li key={i} className="flex items-start gap-2">
              <span className={clsx("uppercase font-bold shrink-0 w-12",
                r.severity === "HIGH" ? "text-accent-red"
                : r.severity === "MEDIUM" ? "text-accent-amber"
                : "text-text-muted")}>
                [{r.severity[0]}]
              </span>
              <span className="text-text-muted shrink-0 w-32">{r.rule}</span>
              <span className="text-text-secondary">{r.note}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function HoraStrip({ data }: { data: any }) {
  const h = data.params?.hora;
  const mkt = data.params?.astro_market_bias;
  const mode = data.params?.consistency_mode;
  if (!h) return null;
  const horaColor = h.bias === "bullish" ? "text-accent-green"
                    : h.bias === "bearish" ? "text-accent-red"
                    : "text-text-secondary";
  return (
    <div className="border border-bg-line rounded bg-bg-panel px-3 py-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px]">
      <div>
        <span className="text-text-muted uppercase">Current Hora:</span>{" "}
        <span className={clsx("font-semibold", horaColor)}>{h.ruler}</span>{" "}
        <span className={clsx("text-[10px] uppercase",
          h.bias === "bullish" ? "text-accent-green"
          : h.bias === "bearish" ? "text-accent-red"
          : "text-text-secondary")}>
          ({h.bias})
        </span>
      </div>
      <div className="text-text-secondary">
        <span className="text-text-muted">Next:</span> {h.next_ruler} in {h.next_change_in_minutes}m
      </div>
      <div className="text-text-secondary">
        <span className="text-text-muted">Market astro:</span>{" "}
        <span className={biasColor(mkt)}>{mkt}</span>
      </div>
      <div className="text-text-secondary ml-auto">
        <span className="text-text-muted">Consistency mode:</span>{" "}
        <span className="text-accent-amber font-semibold uppercase">{mode}</span>
      </div>
      <div className="basis-full text-[10px] text-text-muted italic">{h.notes}</div>
    </div>
  );
}

function RejectedDetails({ data }: { data: any }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <Panel title={`Rejected at Stage 1 (sample, ${data.rejected_stage1?.length || 0} shown)`}>
        <table className="w-full text-[10px] tabular">
          <thead className="text-text-muted text-[9px] uppercase">
            <tr><th className="text-left">Sym</th><th className="text-right">Score</th><th className="text-center">Lean</th></tr>
          </thead>
          <tbody>
            {(data.rejected_stage1 || []).map((r: any) => (
              <tr key={r.symbol} className="border-b border-bg-line/30">
                <td className="text-text-secondary">{r.symbol}</td>
                <td className="text-right">{r.esoteric_score}</td>
                <td className={`text-center ${biasColor(r.direction)}`}>{r.direction}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title={`Rejected at Stage 2 (sample, ${data.rejected_stage2?.length || 0} shown)`}>
        <table className="w-full text-[10px] tabular">
          <thead className="text-text-muted text-[9px] uppercase">
            <tr>
              <th className="text-left">Sym</th>
              <th className="text-center">Eso dir / score</th>
              <th className="text-center">Tech dir / score</th>
              <th className="text-center">Agree?</th>
            </tr>
          </thead>
          <tbody>
            {(data.rejected_stage2 || []).map((r: any) => (
              <tr key={r.symbol} className="border-b border-bg-line/30">
                <td className="text-text-secondary">{r.symbol}</td>
                <td className={`text-center ${biasColor(r.esoteric_dir)}`}>{r.esoteric_dir} / {r.esoteric_score}</td>
                <td className={`text-center ${biasColor(r.technical_dir)}`}>{r.technical_dir} / {r.technical_score}</td>
                <td className={`text-center ${r.agreement ? "text-accent-green" : "text-accent-red"}`}>
                  {r.agreement ? "YES" : "NO"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
