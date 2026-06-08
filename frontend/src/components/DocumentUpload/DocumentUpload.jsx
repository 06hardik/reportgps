import React, { useRef, useState, useEffect, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { uploadDocument } from '../../store/documentSlice';
import { selectIsLoading, selectError } from '../../store/selectors/issueSelectors';
import { useFileContext } from '../../context/FileContext';
import './DocumentUpload.css';

const ANALYSIS_STEPS = [
  { id: 'upload',      label: 'Uploading document…'              },
  { id: 'language',   label: 'Checking language & grammar…'      },
  { id: 'grobid',     label: 'Extracting references (GROBID)…'   },
  { id: 'references', label: 'Analysing reference errors…'        },
  { id: 'figures',    label: 'Detecting figure / table issues…'   },
  { id: 'merge',      label: 'Compiling results…'                 },
];

const formatBytes = (b) => {
  if (!b) return '';
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
};

const DocumentUpload = () => {
  const dispatch  = useDispatch();
  const isLoading = useSelector(selectIsLoading);
  const error     = useSelector(selectError);
  const { storeFileData } = useFileContext();

  const fileInputRef  = useRef(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [activeStep,  setActiveStep]  = useState(0);

  // Step ticker while loading
  useEffect(() => {
    if (!isLoading) { setActiveStep(0); return; }
    const delays  = [0, 3000, 8000, 18000, 28000, 38000];
    const timers  = delays.map((d, i) => setTimeout(() => setActiveStep(i), d));
    return () => timers.forEach(clearTimeout);
  }, [isLoading]);

  const validateFile = (file) => {
    if (!file) return 'No file selected.';
    if (file.type !== 'application/pdf') return 'Only PDF files are supported.';
    if (file.size > 50 * 1024 * 1024) return 'File must be under 50 MB.';
    return null;
  };

  /**
   * Core handler: validate → read ArrayBuffer into FileContext (so PDF renders
   * immediately) → dispatch upload to backend.
   * Auto-called on both drop and file-input change.
   */
  const processFile = useCallback((file) => {
    const err = validateFile(file);
    if (err) { alert(err); return; }

    // Read bytes for the PDF viewer (non-blocking)
    const reader = new FileReader();
    reader.onload = (e) => storeFileData(e.target.result.slice(0), file.name);
    reader.readAsArrayBuffer(file);

    // Start backend analysis immediately
    dispatch(uploadDocument({ file }));
  }, [dispatch, storeFileData]);

  const handleInputChange = (e) => {
    if (e.target.files?.[0]) processFile(e.target.files[0]);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }, [processFile]);

  const handleDragOver  = (e) => { e.preventDefault(); setIsDragOver(true);  };
  const handleDragLeave = (e) => { e.preventDefault(); setIsDragOver(false); };
  const handleZoneClick = () => fileInputRef.current?.click();

  // ─── Loading state ────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="upload-loading animate-fade-in">
        <div className="upload-loading-spinner" />
        <div className="upload-loading-title">Analysing your document…</div>
        <p className="text-sm text-secondary" style={{ textAlign: 'center' }}>
          This may take 2–3 minutes while AI services process your paper.
        </p>
        <div className="upload-loading-steps">
          {ANALYSIS_STEPS.map((step, i) => (
            <div
              key={step.id}
              className={`upload-loading-step ${i === activeStep ? 'active' : ''} ${i < activeStep ? 'done' : ''}`}
            >
              <span className="step-dot" />
              {i < activeStep ? '✓ ' : ''}{step.label}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ─── Drop zone (shown on landing page) ───────────────────────────────────
  return (
    <div className="upload-zone-wrapper animate-fade-in">
      {error && (
        <div className="upload-error" style={{ marginBottom: '16px' }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          <span>{typeof error === 'string' ? error : 'Analysis failed. Please try again.'}</span>
        </div>
      )}

      <div
        className={`upload-zone ${isDragOver ? 'drag-over' : ''}`}
        onClick={handleZoneClick}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
        aria-label="Upload PDF file — drop here or click to browse"
        id="pdf-upload-zone"
      >
        <div className="upload-icon-wrap">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <div className="upload-title">Drop your research paper here</div>
        <p className="upload-subtitle">
          <span
            onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
            style={{ cursor: 'pointer', color: 'var(--color-primary)', fontWeight: 600 }}
          >
            Click to browse
          </span>
          {' '}or drag & drop — analysis starts immediately
        </p>
        <div className="upload-meta">
          <span>PDF only</span>
          <span className="upload-meta-dot" />
          <span>Max 50 MB</span>
          <span className="upload-meta-dot" />
          <span>Single document</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={handleInputChange}
          className="upload-file-input"
          id="pdf-file-input"
        />
      </div>
    </div>
  );
};

export default DocumentUpload;
