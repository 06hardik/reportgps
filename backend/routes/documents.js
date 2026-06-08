import express from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

import { logInfo, logError } from '../utils/logger.js';
import { upload, UPLOADS_DIR } from '../utils/fileStorage.js';
import { mergeIssues } from '../utils/issueProcessor.js';
import {
  processDocumentWithRegexValidation,
  extractReferences,
  analyzeReferenceErrors,
  analyzeFiguresTablesEquations,
  generateAnnotatedPDF
} from '../services/documentProcessor.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const router = express.Router();

/**
 * POST /api/documents/upload
 * Main analysis endpoint. Accepts a PDF, runs all 4 checks, returns merged results.
 */
router.post('/upload', upload.single('document'), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: 'No file uploaded. Please upload a PDF.' });
  }

  const filename = req.file.filename;
  const filePath = req.file.path;
  logInfo(`Processing document: ${filename}`);

  let fileBuffer;
  try {
    fileBuffer = fs.readFileSync(filePath);
  } catch (err) {
    logError('Could not read uploaded file', err);
    return res.status(500).json({ error: 'Could not read uploaded file.' });
  }

  try {
    // Run regex, GROBID, and figure analysis in parallel where possible
    logInfo('Starting parallel analysis pipeline');

    // Step 1 & 4 can run in parallel (both need raw PDF)
    // Step 2 (GROBID) also needs raw PDF
    // Step 3 (reference errors) needs Step 2 output
    const [regexResults, referenceData, figureResults] = await Promise.all([
      processDocumentWithRegexValidation(fileBuffer),
      extractReferences(fileBuffer),
      analyzeFiguresTablesEquations(fileBuffer)
    ]);

    // Step 3: Analyze reference errors (depends on Step 2)
    logInfo('Analyzing reference errors');
    // Extract raw reference strings produced by the section extractor
    const rawRefStrings = Array.isArray(regexResults.raw_ref_strings)
      ? regexResults.raw_ref_strings
      : [];
    if (rawRefStrings.length > 0) {
      logInfo(`Passing ${rawRefStrings.length} raw reference strings to reference-analyser`);
    }
    const referenceAnalysisResults = await analyzeReferenceErrors(
      referenceData.bibtexData,
      referenceData.coordinatesData,
      rawRefStrings,
    );

    // Step 5: Merge all issues
    logInfo('Merging all issues');
    const regexIssuesObject = {
      issues: Array.isArray(regexResults.issues) ? regexResults.issues : []
    };
    const mergedIssues = mergeIssues({
      issues: regexIssuesObject,
      referenceIssues: referenceAnalysisResults
    });

    const allIssues = mergedIssues.issues.issues || [];
    const documentChecks = regexResults.document_checks || {};

    logInfo(`Total merged issues: ${allIssues.length}, Figure issues: ${figureResults.length}`);

    // Store the annotated PDF path for later download
    // Generate annotated PDF and save to disk
    let annotatedFilename = null;
    try {
      const annotatedBuffer = await generateAnnotatedPDF(fileBuffer, allIssues, figureResults);
      annotatedFilename = `annotated_${filename}`;
      const annotatedPath = path.join(UPLOADS_DIR, 'anonymous', annotatedFilename);
      fs.writeFileSync(annotatedPath, annotatedBuffer);
      logInfo(`Annotated PDF saved: ${annotatedFilename}`);
    } catch (annotateErr) {
      logError('Failed to generate annotated PDF (non-fatal)', annotateErr);
    }

    res.status(200).json({
      issues: allIssues,
      regex_issues: documentChecks,
      llm_issues: figureResults,
      annotated_pdf: annotatedFilename ? `/api/documents/annotated/${annotatedFilename}` : null,
      meta: {
        filename: filename,
        total_issues: allIssues.length + figureResults.length,
        processed_at: new Date().toISOString()
      }
    });

  } catch (error) {
    logError('Error processing document', error);
    res.status(500).json({ error: 'Internal server error during document processing.' });
  }
});

/**
 * GET /api/documents/annotated/:filename
 * Serve the annotated PDF file for download.
 */
router.get('/annotated/:filename', (req, res) => {
  const { filename } = req.params;
  // Sanitize filename to prevent path traversal
  const safeFilename = path.basename(filename);
  const filePath = path.join(UPLOADS_DIR, 'anonymous', safeFilename);

  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'Annotated PDF not found.' });
  }

  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Disposition', `attachment; filename="annotated_report.pdf"`);
  res.sendFile(path.resolve(filePath));
});

/**
 * GET /api/documents/health
 */
router.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

export default router;
