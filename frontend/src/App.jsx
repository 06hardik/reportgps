import React, { useState, useRef, useEffect, useCallback } from 'react';
import axios from 'axios';
import * as pdfjsLib from 'pdfjs-dist';
import './index.css';

// Configure PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();


/* ─── helpers ───────────────────────────────────────────────────────────────── */
const safe = (v, fallback = '—') => (v !== null && v !== undefined && v !== '') ? v : fallback;
const arr = (v) => Array.isArray(v) ? v : [];

const parseIssues = (results) => {
  const issues = [];
  let idCounter = 1;
  const addIssue = (cat, title, desc, ev, rec, page, extra = {}) => {
    issues.push({
      id: `${cat.substring(0,3).toUpperCase()}-${String(idCounter++).padStart(3, '0')}`,
      category: cat,
      title,
      description: desc,
      evidence: ev,
      recommendation: rec,
      page,
      ...extra,
    });
  }

  // ── Fast path: use AI-validated findings when the verifier is enabled ───────
  // FALSE_POSITIVE decisions are already discarded by the backend.
  // UNCERTAIN findings carry a badge but are still shown.
  const vf = results.validated_findings;
  if (Array.isArray(vf) && vf.length > 0) {
    vf.forEach(f => {
      addIssue(
        f.category || 'General',
        f.title || f.check_id,
        f.why_flagged || f.actual_issue || '',
        f.evidence || '',
        f.recommendation || '',
        f.page || null,
        {
          verified: true,
          decision: f.decision,
          confidence: f.confidence,
          finding_id: f.finding_id,
          actual_issue: f.actual_issue,
        }
      );
    });
    return issues;
  }

  // ── Fallback: raw parsing (verifier disabled or returned no findings) ───────

  // Parse Figures & Tables Checks
  if (results.figures_tables_checks) {
    const ft = results.figures_tables_checks;
    
    if (ft.figure_sequential_numbering && !ft.figure_sequential_numbering.passed) {
      addIssue('Figures', 'Figure Numbering', 'Figures are not numbered sequentially.', ft.figure_sequential_numbering.detail, 'Ensure all figures are numbered sequentially without skipping or repeating.', null);
    }
    if (ft.table_sequential_numbering && !ft.table_sequential_numbering.passed) {
      addIssue('Tables', 'Table Numbering', 'Tables are not numbered sequentially.', ft.table_sequential_numbering.detail, 'Ensure all tables are numbered sequentially without skipping or repeating.', null);
    }
    
    (ft.figure_chronological_order?.violations || []).forEach(v => {
      addIssue('Figures', 'Chronological Appearance', 'Figures are mentioned out of numerical order.', v.detail, 'Mention figures in the text in numerical order.', v.mentioned_on_page);
    });
    (ft.table_chronological_order?.violations || []).forEach(v => {
      addIssue('Tables', 'Chronological Appearance', 'Tables are mentioned out of numerical order.', v.detail, 'Mention tables in the text in numerical order.', v.mentioned_on_page);
    });
    
    (ft.table_caption_above?.violations || []).forEach(v => {
      addIssue('Tables', 'Caption Positioning', 'Table caption must be positioned above the table body.', v.detail, 'Move the caption above the table.', v.page);
    });
    (ft.figure_caption_below?.violations || []).forEach(v => {
      addIssue('Figures', 'Caption Positioning', 'Figure caption must be positioned below the image.', v.detail, 'Move the caption below the figure.', v.page);
    });
    (ft.figure_parts_mention?.violations || []).forEach(v => {
      addIssue('Figures', 'Figure Parts Mention', 'Caption sub-parts labeling is incomplete or does not start from (a).', v.detail, 'Ensure all sub-parts are listed consecutively.', v.page);
    });
  }

  // Parse Syntax & Grammar Checks
  if (results.syntax_grammar_checks) {
    const sg = results.syntax_grammar_checks;
    
    (sg.acronym_definition?.violations || []).forEach(v => {
      addIssue('Structure', 'Acronym Definition', 'Acronyms must be defined at their first occurrence.', v.detail, 'Provide the full definition in parentheses.', null);
    });
    (sg.en_dash_ranges?.violations || []).forEach(v => {
      addIssue('Formatting', 'En-dash for Ranges', 'Use an en-dash for number ranges.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null);
    });
    (sg.nonbreaking_space_units?.violations || []).forEach(v => {
      addIssue('Formatting', 'Non-breaking Space', 'Use a non-breaking space between numbers and units.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null);
    });
    (sg.no_space_percent_degree?.violations || []).forEach(v => {
      addIssue('Formatting', 'Percent/Degree Spacing', 'Do not use a space before % or ° symbols.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null);
    });
    (sg.double_spaces?.violations || []).forEach(v => {
      addIssue('Formatting', 'Double Spaces', 'Avoid multiple consecutive spaces.', v.detail, 'Remove extra spaces.', null);
    });
    (sg.punctuation_spacing?.violations || []).forEach(v => {
      addIssue('Formatting', 'Punctuation Spacing', 'Incorrect spacing around punctuation.', v.detail, 'Adjust spacing.', null);
    });
    (sg.quote_style_consistency?.violations || []).forEach(v => {
      addIssue('Formatting', 'Quote Style Consistency', 'Inconsistent quotation mark styles used.', v.detail, 'Use a consistent quote style.', null);
    });
    (sg.english_spelling_consistency?.violations || []).forEach(v => {
      addIssue('Formatting', 'Spelling Consistency', 'Mixed American and British spellings.', v.detail, 'Standardize to one spelling variant.', null);
    });
  }

  // Parse old Typography Checks (in case they are populated)
  if (results.typography) {
    const typo = results.typography;
    (typo.en_dash_violations || []).forEach(v => addIssue('Formatting', 'En-dash Violation', 'Hyphen used where en-dash is required.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null));
    (typo.number_unit_violations || []).forEach(v => addIssue('Formatting', 'Number-Unit Spacing', 'Missing space between number and unit.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null));
    (typo.percent_degree_violations || []).forEach(v => addIssue('Formatting', 'Percent/Degree Formatting', 'Incorrect spacing around % or °.', `Found: "${v.found}"`, `Change to: "${v.correct}"`, null));
  }
  
  // Manuscript checks
  if (results.manuscript) {
      if (!results.manuscript.keywords_section_present) {
          addIssue('Structure', 'Missing Keywords', 'No keywords section detected in the manuscript.', 'Abstract section analyzed', 'Add a keywords section after the abstract.', null);
      }
  }

  // Parse Reference Checks
  if (results.reference_checks) {
    const rc = results.reference_checks;

    // Check 1: Style Compliance
    (rc.style_compliance?.violations || []).forEach(v => {
      addIssue('References', 'Style Compliance', 'Reference style inconsistency detected.',
        v.context || v.detail, v.suggestion || 'Reformat to match the dominant citation style.', null);
    });

    // Check 2: Bidirectional Match
    (rc.bidirectional_match?.violations || []).forEach(v => {
      const title = v.type === 'missing_from_refs' ? 'Missing Reference Entry' : 'Uncited Reference';
      addIssue('References', title, v.detail,
        `Reference number: [${v.number}]`, v.suggestion, v.page || null);
    });

    // Check 3: Metadata Completeness
    (rc.metadata_completeness?.violations || []).forEach(v => {
      addIssue('References', 'Metadata Completeness', v.detail,
        v.context || '', v.suggestion || 'Add the missing metadata field.', null);
    });

    // Check 4: DOI / URL
    (rc.doi_url?.violations || []).forEach(v => {
      addIssue('References', 'DOI / URL Issue', v.detail,
        v.context || '', v.suggestion || 'Verify or add the DOI/URL for this reference.', null);
    });

    // Check 5: Sequential Ordering
    (rc.sequential_ordering?.violations || []).forEach(v => {
      addIssue('References', 'Sequential Ordering', v.detail,
        v.context || '', v.suggestion || 'Reorder the reference list sequentially.', null);
    });

    // Check 6: Field Consistency
    (rc.field_consistency?.violations || []).forEach(v => {
      addIssue('References', 'Field Consistency', v.detail,
        v.context || '', v.suggestion || 'Ensure consistent fields across all references of the same type.', null);
    });
  }

  return issues;
}

const CATEGORIES = [
  { id: 'References', icon: 'menu_book' },
  { id: 'Figures', icon: 'image' },
  { id: 'Tables', icon: 'table_chart' },
  { id: 'Equations', icon: 'functions' },
  { id: 'Structure', icon: 'account_tree' },
  { id: 'Language', icon: 'translate' },
  { id: 'Formatting', icon: 'format_align_left' }
];

/* ─── Shared Components ─────────────────────────────────────────────────────── */
function Navbar({ currentRoute, setCurrentRoute, onUploadClick }) {
  const navLinkClass = (route) => 
    `font-label-md text-label-md cursor-pointer transition-colors ${currentRoute === route ? 'text-secondary dark:text-secondary-fixed-dim font-bold border-b-2 border-secondary pb-1' : 'text-on-surface-variant dark:text-on-tertiary-container hover:text-primary'}`;

  return (
    <nav className="bg-surface dark:bg-surface-container-lowest text-primary dark:text-on-primary docked full-width top-0 border-b border-outline-variant dark:border-outline shadow-sm transition-colors cursor-pointer active:opacity-80 transition-opacity fixed top-0 w-full z-50 flex justify-between items-center px-lg h-16 max-w-container-max mx-auto">
      <div className="flex items-center gap-md cursor-pointer" onClick={() => setCurrentRoute('home')}>
        <img src="/logo.png" alt="ReportGPS Logo" className="h-16 md:h-20 w-auto object-contain scale-125 md:scale-[1.35] origin-left" />
      </div>
      <div className="hidden md:flex items-center gap-lg">
        <a className={navLinkClass('home')} onClick={() => setCurrentRoute('home')}>Product</a>
        <a className={navLinkClass('checks')} onClick={() => setCurrentRoute('checks')}>Checks</a>
      </div>
      <div className="flex items-center gap-sm">
        <button className="px-md py-sm bg-surface text-primary border border-outline-variant rounded-DEFAULT font-label-sm text-label-sm hover:bg-surface-variant transition-colors">Sign In</button>
        <button onClick={() => { setCurrentRoute('home'); if (onUploadClick) onUploadClick(); }} className="px-md py-sm bg-primary text-on-primary rounded-DEFAULT font-label-sm text-label-sm hover:opacity-90 transition-opacity">Request Demo</button>
      </div>
    </nav>
  );
}

function Footer() {
  return (
    <footer className="w-full py-lg px-lg flex flex-col md:flex-row justify-between items-center max-w-container-max mx-auto bg-surface-container-lowest dark:bg-surface-container-low text-on-surface-variant dark:text-on-surface border-t border-outline-variant mt-auto">
      <div className="flex items-center gap-sm mb-md md:mb-0">
        <img src="/logo.png" alt="ReportGPS Logo" className="h-12 md:h-16 w-auto object-contain scale-125 md:scale-150 origin-left grayscale opacity-70" />
        <span className="font-body-sm text-body-sm text-on-surface-variant ml-md md:ml-xl">© 2024 ReportGPS. Technical Validation Excellence.</span>
      </div>
      <div className="flex gap-lg">
        <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-all cursor-pointer hover:underline">Privacy Policy</a>
        <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-all cursor-pointer hover:underline">Terms of Service</a>
        <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-all cursor-pointer hover:underline">Security</a>
        <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-all cursor-pointer hover:underline">Contact</a>
      </div>
    </footer>
  );
}

/* ─── State Views ───────────────────────────────────────────────────────────── */

function LandingView({ onFileSelect, fileInputRef, dragActive, handleDrag, handleDrop }) {
  return (
    <main className="flex-grow pt-24 pb-xl px-lg max-w-container-max mx-auto w-full flex flex-col gap-xl">
      <section className="flex flex-col md:flex-row items-center gap-xl py-xl border-b border-surface-variant">
        <div className="w-full md:w-7/12 flex flex-col gap-lg items-start">
          <div className="inline-flex items-center gap-xs bg-surface-container-highest px-sm py-xs rounded-full border border-surface-variant text-label-sm font-label-sm text-on-surface-variant">
            <span className="material-symbols-outlined text-[14px]">bolt</span>
            New: Advanced Structural Analysis
          </div>
          <h1 className="font-headline-lg text-headline-lg text-on-surface max-w-xl">Navigate every detail of your research paper.</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant max-w-md">ReportGPS performs high-density validation of structural integrity, citations, and formatting, delivering precise, actionable insights for technical and academic publishing.</p>
          
          {/* Upload Zone */}
          <div 
              className={`mt-4 w-full bg-surface-container-lowest border-2 ${dragActive ? 'border-primary border-solid' : 'border-dashed border-outline-variant'} rounded-lg p-xl flex flex-col items-center justify-center gap-md text-center hover:bg-surface-container-low transition-colors cursor-pointer group relative`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current.click()}
          >
              <div className="w-16 h-16 rounded-full bg-surface-variant flex items-center justify-center mb-sm group-hover:bg-surface-container-highest transition-colors">
                  <span className="material-symbols-outlined text-[32px] text-on-surface-variant" style={{fontVariationSettings: "'FILL' 1"}}>cloud_upload</span>
              </div>
              <div>
                  <p className="font-headline-sm text-headline-sm text-primary">Drag & drop your PDF here</p>
                  <p className="font-body-sm text-body-sm text-on-surface-variant mt-xs">or click to browse files (Max 50MB)</p>
              </div>
              <button className="mt-sm px-lg py-sm bg-surface text-primary border border-outline-variant rounded-DEFAULT font-label-md text-label-md group-hover:border-primary transition-colors">Select File</button>
          </div>
        </div>

        <div className="w-full md:w-5/12 rounded-lg border border-surface-variant bg-surface-container-lowest p-sm shadow-sm ambient-shadow relative overflow-hidden h-[450px]">
          <div className="absolute inset-0 bg-surface-container-low flex">
            <div className="w-2/3 p-md border-r border-surface-variant bg-white flex flex-col gap-sm overflow-hidden pt-lg">
              <div className="h-4 w-3/4 bg-surface-variant rounded-sm mb-sm"></div>
              <div className="h-3 w-full bg-surface-variant rounded-sm"></div>
              <div className="h-3 w-5/6 bg-surface-variant rounded-sm"></div>
              <div className="h-3 w-full bg-surface-variant rounded-sm"></div>
              <div className="h-3 w-2/3 bg-surface-variant rounded-sm"></div>
              <div className="mt-md h-40 w-full bg-surface-variant rounded-sm border-l-4 border-secondary opacity-50 relative">
                <div className="absolute -left-4 top-2 bg-secondary text-on-primary text-[10px] px-1 rounded-sm">Check</div>
              </div>
            </div>
            <div className="w-1/3 p-sm bg-surface-container-lowest flex flex-col gap-sm pt-lg">
              <div className="font-label-sm text-label-sm text-on-surface-variant mb-xs">Issues Found (3)</div>
              <div className="border border-error-container bg-error-container/20 p-xs rounded-sm border-l-2 border-l-error">
                <div className="font-label-sm text-label-sm text-error">Citation Mismatch</div>
                <div className="font-mono-sm text-mono-sm text-on-surface-variant text-[10px] mt-xs">[24] missing from bibliography.</div>
              </div>
              <div className="border border-surface-variant bg-surface p-xs rounded-sm border-l-2 border-l-secondary">
                <div className="font-label-sm text-label-sm text-secondary">Figure Formatting</div>
                <div className="font-mono-sm text-mono-sm text-on-surface-variant text-[10px] mt-xs">Fig 3 caption style deviation.</div>
              </div>
            </div>
          </div>
        </div>
      </section>
      
      {/* Restored Bento Box section for What ReportGPS checks */}
      <section className="py-xl">
          <h2 className="font-headline-md text-headline-md text-on-surface mb-lg">What ReportGPS checks</h2>
          <div className="bento-grid">
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>menu_book</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">References & Citations</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Cross-validates in-text citations against the bibliography for precise mapping and formatting.</p>
              </div>
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>image</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">Figures & Tables</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Verifies caption styling, numbering continuity, and callout presence in the main text.</p>
              </div>
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>functions</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">Equations</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Analyzes mathematical blocks for alignment, numbering, and symbol definition consistency.</p>
              </div>
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>account_tree</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">Structure</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Checks heading hierarchy, section order, and required manuscript components.</p>
              </div>
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>translate</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">Language</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Identifies passive voice overuse, tense inconsistencies, and clarity issues in technical prose.</p>
              </div>
              <div className="bento-card flex flex-col gap-sm">
                  <span className="material-symbols-outlined text-secondary" style={{fontVariationSettings: "'FILL' 1"}}>format_align_left</span>
                  <h3 className="font-label-md text-label-md text-on-surface font-semibold">Formatting</h3>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">Enforces strict margin, font, and spacing rules based on target journal templates.</p>
              </div>
          </div>
      </section>

      <section className="py-xl border-t border-surface-variant">
        <h2 className="font-headline-md text-headline-md text-on-surface mb-lg text-center">From PDF to actionable report</h2>
        <div className="flex flex-col md:flex-row gap-lg justify-between relative">
          <div className="hidden md:block absolute top-1/2 left-0 w-full h-[1px] bg-surface-variant -z-10 transform -translate-y-1/2"></div>
          <div className="flex-1 flex flex-col items-center text-center gap-md bg-surface-container-lowest p-md border border-surface-variant rounded-lg relative z-10 ambient-shadow">
            <div className="w-8 h-8 rounded-full bg-surface-container-high border border-surface-variant flex items-center justify-center font-mono-sm text-mono-sm text-on-surface-variant">01</div>
            <h3 className="font-label-md text-label-md text-on-surface font-semibold">Upload</h3>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Submit your manuscript in PDF or DOCX format.</p>
          </div>
          <div className="flex-1 flex flex-col items-center text-center gap-md bg-surface-container-lowest p-md border border-surface-variant rounded-lg relative z-10 ambient-shadow">
            <div className="w-8 h-8 rounded-full bg-surface-container-high border border-surface-variant flex items-center justify-center font-mono-sm text-mono-sm text-on-surface-variant">02</div>
            <h3 className="font-label-md text-label-md text-on-surface font-semibold">Understand</h3>
            <p className="font-body-sm text-body-sm text-on-surface-variant">AI parses the document structure and extracts metadata.</p>
          </div>
          <div className="flex-1 flex flex-col items-center text-center gap-md bg-surface-container-lowest p-md border border-surface-variant rounded-lg relative z-10 ambient-shadow">
            <div className="w-8 h-8 rounded-full bg-secondary text-on-primary border border-secondary flex items-center justify-center font-mono-sm text-mono-sm">03</div>
            <h3 className="font-label-md text-label-md text-on-surface font-semibold">Validate</h3>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Engine applies hundreds of technical validation rules.</p>
          </div>
          <div className="flex-1 flex flex-col items-center text-center gap-md bg-surface-container-lowest p-md border border-surface-variant rounded-lg relative z-10 ambient-shadow">
            <div className="w-8 h-8 rounded-full bg-surface-container-high border border-surface-variant flex items-center justify-center font-mono-sm text-mono-sm text-on-surface-variant">04</div>
            <h3 className="font-label-md text-label-md text-on-surface font-semibold">Review</h3>
            <p className="font-body-sm text-body-sm text-on-surface-variant">Inspect findings in the high-density issue panel.</p>
          </div>
        </div>
      </section>
    </main>
  );
}

function ChecksView() {
  const checkCategories = [
    {
      title: "References & Citations",
      icon: "menu_book",
      checks: [
        { name: "Style Compliance", desc: "The reference strings strictly obey the formatting rules of the predicted/target style." },
        { name: "Bidirectional Match", desc: "Every in-text citation marker must exist in the reference list, and every reference in the list must be cited at least once." },
        { name: "Metadata Completeness", desc: "Ensures all required metadata fields are present and properly formatted." },
        { name: "DOI / URL Liveness", desc: "DOIs and URLs in the reference list are properly formatted, unbroken, and return a valid HTTP 200 response." },
        { name: "Sequential Ordering", desc: "For numbered styles, references appear in the bibliography in the exact order they are first mentioned in the text." },
        { name: "Consistency in references", desc: "References of the same type must follow the same number of fields without deviation." },
      ]
    },
    {
      title: "Figures & Tables",
      icon: "image",
      checks: [
        { name: "Figure Sequential Numbering", desc: "Figures numbered sequentially without skipping or repeating." },
        { name: "Table Sequential Numbering", desc: "Tables are numbered sequentially without skipping or repeating." },
        { name: "Chronological Appearance of Figures", desc: "Figures are mentioned in the text in numerical order." },
        { name: "Chronological Appearance of Tables", desc: "Tables are mentioned in the text in numerical order." },
        { name: "Caption Positioning of Table", desc: "Table captions are strictly located above the table." },
        { name: "Caption Positioning of Figure", desc: "Figure captions are strictly located below the figure." },
        { name: "Figure Parts Mention", desc: "Ensures that if a figure has parts (a, b, c), all parts are explicitly mentioned in the caption." },
        { name: "Placement After Mention", desc: "The actual Figure or Table block appears after (or on the same page as) its first textual mention." },
      ]
    },
    {
      title: "Equations",
      icon: "functions",
      checks: [
        { name: "Equation Sequential Numbering", desc: "Equations are numbered consecutively without skipping." },
        { name: "Equation Punctuation", desc: "Ensures equations end with appropriate punctuation if they conclude or pause a sentence." },
        { name: "In-text Reference Consistency", desc: "Verifies that all equation call-outs follow a single, consistent stylistic format throughout the document." },
      ]
    },
    {
      title: "Formatting & Typography",
      icon: "format_align_left",
      checks: [
        { name: "Delimiter Balance & Scaling", desc: "Checks for equal opening/closing brackets and flags unscaled delimiters around tall mathematical elements." },
        { name: "En-dash for Ranges", desc: "An en-dash (–) is used for number ranges (e.g., 10–20), rather than a standard hyphen (-)." },
        { name: "Non-breaking Space for Units", desc: "A non-breaking space is used between numbers and standard units (e.g., 10 kg)." },
        { name: "No Space for Percentages/Degrees", desc: "No space is used for percentages or degrees (e.g., 10%, 90°C)." },
        { name: "Double Spaces Check", desc: "No accidental double spaces exist between words or sentences." },
        { name: "Consistent Punctuation Spacing", desc: "Consistent spacing after commas and full stops." },
        { name: "Quote Style Consistency", desc: "Ensures consistent use of straight quotes vs. smart quotes." },
        { name: "English Spelling Consistency", desc: "Checks that the document does not mix American and British English spellings." },
      ]
    },
    {
      title: "Structure & Language",
      icon: "account_tree",
      checks: [
        { name: "Acronym Definition", desc: "Any acronym (3+ capital letters) is fully defined in parentheses at its very first occurrence." },
        { name: "Heading Casing Consistency", desc: "Verifies all section headings follow a consistent casing pattern (e.g., all Title Case)." },
        { name: "Keywords Section Presence", desc: "A 'Keywords' section exists immediately following the abstract." },
        { name: "Heading Sequential Numbering", desc: "Ensures section headings are numbered sequentially without skipping." },
        { name: "Publishing Statements", desc: "The manuscript includes necessary publishing statements (e.g., Conflict of Interest, Funding)." },
      ]
    }
  ];

  return (
    <main className="flex-grow pt-24 pb-xl px-lg max-w-container-max mx-auto w-full flex flex-col gap-xl">
      <header className="text-center mb-md">
        <h1 className="font-headline-lg text-headline-lg text-primary mb-xs">Comprehensive Validation Checks</h1>
        <p className="font-body-md text-body-md text-on-surface-variant max-w-2xl mx-auto">
          ReportGPS runs over 30 distinct technical validation checks on every manuscript to ensure pristine quality prior to submission or publication.
        </p>
      </header>

      <div className="flex flex-col gap-xl">
        {checkCategories.map((category, idx) => (
          <section key={idx} className="bg-surface-container-lowest border border-surface-variant rounded-lg p-lg ambient-shadow">
            <div className="flex items-center gap-sm mb-md border-b border-surface-variant pb-sm">
              <span className="material-symbols-outlined text-secondary text-2xl" style={{fontVariationSettings: "'FILL' 1"}}>{category.icon}</span>
              <h2 className="font-headline-md text-headline-md text-on-surface">{category.title}</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-md">
              {category.checks.map((check, cIdx) => (
                <div key={cIdx} className="bg-surface border border-surface-variant rounded-md p-md flex items-start gap-sm hover:border-outline transition-colors">
                  <span className="material-symbols-outlined text-primary text-sm mt-1" style={{fontVariationSettings: "'FILL' 1"}}>check_circle</span>
                  <div>
                    <h3 className="font-label-md text-label-md font-bold text-on-surface mb-1">{check.name}</h3>
                    <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">{check.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}



function LoadingView({ file }) {
  return (
    <main className="flex-grow pt-24 pb-xl px-md md:px-lg max-w-container-max mx-auto w-full flex flex-col items-center justify-center">
      <div className="w-full max-w-3xl flex flex-col gap-lg">
        <header className="text-center mb-md">
          <h1 className="font-headline-lg text-headline-lg text-primary mb-xs">Analyzing your research paper</h1>
          <p className="font-body-md text-body-md text-on-surface-variant">This typically takes 1-3 seconds.</p>
        </header>
        
        <div className="w-full bg-surface-container-lowest border border-outline-variant rounded-lg p-lg ambient-shadow mt-lg">
          <div className="flex items-center gap-md mb-lg pb-md border-b border-outline-variant">
            <span className="material-symbols-outlined text-secondary text-2xl" style={{fontVariationSettings: "'FILL' 1"}}>description</span>
            <div className="flex-grow">
              <h3 className="font-label-md text-label-md text-primary">{file.name}</h3>
              <p className="font-body-sm text-body-sm text-on-surface-variant mt-xs">{(file.size / 1024 / 1024).toFixed(2)} MB • Uploading & Processing...</p>
            </div>
            <div className="mt-xs flex items-center justify-center w-[18px] h-[18px]">
              <div className="w-3 h-3 bg-secondary rounded-full pulse-dot"></div>
            </div>
          </div>
          
          <div className="flex flex-col gap-sm">
            <div className="flex items-start gap-md">
              <div className="mt-xs">
                <span className="material-symbols-outlined text-primary text-[18px]" style={{fontVariationSettings: "'FILL' 1"}}>check_circle</span>
              </div>
              <div>
                <p className="font-label-md text-label-md text-primary">Upload received</p>
                <p className="font-body-sm text-body-sm text-on-surface-variant">File successfully securely transferred.</p>
              </div>
            </div>
            <div className="w-px h-6 bg-outline-variant ml-[9px] -mt-sm -mb-sm"></div>
            
            <div className="flex items-start gap-md">
              <div className="mt-xs flex items-center justify-center w-[18px] h-[18px]">
                <div className="w-2.5 h-2.5 bg-primary rounded-full pulse-dot"></div>
              </div>
              <div>
                <p className="font-label-md text-label-md text-primary font-bold">Running Extraction Pipeline</p>
                <p className="font-body-sm text-body-sm text-on-surface-variant">Executing PyMuPDF and Regex passes...</p>
              </div>
            </div>
            <div className="w-px h-6 bg-surface-variant ml-[9px] -mt-sm -mb-sm"></div>
            
            <div className="flex items-start gap-md opacity-50">
              <div className="mt-xs">
                <span className="material-symbols-outlined text-outline text-[18px]">radio_button_unchecked</span>
              </div>
              <div>
                <p className="font-label-md text-label-md text-on-surface-variant">Finalizing report</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

/* ─── PDF Viewer with Highlight Support ─────────────────────────────────────── */

/**
 * Extract the best short search string from an issue to find in the PDF text layer.
 */
function extractSearchText(issue) {
  if (!issue) return null;
  
  // 1. Look for explicit quoted text in evidence (e.g. Found: "X")
  let m = issue.evidence?.match(/(?:Found:|Change to:)?\s*["']([^"'\n]{2,80})["']/);
  if (m) return m[1];
  
  // 2. Look for specific identifiers (Figure N, Table N, [N]) in any field
  for (const src of [issue.evidence, issue.title, issue.description, issue.extra?.actual_issue]) {
    if (!src) continue;
    m = src.match(/((?:Fig(?:ure)?|Table)\s+\d+(?:\.\d+)?)/i) ||
        src.match(/\[(\d+(?:[,\s\-\u2013]\d+)*)\]/) ||
        src.match(/((?:Reference|Citation)\s+\[?\d+\]?)/i);
    if (m) return m[1] || m[0];
  }

  // 3. Fallback to evidence fragment if it looks like a text excerpt
  if (issue.evidence && issue.evidence.length > 8 && !issue.evidence.includes('is NOT sequential')) {
    const frag = issue.evidence.split(/[.;\n]/)[0].trim();
    if (frag.length >= 8 && /[a-zA-Z]/.test(frag)) return frag.substring(0, 60);
  }
  
  return null;
}

function PDFViewer({ fileUrl, activeIssue }) {
  const canvasRef        = useRef(null);
  const textLayerRef     = useRef(null);
  const highlightRef     = useRef(null);
  const containerRef     = useRef(null);
  const pdfDocRef        = useRef(null);

  const [currentPage, setCurrentPage]   = useState(1);
  const [totalPages,  setTotalPages]    = useState(0);
  const [scale,       setScale]         = useState(1.4);
  const [renderKey,   setRenderKey]     = useState(0); // force re-render
  const [highlightFound, setHighlightFound] = useState(false);

  // Load PDF document once when fileUrl changes
  useEffect(() => {
    if (!fileUrl) return;
    let cancelled = false;
    (async () => {
      try {
        const loadingTask = pdfjsLib.getDocument({ url: fileUrl });
        const pdf = await loadingTask.promise;
        if (cancelled) return;
        pdfDocRef.current = pdf;
        setTotalPages(pdf.numPages);
        setCurrentPage(1);
        setRenderKey(k => k + 1);
      } catch (e) {
        console.error('PDF load error:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [fileUrl]);

  // Navigate to issue page when activeIssue changes
  useEffect(() => {
    if (!activeIssue) return;
    const targetPage = activeIssue.page;
    if (targetPage && targetPage !== currentPage) {
      setCurrentPage(targetPage);
    } else {
      // Same page — just trigger a re-render to update highlights
      setRenderKey(k => k + 1);
    }
  }, [activeIssue]);

  // Render page on canvas whenever currentPage / scale / renderKey changes
  useEffect(() => {
    const pdf = pdfDocRef.current;
    if (!pdf || !canvasRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        const page    = await pdf.getPage(currentPage);
        const viewport = page.getViewport({ scale });

        const canvas  = canvasRef.current;
        const ctx     = canvas.getContext('2d');
        
        // High DPI rendering fix for crisp text
        const ratio = window.devicePixelRatio || 1;
        canvas.width  = viewport.width * ratio;
        canvas.height = viewport.height * ratio;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        ctx.scale(ratio, ratio);

        if (textLayerRef.current) {
          textLayerRef.current.style.width  = `${viewport.width}px`;
          textLayerRef.current.style.height = `${viewport.height}px`;
          textLayerRef.current.innerHTML    = '';
        }
        if (highlightRef.current) {
          highlightRef.current.style.width  = `${viewport.width}px`;
          highlightRef.current.style.height = `${viewport.height}px`;
          highlightRef.current.innerHTML    = '';
        }

        await page.render({ canvasContext: ctx, viewport }).promise;
        if (cancelled) return;

        // Build text layer
        const textContent = await page.getTextContent();
        if (cancelled) return;

        const spans = [];
        for (const item of textContent.items) {
          if (!item.str) continue;
          const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
          const x  = tx[4];
          const y  = tx[5] - item.height * scale;
          const w  = item.width  * scale;
          const h  = item.height * scale;
          spans.push({ str: item.str, x, y, w, h });

          if (textLayerRef.current) {
            const span = document.createElement('span');
            span.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;font-size:${h * 0.9}px;opacity:0;user-select:text;white-space:pre;`;
            span.textContent = item.str;
            textLayerRef.current.appendChild(span);
          }
        }

        // Highlight matching text
        const searchText = extractSearchText(activeIssue);
        let found = false;
        if (searchText && highlightRef.current) {
          const searchLower = searchText.toLowerCase().trim();
          // Try to find the search text by scanning adjacent spans
          const fullText  = spans.map(s => s.str).join(' ');
          const fullLower = fullText.toLowerCase();
          const matchIdx  = fullLower.indexOf(searchLower);

          if (matchIdx !== -1) {
            // Find which span(s) cover the match — highlight their bounding box
            const matchedSpans = [];
            let charCount = 0;
            for (const sp of spans) {
              const spanEnd = charCount + sp.str.length + 1; // +1 for space separator
              if (charCount < matchIdx + searchLower.length && spanEnd > matchIdx) {
                matchedSpans.push(sp);
              }
              charCount = spanEnd;
            }

            if (matchedSpans.length > 0) {
              for (const sp of matchedSpans) {
                const hlDiv = document.createElement('div');
                hlDiv.className = 'pdf-highlight-target';
                hlDiv.style.cssText = `position:absolute;left:${sp.x - 2}px;top:${sp.y - 2}px;width:${sp.w + 4}px;height:${sp.h + 4}px;background:rgba(255,220,0,0.45);border:2px solid rgba(200,150,0,0.7);border-radius:3px;pointer-events:none;`;
                highlightRef.current.appendChild(hlDiv);
              }
              found = true;

              // Scroll highlight into view after a brief delay
              setTimeout(() => {
                const firstHighlight = highlightRef.current.querySelector('.pdf-highlight-target');
                if (firstHighlight) {
                   firstHighlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
              }, 80);
            }
          }
        }
        setHighlightFound(found);
      } catch (e) {
        console.error('PDF render error:', e);
      }
    })();

    return () => { cancelled = true; };
  }, [currentPage, scale, renderKey, activeIssue]);

  const goToPrev = () => setCurrentPage(p => Math.max(1, p - 1));
  const goToNext = () => setCurrentPage(p => Math.min(totalPages, p + 1));
  const zoomIn   = () => setScale(s => Math.min(3.0, +(s + 0.2).toFixed(1)));
  const zoomOut  = () => setScale(s => Math.max(0.5, +(s - 0.2).toFixed(1)));

  const searchText = extractSearchText(activeIssue);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="h-12 bg-surface border-b border-outline-variant flex items-center justify-between px-md shrink-0">
        <div className="flex items-center gap-xs">
          <span className="font-label-md text-on-surface font-bold text-sm text-on-surface-variant">Original Document Viewer</span>
        </div>
        <div className="flex items-center gap-xs">
          {/* Page navigation */}
          <button onClick={goToPrev} disabled={currentPage <= 1}
            className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-low disabled:opacity-30 transition-colors">
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">chevron_left</span>
          </button>
          <span className="font-label-sm text-on-surface-variant text-xs min-w-[60px] text-center">
            {currentPage} / {totalPages || '…'}
          </span>
          <button onClick={goToNext} disabled={currentPage >= totalPages}
            className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-low disabled:opacity-30 transition-colors">
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">chevron_right</span>
          </button>
          <div className="w-px h-5 bg-outline-variant mx-xs" />
          {/* Zoom */}
          <button onClick={zoomOut} className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-low transition-colors">
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">zoom_out</span>
          </button>
          <span className="font-label-sm text-on-surface-variant text-xs w-10 text-center">{Math.round(scale*100)}%</span>
          <button onClick={zoomIn} className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-low transition-colors">
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">zoom_in</span>
          </button>
          {/* Active issue page badge */}
          {activeIssue?.page && (
            <div className="ml-xs font-label-sm text-secondary bg-secondary-container/20 px-2 py-0.5 rounded text-xs flex items-center gap-1">
              <span className="material-symbols-outlined text-[12px]">my_location</span>
              p.{activeIssue.page}
            </div>
          )}
          {activeIssue && searchText && !highlightFound && (
            <div className="ml-xs font-label-sm text-on-surface-variant bg-surface-container px-2 py-0.5 rounded text-xs opacity-60">
              (text not found on page)
            </div>
          )}
        </div>
      </div>

      {/* Highlight search bar */}
      {activeIssue && searchText && (
        <div className="px-md py-1 bg-amber-50 border-b border-amber-200 flex items-center gap-xs shrink-0">
          <span className="material-symbols-outlined text-[14px] text-amber-700">search</span>
          <span className="font-label-sm text-amber-800 text-xs truncate">
            Highlighting: <span className="font-mono font-bold">"{searchText.substring(0, 60)}{searchText.length > 60 ? '…' : ''}"</span>
          </span>
        </div>
      )}

      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 overflow-auto bg-surface-container-high flex justify-center py-md">
        {totalPages === 0 ? (
          <div className="flex items-center justify-center text-on-surface-variant">
            <span className="material-symbols-outlined animate-spin text-3xl mr-2">progress_activity</span>
            Loading PDF…
          </div>
        ) : (
          <div className="relative shadow-xl" style={{ display: 'inline-block' }}>
            <canvas ref={canvasRef} className="block" />
            {/* Invisible text selection layer */}
            <div ref={textLayerRef} className="absolute inset-0 pointer-events-none select-text" style={{ position: 'absolute', top: 0, left: 0 }} />
            {/* Yellow highlight overlay */}
            <div ref={highlightRef} className="absolute inset-0 pointer-events-none" style={{ position: 'absolute', top: 0, left: 0 }} />
          </div>
        )}
      </div>
    </div>
  );
}

function WorkspaceView({ file, fileUrl, results, onReset }) {

  const [activeCategory, setActiveCategory] = useState(CATEGORIES[1].id); // Default to Figures for demo
  const [activeIssue, setActiveIssue] = useState(null);
  
  const issues = parseIssues(results);

  // Group issues by category
  const issuesByCategory = CATEGORIES.reduce((acc, cat) => {
    acc[cat.id] = issues.filter(i => i.category === cat.id);
    return acc;
  }, {});

  const currentIssues = issuesByCategory[activeCategory] || [];
  const totalIssues = issues.length;

  return (
    <div className="bg-surface text-on-surface h-screen flex flex-col font-body-sm overflow-hidden">
      {/* Top Bar */}
      <header className="bg-surface border-b border-outline-variant h-16 flex items-center px-lg justify-between shrink-0 shadow-sm z-50">
        <div className="flex items-center gap-md">
          <img src="/logo.png" alt="ReportGPS Logo" className="h-14 md:h-16 w-auto object-contain scale-125 origin-left cursor-pointer" onClick={onReset} />
          <div className="h-6 w-px bg-outline-variant mx-sm"></div>
          <div className="flex items-center gap-sm">
            <span className="material-symbols-outlined text-on-surface-variant text-lg">description</span>
            <span className="font-label-md text-on-surface font-medium truncate max-w-[200px] md:max-w-md">{file.name}</span>
          </div>
        </div>
        <div className="flex items-center gap-lg">
          <div className="hidden md:flex items-center gap-xs bg-surface-container-low px-sm py-xs rounded-full border border-outline-variant">
            <span className="material-symbols-outlined text-green-600 text-sm" style={{fontVariationSettings: "'FILL' 1"}}>check_circle</span>
            <span className="font-label-sm text-on-surface-variant">Analysis complete</span>
          </div>
          <button className="bg-surface-variant text-on-surface-variant font-label-md px-md py-sm rounded-lg hover:bg-surface-container-highest transition-colors flex items-center gap-xs" onClick={onReset}>
            Upload Another
          </button>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: Categories */}
        <aside className="w-64 bg-surface-container-lowest border-r border-outline-variant flex flex-col h-full shrink-0">
          <div className="p-md border-b border-outline-variant">
            <h2 className="font-label-md text-on-surface-variant uppercase tracking-wider mb-sm">Analysis Categories</h2>
            <div className="flex items-center justify-between text-body-sm text-on-surface">
              <span>Total Issues</span>
              <span className="font-bold">{totalIssues}</span>
            </div>
          </div>
          <nav className="flex-1 overflow-y-auto py-sm">
            {CATEGORIES.map(cat => {
              const count = issuesByCategory[cat.id]?.length || 0;
              const isActive = activeCategory === cat.id;
              
              let badgeClass = "bg-surface-variant text-on-surface-variant";
              if (count > 0) badgeClass = "bg-error-container text-on-error-container";

              return (
                <div 
                  key={cat.id}
                  onClick={() => { setActiveCategory(cat.id); setActiveIssue(null); }}
                  className={`flex items-center justify-between px-md py-sm hover:bg-surface-container-low transition-colors group cursor-pointer ${isActive ? 'bg-secondary-container/10 border-l-2 border-secondary' : 'border-l-2 border-transparent'}`}
                >
                  <div className="flex items-center gap-sm">
                    <span className={`material-symbols-outlined text-lg ${isActive ? 'text-secondary' : 'text-on-surface-variant group-hover:text-primary'}`}>{cat.icon}</span>
                    <span className={`font-body-md font-medium ${isActive ? 'text-primary' : 'text-on-surface-variant group-hover:text-primary'}`}>{cat.id}</span>
                  </div>
                  <span className={`${badgeClass} font-label-sm px-xs py-0.5 rounded-full min-w-[20px] text-center`}>{count}</span>
                </div>
              );
            })}
          </nav>
        </aside>

        {/* Center Column: PDF Viewer */}
        <section className="flex-1 bg-surface-container flex flex-col h-full relative border-r border-outline-variant overflow-hidden">
          <PDFViewer fileUrl={fileUrl} activeIssue={activeIssue} />
        </section>

        {/* Right Column: Issue Inspector */}
        <aside className="w-80 bg-surface-container-lowest flex flex-col h-full shrink-0 shadow-[-4px_0_15px_-3px_rgba(0,0,0,0.02)]">
          <div className="h-12 border-b border-outline-variant flex items-center px-md bg-surface">
            <span className="material-symbols-outlined text-on-surface-variant mr-sm text-lg">policy</span>
            <h2 className="font-label-md text-on-surface font-bold">Issue Inspector</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-md space-y-md">
            {currentIssues.length === 0 ? (
                <div className="text-center p-xl text-on-surface-variant">
                    <span className="material-symbols-outlined text-4xl mb-2 opacity-50">check_circle</span>
                    <p className="font-body-sm">No issues found in {activeCategory}.</p>
                </div>
            ) : (
                currentIssues.map((issue) => {
                    const isActive = activeIssue?.id === issue.id;
                    
                    if (isActive) {
                        return (
                            <div key={issue.id} className="border border-outline-variant rounded-lg bg-surface shadow-sm overflow-hidden flex flex-col">
                                <div className="border-l-4 border-error p-md bg-surface-bright border-b border-outline-variant">
                                  <div className="flex items-center justify-between mb-xs">
                                      <div className="flex items-center gap-sm">
                                        <span className="bg-error-container text-on-error-container font-label-sm px-xs py-0.5 rounded uppercase tracking-wider text-[10px]">Error</span>
                                        <span className="font-mono-sm text-on-surface-variant">{issue.id}</span>
                                      </div>
                                      <button className="material-symbols-outlined text-on-surface-variant text-sm hover:text-primary" onClick={() => setActiveIssue(null)}>close</button>
                                  </div>
                                  <h3 className="font-headline-sm text-on-surface mt-1">{issue.title}</h3>
                                </div>
                                <div className="p-md flex flex-col gap-md">
                                  <div>
                                    <h4 className="font-label-sm text-on-surface-variant uppercase tracking-wider mb-xs flex items-center gap-xs">
                                      <span className="material-symbols-outlined text-[14px]">info</span> Why this was flagged
                                    </h4>
                                    <p className="font-body-sm text-on-surface leading-relaxed">{issue.description}</p>
                                  </div>
                                  {issue.evidence && (
                                      <div>
                                        <h4 className="font-label-sm text-on-surface-variant uppercase tracking-wider mb-xs flex items-center gap-xs">
                                          <span className="material-symbols-outlined text-[14px]">find_in_page</span> Evidence
                                        </h4>
                                        <div className="bg-surface-container-lowest border border-outline-variant rounded p-sm font-serif text-sm text-on-surface whitespace-pre-wrap">
                                            {issue.evidence}
                                        </div>
                                      </div>
                                  )}
                                  {issue.recommendation && (
                                      <div>
                                        <h4 className="font-label-sm text-on-surface-variant uppercase tracking-wider mb-xs flex items-center gap-xs">
                                          <span className="material-symbols-outlined text-[14px]">build</span> Recommendation
                                        </h4>
                                        <p className="font-body-sm text-on-surface leading-relaxed">{issue.recommendation}</p>
                                      </div>
                                  )}
                                </div>
                            </div>
                        );
                    } else {
                        return (
                            <div 
                                key={issue.id}
                                onClick={() => setActiveIssue(issue)}
                                className="border border-outline-variant rounded-lg p-sm flex items-center justify-between cursor-pointer hover:bg-surface-container-low transition-colors"
                            >
                                <div className="flex items-center gap-sm">
                                  <div className="w-1 h-8 bg-error rounded-full"></div>
                                  <div className="flex flex-col overflow-hidden max-w-[200px]">
                                    <span className="font-label-sm text-on-surface-variant block">{issue.id}</span>
                                    <span className="font-body-sm text-on-surface truncate" title={issue.title}>{issue.title}</span>
                                  </div>
                                </div>
                                <span className="material-symbols-outlined text-on-surface-variant shrink-0">chevron_right</span>
                            </div>
                        )
                    }
                })
            )}
          </div>
        </aside>
      </main>
    </div>
  );
}


/* ─── Main App ──────────────────────────────────────────────────────────────── */
export default function App() {
  const [currentRoute, setCurrentRoute] = useState('home');
  const [file, setFile]           = useState(null);
  const [fileUrl, setFileUrl]     = useState(null);
  const [loading, setLoading]     = useState(false);
  const [results, setResults]     = useState(null);
  const [error, setError]         = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Clean up object URL to prevent memory leaks
  useEffect(() => {
      return () => {
          if (fileUrl) URL.revokeObjectURL(fileUrl);
      };
  }, [fileUrl]);

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
    if (f.type !== 'application/pdf') { 
        setError('Please upload a PDF file.'); 
        setTimeout(() => setError(null), 3000); // Clear error after 3s
        return; 
    }
    
    // Create object URL for iframe PDF viewer
    if (fileUrl) URL.revokeObjectURL(fileUrl);
    setFileUrl(URL.createObjectURL(f));
    setFile(f);
    
    setError(null);
    setResults(null);
    
    // Automatically process file upon selection to match typical modern flows
    processFile(f);
  };

  const processFile = async (f) => {
    if (!f) return;
    setLoading(true);
    setError(null);
    const fd = new FormData();
    fd.append('file', f);
    try {
      const res = await axios.post('/api/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setResults(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Processing failed.');
      setFile(null); // Reset on error so they can try again
    } finally {
      setLoading(false);
    }
  };

  const reset = () => { 
      setResults(null); 
      setFile(null); 
      if (fileUrl) URL.revokeObjectURL(fileUrl);
      setFileUrl(null);
      setError(null); 
  };

  // If there are results, the app stays in the workspace mode regardless of routing, 
  // or we can allow navigating away? We'll just show Workspace if results exist.
  if (results && !loading) {
      return <WorkspaceView file={file} fileUrl={fileUrl} results={results} onReset={reset} />;
  }

  return (
    <div className="bg-background text-on-surface font-body-md antialiased min-h-screen flex flex-col">
        {/* Error Toast */}
        {error && (
            <div className="fixed top-20 left-1/2 transform -translate-x-1/2 z-[100] bg-error-container text-on-error-container px-lg py-sm rounded shadow-lg border border-error font-body-sm font-bold flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px]">error</span>
                {error}
            </div>
        )}

        {/* Hidden file input for LandingView click handlers */}
        <input
            ref={fileInputRef}
            id="pdf-file-input"
            type="file"
            className="hidden"
            accept="application/pdf"
            onChange={(e) => e.target.files?.[0] && selectFile(e.target.files[0])}
        />

        <Navbar currentRoute={currentRoute} setCurrentRoute={setCurrentRoute} onUploadClick={() => fileInputRef.current.click()} />

        {loading ? (
            <LoadingView file={file} />
        ) : (
            <>
                {currentRoute === 'home' && (
                    <LandingView 
                        onFileSelect={selectFile} 
                        fileInputRef={fileInputRef} 
                        dragActive={dragActive} 
                        handleDrag={handleDrag} 
                        handleDrop={handleDrop} 
                    />
                )}
                {currentRoute === 'checks' && <ChecksView />}
            </>
        )}

        <Footer />
    </div>
  );
}
