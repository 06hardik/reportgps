import React, { useState, useRef } from 'react';
import axios from 'axios';
import {
  UploadCloud, FileText, CheckCircle, AlertCircle, Play,
  RotateCcw, BookOpen, Image, Table2, Quote,
  Type, Layers, Clock, Code2, Users, Tag, AlignLeft, Hash
} from 'lucide-react';
import './index.css';

/* ─── helpers ───────────────────────────────────────────────────────────────── */
const safe = (v, fallback = '—') => (v !== null && v !== undefined && v !== '') ? v : fallback;
const arr = (v) => Array.isArray(v) ? v : [];

function Badge({ children, variant = 'info' }) {
  return <span className={`fig-tag tag-${variant}`}>{children}</span>;
}

function SectionHeading({ children }) {
  return <div className="panel-heading">{children}</div>;
}

function EmptyState({ icon: Icon, text }) {
  return (
    <div className="empty-state">
      <Icon size={32} />
      <p>{text}</p>
    </div>
  );
}

/* ─── Tab: Manuscript ───────────────────────────────────────────────────────── */
function ManuscriptTab({ data }) {
  const ms = data?.manuscript || {};
  const authors = arr(ms.authors);
  const keywords = arr(ms.keywords);

  return (
    <div className="panel">
      {ms.title && <p className="ms-title">"{ms.title}"</p>}

      <div className="ms-meta-grid">
        <div className="ms-field">
          <div className="ms-field-label">Authors</div>
          <div className="ms-field-value">
            {authors.length > 0 ? authors.join(', ') : <em style={{ color: 'var(--text-tertiary)' }}>Not detected</em>}
          </div>
        </div>
        <div className="ms-field">
          <div className="ms-field-label">Abstract Length</div>
          <div className="ms-field-value">
            {ms.abstract_word_count ? `${ms.abstract_word_count} words` : '—'}
          </div>
        </div>
        <div className="ms-field">
          <div className="ms-field-label">Keywords Present</div>
          <div className="ms-field-value" style={{ color: ms.keywords_section_present ? 'var(--success)' : 'var(--error)' }}>
            {ms.keywords_section_present ? '✓ Yes' : '✗ Not found'}
          </div>
        </div>
        <div className="ms-field">
          <div className="ms-field-label">Est. Word Count (body)</div>
          <div className="ms-field-value">{safe(data?.estimated_word_count)}</div>
        </div>
      </div>

      {ms.abstract_text && (
        <>
          <SectionHeading>Abstract</SectionHeading>
          <p className="ms-abstract">{ms.abstract_text}</p>
        </>
      )}

      {keywords.length > 0 && (
        <>
          <SectionHeading>Keywords</SectionHeading>
          <div className="kw-list">
            {keywords.map((k, i) => <span key={i} className="kw-chip">{k}</span>)}
          </div>
        </>
      )}
    </div>
  );
}

/* ─── Tab: Sections ─────────────────────────────────────────────────────────── */
function SectionsTab({ data }) {
  const sections = arr(data?.sections);
  if (sections.length === 0) return (
    <div className="panel"><EmptyState icon={Layers} text="No sections detected in this paper." /></div>
  );

  const levelClass = (lvl) => {
    const map = { 1: 'level-1', 2: 'level-2', 3: 'level-3', 4: 'level-4', 5: 'level-5' };
    return map[lvl] || 'level-5';
  };

  return (
    <div className="panel">
      <div className="section-list">
        {sections.map((s, i) => (
          <div className="section-item" key={i}>
            <span className={`section-level-badge ${levelClass(s.heading_level)}`}>
              H{s.heading_level}
            </span>
            <span className="section-num">{s.heading_number || ''}</span>
            <span className="section-text">{s.heading_text}</span>
            <span className="section-page">p.{s.page_number}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Tab: Figures ──────────────────────────────────────────────────────────── */
function FiguresTab({ data }) {
  const figures = arr(data?.figures);
  if (figures.length === 0) return (
    <div className="panel"><EmptyState icon={Image} text="No figures detected." /></div>
  );

  return (
    <div className="panel">
      <div className="fig-table-grid">
        {figures.map((f, i) => (
          <div className="fig-card" key={i}>
            <div className="fig-card-header">
              <span className="fig-num">Figure {f.number}</span>
              <span className="fig-page">Caption p.{f.caption_page} · Mention p.{f.first_mention_page}</span>
            </div>
            <p className="fig-caption">{f.caption_text || <em>No caption found</em>}</p>
            <div className="fig-tags">
              {f.caption_text ? <Badge variant="ok">Caption ✓</Badge> : <Badge variant="err">No Caption</Badge>}
              {f.caption_ends_period ? <Badge variant="ok">Ends .</Badge> : <Badge variant="warn">No period</Badge>}
              {f.coordinate_found ? <Badge variant="info">Bbox ✓</Badge> : <Badge variant="warn">No bbox</Badge>}
              {f.first_mention_page && f.first_mention_page <= f.caption_page
                ? <Badge variant="ok">Cross-ref ✓</Badge>
                : <Badge variant="warn">Check cross-ref</Badge>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Tab: Tables ───────────────────────────────────────────────────────────── */
function TablesTab({ data }) {
  const tables = arr(data?.tables);
  if (tables.length === 0) return (
    <div className="panel"><EmptyState icon={Table2} text="No tables detected." /></div>
  );

  return (
    <div className="panel">
      <div className="fig-table-grid">
        {tables.map((t, i) => (
          <div className="fig-card" key={i}>
            <div className="fig-card-header">
              <span className="fig-num">Table {t.number}</span>
              <span className="fig-page">Caption p.{t.caption_page} · Mention p.{t.first_mention_page}</span>
            </div>
            <p className="fig-caption">{t.caption_text || <em>No caption found</em>}</p>
            <div className="fig-tags">
              {t.caption_text ? <Badge variant="ok">Caption ✓</Badge> : <Badge variant="err">No Caption</Badge>}
              {t.caption_ends_period ? <Badge variant="ok">Ends .</Badge> : <Badge variant="warn">No period</Badge>}
              {t.first_mention_page && t.first_mention_page <= t.caption_page
                ? <Badge variant="ok">Cross-ref ✓</Badge>
                : <Badge variant="warn">Check cross-ref</Badge>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Tab: References ───────────────────────────────────────────────────────── */
function ReferencesTab({ data }) {
  const refs = arr(data?.references);
  const cites = arr(data?.in_text_citations);

  if (refs.length === 0) return (
    <div className="panel"><EmptyState icon={BookOpen} text="No references detected." /></div>
  );

  return (
    <div className="panel">
      <SectionHeading>Reference List ({refs.length})</SectionHeading>
      <div className="ref-list">
        {refs.map((r, i) => (
          <div className="ref-item" key={i}>
            <span className="ref-num">[{r.number || i + 1}]</span>
            <div className="ref-body">
              <span className="ref-raw">{r.raw_string}</span>
              <div className="ref-meta">
                {r.year && <span className="ref-year">{r.year}</span>}
                {r.doi && <Badge variant="info">DOI</Badge>}
                {r.url && <Badge variant="info">URL</Badge>}
              </div>
            </div>
          </div>
        ))}
      </div>

      {cites.length > 0 && (
        <>
          <SectionHeading style={{ marginTop: '1.5rem' }}>In-Text Citations ({cites.length})</SectionHeading>
          <div className="citation-grid">
            {cites.slice(0, 60).map((c, i) => (
              <div className="citation-item" key={i}>
                <span className="citation-marker">{c.marker}</span>
                <span className="citation-page">p.{c.page_number}</span>
              </div>
            ))}
            {cites.length > 60 && (
              <div className="citation-item" style={{ color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                +{cites.length - 60} more…
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ─── Tab: Typography ───────────────────────────────────────────────────────── */
const TYPO_CHECKS = [
  { key: 'en_dash_violations',        label: 'En-dash for Numeric Ranges', desc: 'Hyphen used where en-dash (–) is required' },
  { key: 'number_unit_violations',    label: 'Number–Unit Spacing',        desc: 'Missing space between number and unit (e.g. 10ms → 10 ms)' },
  { key: 'percent_degree_violations', label: 'Percent/Degree Formatting',  desc: 'Incorrect spacing around % or ° symbols' },
  { key: 'latin_abbrev_violations',   label: 'Latin Abbreviations',        desc: 'Malformed eg, ie, etc, et al usage' },
];

function TypographyTab({ data }) {
  const typo = data?.typography || {};
  const totalViolations = TYPO_CHECKS.reduce((s, c) => s + arr(typo[c.key]).length, 0);

  return (
    <div className="panel">
      {totalViolations === 0 ? (
        <div className="typo-ok">
          <CheckCircle size={16} /> No typography violations detected.
        </div>
      ) : (
        <div style={{ background: 'var(--warning-bg)', border: '1px solid #fcd34d', borderRadius: 'var(--radius-xs)', padding: '0.6rem 1rem', marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--warning)', fontWeight: 600 }}>
          ⚠ {totalViolations} violation{totalViolations !== 1 ? 's' : ''} found across {TYPO_CHECKS.filter(c => arr(typo[c.key]).length > 0).length} categor{TYPO_CHECKS.filter(c => arr(typo[c.key]).length > 0).length !== 1 ? 'ies' : 'y'}
        </div>
      )}

      {TYPO_CHECKS.map(({ key, label, desc }) => {
        const violations = arr(typo[key]);
        return (
          <div className="typo-section" key={key}>
            <div className="typo-section-header">
              <Type size={14} />
              {label}
              <Badge variant={violations.length === 0 ? 'ok' : 'warn'}>
                {violations.length === 0 ? 'OK' : violations.length}
              </Badge>
              <span style={{ fontWeight: 400, color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>{desc}</span>
            </div>
            {violations.length === 0 ? (
              <div className="typo-ok"><CheckCircle size={14} /> No issues</div>
            ) : (
              <div className="violation-list">
                {violations.map((v, i) => (
                  <div className="violation-item" key={i}>
                    <span className="violation-found">"{v.found}"</span>
                    {v.correct && (
                      <>
                        <span className="violation-arrow">→</span>
                        <span className="violation-correct">"{v.correct}"</span>
                      </>
                    )}
                    {v.snippet && (
                      <span className="violation-snippet">…{v.snippet}…</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Tab: Raw JSON ─────────────────────────────────────────────────────────── */
function RawTab({ data }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.75rem' }}>
        <button onClick={copy} style={{ background: 'var(--surface-3)', border: '1px solid var(--border)', padding: '0.4rem 0.9rem', borderRadius: 'var(--radius-xs)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: copied ? 'var(--success)' : 'var(--text-secondary)' }}>
          {copied ? '✓ Copied!' : 'Copy JSON'}
        </button>
      </div>
      <pre className="json-view">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

/* ─── Results Viewer ─────────────────────────────────────────────────────────── */
const TABS = [
  { id: 'manuscript', label: 'Manuscript', icon: FileText,  countKey: null },
  { id: 'sections',   label: 'Sections',   icon: Layers,    countKey: 'sections' },
  { id: 'figures',    label: 'Figures',    icon: Image,     countKey: 'figures' },
  { id: 'tables',     label: 'Tables',     icon: Table2,    countKey: 'tables' },
  { id: 'references', label: 'References', icon: BookOpen,  countKey: 'references' },
  { id: 'typography', label: 'Typography', icon: Type,      countKey: null },
  { id: 'raw',        label: 'Raw JSON',   icon: Code2,     countKey: null },
];

function ResultsViewer({ data, onReset }) {
  const [activeTab, setActiveTab] = useState('manuscript');
  const t = data?.pipeline_timings || {};

  const typo = data?.typography || {};
  const typoCount = ['en_dash_violations','number_unit_violations','percent_degree_violations','latin_abbrev_violations']
    .reduce((s, k) => s + arr(typo[k]).length, 0);

  const getCount = (key) => {
    if (!key) return null;
    return arr(data?.[key]).length;
  };

  return (
    <div className="results-wrapper">
      {/* Top bar */}
      <div className="results-topbar">
        <div>
          <div className="results-title">Extraction Results</div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            {data?.manuscript?.title ? `"${data.manuscript.title.slice(0, 70)}${data.manuscript.title.length > 70 ? '…' : ''}"` : 'Untitled paper'}
          </div>
        </div>
        <button className="reset-btn" onClick={onReset}>
          <RotateCcw size={14} /> Upload Another
        </button>
      </div>

      {/* Stats grid */}
      <div className="stats-grid">
        {[
          { label: 'Pages',      value: data?.total_pages_processed },
          { label: 'Sections',   value: arr(data?.sections).length },
          { label: 'Figures',    value: arr(data?.figures).length },
          { label: 'Tables',     value: arr(data?.tables).length },
          { label: 'References', value: arr(data?.references).length },
          { label: 'Citations',  value: arr(data?.in_text_citations).length },
          { label: 'Typo flags', value: typoCount },
          { label: '~Words',     value: data?.estimated_word_count?.toLocaleString() },
        ].map(({ label, value }) => (
          <div className="stat-card" key={label}>
            <div className="stat-value">{value ?? '—'}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>

      {/* Timing bar */}
      <div className="timing-bar">
        <Clock size={13} />
        {[
          { step: 'PyMuPDF', key: 'pymupdf_s' },
          { step: 'Structure', key: 'structural_s' },
          { step: 'Regex', key: 'regex_s' },
          { step: 'Typography', key: 'typography_s' },
        ].map(({ step, key }) => t[key] != null && (
          <span className="timing-item" key={key}>
            <span className="timing-step">{step}</span>
            <span className="timing-val">{t[key]}s</span>
          </span>
        ))}
        {t.total_s != null && (
          <span className="timing-total">⚡ {t.total_s}s total</span>
        )}
      </div>

      {/* Tabs */}
      <div className="tabs-container">
        <div className="tab-list" role="tablist">
          {TABS.map(({ id, label, icon: Icon, countKey }) => {
            const count = getCount(countKey);
            const isBadge = id === 'typography' ? typoCount : count;
            return (
              <button
                key={id}
                className={`tab-btn ${activeTab === id ? 'active' : ''}`}
                onClick={() => setActiveTab(id)}
                role="tab"
                aria-selected={activeTab === id}
              >
                <Icon size={14} />
                {label}
                {isBadge != null && (
                  <span className="tab-badge">
                    {id === 'typography' ? typoCount : count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Panel content */}
      {activeTab === 'manuscript'  && <ManuscriptTab  data={data} />}
      {activeTab === 'sections'    && <SectionsTab    data={data} />}
      {activeTab === 'figures'     && <FiguresTab     data={data} />}
      {activeTab === 'tables'      && <TablesTab      data={data} />}
      {activeTab === 'references'  && <ReferencesTab  data={data} />}
      {activeTab === 'typography'  && <TypographyTab  data={data} />}
      {activeTab === 'raw'         && <RawTab         data={data} />}
    </div>
  );
}

/* ─── Main App ──────────────────────────────────────────────────────────────── */
export default function App() {
  const [file, setFile]           = useState(null);
  const [loading, setLoading]     = useState(false);
  const [results, setResults]     = useState(null);
  const [error, setError]         = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) selectFile(e.dataTransfer.files[0]);
  };

  const selectFile = (f) => {
    if (f.type !== 'application/pdf') { setError('Please upload a PDF file.'); return; }
    setFile(f);
    setError(null);
    setResults(null);
  };

  const processFile = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await axios.post('/api/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setResults(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Processing failed.');
    } finally {
      setLoading(false);
    }
  };

  const reset = () => { setResults(null); setFile(null); setError(null); };

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">RG</div>
          <div>
            <h1>ReportGPS</h1>
            <div className="header-sub">PDF Academic Paper Extractor</div>
          </div>
        </div>
        <div className="header-badge">Lean Pipeline v3.0</div>
      </header>

      <main className="main-content">
        {/* Upload state */}
        {!loading && !results && (
          <div>
            <div className="upload-hero">
              <h2>Analyse Your Paper</h2>
              <p>Upload a PDF to extract structure, figures, tables, references & more in under 2 seconds.</p>
            </div>

            <div
              id="upload-zone"
              className={`upload-card ${dragActive ? 'drag-active' : ''}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current.click()}
            >
              <input
                ref={fileInputRef}
                id="pdf-file-input"
                type="file"
                className="file-input"
                accept="application/pdf"
                onChange={(e) => e.target.files?.[0] && selectFile(e.target.files[0])}
              />
              <div className="upload-icon-wrap">
                <UploadCloud size={32} />
              </div>
              <p className="upload-text">Drop your PDF here</p>
              <p className="upload-subtext">or click to browse — PDF files only</p>

              {file && (
                <div className="file-selected">
                  <CheckCircle size={16} /> {file.name}
                  <span style={{ color: 'var(--text-tertiary)', marginLeft: '0.5rem', fontSize: '0.75rem' }}>
                    ({(file.size / 1024 / 1024).toFixed(1)} MB)
                  </span>
                </div>
              )}
            </div>

            {error && (
              <div className="error-message">
                <AlertCircle size={18} /> {error}
              </div>
            )}

            {file && (
              <div style={{ textAlign: 'center' }}>
                <button
                  id="process-btn"
                  className="process-btn"
                  onClick={(e) => { e.stopPropagation(); processFile(); }}
                >
                  <Play size={18} /> Analyse Document
                </button>
              </div>
            )}
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className="loading-container">
            <div className="spinner-ring" />
            <div className="loading-title">Analysing Document…</div>
            <p className="loading-sub">
              Running PyMuPDF extraction → structural analysis → regex passes<br />
              This typically takes <strong>1–3 seconds</strong>.
            </p>
          </div>
        )}

        {/* Results */}
        {results && !loading && (
          <ResultsViewer data={results} onReset={reset} />
        )}
      </main>
    </div>
  );
}
