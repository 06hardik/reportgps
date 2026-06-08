import React, {
  useEffect, useRef, useMemo, useCallback,
  forwardRef, useImperativeHandle
} from 'react';
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist';
import PropTypes from 'prop-types';
import { useSelector } from 'react-redux';
import { selectActiveIssue } from '../../store/selectors/issueSelectors';
import './PDFViewer.css';

GlobalWorkerOptions.workerSrc =
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs';

const CATEGORY_COLORS = {
  TYPOS:        'rgba(239, 68, 68, 0.25)',
  GRAMMAR:      'rgba(16, 185, 129, 0.25)',
  TYPOGRAPHY:   'rgba(99, 102, 241, 0.25)',
  MISC:         'rgba(245, 158, 11, 0.25)',
  Formatting:   'rgba(245, 158, 11, 0.25)',
  ARTICLE:      'rgba(14, 165, 233, 0.25)',
  FIGURE:       'rgba(139, 92, 246, 0.25)',
  TABLE:        'rgba(20, 184, 166, 0.25)',
  EQUATION:     'rgba(251, 191, 36, 0.25)',
  DEFAULT:      'rgba(107, 114, 128, 0.25)',
};

const PDFViewer = forwardRef(({
  fileData, issues, llmIssues, onAnnotationClick, activeIssue: propActiveIssue
}, ref) => {
  const viewerRef = useRef(null);
  const overlaysRef = useRef({});
  const renderedRef = useRef(false);
  const renderingRef = useRef(false);
  const mountedRef = useRef(false);
  const scrollPosRef = useRef(0);
  const lastActiveRef = useRef(null);

  const storeActiveIssue = useSelector(selectActiveIssue);
  const activeIssue = propActiveIssue || storeActiveIssue;

  const parsedLlmIssues = useMemo(() => {
    if (!llmIssues) return [];
    if (Array.isArray(llmIssues)) return llmIssues;
    if (llmIssues?.rawData && Array.isArray(llmIssues.rawData)) return llmIssues.rawData;
    return [];
  }, [llmIssues]);

  useImperativeHandle(ref, () => ({
    scrollToIssue: (issueId) => {
      const overlay = overlaysRef.current[String(issueId)];
      if (!viewerRef.current || !overlay) return;
      const vRect = viewerRef.current.getBoundingClientRect();
      const oRect = overlay.getBoundingClientRect();
      viewerRef.current.scrollTo({
        top: viewerRef.current.scrollTop + (oRect.top - vRect.top) - vRect.height / 2 + oRect.height / 2,
        behavior: 'smooth'
      });
      updateActiveHighlight(String(issueId));
    }
  }));

  const updateActiveHighlight = useCallback((activeId) => {
    if (!overlaysRef.current) return;
    if (lastActiveRef.current === activeId) return;
    lastActiveRef.current = activeId;
    Object.entries(overlaysRef.current).forEach(([id, el]) => {
      el.classList.toggle('active-overlay', id === String(activeId));
    });
  }, []);

  const getClickHandler = useCallback((issueId) => () => {
    onAnnotationClick?.(String(issueId));
  }, [onAnnotationClick]);

  const createOverlay = useCallback((issue, viewport, pageWrapper) => {
    const issueId = String(issue.id || issue.ID || issue.offset || Math.random());
    if (!issue.coordinates || issue.coordinates.length !== 4) return;
    const [x1, y1, x2, y2] = issue.coordinates;
    if (x2 <= x1 || y2 <= y1) return;

    const overlay = document.createElement('div');
    overlay.className = 'pdf-overlay';
    overlay.dataset.issueId = issueId;
    overlay.style.left   = `${x1 * viewport.scale}px`;
    overlay.style.top    = `${y1 * viewport.scale}px`;
    overlay.style.width  = `${(x2 - x1) * viewport.scale}px`;
    overlay.style.height = `${(y2 - y1) * viewport.scale}px`;
    overlay.style.backgroundColor = CATEGORY_COLORS[issue.category] || CATEGORY_COLORS.DEFAULT;
    overlay.style.border = `1px solid ${(CATEGORY_COLORS[issue.category] || CATEGORY_COLORS.DEFAULT).replace('0.25', '0.6')}`;

    // Tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'pdf-tooltip';
    if (issue.ENTRYTYPE) {
      tooltip.innerHTML = `<strong>${issue.ENTRYTYPE}</strong>${issue.author ? `Author: ${issue.author}` : ''}${issue.title ? `<br>Title: ${issue.title}` : ''}`;
    } else {
      tooltip.innerHTML = `<strong>${issue.category || 'Issue'}</strong>${issue.message || ''}${issue.suggestions?.length ? `<em>Suggestion: ${issue.suggestions.slice(0,2).join(', ')}</em>` : ''}`;
    }

    overlay.addEventListener('mouseover', (e) => {
      tooltip.style.display = 'block';
      tooltip.style.left = `${e.clientX + 12}px`;
      tooltip.style.top  = `${e.clientY + 12}px`;
    });
    overlay.addEventListener('mousemove', (e) => {
      tooltip.style.left = `${e.clientX + 12}px`;
      tooltip.style.top  = `${e.clientY + 12}px`;
    });
    overlay.addEventListener('mouseout', () => { tooltip.style.display = 'none'; });
    overlay.addEventListener('click', getClickHandler(issueId));

    document.body.appendChild(tooltip);
    pageWrapper.appendChild(overlay);
    overlaysRef.current[issueId] = overlay;

    // Cleanup tooltip on unmount via a WeakRef-style approach
    overlay._tooltip = tooltip;
  }, [getClickHandler]);

  const createLlmOverlay = useCallback((issue, viewport, pageWrapper) => {
    if (!issue?.caption_coordinate) return;
    const { x1: cx1, y1: cy1, x2: cx2, y2: cy2 } = issue.caption_coordinate;
    if (!cx1 && !cy1 && !cx2 && !cy2) return;

    const itemId = String(issue.id || `llm-${issue.page_number}-${Math.random().toString(36).slice(2,6)}`);
    if (overlaysRef.current[itemId]) return; // deduplicate

    const overlay = document.createElement('div');
    overlay.className = 'pdf-overlay llm-overlay';
    overlay.dataset.issueId = itemId;
    overlay.style.left   = `${cx1 * viewport.scale}px`;
    overlay.style.top    = `${cy1 * viewport.scale}px`;
    overlay.style.width  = `${(cx2 - cx1) * viewport.scale}px`;
    overlay.style.height = `${(cy2 - cy1) * viewport.scale}px`;
    const figType = (issue.fig_type || 'FIGURE').toUpperCase();
    overlay.style.backgroundColor = CATEGORY_COLORS[figType] || CATEGORY_COLORS.FIGURE;
    overlay.style.border = '1.5px dashed rgba(139,92,246,0.7)';

    const tooltip = document.createElement('div');
    tooltip.className = 'pdf-tooltip';
    tooltip.innerHTML = `<strong>${issue.fig_type || 'Figure/Table'}</strong>${issue.description || ''}${issue.caption_location ? `<br><em>Caption: ${issue.caption_location}</em>` : ''}`;

    overlay.addEventListener('mouseover', (e) => {
      tooltip.style.display = 'block';
      tooltip.style.left = `${e.clientX + 12}px`;
      tooltip.style.top  = `${e.clientY + 12}px`;
    });
    overlay.addEventListener('mousemove', (e) => {
      tooltip.style.left = `${e.clientX + 12}px`;
      tooltip.style.top  = `${e.clientY + 12}px`;
    });
    overlay.addEventListener('mouseout', () => { tooltip.style.display = 'none'; });
    overlay.addEventListener('click', () => onAnnotationClick?.(itemId));

    document.body.appendChild(tooltip);
    pageWrapper.appendChild(overlay);
    overlaysRef.current[itemId] = overlay;
    overlay._tooltip = tooltip;
  }, [onAnnotationClick]);

  const renderPDF = useCallback(async () => {
    if (renderingRef.current || renderedRef.current || !mountedRef.current) return;
    renderingRef.current = true;

    try {
      if (!viewerRef.current) return;
      // Clear previous render and remove any lingering tooltips
      Object.values(overlaysRef.current).forEach(el => el._tooltip?.remove());
      viewerRef.current.innerHTML = '';
      overlaysRef.current = {};

      if (!(fileData instanceof ArrayBuffer || fileData instanceof Uint8Array)) {
        throw new Error('Invalid file data');
      }

      const pdfData = fileData instanceof ArrayBuffer ? fileData.slice(0) : new Uint8Array(fileData);
      const pdf = await getDocument({ data: pdfData }).promise;

      for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
        if (!mountedRef.current || !viewerRef.current) break;

        const page = await pdf.getPage(pageNum);
        const viewport = page.getViewport({ scale: 1.623 });

        const pageWrapper = document.createElement('div');
        pageWrapper.className = 'pdf-page-wrapper';
        pageWrapper.style.width  = `${viewport.width}px`;
        pageWrapper.style.height = `${viewport.height}px`;
        pageWrapper.style.position = 'relative';
        pageWrapper.style.marginBottom = '12px';
        viewerRef.current.appendChild(pageWrapper);

        // Canvas
        const canvas = document.createElement('canvas');
        canvas.className = 'pdf-page';
        canvas.width  = viewport.width;
        canvas.height = viewport.height;
        pageWrapper.appendChild(canvas);
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;

        // Text layer
        const textLayerDiv = document.createElement('div');
        textLayerDiv.className = 'pdf-text-layer';
        textLayerDiv.style.position = 'absolute';
        textLayerDiv.style.top  = '0';
        textLayerDiv.style.left = '0';
        textLayerDiv.style.width  = `${viewport.width}px`;
        textLayerDiv.style.height = `${viewport.height}px`;
        pageWrapper.appendChild(textLayerDiv);
        const textContent = await page.getTextContent();
        const tl = new TextLayer({ container: textLayerDiv, viewport, textContentSource: textContent });
        await tl.render();

        // Page badge
        const badge = document.createElement('div');
        badge.className = 'page-number-badge';
        badge.textContent = `Page ${pageNum}`;
        pageWrapper.appendChild(badge);

        // Regular issue overlays
        const pageIssues = issues.filter(i => Number(i.page) === pageNum);
        pageIssues.forEach(i => createOverlay(i, viewport, pageWrapper));

        // LLM (figure/table) overlays
        const pageLlm = parsedLlmIssues.filter(i => {
          if (!i?.caption_coordinate) return false;
          return i.page_number === pageNum || i.page_number === pageNum - 1;
        });
        pageLlm.forEach(i => {
          const adjusted = i.page_number === pageNum
            ? i
            : { ...i, page_number: pageNum, _originalPage: i.page_number };
          createLlmOverlay(adjusted, viewport, pageWrapper);
        });
      }

      renderedRef.current = true;
      if (activeIssue) updateActiveHighlight(String(activeIssue));
    } catch (err) {
      console.error('PDF render error:', err);
    } finally {
      renderingRef.current = false;
    }
  }, [fileData, issues, parsedLlmIssues, createOverlay, createLlmOverlay, updateActiveHighlight, activeIssue]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      renderedRef.current = false;
      Object.values(overlaysRef.current).forEach(el => el._tooltip?.remove());
      if (viewerRef.current) viewerRef.current.innerHTML = '';
      overlaysRef.current = {};
    };
  }, []);

  useEffect(() => {
    if (!renderedRef.current && fileData && issues.length >= 0) {
      setTimeout(renderPDF, 0);
    }
  }, [fileData, issues, renderPDF]);

  useEffect(() => {
    if (!renderedRef.current || !activeIssue) return;
    updateActiveHighlight(String(activeIssue));
    const overlay = overlaysRef.current[String(activeIssue)];
    if (viewerRef.current && overlay) {
      const vRect = viewerRef.current.getBoundingClientRect();
      const oRect = overlay.getBoundingClientRect();
      viewerRef.current.scrollTo({
        top: viewerRef.current.scrollTop + (oRect.top - vRect.top) - vRect.height / 2 + oRect.height / 2,
        behavior: 'smooth'
      });
    }
  }, [activeIssue, updateActiveHighlight]);

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '16px', minHeight: '100%', boxSizing: 'border-box' }}>
      <div ref={viewerRef} className="pdf-viewer" />
    </div>
  );

});

PDFViewer.displayName = 'PDFViewer';
PDFViewer.propTypes = {
  fileData: PropTypes.oneOfType([PropTypes.instanceOf(ArrayBuffer), PropTypes.instanceOf(Uint8Array)]),
  issues: PropTypes.array.isRequired,
  llmIssues: PropTypes.array,
  activeIssue: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onAnnotationClick: PropTypes.func,
};

export default PDFViewer;
