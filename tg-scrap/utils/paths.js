const path = require("path");

// On Render (or any host), point EXPORT_DIR at your mounted persistent disk,
// e.g. EXPORT_DIR=/data/export
// Locally it just defaults to ./export like the original project.
const EXPORT_DIR = process.env.EXPORT_DIR
  ? path.resolve(process.env.EXPORT_DIR)
  : path.resolve(process.cwd(), "export");

module.exports = { EXPORT_DIR };
