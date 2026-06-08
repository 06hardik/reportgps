import React, { createContext, useContext, useState, useCallback } from 'react';

const FileContext = createContext(null);

export const FileProvider = ({ children }) => {
  const [fileData, setFileData] = useState(null);   // ArrayBuffer of PDF
  const [fileName, setFileName] = useState(null);

  const storeFileData = useCallback((data, name) => {
    setFileData(data);
    if (name) setFileName(name);
  }, []);

  const clearFileData = useCallback(() => {
    setFileData(null);
    setFileName(null);
  }, []);

  return (
    <FileContext.Provider value={{ fileData, fileName, storeFileData, clearFileData }}>
      {children}
    </FileContext.Provider>
  );
};

export const useFileContext = () => {
  const ctx = useContext(FileContext);
  if (!ctx) throw new Error('useFileContext must be used within FileProvider');
  return ctx;
};

export default FileContext;
