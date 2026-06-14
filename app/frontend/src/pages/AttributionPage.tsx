/**
 * Portfolio Attribution Page — Brinson model decomposition.
 *
 * Shows allocation vs selection contribution per ticker in a waterfall-style table.
 * Uses POST /api/portfolio/attribution.
 */
import React, { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  type AttributionResponse,
  type AttributionRequest,
  fetchAttribution,
} from "../services/attribution-api";

/* ─── helpers ─────────────────────────────────────────────── */

function fmtPct(v: number): string {
  return `${(v >= 0 ? "+" : "")}${(v * 100).toFixed(2)}%`;
}

function fmtW(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function contributionColor(v: number): string {
  if (v > 0.001) return "text-green-500";
  if (v < -0.001) return "text-red-500";
  return "text-muted-foreground";
}

function barWidth(v: number, maxAbs: number): string {
  if (maxAbs === 0) return "0%";
  return `${Math.min(Math.abs(v) / maxAbs, 1) * 100}%`;
}

/* ─── component ──────────────────────────────────────────── */

const AttributionPage: React.FC = () => {
  const [result, setResult] = useState<AttributionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  /* Sample data for demo / testing */
  const runDemo = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload: AttributionRequest = {
        start_date: "2026-01-01",
        end_date: "2026-06-01",
        ticker_returns: {
          "000001": 0.12,
          "300750": -0.05,
          "600519": 0.22,
          "002475": 0.08,
          "601318": 0.15,
        },
        ticker_market_values: {
          "000001": 150_000,
          "300750": 80_000,
          "600519": 200_000,
          "002475": 60_000,
          "601318": 110_000,
        },
        total_portfolio_value: 600_000,
        benchmark_weights: {
          "000001": 0.25,
          "300750": 0.15,
          "600519": 0.30,
          "002475": 0.10,
          "601318": 0.20,
        },
        benchmark_returns: {
          "000001": 0.08,
          "300750": 0.02,
          "600519": 0.18,
          "002475": 0.10,
          "601318": 0.10,
        },
      };
      const data = await fetchAttribution(payload);
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to fetch attribution");
    } finally {
      setLoading(false);
    }
  }, []);

  /* Summary cards */
  const SummaryCards = ({ data }: { data: AttributionResponse }) => {
    const cards = [
      {
        label: "Portfolio Return",
        value: data.total_portfolio_return,
        fmt: fmtPct,
        color:
          data.total_portfolio_return >= 0 ? "bg-green-900/40" : "bg-red-900/40",
      },
      {
        label: "Benchmark Return",
        value: data.total_benchmark_return,
        fmt: fmtPct,
        color: "bg-blue-900/40",
      },
      {
        label: "Allocation Δ",
        value: data.total_allocation_contribution,
        fmt: fmtPct,
        color:
          data.total_allocation_contribution >= 0
            ? "bg-green-900/40"
            : "bg-red-900/40",
      },
      {
        label: "Selection Δ",
        value: data.total_selection_contribution,
        fmt: fmtPct,
        color:
          data.total_selection_contribution >= 0
            ? "bg-green-900/40"
            : "bg-red-900/40",
      },
    ];

    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {cards.map((c) => (
          <div key={c.label} className={`rounded-lg p-4 ${c.color}`}>
            <div className="text-xs text-muted-foreground mb-1">{c.label}</div>
            <div className="text-xl font-mono font-bold">{c.fmt(c.value)}</div>
          </div>
        ))}
      </div>
    );
  };

  /* Ticker table with contribution bars */
  const AttributionTable = ({
    data,
  }: {
    data: AttributionResponse;
  }) => {
    if (!data.tickers.length) {
      return <p className="text-muted-foreground text-sm">No ticker data.</p>;
    }

    const maxAbs = Math.max(
      ...data.tickers.map((t) => Math.abs(t.total_contribution)),
      0.01,
    );

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 px-2">Ticker</th>
              <th className="py-2 px-2 text-right">Weight</th>
              <th className="py-2 px-2 text-right">Return</th>
              <th className="py-2 px-2 text-right">Bench Wt</th>
              <th className="py-2 px-2 text-right">Bench Ret</th>
              <th className="py-2 px-2 text-right">Alloc Δ</th>
              <th className="py-2 px-2 text-right">Select Δ</th>
              <th className="py-2 px-2 text-right">Total Δ</th>
              <th className="py-2 px-2 w-32">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {data.tickers.map((t) => (
              <tr
                key={t.ticker}
                className="border-b border-border hover:bg-muted/50"
              >
                <td className="py-2 px-2 font-mono">{t.ticker}</td>
                <td className="py-2 px-2 text-right font-mono">
                  {fmtW(t.portfolio_weight)}
                </td>
                <td
                  className={`py-2 px-2 text-right font-mono ${contributionColor(
                    t.portfolio_return,
                  )}`}
                >
                  {fmtPct(t.portfolio_return)}
                </td>
                <td className="py-2 px-2 text-right font-mono text-muted-foreground">
                  {fmtW(t.benchmark_weight)}
                </td>
                <td className="py-2 px-2 text-right font-mono text-muted-foreground">
                  {fmtPct(t.benchmark_return)}
                </td>
                <td
                  className={`py-2 px-2 text-right font-mono ${contributionColor(
                    t.allocation_contribution,
                  )}`}
                >
                  {fmtPct(t.allocation_contribution)}
                </td>
                <td
                  className={`py-2 px-2 text-right font-mono ${contributionColor(
                    t.selection_contribution,
                  )}`}
                >
                  {fmtPct(t.selection_contribution)}
                </td>
                <td
                  className={`py-2 px-2 text-right font-mono font-bold ${contributionColor(
                    t.total_contribution,
                  )}`}
                >
                  {fmtPct(t.total_contribution)}
                </td>
                <td className="py-2 px-2">
                  <div className="flex items-center gap-1">
                    <div className="flex-1 bg-muted rounded h-3 relative overflow-hidden">
                      <div
                        className={`h-full rounded ${
                          t.total_contribution >= 0
                            ? "bg-green-500"
                            : "bg-red-500"
                        }`}
                        style={{
                          width: barWidth(t.total_contribution, maxAbs),
                        }}
                      />
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Portfolio Attribution</h1>
      <p className="text-muted-foreground text-sm mb-6">
        Brinson model: decompose returns into allocation &amp; selection
        contributions
      </p>

      <Button
        onClick={runDemo}
        disabled={loading}
        className="mb-6"
      >
        {loading ? "Computing…" : "Run Demo Attribution"}
      </Button>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded p-3 text-sm text-red-300 mb-4">
          {error}
        </div>
      )}

      {result && (
        <>
          <SummaryCards data={result} />
          <div className="bg-card rounded-lg p-4">
            <h2 className="text-lg font-semibold mb-3">
              Per-Ticker Breakdown
            </h2>
            <AttributionTable data={result} />
          </div>

          <div className="mt-4 text-xs text-muted-foreground">
            Period: {result.start_date} → {result.end_date} | Residual:{" "}
            {fmtPct(result.total_residual)}
          </div>
        </>
      )}
    </div>
  );
};

export default AttributionPage;
