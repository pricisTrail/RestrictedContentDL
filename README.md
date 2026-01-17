<h1 align="center">Restricted Content Downloader Telegram Bot</h1>

<p align="center">
  <a href="https://github.com/bisnuray/RestrictedContentDL/stargazers"><img src="https://img.shields.io/github/stars/bisnuray/RestrictedContentDL?color=blue&style=flat" alt="GitHub Repo stars"></a>
  <a href="https://github.com/bisnuray/RestrictedContentDL/issues"><img src="https://img.shields.io/github/issues/bisnuray/RestrictedContentDL" alt="GitHub issues"></a>
  <a href="https://github.com/bisnuray/RestrictedContentDL/pulls"><img src="https://img.shields.io/github/issues-pr/bisnuray/RestrictedContentDL" alt="GitHub pull requests"></a>
  <a href="https://github.com/bisnuray/RestrictedContentDL/graphs/contributors"><img src="https://img.shields.io/github/contributors/bisnuray/RestrictedContentDL?style=flat" alt="GitHub contributors"></a>
  <a href="https://github.com/bisnuray/RestrictedContentDL/network/members"><img src="https://img.shields.io/github/forks/bisnuray/RestrictedContentDL?style=flat" alt="GitHub forks"></a>
</p>

<p align="center">
  <em>Restricted Content Downloader: An advanced Telegram bot script to download restricted content such as photos, videos, audio files, or documents from Telegram private chats or channels. This bot can also copy text messages from Telegram posts.</em>
</p>
<hr>

## Features

- 📥 Download media (photos, videos, audio, documents).
- ✅ Supports downloading from both single media posts and media groups.
- 🔄 Progress bar showing real-time downloading progress.
- ✍️ Copy text messages or captions from Telegram posts.
- 🔐 **Multi-user login support** - Users can login with their own Telegram accounts via `/login` command.
- 💾 **MongoDB session storage** - Sessions persist across restarts and redeployments.
- 📢 **Channel forwarding** - Automatically forward downloaded media to a configured channel.

## Requirements

Before you begin, ensure you have met the following requirements:

- Docker and Docker Compose installed on your system
- A Telegram bot token (you can get one from [@BotFather](https://t.me/BotFather) on Telegram)
- API ID and Hash: You can get these by creating an application on [my.telegram.org](https://my.telegram.org)
- **MongoDB database** (required for session storage) - You can use [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) free tier
- ~~SESSION_STRING~~ - No longer required! Users can now login directly via the `/login` command.

> **Note**: All dependencies including Python, `pyrofork`, `pyleaves`, `tgcrypto`, `motor`, and `ffmpeg` are automatically installed when you deploy with Docker Compose.

## Configuration

1. Open the `config.env` file in your favorite text editor.
2. Replace the placeholders for `API_ID`, `API_HASH`, `BOT_TOKEN`, and `MONGO_URI` with your actual values:
   - **`API_ID`**: Your API ID from [my.telegram.org](https://my.telegram.org).
   - **`API_HASH`**: Your API Hash from [my.telegram.org](https://my.telegram.org).
   - **`BOT_TOKEN`**: The token you obtained from [@BotFather](https://t.me/BotFather).
   - **`MONGO_URI`**: Your MongoDB connection string (e.g., `mongodb+srv://user:pass@cluster.mongodb.net/`).
   - **`SESSION_STRING`** (optional): Legacy fallback session. Leave empty if using `/login` command.
   - **`ADMIN_ID`** (optional): Your Telegram user ID to receive startup notifications.
   - **`FORWARD_CHANNEL_ID`** (optional): Channel ID to forward downloaded media to.

3. Optional performance settings:
   - **`MAX_CONCURRENT_DOWNLOADS`**: Number of simultaneous downloads (default: 3)
   - **`BATCH_SIZE`**: Number of posts to process in parallel during batch downloads (default: 10)
   - **`FLOOD_WAIT_DELAY`**: Delay in seconds between batch groups to avoid flood limits (default: 3)

## Deploy the Bot

1. Clone the repository:
   ```sh
   git clone https://github.com/bisnuray/RestrictedContentDL
   cd RestrictedContentDL
   ```

2. Start the bot:
   ```sh
   docker compose up --build --remove-orphans
   ```

The bot will run in a containerized environment with all dependencies (Python, libraries, FFmpeg) automatically installed and managed.

To stop the bot:

```sh
docker compose down
```

### Deploy on Koyeb (Free Tier)

This bot is compatible with Koyeb's free tier **web services**. It includes a built-in HTTP health check server on port 8000.

1. **Create a new Web Service** on Koyeb
2. **Connect your GitHub repository** or use Docker deployment
3. **Configure the following settings**:
   - **Port**: `8000`
   - **Health Check Path**: `/health` or `/`
   - **Environment Variables**: Set the same variables as in `config.env`:
     - `API_ID`
     - `API_HASH`
     - `BOT_TOKEN`
     - `MONGO_URI`
     - `ADMIN_ID` (optional)

4. **Deploy** - The bot will start and respond to health checks automatically

> **Important**: With MongoDB session storage, you no longer get `AUTH_KEY_DUPLICATED` errors on redeployment! Sessions are stored in the database and loaded on startup.

## Usage

### Session Commands (New!)
- **`/login`** – Start the login process to connect your Telegram account.
- **`/logout`** – Remove your session from the bot.
- **`/session`** – Check your current session status.
- **`/cancel`** – Cancel an ongoing login process.

### Download Commands
- **`/start`** – Welcomes you and gives a brief introduction.  
- **`/help`** – Shows detailed instructions and examples.  
- **`/dl <post_URL>`** or simply paste a Telegram post link – Fetch photos, videos, audio, or documents from that post.  
- **`/bdl <start_link> <end_link>`** – Batch-download a range of posts in one go.  

  > 💡 Example: `/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`  

### Utility Commands
- **`/killall`** – Cancel any pending downloads if the bot hangs.  
- **`/logs`** – Download the bot's logs file.  
- **`/stats`** – View current status (uptime, sessions, disk, memory, network, CPU, etc.).
- **`/channel`** – Check the forward channel status and bot permissions.
- **`/ping`** – Check if the bot is responding.

## Login Flow

1. Send `/login` to the bot
2. Enter your phone number with country code (e.g., `+1234567890`)
3. Enter the verification code sent to your Telegram app
4. If you have 2FA enabled, enter your password
5. Done! Your session is saved and will persist across bot restarts.

> **Security Note**: Your password is never stored. Only the session string is saved in MongoDB.

## Multi-User Support

- Each user can login with their own Telegram account
- Sessions are isolated per user
- Users can only access chats they are members of
- The admin can also provide a fallback `SESSION_STRING` in config for shared access

## Author

- Name: Bisnu Ray
- Telegram: [@itsSmartDev](https://t.me/itsSmartDev)

> **Note**: If you found this repo helpful, please fork and star it. Also, feel free to share with proper credit!
