import { configureStore } from '@reduxjs/toolkit';
import documentReducer from './documentSlice';
import issuesReducer from './issuesSlice';

export const store = configureStore({
  reducer: {
    document: documentReducer,
    issues: issuesReducer
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignore these paths as they may contain non-serializable data
        ignoredPaths: ['document.meta']
      }
    })
});

export default store;
