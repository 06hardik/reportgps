/**
 * test-grobid.mjs
 * Run from d:\reportgps\backend:
 *   node test-grobid.mjs
 *
 * Tests BOTH GROBID endpoints against the real HF Space, using the first
 * PDF found in ./uploads (or a tiny synthetic PDF if none found).
 */
import axios   from 'axios';
import FormData from 'form-data';
import fs      from 'fs';
import path    from 'path';
import dotenv  from 'dotenv';

dotenv.config();

const GROBID_URL = process.env.GROBID_URL || 'https://tmkc-100bar-extraction-engine.hf.space';
console.log('GROBID_URL =', GROBID_URL);

/* ── Pick a test PDF ─────────────────────────────────────────────────────── */
function getTestPdf() {
  // Priority: uploads folder → test_sample.pdf
  const uploadsDir = './uploads';
  if (fs.existsSync(uploadsDir)) {
    const pdfs = fs.readdirSync(uploadsDir).filter(f => f.endsWith('.pdf'));
    if (pdfs.length > 0) {
      const fullPath = path.join(uploadsDir, pdfs[0]);
      console.log(`Using uploaded PDF: ${fullPath} (${fs.statSync(fullPath).size} bytes)\n`);
      return fs.readFileSync(fullPath);
    }
  }
  if (fs.existsSync('./test_sample.pdf')) {
    console.log('Using test_sample.pdf\n');
    return fs.readFileSync('./test_sample.pdf');
  }
  throw new Error('No test PDF found. Place a PDF in ./uploads or ./test_sample.pdf');
}

function buildForm(pdfBuffer) {
  const f = new FormData();
  f.append('input', Buffer.from(pdfBuffer), {
    filename:    'test.pdf',
    contentType: 'application/pdf',
  });
  return f;
}

/* ── Test runner ─────────────────────────────────────────────────────────── */
async function test(label, url, acceptHeader, pdfBuffer) {
  console.log(`\n${'─'.repeat(60)}`);
  console.log(`TEST: ${label}`);
  console.log(`URL : ${url}`);
  console.log(`Accept: ${acceptHeader}`);
  console.log(`${'─'.repeat(60)}`);

  const start = Date.now();
  try {
    const form = buildForm(pdfBuffer);
    const res  = await axios.post(url, form, {
      headers:          { ...form.getHeaders(), Accept: acceptHeader },
      timeout:          180_000,           // 3 min
      maxContentLength: Infinity,
      maxBodyLength:    Infinity,
      validateStatus:   () => true,        // don't throw on 4xx/5xx
    });

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    const body    = typeof res.data === 'string' ? res.data : JSON.stringify(res.data);

    if (res.status >= 200 && res.status < 300) {
      console.log(`✅  Status : ${res.status}  (${elapsed}s)`);
      console.log(`    Body   : ${body.slice(0, 400)}`);
      return true;
    } else {
      console.log(`❌  Status : ${res.status}  (${elapsed}s)`);
      console.log(`    Error  : ${body.slice(0, 600)}`);
      return false;
    }
  } catch (err) {
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`❌  NETWORK ERROR (${elapsed}s): ${err.message}`);
    return false;
  }
}

/* ── Main ────────────────────────────────────────────────────────────────── */
(async () => {
  const pdfBuffer = getTestPdf();

  // Sequential — same order as documentProcessor.js
  const r1 = await test(
    'processReferences → BibTeX',
    `${GROBID_URL}/api/processReferences`,
    'application/x-bibtex',
    pdfBuffer,
  );

  const r2 = await test(
    'referenceAnnotations → JSON',
    `${GROBID_URL}/api/referenceAnnotations`,
    'application/json',
    pdfBuffer,
  );

  console.log(`\n${'═'.repeat(60)}`);
  console.log(`SUMMARY`);
  console.log(`  processReferences     : ${r1 ? '✅ PASS' : '❌ FAIL'}`);
  console.log(`  referenceAnnotations  : ${r2 ? '✅ PASS' : '❌ FAIL'}`);
  console.log(`${'═'.repeat(60)}`);
  process.exit(r1 && r2 ? 0 : 1);
})();
