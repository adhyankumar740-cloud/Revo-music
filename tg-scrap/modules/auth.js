const { TelegramClient } = require("telegram");
const { StringSession } = require("telegram/sessions");

// Environment Variables se Credentials fetch kar rahe hain
const apiId = parseInt(process.env.TELEGRAM_API_ID, 10);
const apiHash = process.env.TELEGRAM_API_HASH;
const sessionString = process.env.TELEGRAM_SESSION || "";

const stringSession = new StringSession(sessionString);

let clientInstance = null;

/**
 * Telegram Client Instance get/initialize karne ka function
 */
async function getClient() {
    // Agar client pehle se connected hai toh wahi instance return karo
    if (clientInstance && clientInstance.connected) {
        return clientInstance;
    }

    if (!apiId || !apiHash) {
        throw new Error("Render Environment Variables mein TELEGRAM_API_ID ya TELEGRAM_API_HASH missing hai!");
    }

    console.log("🔐 Telegram Client Initializing...");
    
    clientInstance = new TelegramClient(stringSession, apiId, apiHash, {
        connectionRetries: 5,
    });

    await clientInstance.connect();
    console.log("✅ Telegram Client Connected Successfully!");

    return clientInstance;
}

// Sahi Named Export
module.exports = {
    getClient
};
