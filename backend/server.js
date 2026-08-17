import express from 'express';
import cors from 'cors';
import multer from 'multer';
import axios from 'axios';
import FormData from 'form-data';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 5001;
const EXTRACTION_SERVICE_URL = process.env.EXTRACTION_SERVICE_URL || 'http://localhost:8004';

// Use memory storage
const upload = multer({ storage: multer.memoryStorage() });

app.use(cors());
app.use(express.json());

app.post('/api/upload', upload.single('file'), async (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
    }

    try {
        console.log(`Received file: ${req.file.originalname}, size: ${req.file.size} bytes`);
        console.log(`Forwarding to extraction pipeline at: ${EXTRACTION_SERVICE_URL}/extract`);

        const formData = new FormData();
        formData.append('file', req.file.buffer, {
            filename: req.file.originalname,
            contentType: req.file.mimetype,
        });

        const response = await axios.post(`${EXTRACTION_SERVICE_URL}/extract`, formData, {
            headers: {
                ...formData.getHeaders(),
            },
            // 0 = no timeout — the extraction pipeline manages its own timeouts internally
            timeout: 0,
            maxContentLength: Infinity,
            maxBodyLength: Infinity,
        });

        console.log('Extraction pipeline completed successfully.');
        res.json(response.data);
    } catch (error) {
        console.error('Error calling extraction pipeline:');
        if (error.response) {
            console.error(`Status: ${error.response.status}, Data:`, error.response.data);
            res.status(error.response.status).json({ error: error.response.data });
        } else {
            // Connection refused, network error, etc.
            const msg = error.message || 'Unknown error';
            console.error('Error:', msg);
            res.status(503).json({
                error: 'Extraction service error: ' + msg,
                hint: 'Is the Python extraction pipeline running on port 8004?'
            });
        }
    }
});

const server = app.listen(PORT, () => {
    console.log(`Backend server listening on port ${PORT}`);
});

// No socket timeout — let the Python service control the pace
server.setTimeout(0);
