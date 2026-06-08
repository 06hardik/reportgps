import React, { useRef, useCallback } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Provider } from 'react-redux';
import { store } from './store/index';
import { FileProvider, useFileContext } from './context/FileContext';
import { resetDocument } from './store/documentSlice';
import { resetIssues, setActiveIssue } from './store/issuesSlice';
import {
  selectIsLoading, selectIssues, selectLlmIssues,
  selectActiveIssueId, selectFileName, selectRegexChecks,
} from './store/selectors/issueSelectors';

import Header from './components/Layout/Header';
import DocumentUpload from './components/DocumentUpload/DocumentUpload';
import PDFViewer from './components/PDFViewer/PDFViewer';
import IssuesSidebar from './components/IssuesSidebar/IssuesSidebar';

import './components/Layout/Layout.css';
import './App.css';

const FEATURES = [
  { icon: '📝', label: 'Grammar & Spelling'   },
  { icon: '📚', label: 'Reference Validation' },
  { icon: '📊', label: 'Figure / Table Checks'},
  { icon: '🏗️', label: 'Structure Analysis'   },
  { icon: '📄', label: 'Annotated PDF Export' },
  { icon: '⚡', label: 'Instant Results'      },
];

const AppContent = () => {
  const dispatch = useDispatch();
  const { fileData, clearFileData } = useFileContext();

  const isLoading    = useSelector(selectIsLoading);
  const issues       = useSelector(selectIssues);
  const llmIssues    = useSelector(selectLlmIssues);
  const activeIssueId= useSelector(selectActiveIssueId);
  const regexChecks  = useSelector(selectRegexChecks);

  const pdfViewerRef = useRef(null);

  // Show workspace as soon as fileData exists (bytes are in memory),
  // regardless of whether analysis has started / completed.
  const inWorkspace = !!fileData;

  const handleReset = useCallback(() => {
    clearFileData();
    dispatch(resetDocument());
    dispatch(resetIssues());
  }, [clearFileData, dispatch]);

  const handleIssueClick = useCallback((issueId) => {
    dispatch(setActiveIssue(issueId));
    pdfViewerRef.current?.scrollToIssue?.(issueId);
  }, [dispatch]);

  const handleAnnotationClick = useCallback((issueId) => {
    dispatch(setActiveIssue(issueId));
  }, [dispatch]);

  return (
    <div className="app-layout">
      <Header onReset={handleReset} />

      <main className="app-main">
        {!inWorkspace ? (
          /* ═══════ LANDING — shown until a file is selected ═══════ */
          <div className="landing">
            <div className="landing-hero animate-fade-in">
              <h1>Validate Your Research Paper</h1>
              <p>
                ReportGPS automatically checks your academic PDF for language errors,
                reference issues, figure / table problems and structural compliance —
                then delivers an annotated PDF with every issue highlighted.
              </p>
            </div>

            <DocumentUpload />

            <div className="landing-features animate-fade-in" style={{ animationDelay: '0.15s' }}>
              {FEATURES.map((f) => (
                <div className="feature-chip" key={f.label}>
                  <span className="feature-chip-icon">{f.icon}</span>
                  <span className="feature-chip-text">{f.label}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          /* ═══════ WORKSPACE ═══════ */
          <div className="workspace">

            {/* ── Center: live PDF viewer ── */}
            <div className="workspace-viewer">
              {/* Thin top banner while backend is running */}
              {isLoading && (
                <div className="workspace-analysing">
                  <div className="upload-loading-spinner"
                    style={{ width: 18, height: 18, borderWidth: 2 }} />
                  Analysing document — this may take a few minutes…
                </div>
              )}

              <PDFViewer
                ref={pdfViewerRef}
                fileData={fileData}
                issues={issues}
                llmIssues={llmIssues}
                activeIssue={activeIssueId}
                onAnnotationClick={handleAnnotationClick}
              />
            </div>

            {/* ── Right: tabbed sidebar ── */}
            <div className="workspace-sidebar">
              <IssuesSidebar
                onIssueClick={handleIssueClick}
                regexChecks={regexChecks}
                isAnalysing={isLoading}
              />
            </div>

          </div>
        )}
      </main>
    </div>
  );
};

const App = () => (
  <Provider store={store}>
    <FileProvider>
      <AppContent />
    </FileProvider>
  </Provider>
);

export default App;
