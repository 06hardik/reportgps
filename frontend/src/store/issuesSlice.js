import { createSlice } from '@reduxjs/toolkit';
import { uploadDocument } from './documentSlice';

const issuesSlice = createSlice({
  name: 'issues',
  initialState: {
    issues: [],
    llmIssues: [],
    regexChecks: {},
    activeIssueId: null,
    filter: 'all', // 'all' | 'language' | 'references' | 'figures' | 'structural'
  },
  reducers: {
    setActiveIssue: (state, action) => {
      state.activeIssueId = action.payload;
    },
    clearActiveIssue: (state) => {
      state.activeIssueId = null;
    },
    setFilter: (state, action) => {
      state.filter = action.payload;
    },
    resetIssues: (state) => {
      state.issues = [];
      state.llmIssues = [];
      state.regexChecks = {};
      state.activeIssueId = null;
      state.filter = 'all';
    }
  },
  extraReducers: (builder) => {
    builder.addCase(uploadDocument.fulfilled, (state, action) => {
      state.issues = action.payload.issues || [];
      state.llmIssues = action.payload.llmIssues || [];
      state.regexChecks = action.payload.regexChecks || {};
      state.activeIssueId = null;
    });
    builder.addCase(uploadDocument.pending, (state) => {
      state.issues = [];
      state.llmIssues = [];
      state.regexChecks = {};
      state.activeIssueId = null;
    });
  }
});

export const { setActiveIssue, clearActiveIssue, setFilter, resetIssues } = issuesSlice.actions;
export default issuesSlice.reducer;
