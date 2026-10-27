const path = require("node:path");
const root = path.resolve(__dirname, "..");

module.exports = {
  apps: [{
    name: "piwankanobi",
    cwd: root,
    script: path.join(root, "run-web.sh"),
    interpreter: "/bin/bash",
    exec_mode: "fork",
    instances: 1, // One Gunicorn master owns the Hailo model.
    autorestart: true,
    restart_delay: 5000,
    kill_timeout: 40000,
    env: {
      PYTHONUNBUFFERED: "1",
      PIWANKANOBI_PORT: "3010",
    },
  }],
};
