const fs = require("fs");
const path = require("path");
const { logMessage } = require("./helper");
const { EXPORT_DIR } = require("./paths");

const CONFIG_FILE = path.join(__dirname, "../config.json");
const LAST_SELECTION_FILE = path.join(EXPORT_DIR, "last_selection.json");

// True when credentials come from environment variables (Render/production)
// instead of a local config.json file (local dev / original CLI usage).
const usingEnvCredentials = Boolean(
  process.env.TELEGRAM_API_ID && process.env.TELEGRAM_API_HASH
);

/**
 * Reads the content of a file synchronously.
 *
 * @param {string} filePath - The path to the file to be read.
 * @returns {string} The content of the file.
 * @throws Will throw an error if the file cannot be read.
 */
const readFileSync = (filePath, showError = true) => {
  try {
    return fs.readFileSync(filePath, "utf8");
  } catch (err) {
    showError ? logMessage.error(`Error reading file: ${filePath}`, err) : null;
    throw err;
  }
};

/**
 * Writes data to a file synchronously.
 *
 * @param {string} filePath - The path to the file where data should be written.
 * @param {Object} data - The data to be written to the file.
 * @throws Will throw an error if writing to the file fails.
 */
const writeFileSync = (filePath, data) => {
  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
    logMessage.success(`File written successfully: ${filePath}`);
  } catch (err) {
    logMessage.error(`Error writing file: ${filePath}`, err);
    throw err;
  }
};

/**
 * Updates the credentials in the configuration file with the provided object.
 *
 * @param {Object} obj - The object containing the new credentials to be updated.
 * @throws Will log an error message if reading or writing to the configuration file fails.
 */
const updateCredentials = (obj) => {
  if (usingEnvCredentials) {
    // On Render there's no writable config.json - if a new sessionId gets
    // generated (shouldn't happen once TELEGRAM_SESSION is set), just log it
    // so it can be copied into the environment variables manually.
    if (obj.sessionId) {
      logMessage.info(
        "New session generated. Copy this into your TELEGRAM_SESSION env var:"
      );
      console.log(obj.sessionId);
    }
    return;
  }
  try {
    const data = readFileSync(CONFIG_FILE);
    const credentials = { ...JSON.parse(data), ...obj };
    writeFileSync(CONFIG_FILE, credentials);
  } catch (err) {
    logMessage.error("Failed to update credentials", err);
  }
};

/**
 * Reads and parses the credentials from the configuration file.
 *
 * @returns {Object} The parsed credentials from the config file.
 * @throws Will log an error message and exit the process if the config file cannot be read or parsed.
 */
const getCredentials = () => {
  if (usingEnvCredentials) {
    return {
      apiId: parseInt(process.env.TELEGRAM_API_ID, 10),
      apiHash: process.env.TELEGRAM_API_HASH,
      sessionId: process.env.TELEGRAM_SESSION || "",
    };
  }
  try {
    const data = readFileSync(CONFIG_FILE);
    return JSON.parse(data);
  } catch (err) {
    logMessage.error(
      "Please add your credentials in config.json file, follow https://github.com/abhishekjnvk/telegram-channel-downloader#setup for more info"
    );
    process.exit(1);
  }
};

/**
 * Retrieves the last selection from a file.
 *
 * @returns {Object} The last selection data parsed from the file. Returns an empty object if an error occurs.
 */
const getLastSelection = () => {
  try {
    const data = readFileSync(LAST_SELECTION_FILE, false);
    return JSON.parse(data);
  } catch (_) {
    return {};
  }
};

/**
 * Updates the last selection with the provided object.
 *
 * This function merges the provided object with the last selection
 * and writes the result to the LAST_SELECTION_FILE. If an error occurs
 * during the process, it logs an error message.
 *
 * @param {Object} object - The object to merge with the last selection.
 */
const updateLastSelection = (object) => {
  try {
    if (!fs.existsSync(EXPORT_DIR)) {
      fs.mkdirSync(EXPORT_DIR, { recursive: true });
    }
    const last = { ...getLastSelection(), ...object };
    writeFileSync(LAST_SELECTION_FILE, last);
  } catch (err) {
    logMessage.error("Failed to update last selection", err);
  }
};

/**
 * Creates a directory (recursively) if it doesn't already exist.
 *
 * @param {string} dirPath - The directory path to ensure exists.
 */
const ensureDirExists = (dirPath) => {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
};

module.exports = {
  updateCredentials,
  getCredentials,
  getLastSelection,
  updateLastSelection,
  ensureDirExists,
};
