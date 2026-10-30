import React, { useState } from 'react';
import { CheckCircle2, Download, FileText, FolderOpen, Printer, RotateCcw, ShieldCheck, Trash2, XCircle } from 'lucide-react';
import { useControllerActions, useDiskReports } from '../hooks/useFairFlowData';
import { DiskReportEntry } from '../api/types';

function MarkdownReportRenderer({ report }: { report: DiskReportEntry }) {
  const lines = report.report_markdown.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) {
      i++;
      continue;
    }

    if (line.startsWith('# ')) {
      elements.push(
        <h2 key={i} className="text-xl sm:text-2xl font-semibold text-white mt-4 mb-3">
          {line.replace('# ', '')}
        </h2>
      );
      i++;
      continue;
    }

    if (line.startsWith('## ')) {
      elements.push(
        <h3
          key={i}
          className="text-base sm:text-lg font-medium text-[#b79bff] mt-6 mb-3 border-b border-[var(--line)] pb-1.5"
        >
          {line.replace('## ', '')}
        </h3>
      );
      i++;
      continue;
    }

    if (line.startsWith('- ')) {
      const listItems: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('- ')) {
        listItems.push(lines[i].trim().slice(2));
        i++;
      }
      elements.push(
        <ul key={`list-${i}`} className="grid grid-cols-1 sm:grid-cols-2 gap-2 my-3 font-mono text-xs">
          {listItems.map((item, idx) => (
            <li
              key={idx}
              className="rounded-xl border border-[var(--line)] bg-white/[0.02] px-3.5 py-2 text-[var(--text)]"
            >
              {item.replace(/\*\*/g, '').replace(/`/g, '')}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    if (line.startsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const headers = tableLines[0]
          .split('|')
          .map((s) => s.trim())
          .filter(Boolean);
        const rows = tableLines.slice(2).map((rLine) =>
          rLine
            .split('|')
            .map((s) => s.trim())
            .filter(Boolean)
        );
        elements.push(
          <div key={`tbl-${i}`} className="overflow-x-auto my-4 rounded-2xl border border-[var(--line)]">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-[var(--line)] bg-white/[0.04] text-[var(--mute)]">
                  {headers.map((h, hIdx) => (
                    <th key={hIdx} className="py-3 px-3.5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {rows.map((r, rIdx) => (
                  <tr key={rIdx} className="hover:bg-white/[0.02]">
                    {r.map((cell, cIdx) => {
                      const clean = cell.replace(/\*\*/g, '').replace(/`/g, '');
                      const isPass = clean === 'COMPLIANT' || clean.startsWith('PASS');
                      const isFail = clean === 'NON-COMPLIANT' || clean.startsWith('FAIL');
                      return (
                        <td
                          key={cIdx}
                          className={`py-2.5 px-3.5 ${
                            isPass
                              ? 'text-emerald-300 font-semibold'
                              : isFail
                              ? 'text-rose-400 font-semibold'
                              : 'text-[var(--text)]'
                          }`}
                        >
                          {clean}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    elements.push(
      <p key={i} className="text-sm text-[var(--mute)] my-2">
        {line}
      </p>
    );
    i++;
  }

  return <div>{elements}</div>;
}

export const ReportPage: React.FC = () => {
  const { data: reportsData, isLoading } = useDiskReports();
  const { resetSystem } = useControllerActions();
  const reports = reportsData?.reports || [];
  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  const activeReport =
    reports.find((r) => r.run_id === selectedRunId) ||
    reports.find((r) => r.scenario_id === 'policy_evaluation') ||
    reports.find((r) => r.run_id.startsWith('smoke_')) ||
    reports[0] ||
    null;

  const handleExportPdf = () => {
    window.print();
  };

  const handleDownloadMarkdown = () => {
    if (!activeReport) return;
    const blob = new Blob([activeReport.report_markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${activeReport.run_id}_report.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleResetAllReports = async () => {
    try {
      const res = await resetSystem.mutateAsync();
      setSelectedRunId('');
      setResetMessage(res.message || 'Cleared generated policy reports and reset controller state.');
    } catch (err) {
      setResetMessage(err instanceof Error ? err.message : 'Failed to reset system data.');
    }
  };

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 no-print">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[#7c5cff]/50 bg-[#7c5cff]/10 px-3.5 py-1 font-mono text-xs text-[#b79bff] mb-3">
            <FileText className="h-3.5 w-3.5" />
            <span>GENERATED BY src/fairflow/report.py • SHA-256 VERIFIED</span>
          </div>
          <h1 className="text-2xl sm:text-4xl font-light text-white">
            <strong className="font-semibold">FairFlow</strong> evaluation reports
          </h1>
          <p className="mt-1 text-sm text-[var(--mute)]">
            Renders policy completion/rejection reports (with explicit reasons) and scenario harness <code className="font-mono text-xs">report.md</code> artifacts.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={resetSystem.isPending}
            onClick={handleResetAllReports}
            className="rounded-full border border-rose-500/40 bg-rose-500/10 hover:bg-rose-500/20 px-4 py-2 font-mono text-xs text-rose-200 flex items-center gap-2 transition-colors"
          >
            <Trash2 className="h-4 w-4 text-rose-400" />
            <span>{resetSystem.isPending ? 'Resetting...' : 'Reset & clear data'}</span>
          </button>
          <button type="button" onClick={handleDownloadMarkdown} className="btn-secondary !py-2 !px-4 !text-xs">
            <Download className="h-4 w-4" />
            Download report.md
          </button>
          <button type="button" onClick={handleExportPdf} className="btn-primary !py-2 !px-5 !text-xs">
            <Printer className="h-4 w-4" />
            Export to PDF
          </button>
        </div>
      </div>

      {resetMessage && (
        <div
          role="status"
          className="rounded-2xl border border-emerald-500/50 bg-emerald-950/40 p-4 font-mono text-xs text-emerald-200 flex items-center justify-between no-print"
        >
          <span>{resetMessage}</span>
          <button type="button" onClick={() => setResetMessage(null)} className="underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Run Selector Strip */}
      <div className="flex flex-wrap items-center gap-2.5 no-print">
        {reports.map((rep) => {
          const isSelected = activeReport?.run_id === rep.run_id;
          const isPolicyEval = rep.scenario_id === 'policy_evaluation';
          const verdict = String(rep.metrics_summary?.verdict || '');
          return (
            <button
              key={rep.run_id}
              type="button"
              onClick={() => setSelectedRunId(rep.run_id)}
              className={`rounded-full px-4 py-2 font-mono text-xs border transition-all flex items-center gap-2 ${
                isSelected
                  ? isPolicyEval && verdict === 'REJECTED'
                    ? 'border-rose-500 bg-rose-500/25 text-white'
                    : isPolicyEval && verdict === 'ROLLED_BACK'
                    ? 'border-[#f26a1b] bg-[#f26a1b]/25 text-white shadow-orange-glow'
                    : 'border-[#7c5cff] bg-[#7c5cff]/25 text-white shadow-purple-glow'
                  : 'border-[var(--line)] bg-white/[0.03] text-[var(--mute)] hover:text-white'
              }`}
            >
              {isPolicyEval && verdict === 'REJECTED' ? (
                <XCircle className="h-3.5 w-3.5 text-rose-400" />
              ) : isPolicyEval && verdict === 'ROLLED_BACK' ? (
                <RotateCcw className="h-3.5 w-3.5 text-[#f26a1b]" />
              ) : isPolicyEval && verdict === 'ACCEPTED' ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <FolderOpen className="h-3.5 w-3.5 text-[#b79bff]" />
              )}
              <span>{rep.title}</span>
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="glass-card p-12 text-center font-mono text-sm text-[var(--mute)]">
          Loading backend report artifacts...
        </div>
      ) : !activeReport ? (
        <div className="glass-card p-12 text-center font-mono text-sm text-[var(--mute)]">
          No report artifacts found in results/. Run a scenario in the Lab first.
        </div>
      ) : (
        <div className="space-y-8">
          {/* Rendered Markdown Report Card */}
          <section aria-label="Rendered markdown evaluation report" className="glass-card p-6 sm:p-10">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--line)] pb-4 mb-4">
              <div className="font-mono text-xs text-[#b79bff]">
                ARTIFACT PATH: <span className="text-white">{activeReport.artifacts_dir}/report.md</span>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-3 py-0.5 font-mono text-xs text-emerald-300">
                <ShieldCheck className="h-3.5 w-3.5" /> Raw Log Verified
              </span>
            </div>

            <MarkdownReportRenderer report={activeReport} />
          </section>

          {/* Raw Trial Metrics CSV Table if available */}
          {activeReport.trial_metrics && activeReport.trial_metrics.length > 0 && (
            <section aria-label="Per-trial raw metrics table" className="glass-card p-6 sm:p-8 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-medium text-white">
                    Per-trial metrics (<code className="font-mono text-sm text-[#b79bff]">trial_metrics.csv</code>)
                  </h2>
                  <p className="text-xs text-[var(--mute)]">
                    Individual block-randomized trials sliced by observed monotonic clock timestamps.
                  </p>
                </div>
                <span className="font-mono text-xs text-[var(--mute)]">
                  {activeReport.trial_metrics.length} trials
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse font-mono text-xs">
                  <thead>
                    <tr className="border-b border-[var(--line)] text-[var(--mute)] uppercase">
                      <th className="py-3 px-3">Arm</th>
                      <th className="py-3 px-3">Trial</th>
                      <th className="py-3 px-3">Valid</th>
                      <th className="py-3 px-3">Added Delay p99</th>
                      <th className="py-3 px-3">Added Delay p95</th>
                      <th className="py-3 px-3">Congested Jitter</th>
                      <th className="py-3 px-3">Bulk Goodput</th>
                      <th className="py-3 px-3">Target Met</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--line)]">
                    {activeReport.trial_metrics.map((row, idx) => {
                      const isValid = row.valid === 'True';
                      const targetMet = isValid && row.interactive_target_met === 'True';
                      return (
                        <tr key={idx} className="hover:bg-white/[0.02]">
                          <td className="py-2.5 px-3 font-semibold text-white">{row.arm}</td>
                          <td className="py-2.5 px-3">#{row.trial}</td>
                          <td className={`py-2.5 px-3 ${isValid ? 'text-emerald-300' : 'text-amber-400'}`}>{row.valid}</td>
                          <td className={`py-2.5 px-3 font-semibold ${!isValid ? 'text-amber-400' : targetMet ? 'text-emerald-300' : 'text-rose-400'}`}>
                            {row.congested_added_delay_p99_ms} ms
                          </td>
                          <td className="py-2.5 px-3">{row.added_delay_p95_ms} ms</td>
                          <td className="py-2.5 px-3">{row.congested_jitter_ms} ms</td>
                          <td className="py-2.5 px-3 text-[#b79bff]">{row.bulk_goodput_mbps} Mbps</td>
                          <td className="py-2.5 px-3">
                            {!isValid ? (
                              <span className="inline-flex items-center gap-1 text-amber-400">
                                INVALID (RERUN)
                              </span>
                            ) : targetMet ? (
                              <span className="inline-flex items-center gap-1 text-emerald-300">
                                <CheckCircle2 className="h-3.5 w-3.5" /> PASS
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-rose-400">
                                <XCircle className="h-3.5 w-3.5" /> FAIL
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </main>
  );
};

export default ReportPage;
