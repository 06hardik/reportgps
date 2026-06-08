import React, { useState, useCallback } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import {
  selectIssues, selectLlmIssues, selectActiveIssueId,
  selectAnnotatedPdfUrl, selectFilter, selectRegexChecks,
} from '../../store/selectors/issueSelectors';
import { setActiveIssue, setFilter } from '../../store/issuesSlice';
import { apiBaseUrl } from '../../config/config';
import './IssuesSidebar.css';

// ─── category metadata ────────────────────────────────────────────────────────
const CAT_META = {
  TYPOS:      { label: 'Spelling',    icon: '🔤', rgb: '220,38,38',   color: '#dc2626' },
  GRAMMAR:    { label: 'Grammar',     icon: '📝', rgb: '16,185,129',  color: '#10b981' },
  TYPOGRAPHY: { label: 'Typography',  icon: '🖋',  rgb: '79,70,229',  color: '#4f46e5' },
  Formatting: { label: 'Formatting',  icon: '📐', rgb: '234,145,0',   color: '#ea9100' },
  MISC:       { label: 'Other',       icon: '💡', rgb: '107,114,128', color: '#6b7280' },
  ARTICLE:    { label: 'References',  icon: '📚', rgb: '14,165,233',  color: '#0ea5e9' },
  FIGURE:     { label: 'Figures',     icon: '📊', rgb: '139,92,246',  color: '#8b5cf6' },
  TABLE:      { label: 'Tables',      icon: '📋', rgb: '20,184,166',  color: '#14b8a6' },
};
const getCat = (k) => CAT_META[k] || { label: k || 'Other', icon: '💡', rgb: '107,114,128', color: '#6b7280' };

const FILTERS = [
  { id: 'all',        label: 'All'        },
  { id: 'language',   label: 'Language'   },
  { id: 'references', label: 'References' },
  { id: 'figures',    label: 'Figures'    },
];

// ─── Severity helpers ──────────────────────────────────────────────────────────
function getRefSeverity(issue) {
  const missing = issue.asterikError || [];
  const inco    = issue.consistencyError || [];
  const check   = issue.check || '';
  const warn    = issue.warningMessage;

  if (missing.length > 0) return 'critical';
  if (check === 'ordering' || check === 'completeness') return 'error';
  if (inco.length > 0 || check === 'doi' || check === 'journal_casing') return 'warning';
  if (warn || check === 'style_conformity') return 'warning';
  return 'warning';
}


const SEVERITY_META = {
  critical: { label: 'Critical', color: '#ef4444', bg: '#fef2f2', border: '#fecaca', icon: '🚨' },
  error:    { label: 'Error',    color: '#f97316', bg: '#fff7ed', border: '#fed7aa', icon: '⚠️' },
  warning:  { label: 'Warning',  color: '#eab308', bg: '#fefce8', border: '#fde047', icon: '⚡' },
  info:     { label: 'Info',     color: '#3b82f6', bg: '#eff6ff', border: '#bfdbfe', icon: 'ℹ️' },
};

// ─── Location badge ───────────────────────────────────────────────────────────
const LocationBadge = ({ page, coordinates }) => {
  if (!page || page <= 0) return null;
  const hasCoords = coordinates && coordinates.length === 4;
  const tip = hasCoords
    ? `Page ${page} — x:${Math.round(coordinates[0])}, y:${Math.round(coordinates[1])}`
    : `Page ${page}`;
  return (
    <span className="loc-badge" title={tip}>
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
        <circle cx="12" cy="10" r="3"/>
      </svg>
      p.{page}
    </span>
  );
};

// ─── Build a readable summary of a reference entry (for the "full reference" display) ─
function buildRefString(issue) {
  // If the issue has a raw reference string, use it
  if (issue.raw_text && issue.raw_text.length > 10) return issue.raw_text;

  // Reconstruct from BibTeX fields
  const parts = [];
  const authors = issue.author || '';
  const title   = issue.title  || '';
  const year    = issue.year   || '';
  const journal = issue.journal || issue.booktitle || '';
  const volume  = issue.volume || '';
  const pages   = issue.pages  || '';
  const doi     = issue.doi    || '';

  if (authors) parts.push(authors.length > 60 ? authors.slice(0, 60) + '…' : authors);
  if (title)   parts.push(`"${title.length > 80 ? title.slice(0, 80) + '…' : title}"`);
  if (journal) parts.push(journal);
  const after = [volume && `vol. ${volume}`, year && `(${year})`, pages && `pp. ${pages}`, doi && `doi:${doi}`]
    .filter(Boolean).join(', ');
  if (after) parts.push(after);

  return parts.join(' — ') || issue.ID || 'Reference entry';
}

// ─── Render error details for a reference issue ───────────────────────────────
function buildRefErrors(issue) {
  const errors = [];

  // Missing required fields (asterikError) — critical
  if (issue.asterikError?.length > 0) {
    errors.push({
      severity: 'critical',
      type: 'Missing required fields',
      detail: `Required fields absent: ${issue.asterikError.map(f => `"${f}"`).join(', ')}`,
      fix: `Add the missing field(s) to this reference entry.`,
    });
  }

  // Consistency errors — warning
  if (issue.consistencyError?.length > 0) {
    errors.push({
      severity: 'warning',
      type: 'Inconsistent fields',
      detail: `Field(s) ${issue.consistencyError.map(f => `"${f}"`).join(', ')} appear in other entries but not in this one.`,
      fix: 'Make field usage consistent across all reference entries.',
    });
  }

  // warningMessage (truly incomplete misc entries only)
  if (issue.warningMessage) {
    errors.push({
      severity: 'warning',
      type: 'Incomplete entry',
      detail: issue.warningMessage,
      fix: null,
    });
  }

  // Embedded quality_issues (from the 5-check pipeline, no longer top-level cards)
  const CHECK_LABELS = {
    ordering:        'Citation Order',
    doi:             'Missing DOI / URL',
    journal_casing:  'Journal Title Casing',
    completeness:    'Completeness',
    style_conformity: 'Style Conformity',
  };
  const CHECK_SEVERITY = {
    ordering:        'error',
    completeness:    'error',
    doi:             'warning',
    journal_casing:  'warning',
    style_conformity: 'warning',
  };

  const qualityItems = [
    // If this IS a standalone quality issue (came from old separate card path)
    ...(issue.check && issue.message ? [issue] : []),
    // Embedded quality_issues from the 5-check pipeline
    ...(Array.isArray(issue.quality_issues) ? issue.quality_issues : []),
  ];

  qualityItems.forEach(qi => {
    if (!qi.check && !qi.message) return;
    const label   = CHECK_LABELS[qi.check] || qi.check || 'Quality Check';
    const detail  = (qi.message || '').replace(/^\[[\w\s]+\]\s*/, '');
    const fix     = qi.suggestions?.[0] || qi.context || null;
    const sev     = CHECK_SEVERITY[qi.check] || 'warning';
    errors.push({ severity: sev, type: label, detail, fix });
  });

  return errors;
}

// ─── Reference Issue Card (rich, expanded display) ────────────────────────────
const RefIssueCard = ({ issue, issueId, isActive, onClick }) => {
  const [expanded, setExpanded] = useState(false);
  const page    = issue.page || 0;
  const coords  = issue.coordinates || [];
  const refId   = issue.ID || issue.id || '';
  const refNum  = refId.replace(/^b/, '#');   // b0 → #0, b12 → #12
  const errors  = buildRefErrors(issue);
  const refStr  = buildRefString(issue);
  const topSev  = errors[0]?.severity || 'info';
  const sevMeta = SEVERITY_META[topSev] || SEVERITY_META.info;

  return (
    <div
      className={`ref-card ${isActive ? 'active' : ''} sev-${topSev}`}
      style={{ '--sev-color': sevMeta.color, '--sev-bg': sevMeta.bg, '--sev-border': sevMeta.border }}
      onClick={() => { onClick(); setExpanded(true); }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      id={`issue-card-${issueId}`}
    >
      {/* Header row */}
      <div className="ref-card-header">
        <div className="ref-card-title">
          <span className="ref-sev-icon">{sevMeta.icon}</span>
          <span className="ref-id-badge">{refNum || 'Ref'}</span>
          <span className="ref-sev-label" style={{ color: sevMeta.color }}>{sevMeta.label}</span>
        </div>
        <div className="ref-card-right">
          <LocationBadge page={page} coordinates={coords} />
          <button
            className="ref-expand-btn"
            onClick={(e) => { e.stopPropagation(); setExpanded(x => !x); }}
            title={expanded ? 'Collapse' : 'Expand'}
          >
            <svg
              width="11" height="11" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
              style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: '150ms' }}
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Full reference string — always visible but truncated unless expanded */}
      <div className={`ref-card-refstr ${expanded ? 'expanded' : ''}`} title={refStr}>
        {refStr}
      </div>

      {/* Error list — always show at least the first error */}
      {errors.length > 0 && (
        <div className="ref-card-errors">
          {(expanded ? errors : errors.slice(0, 1)).map((err, i) => (
            <div key={i} className={`ref-error-row sev-${err.severity}`}
              style={{ '--sev-color': SEVERITY_META[err.severity]?.color }}>
              <div className="ref-error-type">{err.type}</div>
              <div className="ref-error-detail">{err.detail}</div>
              {err.fix && (
                <div className="ref-error-fix">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  {err.fix}
                </div>
              )}
            </div>
          ))}
          {!expanded && errors.length > 1 && (
            <div className="ref-more-hint" onClick={(e) => { e.stopPropagation(); setExpanded(true); }}>
              +{errors.length - 1} more issue{errors.length > 2 ? 's' : ''} — click to expand
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ─── Generic Issue Card (language/grammar) ────────────────────────────────────
const LangIssueCard = ({ issue, issueId, isActive, onClick }) => {
  const page    = issue.page || issue.page_number || 0;
  const coords  = issue.coordinates || [];
  const message = issue.message || 'Issue detected';
  const context = issue.context || '';
  const suggestion = issue.suggestions?.[0] || '';

  return (
    <div
      className={`issue-card ${isActive ? 'active' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      id={`issue-card-${issueId}`}
    >
      <div className="issue-card-top">
        <span className="issue-card-message">{message}</span>
        <LocationBadge page={page} coordinates={coords} />
      </div>
      {context && (
        <div className="issue-card-context" title={context}>{context}</div>
      )}
      {suggestion && (
        <div className="issue-card-suggestion">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          {suggestion}
        </div>
      )}
    </div>
  );
};

// ─── LLM Figure/Table card ───────────────────────────────────────────────────
const LlmIssueCard = ({ issue, issueId, isActive, onClick }) => {
  const page    = issue.page_number || 0;
  const message = issue.description || 'Caption placement issue';
  const context = `${issue.fig_type || 'Figure'} — Caption: ${issue.caption_location || '?'}`;

  return (
    <div
      className={`issue-card ${isActive ? 'active' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      id={`issue-card-${issueId}`}
    >
      <div className="issue-card-top">
        <span className="issue-card-message">{message}</span>
        {page > 0 && <span className="loc-badge">p.{page}</span>}
      </div>
      <div className="issue-card-context">{context}</div>
    </div>
  );
};

// ─── Collapsible group ────────────────────────────────────────────────────────
const IssueGroup = ({ catKey, issues, activeId, onIssueClick, isRef, isLlm }) => {
  const [collapsed, setCollapsed] = useState(false);
  if (!issues.length) return null;
  const meta = getCat(catKey);
  const rgb  = meta.rgb;

  return (
    <div className="issue-group">
      <div className="issue-group-header" onClick={() => setCollapsed(c => !c)}>
        <div className="issue-group-label">
          <span className="issue-group-icon" style={{ background: `rgba(${rgb},0.12)`, color: `rgb(${rgb})` }}>
            {meta.icon}
          </span>
          {meta.label}
          <span className="issue-group-count" style={{ background: `rgba(${rgb},0.12)`, color: `rgb(${rgb})` }}>
            {issues.length}
          </span>
        </div>
        <svg
          className={`issue-group-chevron ${collapsed ? 'collapsed' : ''}`}
          width="13" height="13" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </div>

      {!collapsed && issues.map((issue, idx) => {
        const id = String(issue.id ?? issue.ID ?? issue.offset ?? `${catKey}-${idx}`);
        const isActive = id === String(activeId);

        if (isLlm) {
          return (
            <LlmIssueCard key={id} issue={issue} issueId={id} isActive={isActive}
              onClick={() => onIssueClick(id)} />
          );
        }
        if (isRef || issue.ENTRYTYPE || issue.category === 'ARTICLE' || issue.check) {
          // Skip clean references — only render if there are actual errors
          const errs = buildRefErrors(issue);
          if (errs.length === 0) return null;
          return (
            <RefIssueCard key={id} issue={issue} issueId={id} isActive={isActive}
              onClick={() => onIssueClick(id)} />
          );
        }

        return (
          <LangIssueCard key={id} issue={issue} issueId={id} isActive={isActive}
            onClick={() => onIssueClick(id)} />
        );
      })}
    </div>
  );
};

// ─── Document Checks tab ───────────────────────────────────────────────────────
const fmt = (key) => key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const CheckRow = ({ label, value }) => {
  let status, display;
  if (typeof value === 'boolean') {
    status  = value ? 'pass' : 'fail';
    display = value ? 'Present' : 'Missing';
  } else if (Array.isArray(value)) {
    status  = value.length === 0 ? 'pass' : 'warn';
    display = value.length === 0 ? 'None' : `${value.length} issue${value.length > 1 ? 's' : ''}`;
  } else {
    status  = 'info';
    display = String(value ?? '—');
  }
  return (
    <div className="check-row">
      <span className="check-row-label">{label}</span>
      <span className={`check-indicator ${status}`}>
        <span className={`check-dot ${status}`} />
        {display}
      </span>
    </div>
  );
};

const CheckSection = ({ title, children }) => (
  <div className="check-section">
    <div className="check-section-title">{title}</div>
    {children}
  </div>
);

const DocumentChecks = ({ checks, isAnalysing }) => {
  if (isAnalysing) {
    return (
      <div className="checks-content">
        <div className="checks-placeholder">
          <div className="upload-loading-spinner" style={{ width: 28, height: 28 }} />
          Analysing structure…
        </div>
      </div>
    );
  }
  if (!checks || !Object.keys(checks).length) {
    return (
      <div className="checks-content">
        <div className="checks-placeholder">Upload a document to see structural checks.</div>
      </div>
    );
  }
  const {
    metadata, disclosures, structure,
    figure_order_analysis, reference_order_analysis,
    references_summary, plain_language_summary_present,
  } = checks;

  return (
    <div className="checks-content">
      {metadata && (
        <CheckSection title="Metadata">
          <CheckRow label="Author Email"  value={metadata.author_email} />
          <CheckRow label="Author List"   value={metadata.list_of_authors} />
          <CheckRow label="Keywords"      value={metadata.keywords_list} />
          <CheckRow label="Word Count"    value={metadata.word_count} />
        </CheckSection>
      )}
      {structure && (
        <CheckSection title="Paper Structure">
          <CheckRow label="IMRAD Structure"     value={structure.imrad_structure} />
          <CheckRow label="Abstract Present"    value={structure.abstract_present} />
          <CheckRow label="References Present"  value={structure.references_present} />
          <CheckRow label="Structured Abstract" value={structure.abstract_structure} />
          {structure.detected_sections?.length > 0 && (
            <CheckRow label="Detected Sections" value={structure.detected_sections.join(', ')} />
          )}
          {plain_language_summary_present !== undefined && (
            <CheckRow label="Plain Language Summary" value={plain_language_summary_present} />
          )}
        </CheckSection>
      )}
      {disclosures && (
        <CheckSection title="Required Disclosures">
          {Object.entries(disclosures).map(([k, v]) => (
            <CheckRow key={k} label={fmt(k)} value={v} />
          ))}
        </CheckSection>
      )}
      {reference_order_analysis && (
        <CheckSection title="Reference Order (In-Text)">
          <CheckRow label="Non-decreasing Citations" value={reference_order_analysis.is_citation_order_non_decreasing_in_text} />
          <CheckRow label="Max Ref Number"            value={reference_order_analysis.max_reference_number_cited} />
          <CheckRow label="Missing in Sequence"       value={reference_order_analysis.missing_references_up_to_max_cited || []} />
        </CheckSection>
      )}
      {figure_order_analysis && (
        <CheckSection title="Figure Order">
          <CheckRow label="Sequential Order"    value={figure_order_analysis.sequential_order_of_unique_figures} />
          <CheckRow label="Unique Figure Count" value={figure_order_analysis.figure_count_unique} />
          <CheckRow label="Missing Figures"     value={figure_order_analysis.missing_figures_in_sequence_to_max || []} />
        </CheckSection>
      )}
      {references_summary && (
        <CheckSection title="References Summary">
          <CheckRow label="Total Citations"       value={references_summary.reference_count} />
          <CheckRow label="Old Refs (pre-2000)"   value={references_summary.old_references} />
          <CheckRow label="Citations in Abstract" value={references_summary.citations_in_abstract} />
        </CheckSection>
      )}
    </div>
  );
};

// ─── Main Sidebar ─────────────────────────────────────────────────────────────
const IssuesSidebar = ({ onIssueClick, regexChecks, isAnalysing }) => {
  const dispatch     = useDispatch();
  const issues       = useSelector(selectIssues);
  const llmIssues    = useSelector(selectLlmIssues);
  const activeId     = useSelector(selectActiveIssueId);
  const filter       = useSelector(selectFilter);
  const annotatedUrl = useSelector(selectAnnotatedPdfUrl);
  const checksFromStore = useSelector(selectRegexChecks);

  const checks = regexChecks || checksFromStore;
  const [tab, setTab] = useState('issues');

  const handleIssueClick = useCallback((id) => {
    dispatch(setActiveIssue(id));
    onIssueClick?.(id);
  }, [dispatch, onIssueClick]);

  const handleDownload = useCallback(() => {
    if (!annotatedUrl) return;
    const base = apiBaseUrl.replace('/api', '');
    const url  = annotatedUrl.startsWith('http') ? annotatedUrl : `${base}${annotatedUrl}`;
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'annotated_report.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, [annotatedUrl]);

  // Group language issues by category; separate reference issues
  const langGroups = {};
  const refIssues  = [];

  issues.forEach((iss) => {
    if (iss.ENTRYTYPE || iss.category === 'ARTICLE' || iss.check) {
      refIssues.push(iss);
    } else {
      const cat = iss.category || 'MISC';
      if (!langGroups[cat]) langGroups[cat] = [];
      langGroups[cat].push(iss);
    }
  });

  const showLang = filter === 'all' || filter === 'language';
  const showRef  = filter === 'all' || filter === 'references';
  const showFig  = filter === 'all' || filter === 'figures';

  const totalIssues = issues.length + llmIssues.length;

  // Summary counts for filter bar
  const langCount = Object.values(langGroups).reduce((s, arr) => s + arr.length, 0);
  const refCount  = refIssues.length;
  const figCount  = llmIssues.length;

  return (
    <div className="sidebar">
      {/* Tab strip */}
      <div className="sidebar-tabs">
        <button className={`sidebar-tab ${tab === 'issues' ? 'active' : ''}`}
          onClick={() => setTab('issues')} id="tab-issues">
          Issues
          {totalIssues > 0 && <span className="sidebar-tab-badge">{totalIssues}</span>}
        </button>
        <button className={`sidebar-tab ${tab === 'checks' ? 'active' : ''}`}
          onClick={() => setTab('checks')} id="tab-checks">
          Doc Checks
        </button>
      </div>

      {/* ═══ ISSUES TAB ═══ */}
      {tab === 'issues' && (
        <>
          {/* Filter pills with counts */}
          <div className="sidebar-filters">
            {[
              { id: 'all',        label: 'All',        count: totalIssues },
              { id: 'language',   label: 'Language',   count: langCount },
              { id: 'references', label: 'References', count: refCount },
              { id: 'figures',    label: 'Figures',    count: figCount },
            ].map(f => (
              <button
                key={f.id}
                className={`filter-btn ${filter === f.id ? 'active' : ''}`}
                onClick={() => dispatch(setFilter(f.id))}
                id={`filter-${f.id}`}
              >
                {f.label}
                {f.count > 0 && <span className="filter-count">{f.count}</span>}
              </button>
            ))}
          </div>

          <div className="sidebar-content">
            {totalIssues === 0 ? (
              <div className="sidebar-empty">
                {isAnalysing ? (
                  <>
                    <div className="upload-loading-spinner" style={{ width: 32, height: 32, borderWidth: 3 }} />
                    <p>Analysing your document…<br/><span style={{ fontSize: '0.75rem' }}>Results appear here shortly.</span></p>
                  </>
                ) : annotatedUrl ? (
                  <>
                    <span className="sidebar-empty-icon">✅</span>
                    <p>No issues detected!<br/><span style={{ fontSize: '0.75rem' }}>Check the Doc Checks tab for structural analysis.</span></p>
                  </>
                ) : (
                  <>
                    <span className="sidebar-empty-icon">📋</span>
                    <p>Upload a PDF to begin analysis.</p>
                  </>
                )}
              </div>
            ) : (
              <>
                {/* Language / grammar groups */}
                {showLang && Object.entries(langGroups).map(([cat, catIssues]) => (
                  <IssueGroup key={cat} catKey={cat} issues={catIssues}
                    activeId={activeId} onIssueClick={handleIssueClick} />
                ))}

                {/* Reference issues */}
                {showRef && refIssues.length > 0 && (
                  <IssueGroup catKey="ARTICLE" issues={refIssues} isRef
                    activeId={activeId} onIssueClick={handleIssueClick} />
                )}

                {/* Figure / table LLM issues */}
                {showFig && llmIssues.length > 0 && (
                  <IssueGroup catKey="FIGURE" issues={llmIssues} isLlm
                    activeId={activeId} onIssueClick={handleIssueClick} />
                )}
              </>
            )}
          </div>
        </>
      )}

      {/* ═══ CHECKS TAB ═══ */}
      {tab === 'checks' && (
        <DocumentChecks checks={checks} isAnalysing={isAnalysing} />
      )}

      {/* Download footer */}
      {annotatedUrl && (
        <div className="sidebar-footer">
          <button className="btn download-btn" onClick={handleDownload} id="download-annotated-pdf">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download Annotated PDF
          </button>
          <p className="download-label">All issues are marked at their exact location</p>
        </div>
      )}
    </div>
  );
};

export default IssuesSidebar;
