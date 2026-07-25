const readline = require("readline");
const { downloadVkMusic } = require("./scripts/download-vkmusic");
// Apne existing authentication module ko require karein
const { getClient } = require("./modules/auth");

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function askQuestion(query) {
    return new Promise((resolve) => rl.question(query, resolve));
}

async function main() {
    console.log("==========================================");
    console.log("  🎵 TELEGRAM VK MUSIC BOT SCRAPER / EXTRACTOR ");
    console.log("==========================================\n");
    console.log("1. Extract Songs from VK Music Bot (@vkmusic_bot)");
    console.log("2. Exit\n");

    const choice = await askQuestion("Option select karein (1-2): ");

    if (choice.trim() === "1") {
        const botUsername = await askQuestion("Bot Username enter karein (default: vkmusic_bot): ");
        const limitInput = await askQuestion("Kitne last messages check karne hain? (default: 100): ");

        const targetBot = botUsername.trim() || "vkmusic_bot";
        const limit = parseInt(limitInput.trim(), 10) || 100;

        console.log("\n🔄 Telegram client connect ho raha hai...");
        const client = await getClient();

        await downloadVkMusic(client, {
            botUsername: targetBot,
            limit: limit
        });

    } else {
        console.log("Exiting...");
    }

    rl.close();
    process.exit(0);
}

main().catch(console.error);
