/**
 * issueProcessor.js
 * Merges all issue sources into a unified issues array.
 *
 * RULES:
 *  - A reference entry is only included if it has ACTUAL errors.
 *    Clean references (no asterikError, no consistencyError, no quality_issues)
 *    are silently dropped — they are not shown to the researcher.
 *  - quality_issues from the 5-check pipeline are EMBEDDED inside their parent
 *    reference card (NOT pushed as separate top-level issues).
 *    This prevents one reference from generating 3+ separate cards.
 */
export function mergeIssues(data) {
  const baseIssues      = data.issues || {};
  const issuesList      = [...(baseIssues.issues || [])];
  const referenceIssues = data.referenceIssues || [];

  referenceIssues.forEach((refIssue) => {
    // ── Determine whether this entry has any real errors ──────────────
    const hasAsterik      = Array.isArray(refIssue.asterikError)     && refIssue.asterikError.length > 0;
    const hasConsistency  = Array.isArray(refIssue.consistencyError) && refIssue.consistencyError.length > 0;
    const hasWarning      = !!refIssue.warningMessage;
    const hasQuality      = Array.isArray(refIssue.quality_issues)   && refIssue.quality_issues.length > 0;
    const isStandaloneQI  = !!(refIssue.check && refIssue.message);   // top-level quality issue

    const hasIssues = hasAsterik || hasConsistency || hasWarning || hasQuality || isStandaloneQI;

    // Skip clean references — nothing to show the researcher
    if (!hasIssues) return;

    // ── NEW format: coordinates already converted (fitz) ──────────────
    if (Array.isArray(refIssue.coordinates) && refIssue.coordinates.length === 4) {
      issuesList.push({
        ...refIssue,
        category:      refIssue.category || 'ARTICLE',
        // Keep quality_issues EMBEDDED in the card — do NOT push them separately
        quality_issues: refIssue.quality_issues || [],
      });
      return;
    }

    // ── OLD format: pos[] array from GROBID (raw, no Y conversion) ───
    if (Array.isArray(refIssue.pos) && refIssue.pos.length > 0) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      let pageNumber = null;
      refIssue.pos.forEach(({ p, x, y, w, h }) => {
        pageNumber = p;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + w);
        maxY = Math.max(maxY, y + h);
      });
      issuesList.push({
        ...refIssue,
        pos:           undefined,
        page:          pageNumber,
        coordinates:   [minX, minY, maxX, maxY],
        category:      refIssue.category || 'ARTICLE',
        quality_issues: refIssue.quality_issues || [],
      });
      return;
    }

    // ── No coordinates — include without location info ─────────────────
    issuesList.push({
      ...refIssue,
      coordinates:   [],
      category:      refIssue.category || 'ARTICLE',
      quality_issues: refIssue.quality_issues || [],
    });
  });

  return {
    issues: {
      ...baseIssues,
      issues: issuesList,
    },
  };
}

/**
 * Normalize an issue ID for consistent cross-source identification.
 */
export function normalizeIssueId(issue, index) {
  return issue.id || issue.ID || issue.offset?.toString() || `issue-${index}`;
}
