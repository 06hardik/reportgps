import React, { useState, useRef } from 'react';
import axios from 'axios';
import { UploadCloud, FileText, CheckCircle, AlertCircle, Play } from 'lucide-react';
import './index.css';

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  const handleDrag = function(e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = function(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelection(e.dataTransfer.files[0]);
    }
  };

  const handleChange = function(e) {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFileSelection(e.target.files[0]);
    }
  };

  const handleFileSelection = (selectedFile) => {
    if (selectedFile.type !== 'application/pdf') {
      setError('Please upload a PDF file.');
      return;
    }
    setFile(selectedFile);
    setError(null);
    setResults(null);
  };

  const onButtonClick = () => {
    fileInputRef.current.click();
  };

  const processFile = async () => {
    if (!file) return;

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Using the proxy configured in vite.config.js
      const response = await axios.post('/api/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      setResults(response.data);
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.error || err.message || 'An error occurred during processing.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-container">
      <header className="header">
        <FileText size={28} color="#8b5cf6" />
        <h1>ReportGPS</h1>
      </header>

      <main className="main-content">
        {!loading && !results && (
          <div>
            <div 
              className={`upload-card ${dragActive ? "drag-active" : ""}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={onButtonClick}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="file-input"
                accept="application/pdf"
                onChange={handleChange}
              />
              <UploadCloud size={48} className="upload-icon" />
              <p className="upload-text">Drag and drop your PDF here</p>
              <p className="upload-subtext">or click to browse</p>
              
              {file && (
                <div style={{ marginTop: '1.5rem', color: '#10b981', fontWeight: 600 }}>
                  <CheckCircle size={20} style={{ verticalAlign: 'middle', marginRight: '0.5rem' }} />
                  {file.name} selected
                </div>
              )}
            </div>

            {error && (
              <div className="error-message">
                <AlertCircle size={20} style={{ verticalAlign: 'middle', marginRight: '0.5rem' }} />
                {error}
              </div>
            )}

            {file && (
              <div style={{ textAlign: 'center', marginTop: '2rem' }}>
                <button 
                  onClick={(e) => { e.stopPropagation(); processFile(); }}
                  style={{
                    background: 'var(--primary-gradient)',
                    color: 'white',
                    border: 'none',
                    padding: '0.75rem 2rem',
                    fontSize: '1.1rem',
                    fontWeight: 600,
                    borderRadius: '2rem',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    boxShadow: '0 4px 6px -1px rgba(99, 102, 241, 0.4)'
                  }}
                >
                  <Play size={20} /> Process Document
                </button>
              </div>
            )}
          </div>
        )}

        {loading && (
          <div className="loading-container">
            <div className="spinner"></div>
            <h2 style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>Processing Document</h2>
            <p style={{ color: 'var(--text-secondary)' }}>
              Extracting structured data using the hybrid pipeline.<br/>
              This may take a few minutes depending on the document length.
            </p>
          </div>
        )}

        {results && !loading && (
          <div className="results-container">
            <div className="results-header">
              <h2>Extraction Results</h2>
              <button 
                onClick={() => { setResults(null); setFile(null); }}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border-color)',
                  padding: '0.5rem 1rem',
                  borderRadius: '0.5rem',
                  cursor: 'pointer',
                  fontWeight: 500
                }}
              >
                Upload Another
              </button>
            </div>
            
            <pre className="json-view">
              {JSON.stringify(results, null, 2)}
            </pre>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
