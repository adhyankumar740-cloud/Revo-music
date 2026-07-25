const express = require('express');
const path = require('path');
const fs = require('fs');
const { getClient } = require('./modules/auth');
const { downloadVkMusic } = require('./scripts/download-vkmusic');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware Setup
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Serve downloaded mp3 files: GET /downloads/<filename>.mp3
app.use('/downloads', express.static(path.join(__dirname, 'downloads')));

// Global Scraper State
let isScrapingRunning = false;
let lastScrapingStatus = {
    status: 'idle',
    message: 'No extraction task has run yet.',
    timestamp: null
};

/**
 * 1. Health Check & Ping Endpoint (UptimeRobot / Cron Jobs ke liye)
 */
app.get('/', (req, res) => {
    res.json({
        service: 'Telegram VK Music Extractor',
        status: 'online',
        isScrapingRunning: isScrapingRunning,
        lastStatus: lastScrapingStatus
    });
});

/**
 * 2. Status Endpoint - Current Job ka Status dekhne ke liye
 */
app.get('/status', (req, res) => {
    res.json({
        isRunning: isScrapingRunning,
        details: lastScrapingStatus
    });
});

/**
 * 3. Extract VK Music Trigger Endpoint
 * Query Params:
 *  - limit: Number of messages to fetch (Default: 20)
 *  - bot: Target Bot username without @ (Default: vkmusic_bot)
 * Example: /extract-vk?limit=50&bot=vkmusic_bot
 */
app.get('/extract-vk', async (req, res) => {
    // Prevent overlapping extraction jobs
    if (isScrapingRunning) {
        return res.status(409).json({
            status: 'busy',
            message: 'An extraction job is already in progress. Please wait for it to finish.',
            lastStatus: lastScrapingStatus
        });
    }

    const limit = parseInt(req.query.limit, 10) || 20;
    const botUsername = req.query.bot ? req.query.bot.trim() : 'vkmusic_bot';
    const song = req.query.song ? req.query.song.trim() : '';

    // Lock job status
    isScrapingRunning = true;
    lastScrapingStatus = {
        status: 'running',
        targetBot: botUsername,
        limit: limit,
        query: song || undefined,
        startedAt: new Date().toISOString()
    };

    // Immediate response to browser/HTTP client
    res.json({
        status: 'initiated',
        message: song
            ? `VK Music search started for "${song}" on @${botUsername}. Check Render Dashboard Logs for live progress!`
            : `VK Music extraction started for @${botUsername} (Last ${limit} messages). Check Render Dashboard Logs for live progress!`,
        timestamp: new Date().toISOString()
    });

    // Background Async Runner
    (async () => {
        try {
            console.log(`\n========================================`);
            console.log(`🚀 Starting VK Music Job for @${botUsername}`);
            console.log(`========================================\n`);

            const client = await getClient();

            const result = await downloadVkMusic(client, {
                botUsername: botUsername,
                limit: limit,
                query: song
            });

            lastScrapingStatus = {
                status: result && result.success ? 'completed' : 'failed',
                targetBot: botUsername,
                limit: limit,
                query: song || undefined,
                fileName: result ? result.fileName : undefined,
                downloadUrl: result && result.fileName ? `/downloads/${result.fileName}` : undefined,
                error: result && !result.success ? result.error : undefined,
                completedAt: new Date().toISOString()
            };
            console.log(`\n✅ VK Music Extraction Job Completed Successfully.\n`);
        } catch (error) {
            console.error(`\n❌ VK Music Extraction Job Failed:`, error.message);
            lastScrapingStatus = {
                status: 'failed',
                targetBot: botUsername,
                error: error.message,
                failedAt: new Date().toISOString()
            };
        } finally {
            isScrapingRunning = false;
        }
    })();
});

// Start Express Server
app.listen(PORT, () => {
    console.log(`=================================================`);
    console.log(`🚀 Telegram Scraper Server running on port ${PORT}`);
    console.log(`🌐 Base URL: http://localhost:${PORT}/`);
    console.log(`🎵 Trigger URL: http://localhost:${PORT}/extract-vk?limit=20`);
    console.log(`=================================================`);
});

// Global Handlers (Render crashes se bachne ke liye)
process.on('unhandledRejection', (reason, promise) => {
    console.error('⚠️ Unhandled Rejection:', reason);
});

process.on('uncaughtException', (error) => {
    console.error('⚠️ Uncaught Exception:', error);
});
