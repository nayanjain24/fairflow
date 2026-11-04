import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Activity, FlaskConical, FileText, Menu, ShieldCheck, X } from 'lucide-react';
import { isUsingMock, setRuntimeMockMode } from '../api/client';

export const Navbar: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mockMode, setMockMode] = useState<boolean>(isUsingMock());

  const handleAnchor = (hash: string) => {
    setMobileOpen(false);
    if (location.pathname !== '/') {
      navigate(`/${hash}`);
      return;
    }
    const el = document.querySelector(hash);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const toggleMock = () => {
    const next = !mockMode;
    setRuntimeMockMode(next);
    setMockMode(next);
  };

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--line)] bg-[#06051a]/80 backdrop-blur-xl no-print">
      <nav
        aria-label="Primary navigation"
        className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6 lg:px-8"
      >
        {/* Logo Wordmark */}
        <Link
          to="/"
          className="flex items-center gap-2.5 text-lg font-semibold tracking-wider text-[var(--text)] focus:outline-none"
        >
          <span className="inline-flex items-center justify-center rounded-lg border border-[#7c5cff]/50 bg-[#7c5cff]/15 px-2 py-0.5 font-mono text-sm font-semibold text-[#b79bff] shadow-purple-glow">
            {'{ }'}
          </span>
          <span className="font-sans tracking-[0.16em] text-sm sm:text-base font-semibold">FAIRFLOW</span>
        </Link>

        {/* Desktop Nav Links */}
        <div className="hidden md:flex items-center gap-6 text-sm text-[var(--mute)]">
          <button
            type="button"
            onClick={() => handleAnchor('#overview')}
            className="hover:text-[var(--text)] transition-colors"
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => handleAnchor('#how-it-works')}
            className="hover:text-[var(--text)] transition-colors"
          >
            How it works
          </button>
          <button
            type="button"
            onClick={() => handleAnchor('#safety-contract')}
            className="hover:text-[#f26a1b] transition-colors flex items-center gap-1"
          >
            <ShieldCheck className="w-3.5 h-3.5 text-[#f26a1b]" />
            Safety contract
          </button>
          <Link
            to="/dashboard"
            className={`hover:text-[var(--text)] transition-colors flex items-center gap-1.5 ${
              location.pathname === '/dashboard' ? 'text-[#b79bff] font-medium' : ''
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            Live demo
          </Link>
          <button
            type="button"
            onClick={() => handleAnchor('#validation')}
            className="hover:text-[var(--text)] transition-colors"
          >
            Validation
          </button>
          <Link
            to="/lab"
            className={`hover:text-[var(--text)] transition-colors flex items-center gap-1.5 ${
              location.pathname === '/lab' ? 'text-[#b79bff] font-medium' : ''
            }`}
          >
            <FlaskConical className="w-3.5 h-3.5" />
            Scenario lab
          </Link>
          <Link
            to="/report"
            className={`hover:text-[var(--text)] transition-colors flex items-center gap-1.5 ${
              location.pathname === '/report' ? 'text-[#b79bff] font-medium' : ''
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            Report
          </Link>
        </div>

        {/* Right Actions */}
        <div className="hidden md:flex items-center gap-3">
          <button
            type="button"
            onClick={toggleMock}
            title="Switch between live FastAPI backend and deterministic interactive engine"
            className={`rounded-full px-3 py-1 text-xs font-mono border transition-colors ${
              mockMode
                ? 'border-[#7c5cff]/50 bg-[#7c5cff]/15 text-[#b79bff]'
                : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
            }`}
          >
            {mockMode ? 'MODE: CLOUD ENGINE' : 'MODE: LIVE API'}
          </button>
          <Link to="/dashboard" className="btn-primary !py-2 !px-4 !text-xs sm:!text-sm">
            Open dashboard
          </Link>
        </div>

        {/* Mobile menu button */}
        <button
          type="button"
          aria-label={mobileOpen ? 'Close navigation menu' : 'Open navigation menu'}
          onClick={() => setMobileOpen(!mobileOpen)}
          className="md:hidden rounded-lg border border-[var(--line)] p-2 text-[var(--text)]"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="md:hidden border-t border-[var(--line)] bg-[#06051a]/95 px-4 pt-3 pb-6 space-y-3">
          <div className="flex flex-col space-y-2 text-sm">
            <button
              type="button"
              onClick={() => handleAnchor('#overview')}
              className="text-left py-1.5 text-[var(--mute)] hover:text-white"
            >
              Overview
            </button>
            <button
              type="button"
              onClick={() => handleAnchor('#how-it-works')}
              className="text-left py-1.5 text-[var(--mute)] hover:text-white"
            >
              How it works
            </button>
            <button
              type="button"
              onClick={() => handleAnchor('#safety-contract')}
              className="text-left py-1.5 text-[#f26a1b] font-medium"
            >
              Safety contract
            </button>
            <button
              type="button"
              onClick={() => handleAnchor('#validation')}
              className="text-left py-1.5 text-[var(--mute)] hover:text-white"
            >
              Validation
            </button>
            <Link
              to="/dashboard"
              onClick={() => setMobileOpen(false)}
              className="py-1.5 text-[var(--text)] font-medium"
            >
              Live dashboard (/dashboard)
            </Link>
            <Link
              to="/lab"
              onClick={() => setMobileOpen(false)}
              className="py-1.5 text-[var(--text)] font-medium"
            >
              Scenario lab (/lab)
            </Link>
            <Link
              to="/report"
              onClick={() => setMobileOpen(false)}
              className="py-1.5 text-[var(--text)] font-medium"
            >
              Evaluation report (/report)
            </Link>
          </div>
          <div className="pt-2 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={toggleMock}
              className="rounded-full px-3 py-1.5 text-xs font-mono border border-[var(--line)] text-[var(--mute)]"
            >
              {mockMode ? 'Mode: Mock' : 'Mode: Live API'}
            </button>
            <Link
              to="/dashboard"
              onClick={() => setMobileOpen(false)}
              className="btn-primary !py-2 !px-4 !text-xs"
            >
              Open dashboard
            </Link>
          </div>
        </div>
      )}
    </header>
  );
};

export const Footer: React.FC = () => {
  return (
    <footer className="relative border-t border-[var(--line)] bg-[#050415] py-16 no-print">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Top CTA Banner */}
        <div className="glass-card p-8 sm:p-10 mb-12 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-[#b79bff] mb-2">
              REAL-TIME KERNEL QOS VERIFICATION
            </p>
            <h2 className="text-2xl sm:text-3xl font-light text-[var(--text)]">
              See it protect a call <strong className="font-semibold text-white">live.</strong>
            </h2>
            <p className="mt-2 text-sm text-[var(--mute)] max-w-xl">
              Inspect 1 Hz telemetry, test candidate policies against the pre-apply gate, or trigger a canary breach to watch automated verified rollback.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link to="/dashboard" className="btn-primary">
              See it protect a call live
            </Link>
            <Link to="/lab" className="btn-secondary">
              Open scenario lab
            </Link>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[var(--mute)]">
          <div className="flex items-center gap-3">
            <span className="font-mono font-semibold text-[var(--text)]">{'{ }'} FAIRFLOW</span>
            <span>•</span>
            <span>Constraint-aware QoS controller with verified rollback</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center gap-2 rounded-full border border-[#7c5cff]/40 bg-[#7c5cff]/10 px-3.5 py-1 font-mono text-xs text-[#b79bff]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#f26a1b]" />
              TELIPORT Season 4 — Tata Elxsi
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
};

