import { useSelector } from 'react-redux';

export const selectIssues = (state) => state.issues.issues;
export const selectLlmIssues = (state) => state.issues.llmIssues;
export const selectRegexChecks = (state) => state.issues.regexChecks;
export const selectActiveIssueId = (state) => state.issues.activeIssueId;
export const selectFilter = (state) => state.issues.filter;
export const selectIsLoading = (state) => state.document.isLoading;
export const selectError = (state) => state.document.error;
export const selectFileName = (state) => state.document.fileName;
export const selectAnnotatedPdfUrl = (state) => state.document.annotatedPdfUrl;

export const selectActiveIssue = (state) => {
  const activeId = state.issues.activeIssueId;
  if (!activeId) return null;
  const found = state.issues.issues.find(
    (i) => (i.id || i.ID || String(i.offset)) === String(activeId)
  );
  if (found) return String(activeId);
  const llmFound = state.issues.llmIssues.find((i) => i.id === String(activeId));
  return llmFound ? String(activeId) : null;
};

export const selectFilteredIssues = (state) => {
  const { issues, llmIssues, filter } = state.issues;
  if (filter === 'all') return { issues, llmIssues };
  if (filter === 'language') return {
    issues: issues.filter(i => ['TYPOS', 'GRAMMAR', 'TYPOGRAPHY', 'MISC', 'Formatting'].includes(i.category)),
    llmIssues: []
  };
  if (filter === 'references') return {
    issues: issues.filter(i => i.category === 'ARTICLE' || i.ENTRYTYPE),
    llmIssues: []
  };
  if (filter === 'figures') return { issues: [], llmIssues };
  if (filter === 'structural') return { issues: [], llmIssues: [] };
  return { issues, llmIssues };
};
