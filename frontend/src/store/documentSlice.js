import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { apiBaseUrl, timeout } from '../config/config';

export const uploadDocument = createAsyncThunk(
  'document/upload',
  async ({ file }, { rejectWithValue }) => {
    try {
      const formData = new FormData();
      formData.append('userId', 'anonymous');
      formData.append('document', file);

      const response = await axios.post(
        `${apiBaseUrl}/documents/upload`,
        formData,
        { timeout }
      );

      return {
        fileName:        file.name,
        fileSize:        file.size,
        uploadTime:      new Date().toISOString(),
        issues:          response.data.issues       || [],
        llmIssues:       response.data.llm_issues   || [],
        regexChecks:     response.data.regex_issues || {},
        annotatedPdfUrl: response.data.annotated_pdf || null,
        meta:            response.data.meta          || {},
      };
    } catch (error) {
      return rejectWithValue(
        error.response?.data?.error || error.message || 'Upload failed'
      );
    }
  }
);

const initialState = {
  fileName:        null,
  fileSize:        null,
  uploadTime:      null,
  isLoading:       false,
  error:           null,
  annotatedPdfUrl: null,
  meta:            {},
};

const documentSlice = createSlice({
  name: 'document',
  initialState,
  reducers: {
    resetDocument: () => initialState,
  },
  extraReducers: (builder) => {
    builder
      .addCase(uploadDocument.pending, (state) => {
        state.isLoading       = true;
        state.error           = null;
        state.annotatedPdfUrl = null;
      })
      .addCase(uploadDocument.fulfilled, (state, action) => {
        state.isLoading       = false;
        state.fileName        = action.payload.fileName;
        state.fileSize        = action.payload.fileSize;
        state.uploadTime      = action.payload.uploadTime;
        state.annotatedPdfUrl = action.payload.annotatedPdfUrl;
        state.meta            = action.payload.meta;
      })
      .addCase(uploadDocument.rejected, (state, action) => {
        state.isLoading = false;
        state.error     = action.payload || 'Failed to upload document';
      });
  },
});

export const { resetDocument } = documentSlice.actions;
export default documentSlice.reducer;
