import React from 'react';
import { useSelector } from 'react-redux';
import { selectFileName, selectIsLoading } from '../../store/selectors/issueSelectors';
import './Layout.css';

const Header = ({ onReset }) => {
  const fileName = useSelector(selectFileName);
  const isLoading = useSelector(selectIsLoading);

  return (
    <header className="header">
      <a href="/" className="header-logo" onClick={(e) => { e.preventDefault(); onReset?.(); }}>
        <div className="header-logo-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            <line x1="11" y1="8" x2="11" y2="14"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </div>
        <div className="header-logo-text">
          <span className="header-logo-name">ReportGPS</span>
          <span className="header-logo-tagline">Research Paper Validator</span>
        </div>
      </a>

      <div className="header-actions">
        {isLoading && (
          <div className="header-status">
            <span className="header-status-dot" style={{ background: 'var(--color-warning)' }} />
            Analyzing…
          </div>
        )}
        {fileName && !isLoading && (
          <div className="header-status">
            <span className="header-status-dot" />
            {fileName.length > 28 ? fileName.slice(0, 25) + '…' : fileName}
          </div>
        )}
        {fileName && (
          <button className="btn btn-ghost btn-sm" onClick={onReset}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
              <path d="M3 3v5h5"/>
            </svg>
            New Upload
          </button>
        )}
      </div>
    </header>
  );
};

export default Header;
