const { Api } = require("telegram");
const { NewMessage } = require("telegram/events");
const fs = require("fs");
const path = require("path");

const DOWNLOAD_DIR = path.join(__dirname, "..", "downloads");
if (!fs.existsSync(DOWNLOAD_DIR)) {
    fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });
}

// Wrapper matching what server.js calls: downloadVkMusic(client, { botUsername, limit, query })
async function downloadVkMusic(client, options = {}) {
    const songName = options.query || options.song || "";
    const bot = options.botUsername || "vkmusic_bot";

    if (!songName) {
        throw new Error("Koi 'song' query param nahi diya gaya. Example: /extract-vk?song=tera+ban+jaunga");
    }

    return fetchVKMusic(client, songName, bot);
}

// Main scraping function
async function fetchVKMusic(client, songName, botUsernameRaw = "vkmusic_bot") {
    const botUsername = "@" + botUsernameRaw.replace(/^@/, "");

    try {
        console.log(`🎵 ${botUsername} par "${songName}" search kiya ja raha hai...`);
        
        // 1. Bot ko query send karna
        await client.sendMessage(botUsername, { message: songName });
        console.log(`📨 Bot ko query bhej di gayi hai: "${songName}"`);

        // 2. Button (Menu) ka wait karna (Max 15 seconds)
        let menuMessage = await waitForMessage(client, botUsername, 15000, (msg) => {
            return msg.replyMarkup && msg.replyMarkup.rows && msg.replyMarkup.rows.length > 0;
        });

        if (!menuMessage) {
            console.log(`⚠️ "${songName}" ke liye 15s tak wait kiya, koi button/menu nahi mila.`);
            return false;
        }

        console.log("✅ Search results aagaye hain. Pehle button par click kar rahe hain...");

        // 3. Pehle button par click karna (Row 0, Button 0)
        await menuMessage.click(0, 0);

        // 4. Ab Audio file aane ka wait karna (Max 30 seconds)
        console.log("⏳ Audio generate hone ka wait kar rahe hain...");
        let audioMessage = await waitForMessage(client, botUsername, 30000, (msg) => {
            return msg.media && (msg.media.document || msg.media.audio);
        });

        if (!audioMessage) {
            console.log("⚠️ Button click kiya, par 30s tak koi audio reply nahi mila.");
            return false;
        }

        // 5. Audio file download karna
        console.log("✅ Audio mil gaya! Downloading...");
        const buffer = await client.downloadMedia(audioMessage);

        const safeName = songName.replace(/[^a-z0-9]/gi, "_").toLowerCase();
        const fileName = `${safeName}_${Date.now()}.mp3`;
        const filePath = path.join(DOWNLOAD_DIR, fileName);
        fs.writeFileSync(filePath, buffer);

        console.log(`✅ "${songName}" Successfully Downloaded! Saved as: ${fileName}`);
        return { success: true, fileName, filePath };

    } catch (error) {
        console.error("❌ Error aagaya VK Music extraction mein:", error);
        return { success: false, error: error.message };
    }
}

// Helper Function: Custom Wait for specific message conditions
async function waitForMessage(client, chatId, timeoutMs, conditionCallback) {
    return new Promise((resolve) => {
        let isResolved = false;

        const timeout = setTimeout(() => {
            if (!isResolved) {
                isResolved = true;
                client.removeEventHandler(messageHandler);
                resolve(null); // Timeout hone par null return karega
            }
        }, timeoutMs);

        const messageHandler = async (event) => {
            if (isResolved) return;

            const msg = event.message;
            if (!msg) return;

            if (conditionCallback(msg)) {
                isResolved = true;
                clearTimeout(timeout);
                client.removeEventHandler(messageHandler);
                resolve(msg);
            }
        };

        client.addEventHandler(messageHandler, new NewMessage({}));
    });
}

module.exports = { downloadVkMusic, fetchVKMusic };
