import axios from 'axios';
import FormData from 'form-data';
import { logInfo, logError } from '../utils/logger.js';
import dotenv from 'dotenv';

dotenv.config();

const REGEX_SERVICE_URL     = process.env.REGEX_SERVICE_URL     || 'http://localhost:8001';
const REFERENCE_SERVICE_URL = process.env.REFERENCE_SERVICE_URL || 'http://localhost:8002';
const FIGURE_SERVICE_URL    = process.env.FIGURE_SERVICE_URL    || 'http://localhost:8003';
const GROBID_URL            = process.env.GROBID_URL            || 'https://tmkc-100bar-extraction-engine.hf.space';

const SERVICE_TIMEOUT = 600_000; // 10 min

/* ─── helper: build a fresh FormData with just the pdf ────────────────────── */
function pdfForm(fileBuffer) {
  const f = new FormData();
  // IMPORTANT: field name must be 'input' (GROBID spec) — NO other fields
  f.append('input', Buffer.from(fileBuffer), {
    filename:    'document.pdf',
    contentType: 'application/pdf',
  });
  return f;
}

/* ─── 1. Regex / Language Validation ─────────────────────────────────────── */
export async function processDocumentWithRegexValidation(fileBuffer) {
  try {
    logInfo('Calling regex-checker service');
    const form = new FormData();
    form.append('file', Buffer.from(fileBuffer), {
      filename: 'document.pdf', contentType: 'application/pdf',
    });
    const response = await axios.post(`${REGEX_SERVICE_URL}/analyze`, form, {
      headers: form.getHeaders(),
      timeout: SERVICE_TIMEOUT,
      maxContentLength: Infinity,
      maxBodyLength:    Infinity,
    });
    logInfo('Regex validation complete');
    return response.data;
  } catch (err) {
    logError('Error in regex validation service', err.message);
    return { issues: [], document_checks: {} };
  }
}

/* ─── 2. GROBID Reference Extraction ─────────────────────────────────────── */
export async function extractReferences(fileBuffer) {
  // Make a single shared copy so we don't re-use the same Buffer reference
  // for two concurrent requests (can corrupt multipart boundaries)
  const pdfCopy = Buffer.from(fileBuffer);

  let bibtexData      = '';
  let coordinatesData = JSON.stringify({ refBibs: [] });

  // ── 2a. processReferences (BibTeX) ────────────────────────────────────
  try {
    logInfo('Calling GROBID /api/processReferences');
    const f1 = pdfForm(pdfCopy);
    const r1 = await axios.post(
      `${GROBID_URL}/api/processReferences`,
      f1,
      {
        headers: { ...f1.getHeaders(), Accept: 'application/x-bibtex' },
        timeout:          SERVICE_TIMEOUT,
        maxContentLength: Infinity,
        maxBodyLength:    Infinity,
      },
    );
    bibtexData = r1.data || '';
    logInfo(`GROBID BibTeX OK — ${String(bibtexData).length} chars`);
  } catch (err) {
    logError(
      `GROBID processReferences failed [${err.response?.status}]`,
      err.response?.data ? String(err.response.data).slice(0, 300) : err.message,
    );
  }

  // ── 2b. referenceAnnotations (coordinates) — sequential after BibTeX ──
  try {
    logInfo('Calling GROBID /api/referenceAnnotations');
    const f2 = pdfForm(pdfCopy);
    const r2 = await axios.post(
      `${GROBID_URL}/api/referenceAnnotations`,
      f2,
      {
        headers: { ...f2.getHeaders(), Accept: 'application/json' },
        timeout:          SERVICE_TIMEOUT,
        maxContentLength: Infinity,
        maxBodyLength:    Infinity,
      },
    );
    coordinatesData = JSON.stringify(r2.data || { refBibs: [] });
    logInfo('GROBID referenceAnnotations OK');
  } catch (err) {
    logError(
      `GROBID referenceAnnotations failed [${err.response?.status}] (non-fatal)`,
      err.response?.data ? String(err.response.data).slice(0, 300) : err.message,
    );
    // non-fatal — references still analysed, just without PDF coordinates
  }

  return { bibtexData, coordinatesData };
}

/* ─── 3. Reference Error Analysis ────────────────────────────────────────── */
export async function analyzeReferenceErrors(bibtexData, coordinatesData, rawRefStrings = []) {
  if (!bibtexData || !String(bibtexData).trim()) {
    logInfo('No BibTeX data, skipping reference analysis');
    return [];
  }
  try {
    logInfo('Calling reference-analyser service');
    const response = await axios.post(
      `${REFERENCE_SERVICE_URL}/analyze`,
      {
        bibtex_string:   bibtexData,
        coordinate_str:  coordinatesData,
        raw_ref_strings: rawRefStrings,   // for the 5-check quality pipeline
      },
      { timeout: SERVICE_TIMEOUT }
    );
    logInfo('Reference analysis complete');
    return response.data;
  } catch (err) {
    logError('Error in reference analysis service', err.message);
    return [];
  }
}

/* ─── 4. Figure / Table Analysis ─────────────────────────────────────────── */
export async function analyzeFiguresTablesEquations(fileBuffer) {
  try {
    logInfo('Calling figure-analyser service');
    const form = new FormData();
    form.append('file', Buffer.from(fileBuffer), {
      filename: 'document.pdf', contentType: 'application/pdf',
    });
    const response = await axios.post(`${FIGURE_SERVICE_URL}/analyze`, form, {
      headers: form.getHeaders(),
      timeout: SERVICE_TIMEOUT,
      maxContentLength: Infinity,
      maxBodyLength:    Infinity,
    });
    logInfo('Figure analysis complete');
    const data = response.data;
    return Array.isArray(data) ? data : [];
  } catch (err) {
    logError('Error in figure analysis service', err.message);
    return [];
  }
}

/* ─── 5. Generate Annotated PDF ──────────────────────────────────────────── */
export async function generateAnnotatedPDF(fileBuffer, issues, llmIssues) {
  try {
    logInfo('Generating annotated PDF');
    const form = new FormData();
    form.append('file',       Buffer.from(fileBuffer), {
      filename: 'document.pdf', contentType: 'application/pdf',
    });
    form.append('issues',     JSON.stringify(issues));
    form.append('llm_issues', JSON.stringify(llmIssues));

    const response = await axios.post(`${REGEX_SERVICE_URL}/annotate`, form, {
      headers:          form.getHeaders(),
      timeout:          SERVICE_TIMEOUT,
      responseType:     'arraybuffer',
      maxContentLength: Infinity,
      maxBodyLength:    Infinity,
    });
    logInfo('Annotated PDF generated');
    return Buffer.from(response.data);
  } catch (err) {
    logError('Error generating annotated PDF', err.message);
    throw new Error('Failed to generate annotated PDF');
  }
}
