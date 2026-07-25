const { Api } = require("telegram");

/**
 * VK Music Bot se Audio / MP3 Messages extract karne ka function
 * @param {Object} client - GramJS Client instance
 * @param {string} botUsername - Target Bot Username (default: "vkmusic_bot")
 * @param {number} limit - Messages limit
 */
async function getVkMusicMessages(client, botUsername = "vkmusic_bot", limit = 100) {
    try {
        // Resolve entity for VK Music Bot
        const entity = await client.getEntity(botUsername);
        
        // Chat history se messages fetch karein
        const messages = await client.getMessages(entity, { limit: limit });

        // Sirf un messages ko filter karein jinme audio ya document media ho
        const audioMessages = messages.filter(msg => {
            if (!msg.media) return false;
            
            const isAudio = msg.media.audio;
            const isDocument = msg.media.document;
            
            // Check if document is an audio file
            const mimeType = isDocument?.mimeType || "";
            const isAudioMime = mimeType.startsWith("audio/") || mimeType.includes("mpeg");

            return isAudio || isAudioMime;
        });

        return { entity, audioMessages };
    } catch (error) {
        console.error("❌ Error fetching messages from VK Music Bot:", error.message);
        throw error;
    }
}

/**
 * VK Music Bot ko ek specific song ka naam bhejo aur uska reply (audio) wait karo
 * @param {Object} client - GramJS Client instance
 * @param {string} botUsername - Target Bot Username
 * @param {string} query - Song ka naam / search query jo bot ko bhejna hai
 * @param {Object} opts - { waitTimeMs, pollIntervalMs, checkLimit }
 */
async function searchVkMusicMessages(client, botUsername = "vkmusic_bot", query, opts = {}) {
    const waitTimeMs = opts.waitTimeMs || 15000;      // total time to wait for bot's reply
    const pollIntervalMs = opts.pollIntervalMs || 2000; // how often to re-check
    const checkLimit = opts.checkLimit || 10;           // how many recent messages to scan each poll

    if (!query || !query.trim()) {
        throw new Error("Search query (song name) khali nahi ho sakta.");
    }

    const entity = await client.getEntity(botUsername);

    // Sirf abhi ke baad aane wale messages count karne ke liye timestamp note karein
    const sentAtUnix = Math.floor(Date.now() / 1000);

    console.log(`📨 Bot ko query bhej rahe hain: "${query}"`);
    await client.sendMessage(entity, { message: query });

    const isAudioMsg = (msg) => {
        if (!msg.media) return false;
        const isAudio = msg.media.audio;
        const isDocument = msg.media.document;
        const mimeType = isDocument?.mimeType || "";
        const isAudioMime = mimeType.startsWith("audio/") || mimeType.includes("mpeg");
        return isAudio || isAudioMime;
    };

    const deadline = Date.now() + waitTimeMs;
    let audioMessages = [];

    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));

        const messages = await client.getMessages(entity, { limit: checkLimit });

        // Sirf woh messages jo humne query bheja uske BAAD aaye hain
        audioMessages = messages.filter((msg) => msg.date >= sentAtUnix && isAudioMsg(msg));

        if (audioMessages.length > 0) break;
    }

    if (audioMessages.length === 0) {
        console.log(`⚠️ "${query}" ke liye ${waitTimeMs / 1000}s tak wait kiya, koi audio reply nahi mila.`);
    }

    return { entity, audioMessages };
}

module.exports = {
    getVkMusicMessages,
    searchVkMusicMessages
};
