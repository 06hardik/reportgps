import React from 'react';
import { useSelector } from 'react-redux';
import { selectRegexChecks } from '../../store/selectors/issueSelectors';
import './ChecksPanel.css';

const CheckRow = ({ label, value, type }) => {
  let status = 'info';
  let display = '';

  if (typeof value === 'boolean') {
    status = value ? 'pass' : 'fail';
    display = value ? 'Present' : 'Missing';
  } else if (typeof value === 'number') {
    status = 'info';
    display = String(value);
  } else if (typeof value === 'string') {
    status = 'info';
    display = value;
  } else if (Array.isArray(value)) {
    status = value.length === 0 ? 'pass' : 'fail';
    display = value.length === 0 ? 'None' : `${value.length} issue${value.length > 1 ? 's' : ''}`;
  } else {
    display = JSON.stringify(value);
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

const formatLabel = (key) =>
  key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const ChecksPanel = () => {
  const checks = useSelector(selectRegexChecks);

  if (!checks || Object.keys(checks).length === 0) {
    return (
      <div className="checks-panel">
        <div className="checks-panel-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 11 12 14 22 4"/>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
          </svg>
          Document Checks
        </div>
        <div className="checks-panel-body">
          <p className="text-sm text-muted" style={{ textAlign: 'center', marginTop: '32px' }}>
            Upload a document to see structural checks
          </p>
        </div>
      </div>
    );
  }

  const {
    metadata, disclosures, structure,
    figure_order_analysis, reference_order_analysis,
    references_summary, figures_and_tables, plain_language_summary_present
  } = checks;

  return (
    <div className="checks-panel">
      <div className="checks-panel-header">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="9 11 12 14 22 4"/>
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
        </svg>
        Document Checks
      </div>

      <div className="checks-panel-body">

        {/* Metadata */}
        {metadata && (
          <CheckSection title="Metadata">
            <CheckRow label="Author Email" value={metadata.author_email} />
            <CheckRow label="Author List" value={metadata.list_of_authors} />
            <CheckRow label="Keywords" value={metadata.keywords_list} />
            <CheckRow label="Word Count" value={metadata.word_count} />
          </CheckSection>
        )}

        {/* Structure */}
        {structure && (
          <CheckSection title="Paper Structure">
            <CheckRow label="IMRAD Structure" value={structure.imrad_structure} />
            <CheckRow label="Structured Abstract" value={structure.abstract_structure} />
            {plain_language_summary_present !== undefined && (
              <CheckRow label="Plain Language Summary" value={plain_language_summary_present} />
            )}
          </CheckSection>
        )}

        {/* Disclosures */}
        {disclosures && (
          <CheckSection title="Required Disclosures">
            {Object.entries(disclosures).map(([key, val]) => (
              <CheckRow key={key} label={formatLabel(key)} value={val} />
            ))}
          </CheckSection>
        )}

        {/* Reference Order */}
        {reference_order_analysis && (
          <CheckSection title="Reference Order">
            <CheckRow label="Citations Non-decreasing" value={reference_order_analysis.is_citation_order_non_decreasing_in_text} />
            <CheckRow label="Max Ref Number" value={reference_order_analysis.max_reference_number_cited} />
            <CheckRow label="Missing in Sequence" value={reference_order_analysis.missing_references_up_to_max_cited || []} />
            <CheckRow label="Out-of-order Citations" value={reference_order_analysis.out_of_order_citations_details?.length || 0} />
          </CheckSection>
        )}

        {/* Figure Order */}
        {figure_order_analysis && (
          <CheckSection title="Figure Order">
            <CheckRow label="Sequential Order" value={figure_order_analysis.sequential_order_of_unique_figures} />
            <CheckRow label="Unique Figure Count" value={figure_order_analysis.figure_count_unique} />
            <CheckRow label="Missing in Sequence" value={figure_order_analysis.missing_figures_in_sequence_to_max || []} />
            <CheckRow label="Cited Only Once" value={figure_order_analysis.figures_mentioned_only_once || []} />
          </CheckSection>
        )}

        {/* References Summary */}
        {references_summary && (
          <CheckSection title="References Summary">
            <CheckRow label="Total Citations" value={references_summary.reference_count} />
            <CheckRow label="Old References (pre-2000)" value={references_summary.old_references} />
            <CheckRow label="Citations in Abstract" value={references_summary.citations_in_abstract} />
          </CheckSection>
        )}

      </div>
    </div>
  );
};

export default ChecksPanel;
